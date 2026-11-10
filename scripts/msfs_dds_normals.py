"""Decode the MSFS BC5 normal formats that Blender may open with size (0, 0)."""

import struct
import zlib

import numpy as np


def normal_format(header):
    if header[:4] != b"DDS " or len(header) < 128:
        return None
    fourcc = header[84:88]
    if fourcc == b"DX10" and len(header) >= 148:
        return {83: "BC5U", 84: "BC5S"}.get(struct.unpack_from("<I", header, 128)[0])
    return {b"BC5S": "BC5S", b"BC5U": "BC5U", b"ATI2": "BC5U", b"DXT5": "DXT5"}.get(fourcc)


def bc4(blocks, signed):
    if signed:
        ends = np.maximum(blocks[:, :2].view(np.int8), -127).astype(np.float32)
        lower, upper = -127, 127
    else:
        ends = blocks[:, :2].astype(np.float32)
        lower, upper = 0, 255
    first, second = ends.T
    long = first > second
    palette = np.empty((len(blocks), 8), dtype=np.float32)
    palette[:, :2] = ends
    for i in range(2, 6):
        palette[:, i] = np.where(long, ((8-i)*first + (i-1)*second)/7,
                                  ((6-i)*first + (i-1)*second)/5)
    palette[:, 6] = np.where(long, (2*first + 5*second)/7, lower)
    palette[:, 7] = np.where(long, (first + 6*second)/7, upper)
    bits = (blocks[:, 2:8].astype(np.uint64) << (np.arange(6, dtype=np.uint64)*8)).sum(axis=1)
    indices = ((bits[:, None] >> (np.arange(16, dtype=np.uint64)*3)) & 7).astype(np.intp)
    values = np.take_along_axis(palette, indices, axis=1)
    return values / 127 if signed else values / 127.5 - 1


def dxt5_green(blocks):
    first = (((blocks[:, 0].astype(np.uint16) + 256*blocks[:, 1].astype(np.uint16)) >> 5) & 63) / 63.0
    second = (((blocks[:, 2].astype(np.uint16) + 256*blocks[:, 3].astype(np.uint16)) >> 5) & 63) / 63.0
    palette = np.stack([first, second, (2*first+second)/3, (first+2*second)/3], axis=1)
    bits = (blocks[:, 4:8].astype(np.uint32) << (np.arange(4, dtype=np.uint32)*8)).sum(axis=1)
    indices = ((bits[:, None] >> (np.arange(16, dtype=np.uint32)*2)) & 3).astype(np.intp)
    return (np.take_along_axis(palette, indices, axis=1)*2 - 1).astype(np.float32)


def png_chunk(tag, payload):
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))


def rgb_scanlines(blocks, width, height, columns, rows, codec):
    x = bc4(blocks[:, :8], codec == "BC5S")
    y = dxt5_green(blocks[:, 8:]) if codec == "DXT5" else bc4(blocks[:, 8:], codec == "BC5S")
    z = np.sqrt(np.maximum(0, 1-x*x-y*y))
    scanlines = np.ones((height, 1+width*3), dtype=np.uint8)  # PNG Sub filter
    for i, channel in enumerate((x, y, z)):
        pixels = (np.rint((channel+1)*127.5).astype(np.uint8).reshape(rows, columns, 4, 4)
                  .transpose(0, 2, 1, 3).reshape(rows*4, columns*4)[:height, :width])
        scanlines[:, 1+i] = pixels[:, 0]
        scanlines[:, 4+i::3] = pixels[:, 1:] - pixels[:, :-1]
    return scanlines.tobytes()


def decode_normal(source, output, codec):
    data = source.read_bytes()
    if normal_format(data) != codec:
        raise ValueError(f"Неизвестный формат DDS: {source.name}")
    height, width = struct.unpack_from("<II", data, 12)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise ValueError(f"Неподдерживаемый размер DDS: {width}×{height}")
    columns, rows = (width+3)//4, (height+3)//4
    offset = 148 if data[84:88] == b"DX10" else 128
    if len(data) < offset + rows * columns * 16:
        raise ValueError(f"DDS BIN truncated: {source.name}")
    blocks = np.frombuffer(data, dtype=np.uint8, count=rows*columns*16, offset=offset).reshape(-1, 16)
    compressor = zlib.compressobj(level=3)
    with output.open("wb") as png:
        png.write(b"\x89PNG\r\n\x1a\n")
        png.write(png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        for row in range(0, rows, 32):
            end = min(row+32, rows)
            stripe = blocks[row*columns:end*columns]
            scanlines = rgb_scanlines(stripe, width, min(end*4, height)-row*4, columns, end-row, codec)
            packed = compressor.compress(scanlines)
            if packed:
                png.write(png_chunk(b"IDAT", packed))
        png.write(png_chunk(b"IDAT", compressor.flush()))
        png.write(png_chunk(b"IEND", b""))

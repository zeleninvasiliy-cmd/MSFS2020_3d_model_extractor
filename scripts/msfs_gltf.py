"""Format-neutral glTF/GLB document and buffer loading.

The pipeline only needs a JSON document plus byte-addressable buffers.  This
module keeps container handling out of the geometry, resolver and skin-split
code.  JSON glTF, GLB, local relative buffers and data URIs are normalized to
the same in-memory representation; callers may then combine buffers into one
standalone buffer before applying MSFS-specific edits.
"""

from __future__ import annotations

import base64
import copy
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes


GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


@dataclass
class GltfAsset:
    path: Path
    document: dict
    buffers: list[bytes]
    source_format: str


def _decode_data_uri(uri: str) -> bytes:
    header, separator, payload = uri.partition(",")
    if not separator or not header.casefold().startswith("data:"):
        raise ValueError("Некорректный data URI буфера")
    if ";base64" in header.casefold():
        try:
            return base64.b64decode(payload, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError(f"Некорректный base64 data URI: {exc}") from exc
    return unquote_to_bytes(payload)


def _read_glb(path: Path) -> tuple[dict, list[bytes]]:
    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError(f"{path}: GLB заголовок усечён")
    magic, version, declared_length = struct.unpack_from("<4sII", raw, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"{path}: неверная сигнатура GLB")
    if version != GLB_VERSION:
        raise ValueError(f"{path}: поддерживается GLB version 2, получена {version}")
    if declared_length != len(raw):
        raise ValueError(f"{path}: длина GLB не совпадает с заголовком")
    cursor = 12
    document = None
    binary_chunks = []
    while cursor < len(raw):
        if cursor + 8 > len(raw):
            raise ValueError(f"{path}: заголовок GLB chunk усечён")
        chunk_length, chunk_type = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        end = cursor + chunk_length
        if end > len(raw):
            raise ValueError(f"{path}: GLB chunk выходит за границы файла")
        payload = raw[cursor:end]
        cursor = end
        if chunk_type == JSON_CHUNK:
            if document is not None:
                raise ValueError(f"{path}: GLB содержит несколько JSON chunks")
            try:
                document = json.loads(payload.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError(f"{path}: JSON chunk GLB не читается: {exc}") from exc
        elif chunk_type == BIN_CHUNK:
            binary_chunks.append(payload)
    if not isinstance(document, dict):
        raise ValueError(f"{path}: GLB не содержит JSON chunk")
    return document, binary_chunks


def _read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: glTF JSON не читается: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: ожидался JSON-объект glTF")
    return document


def _read_buffer(path: Path, uri: str, *, glb_chunks: list[bytes], glb_index: int) -> tuple[bytes, int]:
    if not uri:
        if glb_index >= len(glb_chunks):
            raise ValueError(f"{path}: buffer без uri не имеет BIN chunk в GLB")
        return glb_chunks[glb_index], glb_index + 1
    if uri.casefold().startswith("data:"):
        return _decode_data_uri(uri), glb_index
    relative = unquote(uri.replace("\\", "/"))
    target = (path.parent / relative).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Не найден BIN/буфер модели: {target}")
    return target.read_bytes(), glb_index


def load_gltf(path: Path) -> GltfAsset:
    """Load JSON glTF or GLB and resolve every declared buffer."""
    path = Path(path)
    if path.suffix.casefold() == ".glb":
        document, glb_chunks = _read_glb(path)
        source_format = "glb"
    else:
        document, glb_chunks = _read_json(path), []
        source_format = "gltf"
    buffers = document.get("buffers") or []
    if not isinstance(buffers, list) or not buffers:
        raise ValueError(f"{path}: glTF не содержит buffers")
    data = []
    glb_index = 0
    for index, buffer in enumerate(buffers):
        if not isinstance(buffer, dict):
            raise ValueError(f"{path}: buffer {index} имеет неверный тип")
        raw, glb_index = _read_buffer(path, str(buffer.get("uri") or ""),
                                       glb_chunks=glb_chunks, glb_index=glb_index)
        declared = buffer.get("byteLength")
        if isinstance(declared, int) and declared >= 0:
            if len(raw) < declared:
                raise ValueError(f"{path}: buffer {index} усечён ({len(raw)} < {declared})")
            raw = raw[:declared]
        data.append(bytes(raw))
    return GltfAsset(path=path, document=document, buffers=data, source_format=source_format)


def read_document(path: Path) -> dict:
    """Read only the glTF document, without requiring geometry buffers.

    Metadata-only commands such as ``bones`` need nodes and skins but must
    remain useful for minimal JSON fixtures and partially copied packages.
    Geometry commands continue to use :func:`load_gltf`, which validates every
    declared buffer before processing vertices.
    """
    path = Path(path)
    document = _read_glb(path)[0] if path.suffix.casefold() == ".glb" else _read_json(path)
    if not isinstance(document, dict):
        raise ValueError(f"{path}: ожидался JSON-объект glTF")
    return document


def combine_buffers(asset: GltfAsset, document: dict | None = None) -> bytes:
    """Pack all asset buffers into buffer 0 and rewrite bufferView offsets.

    A deep copy is used by default so resolver inspection never mutates the
    source document.  Geometry preparation passes its working document when it
    wants the normalized one-buffer form.
    """
    target = document if document is not None else copy.deepcopy(asset.document)
    offsets = []
    packed = bytearray()
    for raw in asset.buffers:
        while len(packed) % 4:
            packed.append(0)
        offsets.append(len(packed))
        packed.extend(raw)
    for view in target.get("bufferViews", []) or []:
        if not isinstance(view, dict):
            raise ValueError(f"{asset.path}: bufferView имеет неверный тип")
        buffer_index = view.get("buffer", 0)
        if not isinstance(buffer_index, int) or not 0 <= buffer_index < len(offsets):
            raise ValueError(f"{asset.path}: bufferView ссылается на недопустимый buffer {buffer_index}")
        view["buffer"] = 0
        view["byteOffset"] = offsets[buffer_index] + int(view.get("byteOffset", 0))
    target["buffers"] = [{"byteLength": len(packed)}]
    return bytes(packed)

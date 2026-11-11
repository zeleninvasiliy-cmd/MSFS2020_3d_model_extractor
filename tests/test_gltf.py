"""Synthetic tests for the shared JSON glTF/GLB buffer adapter."""

import base64
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from msfs_gltf import combine_buffers, load_gltf, unsupported_geometry_extensions


def write_glb(path, document, binary):
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    body = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    body += struct.pack("<II", len(binary), 0x004E4942) + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


class GltfLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_data_uri_buffer_is_loaded(self):
        payload = b"DATA"
        uri = "data:application/octet-stream;base64," + base64.b64encode(payload).decode()
        path = self.root / "embedded.gltf"
        path.write_text(json.dumps({"asset": {"version": "2.0"},
                                    "buffers": [{"uri": uri, "byteLength": len(payload)}]}), encoding="utf-8")
        asset = load_gltf(path)
        self.assertEqual(asset.source_format, "gltf")
        self.assertEqual(asset.buffers, [payload])

    def test_multiple_buffers_are_combined_and_buffer_views_rebased(self):
        first, second = b"AAAA", b"BBBBBB"
        path = self.root / "multi.gltf"
        (path.parent / "a.bin").write_bytes(first)
        (path.parent / "b.bin").write_bytes(second)
        path.write_text(json.dumps({"asset": {"version": "2.0"},
                                    "buffers": [{"uri": "a.bin", "byteLength": len(first)},
                                                 {"uri": "b.bin", "byteLength": len(second)}],
                                    "bufferViews": [{"buffer": 0, "byteOffset": 1, "byteLength": 2},
                                                     {"buffer": 1, "byteOffset": 2, "byteLength": 3}]}),
                         encoding="utf-8")
        asset = load_gltf(path)
        document = asset.document
        packed = combine_buffers(asset, document)
        self.assertEqual(document["buffers"], [{"byteLength": len(packed)}])
        self.assertEqual([view["buffer"] for view in document["bufferViews"]], [0, 0])
        self.assertEqual(document["bufferViews"][0]["byteOffset"], 1)
        self.assertEqual(document["bufferViews"][1]["byteOffset"], 6)
        self.assertEqual(packed[1:3], b"AA")
        self.assertEqual(packed[6:9], b"BBB")

    def test_glb_json_and_bin_chunks_are_loaded(self):
        path = self.root / "model.glb"
        write_glb(path, {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}]}, b"GLB!")
        asset = load_gltf(path)
        self.assertEqual(asset.source_format, "glb")
        self.assertEqual(asset.buffers, [b"GLB!"])

    def test_missing_external_buffer_is_explicit(self):
        path = self.root / "missing.gltf"
        path.write_text(json.dumps({"asset": {"version": "2.0"},
                                    "buffers": [{"uri": "missing.bin", "byteLength": 4}]}), encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            load_gltf(path)

    def test_geometry_compression_extensions_are_detected_at_their_use_sites(self):
        document = {
            "extensionsUsed": ["KHR_draco_mesh_compression"],
            "bufferViews": [{"extensions": {"EXT_meshopt_compression": {"buffer": 0}}}],
            "meshes": [{"primitives": [{"extensions": {
                "KHR_draco_mesh_compression": {"bufferView": 0}}}]}],
        }

        unsupported = unsupported_geometry_extensions(document)

        self.assertEqual(len(unsupported), 2)
        self.assertTrue(any("Draco" in value for value in unsupported))
        self.assertTrue(any("Meshopt" in value for value in unsupported))


if __name__ == "__main__":
    unittest.main()

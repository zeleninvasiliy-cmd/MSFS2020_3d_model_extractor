"""Headless regression checks. Run with Blender --background --python this_file."""

import json
import struct
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import msfs_geometry as geometry
import msfs_materials as materials
import msfs_universal_worker as worker


def raises_value_error(action):
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("Expected ValueError")


def check_mirrors():
    """A rotated, scaled and offset source must land on the other side with
    readable decals and correct shading, not merely negated local vertices."""
    mesh = bpy.data.meshes.new("mirror-check")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    layer = mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(layer.data, [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]):
        loop.uv = uv
    source = bpy.data.objects.new("MIRROR_SRC", mesh)
    bpy.context.collection.objects.link(source)
    source.matrix_world = (Matrix.Translation((2, 3, 4)) @ Matrix.Rotation(0.7, 4, "Z")
                           @ Matrix.Diagonal((1.5, 1.5, 1.5, 1.0)))
    target = bpy.data.objects.new("MIRROR_DST", mesh.copy())
    bpy.context.collection.objects.link(target)
    mesh.normals_split_custom_set_from_vertices([(1.0, 0.0, 0.0)] * 3)
    originals = [vertex.co.copy() for vertex in mesh.vertices]
    source_normals = {mesh.loops[index].vertex_index: mesh.corner_normals[index].vector.copy()
                      for index in range(len(mesh.loops))}

    worker.configured_mirrors({"mirror_objects": [{"source": "MIRROR_SRC", "target": "MIRROR_DST", "axis": "X"}]})
    bpy.context.view_layer.update()
    reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    assert (target.matrix_world.translation - Vector((-2.0, 3.0, 4.0))).length < 1e-6
    assert target.matrix_world.determinant() > 0, "mirroring must not leave a negative object scale"
    expected_uv = {0: (0.9, 0.2), 1: (0.7, 0.4), 2: (0.5, 0.6)}
    for index, loop in enumerate(target.data.loops):
        uv = target.data.uv_layers[0].data[index].uv
        want = expected_uv[loop.vertex_index]
        assert abs(uv[0] - want[0]) < 1e-6 and abs(uv[1] - want[1]) < 1e-6, (loop.vertex_index, tuple(uv))
    world = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    wanted = [reflection @ source.matrix_world @ point for point in originals]
    assert max((a - b).length for a, b in zip(world, wanted)) < 1e-5
    normal_matrix = target.matrix_world.to_3x3().inverted().transposed()
    source_matrix = source.matrix_world.to_3x3().inverted().transposed()
    for index, loop in enumerate(target.data.loops):
        direction = (normal_matrix @ target.data.corner_normals[index].vector).normalized()
        expected_direction = (reflection.to_3x3() @ source_matrix @ source_normals[loop.vertex_index]).normalized()
        # Custom normals are stored quantized, so a round trip loses ~1e-4.
        assert (direction - expected_direction).length < 1e-3, (tuple(direction), tuple(expected_direction))


def check_placements():
    anchor = bpy.data.objects.new("PLACE_ANCHOR", None)
    bpy.context.collection.objects.link(anchor)
    anchor.matrix_world = (Matrix.Translation((5, 6, 7)) @ Matrix.Rotation(1.1, 4, "Y")
                           @ Matrix.Diagonal((3.0, 3.0, 3.0, 1.0)))
    part = bpy.data.objects.new("PLACE_PART", bpy.data.meshes.new("place-part"))
    bpy.context.collection.objects.link(part)
    part.matrix_world = Matrix.Translation((-1, -2, -3)) @ Matrix.Rotation(0.4, 4, "X")
    before = part.matrix_world.to_quaternion(), part.matrix_world.to_scale()

    changes = worker.configured_placements({"placements": {"PLACE_PART": {"anchor": "PLACE_ANCHOR",
                                                                         "offset_m": [0.5, 0, -0.25]}}})
    bpy.context.view_layer.update()
    assert (part.matrix_world.translation - Vector((5.5, 6.0, 6.75))).length < 1e-6
    assert (part.matrix_world.to_quaternion().rotation_difference(before[0])).angle < 1e-5
    assert (part.matrix_world.to_scale() - before[1]).length < 1e-5
    assert changes["PLACE_PART"]["anchor"] == "PLACE_ANCHOR"


def main():
    raises_value_error(lambda: geometry._node_world_matrices({"nodes": [{"children": [1]}, {"children": [0]}]}))
    raises_value_error(lambda: materials.texture_filename({}, [], [], -1))
    doc = {"accessors": [{"bufferView": 0, "count": 3}], "bufferViews": [{"byteLength": 4}]}
    raises_value_error(lambda: geometry.read_accessor(doc, b"1234", 0, "<f4", 3))
    with tempfile.TemporaryDirectory(prefix="worker-checks-", dir=Path(__file__).parent) as directory:
        folder = Path(directory)
        source = folder / "test.gltf"
        binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
        (folder / "source.bin").write_bytes(binary)
        doc = {
            "asset": {"version": "2.0"},
            "buffers": [{"uri": "source.bin", "byteLength": len(binary)}],
            "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
            "materials": [{"name": "WingDecal", "alphaMode": "BLEND", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.3, 0.1, 0.5]}}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
            "nodes": [{"name": "WING_LEFT", "mesh": 0}, {"name": "WHEEL_LEFT", "mesh": 0}],
            "scenes": [{"nodes": [0, 1]}], "scene": 0,
        }
        source.write_text(json.dumps(doc), encoding="utf-8")
        import_dir = folder / "import"
        import_dir.mkdir()
        message = raises_value_error(lambda: geometry.prepare_gltf(source, import_dir, draw_mode="msfs"))
        assert source.name in message and "primitive 0" in message and "draw_mode=auto" in message, message
        # A removed runtime material must not renumber the primitive in the message.
        filtered = json.loads(json.dumps(doc))
        filtered["materials"].append({"name": "TutoMeshes"})
        filtered["meshes"][0]["primitives"].insert(0, {"attributes": {"POSITION": 0}, "material": 1})
        filtered_path = folder / "filtered.gltf"
        filtered_path.write_text(json.dumps(filtered), encoding="utf-8")
        message = raises_value_error(lambda: geometry.prepare_gltf(filtered_path, import_dir, draw_mode="msfs"))
        assert "primitive 1" in message, message
        # Sparse POSITION data and a non-indexed triangle strip are normalized
        # before Blender import, so common glTF exporters do not need a
        # hand-written conversion step.
        sparse_path = folder / "sparse-strip.gltf"
        sparse_binary = b"\x00\x01\x02\x00" + struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
        (folder / "sparse-strip.bin").write_bytes(sparse_binary)
        sparse_doc = {
            "asset": {"version": "2.0"},
            "buffers": [{"uri": "sparse-strip.bin", "byteLength": len(sparse_binary)}],
            "bufferViews": [{"byteLength": 3}, {"byteOffset": 4, "byteLength": 36}],
            "accessors": [{"componentType": 5126, "count": 3, "type": "VEC3",
                           "sparse": {"count": 3,
                                      "indices": {"bufferView": 0, "componentType": 5121},
                                      "values": {"bufferView": 1}}}],
            "meshes": [{"primitives": [{"mode": 5, "attributes": {"POSITION": 0}}]}],
            "nodes": [{"name": "SPARSE_STRIP", "mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
        }
        sparse_path.write_text(json.dumps(sparse_doc), encoding="utf-8")
        sparse_out, sparse_report = geometry.prepare_gltf(sparse_path, import_dir, draw_mode="auto")
        normalized = json.loads(sparse_out.read_text(encoding="utf-8"))
        normalized_primitive = normalized["meshes"][0]["primitives"][0]
        assert normalized_primitive["mode"] == 4
        assert sparse_report["triangles"] == 1
        spec = {"aircraft_path": str(folder), "models": [{"path": str(source), "role": "exterior"}],
                "skinning": "strip", "draw_mode": "auto", "filter_runtime": True,
                "output": str(folder / "geometry.blend"), "exclude_objects": ["WHEEL_LEFT"],
                "mirror_objects": [{"source": "WING_LEFT", "target": "WHEEL_LEFT", "axis": "X"}],
                "texture_dirs": [], "texture_overrides": {}, "converted_normal_dir": None,
                "missing_fallback_dirs": []}
        review = []
        report = worker.build_geometry(spec, review)
        catalog = {item["name"]: item for item in report["object_catalog"]}
        assert catalog["WING_LEFT"]["included"] is True
        assert catalog["WHEEL_LEFT"]["included"] is False
        assert "WHEEL_LEFT" not in bpy.data.objects
        assert "WHEEL_LEFT" in report["geometry_fixes"]
        assert bpy.data.objects["WING_LEFT"].hide_get()
        texture_report = worker.build_textures(spec, [])
        assert texture_report["applied_materials"]
        assert not bpy.data.objects["WING_LEFT"].hide_get()
        # A zero-scale animation driver must not cause manual mode to invert
        # a singular transform: manual preserves aircraft-space positions.
        doc["nodes"][0].update({"skin": 0, "scale": [0, 0, 0]})
        doc["skins"] = [{"joints": [1]}]
        geometry.manual_skin_vertices(doc, binary, bytearray(binary))
    check_mirrors()
    check_placements()
    print("BLENDER_WORKER_CHECKS_PASSED")


if __name__ == "__main__":
    main()

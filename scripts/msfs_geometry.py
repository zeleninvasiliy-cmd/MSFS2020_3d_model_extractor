"""Aircraft-agnostic MSFS glTF preparation and Blender import helpers."""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import bpy
import numpy as np
from mathutils import Vector

from msfs_gltf import combine_buffers, load_gltf, unsupported_geometry_extensions


RUNTIME_NODE_TOKENS = ("blur", "frost", "colision", "collision", "occluder", "_slow", "tuto_")
INVISIBLE_EXTENSIONS = {"ASOBO_material_invisible", "ASOBO_material_environment_occluder"}
GLASS_EXTENSIONS = {"ASOBO_material_kitty_glass", "ASOBO_material_glass", "ASOBO_material_windshield_v2"}
RUNTIME_MATERIALS = {"PROPELERSIDE", "TutoMeshes"}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    default = bpy.data.collections.get("Collection")
    if default:
        bpy.data.collections.remove(default)


def import_gltf(path: Path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
    after = set(bpy.data.objects)
    imported = sorted(after - before, key=lambda obj: obj.name)
    if not imported:
        raise RuntimeError(f"No objects imported from {path}")
    return imported


def read_accessor(document, binary, index, dtype, width):
    accessor = document["accessors"][index]
    dtype = np.dtype(dtype)
    count = accessor["count"]

    def read_view(view_index, byte_offset, item_count, item_width, item_dtype):
        view = document["bufferViews"][view_index]
        if view.get("buffer", 0) != 0:
            raise ValueError(f"Accessor {index}: only one local buffer is supported")
        view_offset = int(view.get("byteOffset", 0))
        offset = view_offset + int(byte_offset)
        stride = int(view.get("byteStride", item_width * item_dtype.itemsize))
        view_end = view_offset + int(view["byteLength"])
        end = offset + max(0, item_count - 1) * stride + (item_width * item_dtype.itemsize if item_count else 0)
        if item_count < 0 or offset < 0 or stride < item_width * item_dtype.itemsize or end > min(len(binary), view_end):
            raise ValueError(f"Accessor {index}: invalid bounds/stride or truncated BIN")
        return np.ndarray((item_count, item_width), item_dtype, buffer=binary, offset=offset,
                          strides=(stride, item_dtype.itemsize))

    if count < 0:
        raise ValueError(f"Accessor {index}: отрицательный count")
    if "bufferView" in accessor:
        result = read_view(accessor["bufferView"], accessor.get("byteOffset", 0), count, width, dtype)
    elif "sparse" in accessor:
        result = np.zeros((count, width), dtype=dtype)
    else:
        raise ValueError(f"Accessor {index}: отсутствует bufferView и sparse-данные")

    sparse = accessor.get("sparse")
    if sparse is not None:
        sparse_count = int(sparse.get("count", -1))
        if sparse_count < 0 or sparse_count > count:
            raise ValueError(f"Accessor {index}: invalid sparse count")
        indices = sparse.get("indices") or {}
        values = sparse.get("values") or {}
        index_dtype = {5121: np.dtype("u1"), 5123: np.dtype("<u2"), 5125: np.dtype("<u4")}.get(
            indices.get("componentType"))
        if index_dtype is None:
            raise ValueError(f"Accessor {index}: unsupported sparse index component")
        sparse_indices = read_view(indices["bufferView"], indices.get("byteOffset", 0), sparse_count, 1,
                                   index_dtype)[:, 0].astype(np.int64)
        if np.any(sparse_indices < 0) or np.any(sparse_indices >= count):
            raise ValueError(f"Accessor {index}: sparse index outside accessor")
        sparse_values = read_view(values["bufferView"], values.get("byteOffset", 0), sparse_count, width, dtype)
        result = np.array(result, copy=True)
        result[sparse_indices] = sparse_values
    return result


def triangulate_primitive(document, source_binary, output_binary, primitive):
    """Convert triangle strip/fan to a regular triangle index accessor."""
    mode = int(primitive.get("mode", 4))
    if mode not in {5, 6}:
        return None
    attributes = primitive.get("attributes") or {}
    position_index = attributes.get("POSITION")
    if position_index is None:
        raise ValueError("Triangle strip/fan primitive has no POSITION accessor")
    position_count = int(document["accessors"][position_index]["count"])
    index_index = primitive.get("indices")
    if index_index is None:
        indices = np.arange(position_count, dtype=np.uint32)
    else:
        index_accessor = document["accessors"][index_index]
        index_dtype = {5121: "u1", 5123: "<u2", 5125: "<u4"}.get(index_accessor.get("componentType"))
        if index_dtype is None:
            raise ValueError(f"Unsupported primitive index component {index_accessor.get('componentType')}")
        indices = read_accessor(document, source_binary, index_index, index_dtype, 1)[:, 0].astype(np.uint32)
    if len(indices) < 3:
        raise ValueError("Triangle strip/fan has fewer than three indices")
    triangles = []
    if mode == 5:
        for offset in range(len(indices) - 2):
            tri = (indices[offset], indices[offset + 1], indices[offset + 2])
            triangles.append(tri if offset % 2 == 0 else (tri[2], tri[1], tri[0]))
    else:
        for offset in range(1, len(indices) - 1):
            triangles.append((indices[0], indices[offset], indices[offset + 1]))
    flat = np.asarray(triangles, dtype="<u4").reshape(-1)
    if np.any(flat >= position_count):
        raise ValueError("Triangle strip/fan index points outside POSITION accessor")
    primitive["indices"] = append_accessor(document, output_binary, flat, 5125, "SCALAR", 34963)
    primitive["mode"] = 4
    return len(triangles)


def local_buffer_path(source_path, document):
    """Compatibility helper for legacy callers that need a BIN path."""
    asset = load_gltf(source_path)
    if asset.source_format != "gltf" or len(asset.buffers) != 1:
        raise ValueError(f"{source_path.name}: источник содержит не один локальный BIN; используйте load_gltf")
    uri = str((document.get("buffers") or [{}])[0].get("uri") or "")
    filename = unquote(uri)
    if not filename or Path(filename).name != filename or any(char in filename for char in ("/", "\\", ":")):
        raise ValueError(f"{source_path.name}: требуется один локальный BIN рядом с glTF")
    return source_path.with_name(filename)


def append_accessor(document, binary, values, component_type, shape, target):
    binary.extend(b"\x00" * (-len(binary) % 4))
    data = values.tobytes()
    views = document["bufferViews"]
    accessors = document["accessors"]
    accessors.append({"bufferView": len(views), "componentType": component_type,
                      "count": len(values), "type": shape})
    views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": target})
    binary.extend(data)
    return len(accessors) - 1


def normalize_scalar_skin_weights(document, original, binary):
    """Expand MSFS one-joint scalar weights into Blender-compatible VEC4 data."""
    converted = {}
    repairs = []
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes", {})
            for semantic in ("WEIGHTS_0", "WEIGHTS_1"):
                index = attributes.get(semantic)
                if index is None or document["accessors"][index].get("type") != "SCALAR":
                    continue
                if index not in converted:
                    accessor = document["accessors"][index]
                    if accessor.get("componentType") != 5126:
                        raise ValueError(f"{semantic}: SCALAR skin weight must use FLOAT component")
                    values = read_accessor(document, original, index, "<f4", 1)
                    if not np.isfinite(values).all():
                        raise ValueError(f"{semantic}: non-finite scalar skin weight")
                    padded = np.zeros((len(values), 4), dtype="<f4")
                    padded[:, 0] = values[:, 0]
                    converted[index] = append_accessor(document, binary, padded, 5126, "VEC4", 34962)
                    repairs.append({"source_accessor": int(index), "target_accessor": int(converted[index]),
                                    "vertices": int(len(values))})
                attributes[semantic] = converted[index]
    return repairs


def _node_local_matrix(node):
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype="<f4").reshape(4, 4).T
    translation = np.asarray(node.get("translation", (0, 0, 0)), dtype="<f4")
    scale = np.asarray(node.get("scale", (1, 1, 1)), dtype="<f4")
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    rotation = np.asarray((
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0),
        (0, 0, 0, 1),
    ), dtype="<f4")
    result = rotation.copy()
    result[:3, :3] *= scale[np.newaxis, :]
    result[:3, 3] = translation
    return result


def _node_world_matrices(document):
    nodes = document.get("nodes", [])
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            child = int(child)
            if not 0 <= child < len(nodes) or child in parents:
                raise ValueError("glTF hierarchy has an invalid or multiply parented child")
            parents[child] = index
    cache = {}
    active = set()

    def world(index):
        if index in cache:
            return cache[index]
        if index in active:
            raise ValueError("glTF hierarchy contains a cycle")
        active.add(index)
        local = _node_local_matrix(nodes[index])
        parent = parents.get(index)
        cache[index] = world(parent) @ local if parent is not None else local
        active.remove(index)
        return cache[index]

    return [world(index) for index in range(len(nodes))]


def _read_float_attribute(document, binary, accessor_index, width):
    accessor = document["accessors"][accessor_index]
    component = accessor.get("componentType")
    dtype = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}.get(component)
    if dtype is None:
        raise ValueError(f"Unsupported skin attribute component {component}")
    values = read_accessor(document, binary, accessor_index, dtype, width).astype("<f4")
    if accessor.get("normalized"):
        values /= {5121: 255.0, 5123: 65535.0, 5125: 4294967295.0}[component]
    return values


def manual_skin_vertices(document, original, binary, preserve_pivots=()):
    """Preserve MSFS static aircraft-space positions and remove animation pivots.

    This mode deliberately does not evaluate joint matrices (use bake/hybrid
    for that). Evaluating unused matrices wasted memory and failed on valid
    animation drivers with zero-scale pivots.
    """
    repairs = []
    for node_index, node in enumerate(document.get("nodes", [])):
        skin_index = node.get("skin")
        mesh_index = node.get("mesh")
        if skin_index is None or mesh_index is None:
            continue
        skin = document["skins"][skin_index]
        joints = [int(item) for item in skin.get("joints", [])]
        if not joints:
            continue
        mesh = document["meshes"][mesh_index]
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes or "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
                continue
            position_index = int(attributes["POSITION"])
            position_accessor = document["accessors"][position_index]
            position_width = 4 if position_accessor.get("type") == "VEC4" else 3
            # Use the working buffer: scalar WEIGHTS accessors may have been
            # expanded to appended VEC4 accessors just before this pass.
            positions = _read_float_attribute(document, binary, position_index, position_width)
            positions_h = np.ones((len(positions), 4), dtype="<f4")
            positions_h[:, :3] = positions[:, :3]
            if not np.isfinite(positions).all():
                raise ValueError(f"Node {node_index}: non-finite positions")
            # Some MSFS packages store static vertices in aircraft-space while
            # the joint data is only an animation driver. Keep the source
            # position and remove only the animation pivot below.
            transformed = positions_h
            new_index = append_accessor(document, binary, transformed[:, :3].astype("<f4"), 5126, "VEC3", 34962)
            attributes["POSITION"] = new_index
            repairs.append({"node": node.get("name", str(node_index)), "mesh": int(mesh_index),
                            "vertices": int(len(positions)), "position_accessor": int(new_index)})
        # MSFS skinned meshes commonly keep their vertices in aircraft/world
        # coordinates while the node transform is only an animation pivot.
        # Blender would apply that pivot a second time after the skin is
        # removed (the characteristic doubled engine offset and flipped wing
        # details). The preserved vertices are self-contained, so remove
        # the mesh-node transform but leave all non-skinned hierarchy intact.
        node_name = node.get("name", str(node_index))
        if node_name not in preserve_pivots:
            node.pop("matrix", None)
            node.pop("translation", None)
            node.pop("rotation", None)
            node.pop("scale", None)
            repairs.append({"node": node_name, "transform_reset": True})
        else:
            repairs.append({"node": node_name, "transform_preserved": True})
    return repairs


def unpack_indices(document, original, binary, primitive):
    draw = primitive["extras"]["ASOBO_primitive"]
    start = draw.get("StartIndex", 0)
    count = 3 * draw["PrimitiveCount"]
    index = primitive["indices"]
    accessor = document["accessors"][index]
    if primitive.get("mode", 4) != 4 or not 0 <= start < start + count <= accessor["count"]:
        raise ValueError(f"Invalid MSFS triangle draw {draw}")
    dtype = {5123: "<u2", 5125: "<u4"}[accessor["componentType"]]
    triangles = read_accessor(document, original, index, dtype, 1)[start:start + count].reshape(-1, 3)
    # Packaged MSFS stores the opposite winding from standard glTF.
    indices = triangles[:, ::-1].astype("<u4").ravel() + draw.get("BaseVertexIndex", 0)
    position_count = document["accessors"][primitive["attributes"]["POSITION"]]["count"]
    if int(indices.max()) >= position_count:
        raise ValueError(f"MSFS triangle draw points outside its position accessor: {draw}")
    primitive["indices"] = append_accessor(document, binary, indices, 5125, "SCALAR", 34963)
    return count // 3


def unpack_vertex_attributes(document, original, binary, attributes, converted):
    for semantic, index in list(attributes.items()):
        accessor = document["accessors"][index]
        component = accessor["componentType"]
        if component == 5126 or semantic.startswith(("JOINTS_", "WEIGHTS_")):
            continue
        if (semantic, index) not in converted:
            if semantic.startswith("TEXCOORD_") and component == 5122:
                values = read_accessor(document, original, index, "<f2", 2).astype("<f4")
                shape = "VEC2"
            elif semantic in {"NORMAL", "TANGENT"} and component == 5120:
                width = 3 if semantic == "NORMAL" else 4
                packed = read_accessor(document, original, index, "i1", 4)
                values = np.maximum(packed[:, :width].astype("<f4") / 127.0, -1.0)
                shape = f"VEC{width}"
            elif semantic.startswith("COLOR_") and component == 5120:
                values = read_accessor(document, original, index, "u1", 4).astype("<f4") / 255.0
                shape = "VEC4"
            elif semantic.startswith("COLOR_") and component == 5123:
                values = read_accessor(document, original, index, "<f2", 4).astype("<f4")
                shape = "VEC4"
            else:
                raise ValueError(f"Unhandled MSFS vertex attribute {semantic}: {accessor}")
            if not np.isfinite(values).all():
                raise ValueError(f"Non-finite values in {semantic} accessor {index}")
            converted[semantic, index] = append_accessor(document, binary, values, 5126, shape, 34962)
        attributes[semantic] = converted[semantic, index]


def prepare_gltf(source_path: Path, import_dir: Path, *, draw_mode="msfs", filter_runtime=True,
                 manual_skin=False, preserve_manual_pivots=()):
    """Adapt packaged MSFS geometry into a standalone, untextured glTF."""
    asset = load_gltf(source_path)
    document = asset.document
    unsupported = unsupported_geometry_extensions(document)
    if unsupported:
        raise ValueError(f"{source_path}: неподдерживаемое сжатие геометрии: {', '.join(unsupported)}. "
                         "Распакуйте glTF в экспортёре и повторите сборку.")
    original = combine_buffers(asset, document)
    buffer = document["buffers"][0]
    binary = bytearray(original)
    scalar_weight_repairs = normalize_scalar_skin_weights(document, original, binary)
    materials = document.get("materials", [])
    removed_materials = set()
    for index, material in enumerate(materials):
        name = material.get("name", f"material_{index}")
        extensions = material.get("extensions", {}).keys()
        if filter_runtime and (INVISIBLE_EXTENSIONS & extensions or name in RUNTIME_MATERIALS):
            removed_materials.add(index)
        preview = "solid"
        if GLASS_EXTENSIONS & extensions or name.lower() in {"glass", "windshield"}:
            preview = "glass"
        elif material.get("alphaMode") == "BLEND":
            preview = "decal"
        materials[index] = {"name": name, "extras": {"msfs_material_index": index,
                            "msfs_original_material": name, "msfs_model": source_path.name,
                            "msfs_preview": preview}}

    nodes = document["nodes"]
    _node_world_matrices(document)  # reject cycles and invalid parent references
    meshes = document["meshes"]
    excluded_nodes = []
    for node in nodes:
        if "mesh" not in node:
            continue
        node.setdefault("extras", {})["msfs_source_node"] = node.get("name", "")
        if filter_runtime and any(token in node.get("name", "").lower() for token in RUNTIME_NODE_TOKENS):
            excluded_nodes.append(node["name"])
            node.pop("mesh")
            node.pop("skin", None)
    used_meshes = {node["mesh"] for node in nodes if "mesh" in node}
    mesh_instances = Counter(node["mesh"] for node in nodes if "mesh" in node)
    mesh_counts = {}
    total_triangles = 0
    converted = {}
    for index in sorted(used_meshes):
        mesh = meshes[index]
        # Keep the source index: filtering materials must not renumber the
        # primitive named in an error message about the user's own file.
        keep = [(number, primitive) for number, primitive in enumerate(mesh["primitives"])
                if primitive.get("material") not in removed_materials]
        if not keep:
            for node in nodes:
                if node.get("mesh") == index:
                    excluded_nodes.append(node.get("name", f"node_{nodes.index(node)}"))
                    node.pop("mesh")
                    node.pop("skin", None)
            continue
        mesh["primitives"] = [primitive for _, primitive in keep]
        mesh_name = mesh.get("name", f"mesh_{index}")
        mesh_counts.setdefault(mesh_name, 0)
        for primitive_index, primitive in keep:
            is_msfs = "ASOBO_primitive" in primitive.get("extras", {})
            if draw_mode == "msfs" and not is_msfs:
                raise ValueError(f"{source_path}: mesh '{mesh_name}', primitive {primitive_index} не содержит "
                                 "extras.ASOBO_primitive. Это обычный glTF, а не упакованный MSFS draw range. "
                                 "Используйте draw_mode=auto — он выбирает чтение по содержимому файла.")
            if draw_mode == "msfs" or (draw_mode == "auto" and is_msfs):
                count = unpack_indices(document, original, binary, primitive)
            else:
                triangulated = triangulate_primitive(document, original, binary, primitive)
                if triangulated is not None:
                    count = triangulated
                    indices = primitive["indices"]
                elif primitive.get("mode", 4) != 4:
                    raise ValueError(f"{mesh_name}: unsupported primitive mode {primitive.get('mode')}; "
                                     "supported modes are TRIANGLES, TRIANGLE_STRIP and TRIANGLE_FAN")
                else:
                    indices = primitive.get("indices", primitive["attributes"]["POSITION"])
                    size = document["accessors"][indices]["count"]
                    if size % 3:
                        raise ValueError(f"{mesh_name}: triangle index count {size} is not divisible by three")
                    count = size // 3
            mesh_counts[mesh_name] += count
            total_triangles += count * mesh_instances[index]
            # Packed ASOBO attributes use nonstandard half floats and signed
            # bytes. Ordinary glTF accessors must retain their own normalized
            # integer convention for Blender's importer to read correctly.
            if is_msfs:
                unpack_vertex_attributes(document, original, binary, primitive["attributes"], converted)

    manual_skin_repairs = (manual_skin_vertices(document, original, binary, preserve_manual_pivots)
                           if manual_skin else [])

    # Keep transforms and skins, but leave the source animations and DDS in place.
    for key in ("animations", "images", "textures", "samplers", "extensionsUsed", "extensionsRequired"):
        document.pop(key, None)
    buffer["byteLength"] = len(binary)
    buffer["uri"] = "geometry.bin"
    output_path = import_dir / source_path.name
    output_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    output_path.with_name(buffer["uri"]).write_bytes(binary)
    return output_path, {"mesh_triangles": mesh_counts, "excluded_nodes": sorted(excluded_nodes),
                         "triangles": total_triangles,
                         "scalar_weight_repairs": scalar_weight_repairs,
                         "manual_skin_repairs": manual_skin_repairs}


def move_to_collection(objects, collection):
    for obj in objects:
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        collection.objects.link(obj)


def neutralize_materials(objects):
    materials = set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        object_materials = set()
        for slot in obj.material_slots:
            if slot.material:
                object_materials.add(slot.material)
        if object_materials and all(mat.get("msfs_preview") == "decal" for mat in object_materials):
            obj.hide_set(True)
            obj["msfs_preview_hidden"] = True
        materials.update(object_materials)

    for material in materials:
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        preview = material.get("msfs_preview")
        if preview in {"glass", "decal"}:
            shader = nodes.new("ShaderNodeBsdfTransparent")
        else:
            shader = nodes.new("ShaderNodeBsdfPrincipled")
            color = (0.42, 0.46, 0.51, 1.0)
            shader.inputs["Base Color"].default_value = color
            shader.inputs["Roughness"].default_value = 0.72
            material.diffuse_color = color
        material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])


def scene_bounds(objects):
    points = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        raise RuntimeError("No mesh objects in imported geometry")
    lower = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    upper = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    return lower, upper


def main():
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve()
    model_paths = sorted(source.glob("*.gltf"))
    if len(model_paths) < 2:
        raise FileNotFoundError("Укажите папку с двумя glTF или используйте универсальный orchestrator.")
    exterior_path, cockpit_path = model_paths[:2]
    for path in (exterior_path, cockpit_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    clear_scene()
    scene = bpy.context.scene
    scene.name = f"{source.parent.name}_MSFS_Static_Geometry"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene["source_aircraft"] = source.name
    scene["source_format"] = "MSFS glTF"
    scene["geometry_stage"] = "LOD00 exterior + cockpit; neutral materials; animations not imported"

    root = bpy.data.collections.new("MSFS_AIRCRAFT")
    scene.collection.children.link(root)
    exterior_collection = bpy.data.collections.new("Exterior_LOD00")
    cockpit_collection = bpy.data.collections.new("Cockpit_LOD00")
    root.children.link(exterior_collection)
    root.children.link(cockpit_collection)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="msfs-gltf-", dir=output.parent) as directory:
        prepared_exterior, exterior_stats = prepare_gltf(exterior_path, Path(directory))
        prepared_cockpit, cockpit_stats = prepare_gltf(cockpit_path, Path(directory))
        exterior = import_gltf(prepared_exterior)
        move_to_collection(exterior, exterior_collection)
        cockpit = import_gltf(prepared_cockpit)
        move_to_collection(cockpit, cockpit_collection)
    imported = exterior + cockpit
    neutralize_materials(imported)

    bpy.ops.object.select_all(action="DESELECT")
    for objects, purpose in ((exterior, "Exterior Gear"), (cockpit, "Cockpit Yokes")):
        for obj in objects:
            if obj.type == "ARMATURE":
                obj["msfs_source_armature"] = obj.name
                obj.name = f"MSFS | {purpose} Skin"
                obj.data.name = obj.name
                obj.data.display_type = "STICK"
                obj.hide_set(True)
            elif obj.type == "EMPTY":
                obj.hide_set(True)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.color_type = "MATERIAL"
                space.region_3d.view_location = (0, 1.2, 0.0)
                space.region_3d.view_distance = 15
                space.region_3d.view_rotation = Vector((10, -12, 6)).to_track_quat("Z", "Y")
    bpy.context.view_layer.update()
    lower, upper = scene_bounds(imported)
    dimensions = upper - lower
    mesh_objects = [obj for obj in imported if obj.type == "MESH"]
    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
    vertices = sum(len(obj.data.vertices) for obj in mesh_objects)
    triangles = sum(len(obj.data.loop_triangles) for obj in mesh_objects)

    expected = exterior_stats["triangles"] + cockpit_stats["triangles"]
    if triangles != expected:
        raise ValueError(f"Imported {triangles} triangles, expected {expected} from MSFS draw ranges")
    for group in (exterior, cockpit):
        for obj in group:
            if obj.type == "MESH" and len(obj.data.uv_layers) != 2:
                raise ValueError(f"Missing UV set on {obj.name}")
    assert not bpy.data.actions
    assert not any(bone.custom_shape for obj in imported if obj.type == "ARMATURE" for bone in obj.pose.bones)

    report = {
        "source_package": source.name,
        "exterior": str(exterior_path.relative_to(source)),
        "cockpit": str(cockpit_path.relative_to(source)),
        "output": output.name,
        "blender": bpy.app.version_string,
        "collections": {"exterior": exterior_collection.name, "cockpit": cockpit_collection.name},
        "objects": len(imported),
        "mesh_objects": len(mesh_objects),
        "vertices": vertices,
        "triangles": triangles,
        "source_draw_ranges": {"exterior": exterior_stats, "cockpit": cockpit_stats},
        "skins": {obj.name: [mesh.name for mesh in mesh_objects
                             if any(mod.type == "ARMATURE" and mod.object == obj for mod in mesh.modifiers)]
                  for obj in imported if obj.type == "ARMATURE"},
        "dimensions_m": list(dimensions),
        "bounds_min_m": list(lower),
        "bounds_max_m": list(upper),
        "materials_neutralized": len({slot.material.name for obj in mesh_objects for slot in obj.material_slots if slot.material}),
        "animation_status": "not imported",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False, compress=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verified {triangles:,} triangles in {len(mesh_objects)} mesh objects")


if __name__ == "__main__":
    main()

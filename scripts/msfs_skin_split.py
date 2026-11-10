"""Generic skin-weight-based mesh splitting helpers."""

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msfs_geometry import read_accessor
from msfs_gltf import combine_buffers, load_gltf


CORNER_ID = "msfs_split_source_corner"
CONTROL_COLLECTION = "03_TAIL_AND_CONTROL_SURFACES"


def read_field(doc, binary, index):
    accessor = doc["accessors"][index]
    dtype = {5121: "u1", 5123: "<u2", 5126: "<f4"}[accessor["componentType"]]
    width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    return read_accessor(doc, binary, index, dtype, width)


def wing_groups(doc, binary, wing, hinge, rod):
    nodes = doc["nodes"]
    by_name = {node["name"]: i for i, node in enumerate(nodes) if "name" in node}
    children = {by_name[hinge]}
    pending = list(children)
    while pending:
        for child in nodes[pending.pop()].get("children", []):
            if child not in children:
                children.add(child)
                pending.append(child)
    groups = {nodes[i]["name"]: 1 for i in children}
    groups[rod] = 2
    return skin_groups(doc, binary, wing, wing.name, groups)


def skin_groups(doc, binary, wing, node_name, bone_groups):
    nodes = doc["nodes"]
    matches = [node for node in nodes if node.get("name") == node_name and "skin" in node and "mesh" in node]
    if len(matches) != 1:
        raise ValueError(f"{wing.name}: не найден однозначный исходный skin-узел {node_name}")
    node = matches[0]
    joint_names = [nodes[i].get("name") for i in doc["skins"][node["skin"]]["joints"]]
    missing = bone_groups.keys() - set(joint_names)
    if missing:
        raise ValueError(f"{wing.name}: в исходном skin нет костей {sorted(missing)}")
    joint_groups = np.array([bone_groups.get(name, 0) for name in joint_names])
    positions = []
    groups = []
    for primitive in doc["meshes"][node["mesh"]]["primitives"]:
        attrs = primitive["attributes"]
        if "WEIGHTS_1" in attrs and np.any(read_field(doc, binary, attrs["WEIGHTS_1"]) > 0):
            raise ValueError(f"{wing.name}: split_by_skin does not support active WEIGHTS_1; use split_spatial")
        positions.append(read_field(doc, binary, attrs["POSITION"]))
        weights = read_field(doc, binary, attrs["WEIGHTS_0"])
        joints = read_field(doc, binary, attrs["JOINTS_0"])[:, :weights.shape[1]]
        used = weights > 0
        if not np.all(used.any(axis=1)):
            raise ValueError(f"{wing.name}: a vertex has no skin weights")
        if np.any(used & (joints >= len(joint_groups))):
            raise ValueError(f"{wing.name}: индекс кости выходит за пределы skin")
        owners = joint_groups[np.where(used, joints, 0)]
        primary = owners[np.arange(len(weights)), weights.argmax(axis=1)]
        if np.any(used & (owners != primary[:, None])):
            raise ValueError(f"{wing.name}: mixed wing and aileron weights")
        groups.extend(primary.tolist())

    gltf = np.concatenate(positions)[:, [0, 2, 1]] * [1, -1, 1]
    local = np.asarray([v.co for v in wing.data.vertices])
    if local.shape != gltf.shape or not np.array_equal(local, gltf):
        raise ValueError(f"{wing.name}: source and Blender vertex order differ")
    if any(len({groups[i] for i in face.vertices}) != 1 for face in wing.data.polygons):
        raise ValueError(f"{wing.name}: a face crosses the split boundary")
    return groups


def filter_mesh(mesh, groups, group):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        discard = [v for v in bm.verts if groups[v.index] != group]
        bmesh.ops.delete(bm, geom=discard, context="VERTS")
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def piece(wing, name, collection, pivot):
    obj = wing.copy()
    obj.data = wing.data.copy()
    obj.name = name
    obj.data.name = name
    collection.objects.link(obj)
    old_world = wing.matrix_world.copy()
    new_world = old_world.copy()
    new_world.translation = pivot
    obj.parent = None
    obj.matrix_world = new_world
    obj.data.transform(Matrix.Translation((new_world.inverted() @ old_world).translation))
    return obj


def split_wing(wing, groups, side, hinge, rod, collection):
    parts = {1: (f"AILERON_{side}", collection, bpy.data.objects[hinge].matrix_world.translation)}
    if 2 in groups:
        parts[2] = (f"{side.lower()}_aileron_rod", collection, bpy.data.objects[rod].matrix_world.translation)
    return split_mesh(wing, groups, parts)


def split_mesh(wing, groups, parts):
    if set(groups) != {0, *parts}:
        raise ValueError(f"{wing.name}: хотя бы одна часть или остаток исходного объекта пусты")
    if any(name in bpy.data.objects for name, _, _ in parts.values()):
        raise ValueError(f"{wing.name}: имя одной из новых деталей уже занято")
    if wing.data.users > 1:
        wing.data = wing.data.copy()
    mesh = wing.data
    world = wing.matrix_world.copy()
    positions = [world @ mesh.vertices[loop.vertex_index].co for loop in mesh.loops]
    normals = [normal.vector.copy() for normal in mesh.corner_normals]
    uv = {layer.name: [point.vector.copy() for point in layer.uv] for layer in mesh.uv_layers}
    materials = [0] * len(mesh.loops)
    for polygon in mesh.polygons:
        for i in polygon.loop_indices:
            materials[i] = polygon.material_index
    source_faces = len(mesh.polygons)
    attr = mesh.attributes.new(CORNER_ID, "INT", "CORNER")
    attr.data.foreach_set("value", np.arange(len(mesh.loops), dtype=np.int32))

    pieces = [(wing, 0), *((piece(wing, *options), group) for group, options in parts.items())]

    result = {}
    seen = []
    for obj, group in pieces:
        filter_mesh(obj.data, groups, group)
        corners = [value.value for value in obj.data.attributes[CORNER_ID].data]
        seen.extend(corners)
        if obj.data.has_custom_normals:
            obj.data.normals_split_custom_set([normals[i] for i in corners])
        if any((obj.matrix_world @ obj.data.vertices[loop.vertex_index].co - positions[i]).length > 2e-6
               for loop, i in zip(obj.data.loops, corners)):
            raise ValueError(f"{obj.name}: vertex moved during split")
        for layer in obj.data.uv_layers:
            if any(value.vector != uv[layer.name][i] for value, i in zip(layer.uv, corners)):
                raise ValueError(f"{obj.name}: UV coordinates changed")
        for face in obj.data.polygons:
            if any(face.material_index != materials[corners[i]] for i in face.loop_indices):
                raise ValueError(f"{obj.name}: material assignments changed")
        obj.data.attributes.remove(obj.data.attributes[CORNER_ID])
        result[obj.name] = len(obj.data.polygons)
    if sorted(seen) != list(range(len(positions))) or sum(result.values()) != source_faces:
        raise ValueError(f"{wing.name}: faces were lost or duplicated")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True, type=Path)
    parser.add_argument("--gltf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--object", required=True)
    parser.add_argument("--source-node")
    parser.add_argument("--parts", required=True, type=Path,
                        help="JSON: [{name, bones, collection?, pivot?}, ...]")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    asset = load_gltf(args.gltf)
    doc = asset.document
    binary = combine_buffers(asset, doc)
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()), load_ui=False, use_scripts=False)
    obj = bpy.data.objects[args.object]
    rules = json.loads(args.parts.read_text(encoding="utf-8"))
    groups_by_bone = {}
    parts = {}
    root = bpy.data.collections.get(CONTROL_COLLECTION) or bpy.context.scene.collection
    for index, rule in enumerate(rules, start=1):
        name = rule["name"]
        groups_by_bone.update(dict.fromkeys(rule["bones"], index))
        collection = root
        for level in rule.get("collection", CONTROL_COLLECTION).split("/"):
            collection = bpy.data.collections.get(level) or collection
        pivot = bpy.data.objects.get(rule.get("pivot", args.object))
        parts[index] = (name, collection, (pivot or obj).matrix_world.translation)
    groups = skin_groups(doc, binary, obj, args.source_node or args.object, groups_by_bone)
    result = split_mesh(obj, groups, parts)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

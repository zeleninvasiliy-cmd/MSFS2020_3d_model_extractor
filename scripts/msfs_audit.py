"""Create a machine-readable audit for a Blender checkpoint."""

import hashlib
import json
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Vector


def clean_name(name):
    return re.sub(r"\.\d{3}$", "", name).casefold()


def bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return [list(map(float, values)) for values in (
        [min(point[i] for point in points) for i in range(3)],
        [max(point[i] for point in points) for i in range(3)],
    )]


def mesh_hash(obj, world=False):
    digest = hashlib.sha256()
    matrix = obj.matrix_world if world else None
    for vertex in obj.data.vertices:
        point = matrix @ vertex.co if matrix else vertex.co
        digest.update(struct.pack("<3f", *point))
    for polygon in obj.data.polygons:
        digest.update(struct.pack("<II", len(polygon.vertices), polygon.material_index))
        digest.update(struct.pack(f"<{len(polygon.vertices)}I", *polygon.vertices))
    return digest.hexdigest()


def components(obj):
    count = len(obj.data.vertices)
    parent = list(range(count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in obj.data.edges:
        left, right = map(find, edge.vertices)
        if left != right:
            parent[right] = left
    groups = defaultdict(list)
    for vertex in obj.data.vertices:
        groups[find(vertex.index)].append(vertex)
    result = []
    for vertices in groups.values():
        if len(vertices) < 3:
            continue
        points = [obj.matrix_world @ vertex.co for vertex in vertices]
        low = [min(point[i] for point in points) for i in range(3)]
        high = [max(point[i] for point in points) for i in range(3)]
        result.append({"vertices": len(vertices), "min": low, "max": high,
                       "center": [(a + b) / 2 for a, b in zip(low, high)]})
    result.sort(key=lambda item: item["vertices"], reverse=True)
    return result


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    objects_only = "--objects-only" in args
    args = [value for value in args if value != "--objects-only"]
    blend, output = map(Path, args)
    bpy.ops.wm.open_mainfile(filepath=str(blend.resolve()), load_ui=False, use_scripts=False)
    objects = []
    by_name = defaultdict(list)
    by_local = defaultdict(list)
    by_world = defaultdict(list)
    disconnected = []
    gear = []
    tokens = ("gear", "wheel", "tire", "tyre", "strut", "oleo", "fork", "nose", "axle", "landing")
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        item = {"name": obj.name, "source": obj.get("msfs_pipeline_source", ""), "parent": obj.parent.name if obj.parent else None,
                "collections": [col.name for col in obj.users_collection], "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons), "bounds": bounds(obj), "materials": [slot.name for slot in obj.material_slots]}
        objects.append(item)
        if objects_only:
            continue
        by_name[clean_name(obj.name)].append(obj.name)
        by_local[mesh_hash(obj)].append(obj.name)
        by_world[mesh_hash(obj, True)].append(obj.name)
        if any(token in obj.name.casefold() for token in tokens):
            gear.append(item)
        parts = components(obj)
        if len(parts) > 1:
            centers = [Vector(part["center"]) for part in parts]
            # Avoid quadratic work for meshes containing thousands of small
            # disconnected rivets/gauge markings. Axis extrema are enough to
            # locate distant components for this diagnostic.
            extrema = {tuple(min(centers, key=lambda point: point[axis])) for axis in range(3)}
            extrema.update(tuple(max(centers, key=lambda point: point[axis])) for axis in range(3))
            probes = [Vector(point) for point in extrema]
            spread = max((left - right).length for left in probes for right in probes)
            if spread > 0.5:
                disconnected.append({"name": obj.name, "source": item["source"], "component_count": len(parts),
                                     "spread_m": spread, "components": parts[:20]})
    duplicates = lambda groups: [names for names in groups.values() if len(names) > 1]
    report = {
        "blend": str(blend.resolve()),
        "summary": {"mesh_objects": len(objects), "same_base_name_groups": len(duplicates(by_name)),
                    "same_local_geometry_groups": len(duplicates(by_local)), "same_world_geometry_groups": len(duplicates(by_world)),
                    "gear_candidates": len(gear), "far_disconnected_objects": len(disconnected)},
        "same_base_names": duplicates(by_name), "same_local_geometry": duplicates(by_local),
        "same_world_geometry": duplicates(by_world), "gear_candidates": gear,
        "far_disconnected_objects": disconnected, "objects": objects,
        "objects_only": objects_only,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

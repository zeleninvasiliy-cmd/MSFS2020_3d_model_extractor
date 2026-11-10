"""Organize arbitrary MSFS objects into searchable nested collections."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--root", default="MSFS_AIRCRAFT")
    return parser.parse_args(argv)


def ensure_collection(parent, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Collection name must not be empty")
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if col == parent or parent.name in {child.name for child in col.children_recursive}:
        raise ValueError(f"Collection override would create a cycle: {name}")
    if col.name not in {child.name for child in parent.children}:
        parent.children.link(col)
    return col


def source_kind(obj):
    source_role = obj.get("msfs_source_role", "")
    if source_role:
        return source_role.upper()
    # Retain classification of older checkpoints after their SOURCE
    # collection was replaced by a leaf collection such as 03_CONTROLS.
    source = obj.get("msfs_pipeline_source", "").upper()
    if "INTERIOR" in source or "COCKPIT" in source:
        return "INTERIOR"
    names = {col.name.upper() for col in obj.users_collection}
    if any("INTERIOR" in name or "COCKPIT" in name for name in names):
        return "INTERIOR"
    return "EXTERIOR"


def classify(obj):
    if obj.type == "EMPTY":
        return ("00_HIDDEN_TRANSFORMS", "TRANSFORM_NODES")
    name = obj.name.upper()
    interior = source_kind(obj) == "INTERIOR"

    if any(t in name for t in ("DOOR", "DOOR_")):
        if "LEFT" in name or name.endswith("_L"):
            return ("01_EXTERIOR", "04_DOORS", "LEFT_DOOR")
        if "RIGHT" in name or name.endswith("_R"):
            return ("01_EXTERIOR", "04_DOORS", "RIGHT_DOOR")
        return ("01_EXTERIOR", "04_DOORS", "DOOR_DETAILS")

    if interior:
        if any(t in name for t in ("GAUGE", "INSTRUMENT", "DIAL_", "ALTIMETER", "AIRSPEED", "RPM_", "VSI_", "COMPASS")):
            return ("02_INTERIOR", "02_INSTRUMENTS")
        if any(t in name for t in ("PANEL", "DASH", "CONSOLE", "RADIO", "GTN", "COM_", "NAV_", "GPS")):
            return ("02_INTERIOR", "01_PANEL_AND_RADIO")
        if any(t in name for t in ("SEAT", "CUSHION", "BELT", "HARNESS")):
            return ("02_INTERIOR", "04_SEATS")
        if any(t in name for t in ("YOKE", "PEDAL", "THROTTLE", "MIXTURE", "CONTROL", "SWITCH", "LEVER", "TRIM", "CABLE")):
            return ("02_INTERIOR", "03_CONTROLS")
        return ("02_INTERIOR", "05_INTERIOR_DETAILS")

    if any(t in name for t in ("ELEVATOR", "RUDDER", "AILERON", "FLAP", "SLAT", "STABILIZER", "TAILPLANE", "TRIM_TAB", "TRIMTAB")):
        return ("01_EXTERIOR", "03_TAIL_AND_CONTROL_SURFACES")
    if any(t in name for t in ("WING", "WINGTIP")):
        return ("01_EXTERIOR", "02_WINGS")
    if any(t in name for t in ("GEAR", "WHEEL", "TIRE", "BRAKE", "STRUT", "SKID")):
        return ("01_EXTERIOR", "05_LANDING_GEAR")
    if any(t in name for t in ("PROP", "ENGINE", "EXHAUST", "CYLINDER", "OIL_", "CARB", "MANIFOLD")):
        return ("01_EXTERIOR", "06_ENGINE_AND_PROP")
    if any(t in name for t in ("LIGHT", "BEACON", "NAV_", "LANDING")):
        return ("01_EXTERIOR", "07_LIGHTS")
    if any(t in name for t in ("GLASS", "WINDOW", "WINDSHIELD", "CANOPY", "FUSE", "BODY", "NOSE", "TAILCONE")):
        return ("01_EXTERIOR", "01_FUSELAGE_AND_GLAZING")
    return ("01_EXTERIOR", "08_EXTERNAL_DETAILS")


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()), load_ui=False, use_scripts=False)
    root = bpy.data.collections.get(args.root)
    if root is None:
        root = bpy.data.collections.new(args.root)
        bpy.context.scene.collection.children.link(root)

    old_names = {col.name for col in root.children
                 if col.name.startswith("Exterior_") or col.name.startswith("Interior_")}
    objects = list(bpy.data.objects)
    assignments = {}
    for obj in objects:
        path = classify(obj)
        parent = root
        for part in path:
            parent = ensure_collection(parent, part)
        for old in list(obj.users_collection):
            if old != parent:
                old.objects.unlink(obj)
        if obj.name not in parent.objects:
            parent.objects.link(obj)
        assignments[obj.name] = "/".join(path)
        if obj.type == "EMPTY":
            obj.hide_set(True)

    for name in old_names:
        col = bpy.data.collections.get(name)
        if col is not None and len(col.objects) == 0 and len(col.children) == 0:
            bpy.data.collections.remove(col)

    bpy.context.view_layer.update()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), check_existing=False, compress=True)
    counts = Counter(assignments.values())
    report = {
        "input": str(args.blend.resolve()),
        "output": str(args.output.resolve()),
        "object_count": len(assignments),
        "collection_counts": dict(sorted(counts.items())),
        "empty_transform_nodes": sum(1 for obj in objects if obj.type == "EMPTY"),
        "mesh_objects": sum(1 for obj in objects if obj.type == "MESH"),
        "relationship_lines": "kept disabled in viewport; parent transforms unchanged",
        "assignments": assignments,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"objects": len(assignments), "collections": len(counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

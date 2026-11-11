"""Blender worker for the aircraft-agnostic MSFS universal pipeline."""

import fnmatch
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import msfs_materials as pbr
import msfs_geometry as geometry_tools
from msfs_dds_normals import decode_normal, normal_format
import msfs_collections as collections
import msfs_skin_split as skin_split


ROOT = "MSFS_AIRCRAFT"
CORNER_ID = "msfs_spatial_source_corner"
FACE_ID = "msfs_spatial_source_face"


def strip_skinning(prepared_path):
    document = json.loads(prepared_path.read_text(encoding="utf-8"))
    removed_attributes = 0
    for node in document.get("nodes", []):
        node.pop("skin", None)
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            for semantic in ("JOINTS_0", "JOINTS_1", "WEIGHTS_0", "WEIGHTS_1"):
                if semantic in primitive.get("attributes", {}):
                    primitive["attributes"].pop(semantic)
                    removed_attributes += 1
    skins = len(document.get("skins", []))
    document.pop("skins", None)
    prepared_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    return {"skins_removed": skins, "skinning_attributes_removed": removed_attributes}


def repair_skin_roots(prepared_path):
    document = json.loads(prepared_path.read_text(encoding="utf-8"))
    nodes = document.get("nodes", [])
    by_name = {node.get("name"): index for index, node in enumerate(nodes) if node.get("name")}
    repaired = []
    for skin in document.get("skins", []):
        name = skin.get("name")
        if name in by_name:
            skin["skeleton"] = by_name[name]
            repaired.append({"skin": name, "skeleton": by_name[name]})
    prepared_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    return repaired


def apply_static_pose(objects):
    rigs = [obj for obj in objects if obj.type == "ARMATURE"]
    empties = [obj for obj in objects if obj.type == "EMPTY"]
    survivor_names = [obj.name for obj in objects if obj.type != "ARMATURE"]
    applied, failed = [], []
    for obj in objects:
        if obj.type != "MESH":
            continue
        modifiers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        if not modifiers:
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        for modifier in modifiers:
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                applied.append(f"{obj.name}:{modifier.name}")
            except RuntimeError as exc:
                failed.append(f"{obj.name}:{modifier.name}:{exc}")
        obj.select_set(False)
    world_matrices = {obj.name: obj.matrix_world.copy() for obj in objects
                      if obj.name in bpy.data.objects and obj.type != "ARMATURE"}
    for rig in rigs:
        if rig.name in bpy.data.objects:
            bpy.data.objects.remove(rig, do_unlink=True)
    for obj in empties:
        if obj.name in bpy.data.objects:
            obj.hide_set(True)
    for name, matrix in world_matrices.items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.matrix_world = matrix
    return {"armatures_removed": len(rigs), "empties_hidden": len(empties),
            "survivor_names": survivor_names, "modifiers_applied": applied,
            "modifier_failures": failed}


def meshes():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def object_catalog():
    """Describe real Blender names, including items omitted by user filters."""
    return [{"name": obj.name, "type": obj.type,
             "collections": sorted(col.name for col in obj.users_collection),
             "group_path": list(collections.classify(obj)),
             "source": obj.get("msfs_pipeline_source", ""),
             "source_node": obj.get("msfs_source_node", obj.name),
             "parent": obj.parent.name if obj.parent else None,
             "included": True}
            for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name.casefold())]


def scene_stats():
    objects = meshes()
    if not objects:
        raise ValueError("В сцене нет мешей. Проверьте models и выбранные LOD.")
    if bpy.data.actions or any(o.type == "ARMATURE" for o in bpy.context.scene.objects):
        raise ValueError("Ожидалась статическая сцена без арматур и Actions.")
    for obj in objects:
        obj.data.calc_loop_triangles()
    low, high = geometry_tools.scene_bounds(objects)
    return {
        "mesh_objects": len(objects),
        "triangles": sum(len(obj.data.loop_triangles) for obj in objects),
        "vertices": sum(len(obj.data.vertices) for obj in objects),
        "bounds_m": {"min": list(low), "max": list(high)},
        "missing_uv": sorted(obj.name for obj in objects if not obj.data.uv_layers),
        "empty_transforms": sum(o.type == "EMPTY" for o in bpy.context.scene.objects),
        "collections": {col.name: len(col.objects) for col in bpy.data.collections},
    }


def cleanup(patterns):
    upper = [pattern.upper() for pattern in patterns]
    objects = list(bpy.context.scene.objects)
    doomed = {obj for obj in objects if any(fnmatch.fnmatchcase(obj.name.upper(), pattern) for pattern in upper)}
    for obj in list(doomed):
        doomed.update(obj.children_recursive)
    removed = sorted(obj.name for obj in doomed)
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def hybrid_patterns(spec):
    return tuple(dict.fromkeys(spec.get("hybrid_bake_objects", [])))


def matches_any(name, patterns):
    return any(fnmatch.fnmatchcase(name.casefold(), pattern.casefold()) for pattern in patterns)


def capture_baked_meshes(prepared, patterns, repair_roots=False, pose_position="REST"):
    """Import a disposable baked reference and retain target vertices in world space."""
    before_objects = set(bpy.data.objects)
    before_meshes = set(bpy.data.meshes)
    before_materials = set(bpy.data.materials)
    before_armatures = set(bpy.data.armatures)
    roots = repair_skin_roots(prepared) if repair_roots else []
    imported = geometry_tools.import_gltf(prepared)
    for obj in imported:
        if obj.type == "ARMATURE":
            obj.data.pose_position = pose_position
    bpy.context.view_layer.update()
    pose = apply_static_pose(imported)
    if pose["modifier_failures"]:
        raise ValueError(f"Hybrid bake не применил модификаторы: {pose['modifier_failures']}")
    captures = {}
    survivors = [bpy.data.objects.get(name) for name in pose["survivor_names"]]
    for obj in (obj for obj in survivors if obj is not None):
        if obj.type == "MESH" and matches_any(obj.name, patterns):
            captures[obj.name] = {
                "positions": [(obj.matrix_world @ vertex.co).copy() for vertex in obj.data.vertices],
                "faces": len(obj.data.polygons),
            }
    for obj in list(set(bpy.data.objects) - before_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for datablocks, previous in ((bpy.data.meshes, before_meshes), (bpy.data.materials, before_materials),
                                 (bpy.data.armatures, before_armatures)):
        for block in list(set(datablocks) - previous):
            if block.users == 0:
                datablocks.remove(block)
    bpy.context.view_layer.update()
    return captures, {"repaired_roots": roots, "captured": sorted(captures)}


def apply_hybrid_captures(imported, captures):
    """Put selected stripped meshes at their evaluated rest-pose locations."""
    objects = {obj.name: obj for obj in imported if obj.type == "MESH"}
    result = {}
    for name, capture in captures.items():
        obj = objects.get(name)
        if obj is None:
            raise ValueError(f"Hybrid bake: после strip не найден объект {name}")
        if len(obj.data.vertices) != len(capture["positions"]) or len(obj.data.polygons) != capture["faces"]:
            raise ValueError(f"Hybrid bake: топология {name} отличается между bake и strip")
        before = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        inverse = obj.matrix_world.inverted()
        for vertex, world in zip(obj.data.vertices, capture["positions"]):
            vertex.co = inverse @ world
        obj.data.update()
        deltas = [(after - old).length for after, old in zip(capture["positions"], before)]
        result[name] = {"vertices": len(before), "max_vertex_move_m": max(deltas, default=0.0),
                        "mean_vertex_move_m": sum(deltas) / len(deltas) if deltas else 0.0}
    return result


def organize(root, overrides):
    for obj in list(bpy.context.scene.objects):
        parts = collections.classify(obj)
        for pattern, path in overrides.items():
            if fnmatch.fnmatchcase(obj.name.casefold(), pattern.casefold()):
                parts = path.split("/")
                if not all(parts):
                    raise ValueError(f"Пустое имя коллекции: {path}")
                break
        col = root
        for part in parts:
            col = collections.ensure_collection(col, part)
        if obj.name not in col.objects:
            col.objects.link(obj)
        for old in list(obj.users_collection):
            if old != col:
                old.objects.unlink(obj)


def configured_splits(spec, root):
    changes = {}
    for rule in spec.get("split_by_skin", []):
        obj = bpy.data.objects[rule["object"]]
        source = Path(obj["msfs_pipeline_source"])
        asset = geometry_tools.load_gltf(source)
        doc = asset.document
        binary = geometry_tools.combine_buffers(asset, doc)
        part_names = set()
        bone_groups, parts = {}, {}
        for i, part in enumerate(rule["parts"], start=1):
            name, bones = part["name"], part["bones"]
            if name in part_names or not bones or set(bones) & bone_groups.keys():
                raise ValueError(f"{obj.name}: повтор имени части или кости, либо пустой список bones")
            part_names.add(name)
            bone_groups.update(dict.fromkeys(bones, i))
            col = root
            for level in part.get("collection", "01_EXTERIOR/03_TAIL_AND_CONTROL_SURFACES").split("/"):
                col = collections.ensure_collection(col, level)
            pivot = bpy.data.objects[part["pivot"]] if "pivot" in part else obj
            parts[i] = (name, col, pivot.matrix_world.translation)
        if not parts:
            raise ValueError(f"{obj.name}: список частей split_by_skin пуст")
        groups = skin_split.skin_groups(doc, binary, obj, rule.get("source_node", obj.name), bone_groups)
        changes.update(skin_split.split_mesh(obj, groups, parts))
    return changes


def configured_mirrors(spec):
    """Mirror a damaged one-sided static mesh from its verified counterpart."""
    changes = {}
    for rule in spec.get("mirror_objects", []):
        source_name = rule["source"]
        target_name = rule["target"]
        axis = rule.get("axis", "X").upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError(f"mirror_objects: неподдерживаемая ось {axis} для {target_name}")
        source = bpy.data.objects.get(source_name)
        target = bpy.data.objects.get(target_name)
        if source is None or target is None or source.type != "MESH" or target.type != "MESH":
            raise ValueError(f"mirror_objects: нужны два mesh-объекта {source_name} и {target_name}")
        mirrored = source.data.copy()
        component = {"X": 0, "Y": 1, "Z": 2}[axis]
        reflection = Matrix.Diagonal([1.0, 1.0, 1.0, 1.0])
        reflection[component][component] = -1.0
        source_world = source.matrix_world
        target_world = source_world.copy()
        location = target_world.translation
        location[component] = -location[component]
        target_world.translation = location
        # Reflect about the world symmetry plane, not the object's own axes: a
        # rotated source otherwise lands on the same side. The mesh absorbs the
        # reflection so the object keeps a positive scale, and its origin moves.
        local = target_world.inverted_safe() @ reflection @ source_world
        # Keyed by vertex: flipping a polygon reorders its loops.
        normals = {}
        if mirrored.has_custom_normals:
            for polygon in mirrored.polygons:
                for loop_index in polygon.loop_indices:
                    key = (polygon.index, mirrored.loops[loop_index].vertex_index)
                    normals[key] = mirrored.corner_normals[loop_index].vector.copy()
        for vertex in mirrored.vertices:
            vertex.co = local @ vertex.co
        for polygon in mirrored.polygons:
            polygon.flip()
        for layer in mirrored.uv_layers:
            for loop in layer.data:
                # Mirroring reverses the surface, so decals read backwards without this.
                loop.uv[0] = 1.0 - loop.uv[0]
        if normals:
            normal_matrix = local.to_3x3().inverted_safe().transposed()
            values = []
            for polygon in mirrored.polygons:
                for loop_index in polygon.loop_indices:
                    key = (polygon.index, mirrored.loops[loop_index].vertex_index)
                    values.append((normal_matrix @ normals[key]).normalized())
            mirrored.normals_split_custom_set(values)
        mirrored.update()
        target.data = mirrored
        target.parent = None
        target.matrix_world = target_world
        changes[target_name] = {"source": source_name, "axis": axis}
    return changes


def configured_placements(spec):
    """Move a part to an anchor's position without inheriting its orientation."""
    changes = {}
    for name, placement in spec.get("placements", {}).items():
        obj = bpy.data.objects[name]
        anchor = bpy.data.objects[placement["anchor"]]
        obj.parent = None
        # Only the anchor's position is inherited: a rotated gear or rudder node
        # must not tilt the part placed at it.
        world = obj.matrix_world.copy()
        world.translation = anchor.matrix_world.translation + Vector(placement.get("offset_m", (0, 0, 0)))
        obj.matrix_world = world
        changes[name] = {"anchor": anchor.name, "world_origin": list(world.translation)}
    return changes


def face_group(rule, center):
    if "axis" in rule:
        axis = "XYZ".index(rule["axis"].upper())
        return sum(center[axis] >= cut for cut in rule["cuts"])
    axes = {"x": 0, "y": 1, "z": 2}
    for index, region in enumerate(rule["regions"], start=1):
        if all((limits[0] is None or center[axes[axis]] >= limits[0]) and
               (limits[1] is None or center[axes[axis]] < limits[1])
               for axis, limits in region["bounds"].items()):
            return index
    return 0


def filter_faces(mesh, keep):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[face for face in bm.faces if face.index not in keep], context="FACES")
        bmesh.ops.delete(bm, geom=[vertex for vertex in bm.verts if not vertex.link_faces], context="VERTS")
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def split_spatial_object(obj, rule, root):
    if "axis" in rule:
        names = list(rule["names"])
        if len(names) != len(rule["cuts"]) + 1 or sorted(rule["cuts"]) != list(rule["cuts"]):
            raise ValueError(f"{obj.name}: names/cuts в split_spatial не согласованы")
    else:
        names = [rule["default"], *(region["name"] for region in rule["regions"])]
    if len(names) != len(set(names)) or any(name in bpy.data.objects and name != obj.name for name in names):
        raise ValueError(f"{obj.name}: имена результатов split_spatial заняты или повторяются")
    groups = defaultdict(set)
    for polygon in obj.data.polygons:
        center = obj.matrix_world @ polygon.center
        groups[face_group(rule, center)].add(polygon.index)
    if set(groups) != set(range(len(names))):
        raise ValueError(f"{obj.name}: одна из пространственных частей пуста; измените границы")

    mesh = obj.data
    source_world = obj.matrix_world.copy()
    source_faces = len(mesh.polygons)
    positions = [source_world @ mesh.vertices[loop.vertex_index].co for loop in mesh.loops]
    normals = [normal.vector.copy() for normal in mesh.corner_normals]
    uv = {layer.name: [point.vector.copy() for point in layer.uv] for layer in mesh.uv_layers}
    materials = [polygon.material_index for polygon in mesh.polygons]
    corner_attr = mesh.attributes.new(CORNER_ID, "INT", "CORNER")
    corner_attr.data.foreach_set("value", np.arange(len(mesh.loops), dtype=np.int32))
    face_attr = mesh.attributes.new(FACE_ID, "INT", "FACE")
    face_attr.data.foreach_set("value", np.arange(len(mesh.polygons), dtype=np.int32))
    pieces = []
    for group, name in enumerate(names):
        piece = obj.copy()
        piece.data = mesh.copy()
        piece.name = name
        piece.data.name = name
        for collection in obj.users_collection:
            collection.objects.link(piece)
        filter_faces(piece.data, groups[group])
        corners = [value.value for value in piece.data.attributes[CORNER_ID].data]
        faces = [value.value for value in piece.data.attributes[FACE_ID].data]
        if piece.data.has_custom_normals:
            piece.data.normals_split_custom_set([normals[index] for index in corners])
        if any((piece.matrix_world @ piece.data.vertices[loop.vertex_index].co - positions[source]).length > 2e-6
               for loop, source in zip(piece.data.loops, corners)):
            raise ValueError(f"{name}: координаты изменились при split_spatial")
        for layer in piece.data.uv_layers:
            if any(value.vector != uv[layer.name][source] for value, source in zip(layer.uv, corners)):
                raise ValueError(f"{name}: UV изменились при split_spatial")
        if any(polygon.material_index != materials[source] for polygon, source in zip(piece.data.polygons, faces)):
            raise ValueError(f"{name}: материалы изменились при split_spatial")
        piece.data.attributes.remove(piece.data.attributes[CORNER_ID])
        piece.data.attributes.remove(piece.data.attributes[FACE_ID])
        pieces.append(piece)
    if sum(len(piece.data.polygons) for piece in pieces) != source_faces:
        raise ValueError(f"{obj.name}: потеряны грани при split_spatial")
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    return {piece.name: len(piece.data.polygons) for piece in pieces}


def configured_spatial_splits(spec, root):
    changes = {}
    rules = list(spec.get("split_spatial", []))
    for rule in rules:
        obj = bpy.data.objects.get(rule["object"])
        if obj is None or obj.type != "MESH":
            raise ValueError(f"split_spatial: объект не найден: {rule['object']}")
        changes.update(split_spatial_object(obj, rule, root))
    return changes


def skin_catalog(doc):
    nodes = doc.get("nodes", [])
    return [{"node": node.get("name"), "joints": [nodes[i].get("name") for i in doc["skins"][node["skin"]]["joints"]]}
            for node in nodes if "mesh" in node and "skin" in node]


def build_geometry(spec, review):
    geometry_tools.clear_scene()
    scene = bpy.context.scene
    scene.name = Path(spec["aircraft_path"]).name
    scene.unit_settings.system = "METRIC"
    scene["msfs_pipeline_models"] = json.dumps([m["path"] for m in spec["models"]], ensure_ascii=False)
    root = bpy.data.collections.new(ROOT)
    scene.collection.children.link(root)
    model_stats = []
    source_collections = []
    out = Path(spec["output"]).parent
    hybrid_targets = hybrid_patterns(spec)
    if spec["skinning"] == "hybrid" and not hybrid_targets:
        raise ValueError("Для skinning=hybrid задайте hybrid_bake_objects или используйте профиль с такими объектами.")
    for item in spec["models"]:
        source = Path(item["path"])
        doc = geometry_tools.load_gltf(source).document
        manual_nodes = {node.get("name") for node in doc.get("nodes", [])
                        if node.get("name") and "mesh" in node and "skin" in node}
        manual_keep_pivots = set(spec.get("manual_keep_pivots", []))
        source_collection = bpy.data.collections.new(f"{item['role'].title()}_SOURCE")
        source_collections.append(source_collection)
        root.children.link(source_collection)
        old_materials = set(bpy.data.materials)
        with tempfile.TemporaryDirectory(prefix="msfs-prepared-", dir=out) as folder:
            folder = Path(folder)
            captures = {}
            hybrid_reference = {}
            target_nodes = [node.get("name", "") for node in doc.get("nodes", [])
                            if "mesh" in node and "skin" in node and matches_any(node.get("name", ""), hybrid_targets)]
            if spec["skinning"] == "hybrid" and target_nodes:
                bake_dir = folder / "bake"
                bake_dir.mkdir()
                baked, _ = geometry_tools.prepare_gltf(source, bake_dir, draw_mode=spec["draw_mode"],
                                                       filter_runtime=spec.get("filter_runtime", True))
                captures, hybrid_reference = capture_baked_meshes(
                    baked, hybrid_targets, repair_roots=spec.get("repair_skin_roots", False),
                    pose_position=spec.get("pose_position", "REST"))
                missing_targets = sorted(set(target_nodes) - captures.keys())
                if missing_targets:
                    raise ValueError(f"Hybrid bake не захватил: {missing_targets}")
            main_dir = folder / "main"
            main_dir.mkdir()
            prepared, stats = geometry_tools.prepare_gltf(
                source, main_dir, draw_mode=spec["draw_mode"],
                filter_runtime=spec.get("filter_runtime", True),
                manual_skin=spec["skinning"] == "manual",
                preserve_manual_pivots=manual_keep_pivots)
            if spec["skinning"] in {"strip", "hybrid", "manual"}:
                skin = strip_skinning(prepared)
            else:
                skin = {"repaired_roots": repair_skin_roots(prepared)
                        if spec.get("repair_skin_roots", False) else []}
            try:
                imported = geometry_tools.import_gltf(prepared)
            except Exception as error:
                raise ValueError(f"{source.name}: Blender не импортировал glTF. Если ошибка связана с JOINTS/WEIGHTS, "
                                 "соберите черновик с skinning=strip и проверьте стойки, двери и рули. "
                                 "Для индексов проверьте draw_mode и LOD.") from error
            if spec["skinning"] == "manual":
                detached = []
                for obj in imported:
                    source_name = obj.get("msfs_source_node", obj.name)
                    if obj.type == "MESH" and source_name in manual_nodes and source_name not in manual_keep_pivots:
                        obj.parent = None
                        obj.matrix_world = Matrix.Identity(4)
                        detached.append(obj.name)
                skin = {"manual_detached_nodes": sorted(detached), **skin}
            if captures:
                skin["hybrid_reference"] = hybrid_reference
                skin["hybrid_applied"] = apply_hybrid_captures(imported, captures)
        geometry_tools.move_to_collection(imported, source_collection)
        for obj in imported:
            obj["msfs_source_role"] = item["role"]
            if obj.type == "MESH":
                obj["msfs_pipeline_source"] = str(source)
        for material in set(bpy.data.materials) - old_materials:
            material["msfs_source_path"] = str(source)
        model_stats.append({"path": str(source), "skin": skin, "skinned_meshes": skin_catalog(doc), **stats})

    objects = list(scene.objects)
    geometry_tools.neutralize_materials(objects)
    pose = {}
    if spec["skinning"] == "bake":
        pose_position = spec.get("pose_position", "REST")
        if pose_position not in {"REST", "POSE"}:
            raise ValueError("pose_position: REST или POSE")
        for obj in objects:
            if obj.type == "ARMATURE":
                obj.data.pose_position = pose_position
        bpy.context.view_layer.update()
        pose = apply_static_pose(objects)
        pose.pop("survivor_names", None)
        if pose["modifier_failures"]:
            raise ValueError(f"Не удалось запечь: {pose['modifier_failures']}. Проверьте кожу меша или skinning=strip.")
    bpy.context.view_layer.update()
    before_cleanup = scene_stats()
    expected = sum(s["triangles"] for s in model_stats)
    delta = before_cleanup["triangles"] - expected
    if delta:
        review.append(f"Расхождение треугольников до очистки: {delta:+d}. Сверьте дубли LOD и артефакты крыла; "
                      "в отчёте есть исходные draw ranges.")

    organize(root, spec.get("collection_overrides", {}))
    for col in source_collections:
        if not col.objects and not col.children:
            bpy.data.collections.remove(col)
    bpy.context.view_layer.update()
    changes = {}
    changes.update(configured_splits(spec, root))
    changes.update(configured_spatial_splits(spec, root))
    changes.update(configured_mirrors(spec))
    changes.update(configured_placements(spec))
    # Edits must run before exclusion: a user may hide a split result or a
    # mirror reference without invalidating the editing rule itself.
    catalog = object_catalog()
    removed = cleanup(list(spec.get("exclude_objects", [])))
    removed_names = set(removed)
    for item in catalog:
        item["included"] = item["name"] not in removed_names
    bpy.context.view_layer.update()
    for obj in scene.objects:
        if obj.type == "EMPTY":
            obj.hide_set(True)
    bpy.ops.object.select_all(action="DESELECT")
    review.append("Откройте 01_geometry.blend и проверьте обе стороны крыла, стойки, остекление, двери, рули "
                  "и доступность каждого нужного элемента как отдельного объекта.")
    if spec["skinning"] == "strip":
        review.append("Весовые связи сняты. Проверьте детали, положение которых зависело от костей. "
                      "При смещении сравните с bake или задайте placements по посадочному узлу.")
    elif spec["skinning"] == "hybrid":
        review.append("Статическая основа собрана через strip; выбранные skinned-меши автоматически восстановлены "
                      "из bake-reference. Проверьте их стыки с соседними статическими деталями.")
    elif spec["skinning"] == "manual":
        review.append("Сохранены статические MSFS вершины в координатах самолёта и сняты animation pivots. Проверьте симметрию крыла, двигателей "
                      "и рулевых поверхностей; это безопасный режим для моделей с нестандартными scalar weights.")
    review.append("Универсальная сборка: для слитых поверхностей проверьте skinned_meshes и при необходимости задайте "
                  "split_by_skin или split_spatial. Коллекции уточняются через collection_overrides.")
    return {"sources": model_stats, "source_triangles": expected, "triangle_delta_before_cleanup": delta,
            "pose": pose, "removed_objects": removed, "geometry_fixes": changes,
            "object_catalog": catalog}


def basename(uri):
    return Path(unquote(uri).replace("\\", "/")).name.casefold()


def file_index(folder):
    result = defaultdict(list)
    for path in sorted(Path(folder).rglob("*"), key=lambda p: (len(p.parts), str(p).casefold(), str(p))):
        if path.is_file():
            result[path.name.casefold()].append(path)
    return result


def build_textures(spec, review):
    directories = [file_index(folder) for folder in spec["texture_dirs"]]
    converted = file_index(spec["converted_normal_dir"]) if spec["converted_normal_dir"] else {}
    overrides = spec["texture_overrides"]
    sources = {item["path"]: pbr.read_materials(Path(item["path"])) for item in spec["models"]}
    names = defaultdict(list)
    for path in sources:
        names[Path(path).name].append(path)
    missing, skipped, applied = [], [], []
    chosen, unreadable, compressed_normals, ambiguous, decoded = {}, {}, {}, {}, {}
    decode_mode = spec.get("normal_decode", "auto")
    generated = Path(spec["output"]).parent / "decoded_normals"

    def resolve(kind, uri):
        if not uri:
            return None
        key = basename(uri)
        token = (kind, key)
        if token in chosen:
            return chosen[token]
        if key in overrides:
            candidates = [Path(overrides[key])]
        elif kind == "norm" and key + ".png" in converted:
            candidates = converted[key + ".png"]
        else:
            candidates = next((d[key] for d in directories if key in d), [])
        if len(candidates) > 1:
            ambiguous[key] = list(map(str, candidates))
        path = candidates[0] if candidates else None
        if path:
            original = path
            try:
                codec = None
                if kind == "norm" and path.suffix.casefold() == ".dds":
                    with path.open("rb") as stream:
                        codec = normal_format(stream.read(148))
                if ((codec in {"BC5S", "BC5U"} and decode_mode != "off")
                        or (codec == "DXT5" and decode_mode == "dxt5n")):
                    generated.mkdir(exist_ok=True)
                    key_hash = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:10]
                    png = generated / f"{key_hash}-{path.name}.png"
                    decode_normal(path, png, codec)
                    decoded[str(path)] = {"codec": codec, "png": str(png)}
                    path = png
                elif codec:
                    compressed_normals[str(path)] = codec
                colorspace = "sRGB" if kind in {"albd", "emissive"} else "Non-Color"
                if not all(pbr.load_image(path, colorspace).size):
                    raise ValueError("Blender прочитал нулевой размер изображения")
            except (RuntimeError, OSError, ValueError) as error:
                unreadable[str(original)] = str(error)
                path = None
        chosen[token] = path
        return path

    used = {slot.material for obj in meshes() for slot in obj.material_slots if slot.material}
    for material in sorted(used, key=lambda m: m.name):
        path = material.get("msfs_source_path")
        if path not in sources:
            matching = names[material.get("msfs_model")]
            path = matching[0] if len(matching) == 1 else None
        index = material.get("msfs_material_index")
        if not path or index not in sources[path]:
            skipped.append(material.name)
            continue
        entry = sources[path][index]
        if any(name in material.name.casefold() for name in ("glass_fiber", "fiberglass", "fibreglass")):
            # The legacy shader heuristic treats any "glass" as a canopy.
            # Keep these composite materials opaque after binding.
            pbr.build_material(material, entry, None, missing, resolver=resolve)
            shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            shader.inputs["Transmission Weight"].default_value = 0
            if not shader.inputs["Alpha"].is_linked:
                shader.inputs["Alpha"].default_value = entry["base_color_factor"][3]
            if not shader.inputs["Roughness"].is_linked:
                shader.inputs["Roughness"].default_value = entry["roughness_factor"]
        else:
            pbr.build_material(material, entry, None, missing, resolver=resolve)
        applied.append(material.name)

    hashes = defaultdict(list)
    for path in sorted({path for path in chosen.values() if path}):
        with path.open("rb") as stream:
            hashes[hashlib.file_digest(stream, "sha256").hexdigest()].append(str(path))
    duplicates = [paths for paths in hashes.values() if len(paths) > 1]
    if missing or unreadable:
        review.append(f"Отсутствуют или не читаются {len({item['filename'] for item in missing})} уникальных карт. "
                      "Смотрите missing_textures/unreadable_images. Укажите extra_texture_dirs, "
                      "texture_overrides или converted_normal_dir и повторите textures.")
    if skipped:
        review.append(f"{len(skipped)} материалов без сопоставления с glTF. Сверьте models и provenance в skipped_materials.")
    if ambiguous or duplicates:
        review.append("В отчёте отмечены одноимённые карты и одинаковые файлы. Сверьте ливрею и исключите заглушки.")
    if compressed_normals:
        review.append("Проверьте рельеф на DDS NORM. Если освещение выглядит неверно, используйте распакованные "
                      "нормали через converted_normal_dir или texture_overrides.")
    # Missing fallback folders matter to the user only when a required image
    # could not be resolved. Keep the raw list in the report for diagnostics,
    # but avoid a noisy warning when every used texture was found elsewhere.
    if spec["missing_fallback_dirs"] and (missing or unreadable):
        review.append("В texture.cfg есть недоступные fallback-папки. Сверьте missing_fallback_dirs и при необходимости добавьте extra_texture_dirs.")
    review.append("Откройте 02_textured.blend в Material Preview. Сверьте ливрею, стекло и приборные карты.")
    for obj in meshes():
        if obj.get("msfs_preview_hidden"):
            obj.hide_set(False)
            del obj["msfs_preview_hidden"]
    report = {"missing_textures": missing, "unreadable_images": unreadable, "applied_materials": applied,
              "skipped_materials": skipped, "compressed_normals_to_review": compressed_normals,
              "decoded_normals": decoded,
              "duplicate_content": duplicates, "ambiguous_textures": ambiguous,
              "resolved_textures": {f"{kind}:{name}": str(path) for (kind, name), path in chosen.items() if path},
              "texture_search_order": spec["texture_dirs"], "missing_fallback_dirs": spec["missing_fallback_dirs"]}
    bpy.context.scene["msfs_pipeline_texture_gaps"] = len(missing) + len(skipped)
    return report


def used_images():
    materials = {slot.material for obj in meshes() for slot in obj.material_slots if slot.material}
    return {node.image for material in materials if material.use_nodes and material.node_tree
            for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image}


def pack_images():
    failures = {}
    images = used_images()
    for image in sorted(images, key=lambda img: img.name):
        if image.source == "FILE" and not image.packed_file:
            try:
                image.pack()
                if not image.packed_file:
                    raise ValueError("изображение не упаковано")
            except (RuntimeError, OSError, ValueError) as error:
                failures[image.name] = str(error)
    return {"used_images": len(images), "packed_images": sum(bool(image.packed_file) for image in images),
            "packing_failures": failures}


def viewport(bounds=None):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.overlay.show_relationship_lines = False
                if bounds:
                    low, high = Vector(bounds["min"]), Vector(bounds["max"])
                    space.region_3d.view_location = (low + high) / 2
                    space.region_3d.view_distance = max(1.0, max(high - low) * 1.6)


def main():
    spec = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
    stage = spec["stage"]
    review = []
    if spec["input_blend"]:
        bpy.ops.wm.open_mainfile(filepath=spec["input_blend"], load_ui=False, use_scripts=False)
    if stage == "geometry":
        report = build_geometry(spec, review)
    elif stage == "textures":
        recorded = bpy.context.scene.get("msfs_pipeline_models")
        if recorded and set(json.loads(recorded)) != {item["path"] for item in spec["models"]}:
            raise ValueError("Входной blend собран из другого набора models. Укажите исходные glTF этой геометрии "
                             "или пересоберите этап geometry.")
        report = build_textures(spec, review)
    else:
        report = {}
        review.append("Откройте 03_model.blend и подтвердите положение деталей, комплектность и внешний вид.")
    report.update(scene_stats())
    report["objects"] = object_catalog()
    viewport(report["bounds_m"] if stage == "geometry" else None)
    if report["missing_uv"]:
        review.append("У части мешей нет UV. Смотрите missing_uv и проверьте, нужны ли этим деталям карты.")
    gaps = 0
    if stage != "geometry":
        report.update(pack_images())
        gaps = bpy.context.scene.get("msfs_pipeline_texture_gaps")
        if report["packing_failures"]:
            review.append("Часть изображений не удалось упаковать. Проверьте packing_failures и пути файлов.")
        if gaps is None:
            review.append("Текстуры входного файла не проверены этим конвейером. Выполните textures или проверьте материалы вручную.")
        elif stage == "final" and gaps:
            review.append(f"Сохранились пропуски этапа textures ({gaps} ссылок/материалов). "
                          "Смотрите 02_textured.json и повторите этап с дополнительными картами.")
    report.update({"blend": spec["output"], "profile": spec["profile"], "review": review,
                   "stage": stage, "build_variant": spec.get("build_variant"),
                   "build_sequence": spec.get("build_sequence"), "models": spec["models"],
                   "incomplete": bool(gaps is None or gaps or report.get("packing_failures"))})
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=spec["output"], compress=True)
    Path(spec["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

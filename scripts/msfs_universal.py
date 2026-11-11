"""Universal MSFS glTF -> Blender static pipeline (aircraft-agnostic v1)."""

import argparse
import json
import math
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_resolver import (GENERATED_AIRCRAFT_DIRS, aircraft_folders, by_case, directories,
                              find_aircraft, installed_package_roots, model_choices, model_from_cfg,
                              model_variants, read_document, reason_text, rebase, resolve, resolve_aircraft,
                              sections, skin_joints)
from package_index import PackageIndex, default_cache_path


STAGES = {"geometry": "01_geometry", "textures": "02_textured", "final": "03_model"}
CONFIG_KEYS = {
    "source", "aircraft", "blender", "output_dir", "profile", "models", "model_folder", "livery",
    "build_variant", "build_sequence",
    "skinning", "draw_mode", "filter_runtime", "exclude_objects",
    "placements", "collection_overrides", "extra_texture_dirs", "converted_normal_dir",
    "texture_overrides", "normal_decode", "split_by_skin", "split_spatial", "hybrid_bake_objects",
    "repair_skin_roots", "pose_position", "manual_keep_pivots", "mirror_objects", "include_all_liveries",
}


def stage_stem(stage, variant=None, sequence=None):
    """Return a stable checkpoint stem, optionally annotated with a build mode."""
    stem = STAGES[stage]
    if variant:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(variant).strip()).strip("._-")
        if safe and safe.casefold() not in {"default", "base"}:
            stem = f"{stem}_{safe}"
    if sequence is not None:
        stem = f"{stem}_{int(sequence):03d}"
    return stem


def stage_sequences(out, stage, variant):
    prefix = stage_stem(stage, variant)
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{3,}})\.blend$", re.I)
    values = []
    for path in out.glob("*.blend"):
        match = pattern.match(path.name)
        if match and path.is_file():
            values.append((int(match.group(1)), path))
    return sorted(values)


def latest_stage_file(out, stage, variant):
    values = stage_sequences(out, stage, variant)
    legacy = out / f"{stage_stem(stage, variant)}.blend"
    return values[-1][1] if values else legacy if legacy.is_file() else None


def choose_build_sequence(out, variant, selected, requested=None):
    if requested is not None:
        try:
            value = int(requested)
            if not isinstance(requested, bool) and str(requested) == str(value) and value > 0:
                return value
        except (TypeError, ValueError):
            pass
        raise ValueError("build_sequence должен быть положительным целым числом.")
    if selected in {"geometry", "all"}:
        previous = [number for stage in STAGES for number, _ in stage_sequences(out, stage, variant)]
        return max(previous, default=0) + 1
    dependency = "geometry" if selected == "textures" else "textures"
    source = latest_stage_file(out, dependency, variant)
    candidate = next((number for number, path in stage_sequences(out, dependency, variant) if path == source), None)
    if candidate is None:
        candidate = max((number for stage in STAGES for number, _ in stage_sequences(out, stage, variant)), default=0) + 1
    target = out / f"{stage_stem(selected, variant, candidate)}.blend"
    if target.exists():
        candidate = max((number for stage in STAGES for number, _ in stage_sequences(out, stage, variant)), default=0) + 1
    return candidate


def package_container(path):
    """The directory that holds the package: a mod folder or a test fixture is
    indexed on its own instead of dragging in the whole installed simulator."""
    path = Path(path).resolve()
    top = None
    for parent in (path, *path.parents):
        if (parent / "manifest.json").is_file() or (parent / "layout.json").is_file():
            top = parent
    return top.parent if top is not None else path


def build_index(extra_roots=(), *, cache=True, near=None):
    """One index per scan: liveries rebase their VFS-relative paths through it."""
    roots = installed_package_roots(extra_roots)
    ad_hoc = False
    if near is not None:
        near = Path(near).resolve()
        if not any(near.is_relative_to(root) for root in roots):
            roots = [package_container(near), *roots] if extra_roots else [package_container(near)]
            ad_hoc = True
    # A scan of one local folder has its own roots; caching it under the shared
    # path would evict the installed-simulator index on every project open.
    return PackageIndex.build(roots, cache_path=default_cache_path() if cache and not ad_hoc else None)


def inventory(source, deep=False, roots=(), index=None):
    """Diagnose every aircraft below a package, an aircraft folder or a wrapper.

    Shallow mode only checks that declared resources exist; it is what the
    catalog scan uses. Deep mode also parses the selected glTF documents to
    report missing BIN buffers and features the decoder cannot handle.
    """
    return [resolve_aircraft(folder, roots=roots, deep=deep, index=index)
            for folder in aircraft_folders(source)]


def catalog(extra_roots=(), matches=(), deep=False):
    """Return the aircraft catalog.

    The default scan is intentionally shallow so the GUI stays responsive.
    ``deep=True`` performs the same pre-Blender glTF/GLB validation as
    ``inventory --deep`` and therefore exposes missing buffers and unsupported
    primitives before a project is created.  No source files are modified.
    """
    roots = installed_package_roots(extra_roots)
    index = build_index(extra_roots)
    tokens = [token.casefold() for token in matches]
    entries = []
    seen = set()
    for root in roots:
        for folder in find_aircraft(root):
            resolved = folder.resolve()
            if resolved in seen or (tokens and not any(token in folder.name.casefold() for token in tokens)):
                continue
            seen.add(resolved)
            try:
                [item] = inventory(folder, deep=deep, index=index)
            except (ValueError, OSError, ET.ParseError) as error:
                code = "PACKAGE_NOT_FOUND" if not folder.is_dir() else "SCAN_FAILED"
                reason, action = reason_text(code)
                item = {"aircraft": folder.name, "path": str(folder), "profile": "generic", "variants": [],
                        "textures": [], "can_build_geometry": False, "can_build_textures": False,
                        "partial": False, "needs_model_selection": False, "reason_code": code,
                        "reason": reason, "action": action, "missing_resources": [], "candidates": [],
                        "dependencies": [], "best_models": [], "detail": str(error)}
            item["package_root"] = str(root)
            entries.append(item)
    # ``fs-base-history`` can contain empty SimObjects placeholders for an
    # aircraft whose real model is installed in another Official package.
    # Keep genuine same-name candidates visible, but keep these non-buildable
    # history records in diagnostics instead of presenting them as aircraft.
    grouped = {}
    for item in entries:
        grouped.setdefault(item.get("aircraft", "").casefold(), []).append(item)
    visible_entries = []
    suppressed_history_stubs = []
    for candidates in grouped.values():
        buildable = [item for item in candidates if item.get("can_build_geometry")]
        for item in candidates:
            path_parts = {part.casefold() for part in Path(item.get("path", "")).parts}
            is_history_stub = ("fs-base-history" in path_parts
                               and not item.get("can_build_geometry"))
            if is_history_stub and buildable:
                suppressed_history_stubs.append({
                    "aircraft": item.get("aircraft"),
                    "path": item.get("path"),
                    "reason_code": item.get("reason_code"),
                    "shadowed_by": [candidate.get("path") for candidate in buildable],
                })
            else:
                visible_entries.append(item)

    name_counts = {}
    for item in visible_entries:
        name = item.get("aircraft", "").casefold()
        name_counts[name] = name_counts.get(name, 0) + 1
    for item in visible_entries:
        count = name_counts.get(item.get("aircraft", "").casefold(), 0)
        if count > 1:
            # Keep every physical candidate selectable, but make the ambiguity
            # explicit instead of silently showing a duplicate aircraft.
            item["duplicate_name"] = True
            item["duplicate_count"] = count
    return {"searched_roots": list(map(str, roots)),
            "index": {"packages": len(index.packages), "aircraft_names": len(index.aircraft),
                      "cached": index.reused, "scanned": index.scanned, "errors": index.errors},
            "aircraft": sorted(visible_entries, key=lambda item: item["aircraft"].casefold()),
            "suppressed_history_stubs": sorted(suppressed_history_stubs,
                                                key=lambda item: item["aircraft"].casefold())}


def locate_report_textures(report_file, extra_roots=()):
    """Locate unresolved texture basenames from a pipeline texture report."""
    report = json.loads(report_file.read_text(encoding="utf-8-sig"))
    requested = sorted({item.get("filename", "") for item in report.get("missing_textures", []) if item.get("filename")},
                       key=str.casefold)
    if not requested:
        return {"report": str(report_file), "requested": [], "searched_roots": [], "matches": {},
                "suggested_extra_texture_dirs": [], "missing": []}
    # Missing reports may contain MSFS relative URIs such as ..\TEXTURE4\FROST_ALBD.PNG.DDS.
    # Search by basename while preserving the original report key in the result.
    folded = {Path(name.replace("\\", "/")).name.casefold(): name for name in requested}
    roots = installed_package_roots(extra_roots)
    matches = {name: [] for name in requested}
    for root in roots:
        for current, folders, files in os.walk(root):
            folders[:] = sorted((name for name in folders if not name.startswith(".")), key=str.casefold)
            for filename in files:
                original = folded.get(filename.casefold())
                if original:
                    path = str((Path(current) / filename).resolve())
                    if path not in matches[original]:
                        matches[original].append(path)
    suggested = sorted({str(Path(path).parent) for paths in matches.values() for path in paths}, key=str.casefold)
    return {"report": str(report_file), "requested": requested, "searched_roots": list(map(str, roots)),
            "matches": matches, "suggested_extra_texture_dirs": suggested,
            "missing": [name for name, paths in matches.items() if not paths]}


def texture_folders(aircraft, livery, extras, allow_other_liveries, index=None):
    common = by_case(aircraft, "texture")
    # Explicit "base" selects the common directory, falling back to texture.BASE if present.
    selected = common if not livery or (livery.casefold() == "base" and common.is_dir()) else by_case(aircraft, f"texture.{livery}")
    if livery and not selected.is_dir():
        raise ValueError(f"Не найдена ливрея {livery}: {selected}. Список папок показывает inventory.")
    paths = []
    missing = []

    def visit(folder):
        folder = folder.resolve()
        if folder in paths or not folder.is_dir():
            return
        paths.append(folder)
        cfg = by_case(folder, "texture.cfg")
        if cfg.is_file():
            fallbacks = sorted((int(key[9:]), value) for _, key, value in sections(cfg)
                               if key.startswith("fallback.") and key[9:].isdigit())
            for _, value in fallbacks:
                target = resolve(folder, value.replace("\\", "/"))
                if not target.is_dir() and index is not None:
                    target, _, _ = rebase(target, aircraft, index)
                if not target.is_dir():
                    missing.append(str(target))
                else:
                    visit(target)

    visit(selected)
    visit(common)
    for path in extras:
        visit(path)
    if allow_other_liveries:
        for folder in directories(aircraft):
            if folder.name.casefold().startswith("texture."):
                visit(folder)
    return paths, sorted(set(missing))


def _rule_text(rule, field, where):
    value = rule.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: укажите непустое имя {field}.")
    return value


def _rule_number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{where}: ожидается конечное число, получено {value!r}.")
    return float(value)


def _rule_names(names, count, where):
    if not isinstance(names, list) or len(names) != count:
        raise ValueError(f"{where}: нужно ровно {count} имён результатов.")
    cleaned = [_rule_text({"name": name}, "name", where) for name in names]
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"{where}: имена результатов повторяются.")
    return cleaned


def validate_mirror_objects(rules):
    for index, rule in enumerate(rules, start=1):
        where = f"mirror_objects/{index}"
        source = _rule_text(rule, "source", where)
        target = _rule_text(rule, "target", where)
        if source == target:
            raise ValueError(f"{where}: источник и цель должны быть разными объектами.")
        axis = str(rule.get("axis", "X")).upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError(f"{where}: ось должна быть X, Y или Z.")


def validate_placements(placements):
    for name, placement in placements.items():
        where = f"placements/{name}"
        if not isinstance(name, str) or not name.strip():
            raise ValueError("placements: имя объекта не может быть пустым.")
        if not isinstance(placement, dict):
            raise ValueError(f"{where}: ожидается JSON-объект с anchor.")
        _rule_text(placement, "anchor", where)
        offset = placement.get("offset_m", [0, 0, 0])
        if not isinstance(offset, (list, tuple)) or len(offset) != 3:
            raise ValueError(f"{where}: offset_m должен содержать три числа.")
        for value in offset:
            _rule_number(value, f"{where}/offset_m")


def validate_split_spatial(rules):
    for index, rule in enumerate(rules, start=1):
        where = f"split_spatial/{index}"
        _rule_text(rule, "object", where)
        if "axis" in rule:
            axis = str(rule["axis"]).upper()
            if axis not in {"X", "Y", "Z"}:
                raise ValueError(f"{where}: ось должна быть X, Y или Z.")
            cuts = rule.get("cuts")
            if not isinstance(cuts, list) or not cuts:
                raise ValueError(f"{where}: укажите хотя бы одну границу cuts.")
            values = [_rule_number(cut, f"{where}/cuts") for cut in cuts]
            if values != sorted(values):
                raise ValueError(f"{where}: границы cuts должны идти по возрастанию.")
            if len(set(values)) != len(values):
                raise ValueError(f"{where}: границы cuts повторяются.")
            _rule_names(rule.get("names"), len(values) + 1, where)
        else:
            default = _rule_text(rule, "default", where)
            regions = rule.get("regions")
            if not isinstance(regions, list) or not regions:
                raise ValueError(f"{where}: укажите regions либо axis с cuts.")
            names = [default]
            for number, region in enumerate(regions, start=1):
                spot = f"{where}/regions/{number}"
                if not isinstance(region, dict):
                    raise ValueError(f"{spot}: ожидается JSON-объект.")
                names.append(_rule_text(region, "name", spot))
                bounds = region.get("bounds")
                if not isinstance(bounds, dict) or not bounds:
                    raise ValueError(f"{spot}: укажите bounds хотя бы по одной оси.")
                for axis, limits in bounds.items():
                    if axis not in {"x", "y", "z"}:
                        raise ValueError(f"{spot}: ось bounds должна быть x, y или z (строчными).")
                    if not isinstance(limits, (list, tuple)) or len(limits) != 2:
                        raise ValueError(f"{spot}/bounds/{axis}: нужны два предела — нижний и верхний.")
                    low, high = limits
                    for value in limits:
                        if value is not None:
                            _rule_number(value, f"{spot}/bounds/{axis}")
                    if low is not None and high is not None and low >= high:
                        raise ValueError(f"{spot}/bounds/{axis}: нижний предел должен быть меньше верхнего.")
            if len(set(names)) != len(names):
                raise ValueError(f"{where}: имена результатов повторяются.")


def validate_split_by_skin(rules):
    for index, rule in enumerate(rules, start=1):
        where = f"split_by_skin/{index}"
        _rule_text(rule, "object", where)
        if "source_node" in rule:
            _rule_text(rule, "source_node", where)
        parts = rule.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"{where}: список частей пуст.")
        seen_names, seen_bones = set(), set()
        for number, part in enumerate(parts, start=1):
            spot = f"{where}/parts/{number}"
            if not isinstance(part, dict):
                raise ValueError(f"{spot}: ожидается JSON-объект.")
            name = _rule_text(part, "name", spot)
            if name in seen_names:
                raise ValueError(f"{spot}: имя части {name} повторяется.")
            seen_names.add(name)
            bones = part.get("bones")
            if not isinstance(bones, list) or not bones:
                raise ValueError(f"{spot}: укажите хотя бы одну кость.")
            for bone in bones:
                bone = _rule_text({"bone": bone}, "bone", spot)
                if bone in seen_bones:
                    raise ValueError(f"{spot}: кость {bone} уже назначена другой части.")
                seen_bones.add(bone)
            if "collection" in part:
                path = _rule_text(part, "collection", spot)
                if not all(path.split("/")):
                    raise ValueError(f"{spot}: пустое имя коллекции в {path}.")
            if "pivot" in part:
                _rule_text(part, "pivot", spot)


def validate_overrides(mapping, where, *, path_value):
    for key, value in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{where}: пустой ключ.")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}/{key}: укажите непустой путь.")
        if path_value and not all(value.split("/")):
            raise ValueError(f"{where}/{key}: пустое имя коллекции в {value}.")


def validate_config(config):
    """Validate user-editable values before filesystem or Blender operations."""
    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна быть JSON-объектом.")
    for key in ("source", "output_dir"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"Укажите непустой путь {key}.")
    for key in ("aircraft", "blender", "model_folder", "build_variant"):
        if key in config and (not isinstance(config[key], str) or not config[key].strip()):
            raise ValueError(f"{key} должен быть непустой строкой.")
    for key in ("filter_runtime", "include_all_liveries", "repair_skin_roots"):
        if key in config and not isinstance(config[key], bool):
            raise ValueError(f"{key} должен иметь значение true или false.")
    for key in ("exclude_objects", "hybrid_bake_objects", "manual_keep_pivots", "extra_texture_dirs"):
        if key in config and (not isinstance(config[key], list) or
                              any(not isinstance(item, str) or not item.strip() for item in config[key])):
            raise ValueError(f"{key} должен быть списком непустых строк.")
    for key in ("placements", "collection_overrides", "texture_overrides"):
        if key in config and not isinstance(config[key], dict):
            raise ValueError(f"{key} должен быть JSON-объектом.")
    for key in ("models", "split_by_skin", "split_spatial", "mirror_objects"):
        if key in config and (not isinstance(config[key], list) or
                              any(not isinstance(item, dict) for item in config[key])):
            raise ValueError(f"{key} должен быть списком JSON-объектов.")
    validate_placements(config.get("placements", {}))
    validate_mirror_objects(config.get("mirror_objects", []))
    validate_split_spatial(config.get("split_spatial", []))
    validate_split_by_skin(config.get("split_by_skin", []))
    validate_overrides(config.get("collection_overrides", {}), "collection_overrides", path_value=True)
    validate_overrides(config.get("texture_overrides", {}), "texture_overrides", path_value=False)
    if config.get("pose_position", "REST") not in {"REST", "POSE"}:
        raise ValueError("pose_position: REST или POSE.")
    if config.get("skinning") == "hybrid" and not config.get("hybrid_bake_objects"):
        raise ValueError("Для hybrid выберите хотя бы один объект в hybrid_bake_objects.")


def validate_rules(config_path):
    """Check a project's editing rules without touching the filesystem or Blender."""
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    validate_config(config)
    keys = ("split_by_skin", "split_spatial", "mirror_objects", "placements",
            "collection_overrides", "manual_keep_pivots", "texture_overrides")
    print(json.dumps({"ok": True, "rules": {key: len(config.get(key) or []) for key in keys}},
                     ensure_ascii=False))
    return 0


def selection_diagnosis(aircraft):
    """Explain a failed model selection with the pre-build package resolver."""
    report = resolve_aircraft(aircraft, deep=True, index=build_index(near=aircraft))
    lines = [f"Диагностика пакета: {report['reason']} [{report['reason_code']}].", report["action"]]
    for item in report["missing_resources"][:8]:
        lines.append(f"  Нет ресурса ({item['kind']}): {item.get('path') or item.get('name')}")
    if report["best_models"]:
        lines.append("  Доступные модели: " + ", ".join(
            f"{Path(model['path']).name} ({model['role']})" for model in report["best_models"]))
        lines.append("  Для частичной сборки задайте models этими путями явно.")
        lines.append(f"  Все кандидаты с LOD и числом вершин: models \"{aircraft}\".")
    return "\n".join(lines)


def validate_draw_mode_models(models, draw_mode):
    """Reject a plain glTF early when the user explicitly selected MSFS draw ranges.

    The worker still performs the authoritative check after import.  This
    preflight only reads JSON/GLB metadata and avoids launching Blender for a
    deterministic configuration error.
    """
    if draw_mode != "msfs":
        return
    for item in models:
        path = Path(item["path"])
        try:
            document = read_document(path)
        except (OSError, ValueError):
            continue  # the normal resolver/worker reports unreadable buffers
        for mesh_index, mesh in enumerate(document.get("meshes") or []):
            mesh_name = mesh.get("name", f"mesh_{mesh_index}") if isinstance(mesh, dict) else f"mesh_{mesh_index}"
            for primitive_index, primitive in enumerate((mesh or {}).get("primitives") or []):
                if "ASOBO_primitive" not in (primitive.get("extras") or {}):
                    raise ValueError(f"{path}: mesh '{mesh_name}', primitive {primitive_index} не содержит "
                                     "extras.ASOBO_primitive. Это обычный glTF, а не упакованный MSFS draw range. "
                                     "Используйте draw_mode=auto — он выбирает чтение по содержимому файла.")


def make_plan(config_file, stage=None):
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    validate_config(config)
    unknown = config.keys() - CONFIG_KEYS
    if unknown:
        raise ValueError(f"Неизвестные параметры JSON: {', '.join(sorted(unknown))}")
    base = config_file.parent
    source = resolve(base, config["source"])
    output = resolve(base, config["output_dir"])
    folders = aircraft_folders(source)
    if config.get("aircraft"):
        folders = [f for f in folders if f.name.casefold() == config["aircraft"].casefold()]
    if len(folders) != 1:
        raise ValueError(f"Укажите aircraft из inventory. Совпадения: {[p.name for p in folders]}")
    aircraft = folders[0]
    profile = config.get("profile", "generic")
    if profile in {"auto", ""}:
        profile = "generic"
    if profile != "generic":
        raise ValueError("Универсальная версия не содержит профилей самолётов. Используйте profile=generic.")
    skinning = config.get("skinning", "strip")
    draw = config.get("draw_mode", "auto")
    if skinning not in {"bake", "strip", "hybrid", "manual"} or draw not in {"auto", "msfs", "standard"}:
        raise ValueError("skinning: bake, strip, hybrid или manual. draw_mode: auto, msfs или standard.")
    if config.get("normal_decode", "auto") not in {"auto", "dxt5n", "off"}:
        raise ValueError("normal_decode: auto, dxt5n или off.")

    index = build_index(near=source)
    try:
        if "models" in config:
            models = [{"path": str(resolve(aircraft, item["path"])), "role": item["role"]} for item in config["models"]]
        elif "model_folder" in config:
            models = model_from_cfg(resolve(aircraft, config["model_folder"]), index=index, aircraft=aircraft)
        else:
            variants = model_variants(aircraft)
            if len(variants) != 1:
                raise ValueError("Укажите model_folder или models. Доступные варианты показывает inventory.")
            models = model_from_cfg(variants[0], index=index, aircraft=aircraft)
        seen = set()
        for item in models:
            path = Path(item["path"])
            if path.suffix.casefold() not in {".gltf", ".glb"} or not path.is_file() or item["role"] not in {"exterior", "interior"}:
                raise ValueError(f"Требуется доступный glTF/GLB и роль exterior/interior: {item}. Проверьте inventory.")
            if path in seen:
                raise ValueError(f"Дублирующаяся модель: {path}")
            seen.add(path)
        if not models:
            raise ValueError("Список models пуст.")
    except ValueError as error:
        raise ValueError(f"{error}\n{selection_diagnosis(aircraft)}") from error
    validate_draw_mode_models(models, draw)

    livery = config.get("livery")
    if livery is None:
        available = [p for p in directories(aircraft) if p.name.casefold().startswith("texture.")]
        if available and (len(available) != 1 or by_case(aircraft, "texture").is_dir()):
            raise ValueError("Укажите livery из inventory. Используйте base для общей папки texture.")
        livery = available[0].name.split(".", 1)[1] if available else None
    extras = [resolve(base, p) for p in config.get("extra_texture_dirs", [])]
    converted = config.get("converted_normal_dir")
    overrides = {name.casefold(): resolve(base, path) for name, path in config.get("texture_overrides", {}).items()}
    if converted:
        converted = resolve(base, converted)
    missing = [p for p in [*extras, *([converted] if converted else [])] if not p.is_dir()]
    missing += [p for p in overrides.values() if not p.is_file()]
    if missing and stage != "geometry":
        raise ValueError(f"Проверьте пути к дополнительным картам: {', '.join(map(str, missing))}")
    if stage == "geometry":
        paths, fallback_missing = [], []
    else:
        paths, fallback_missing = texture_folders(aircraft, livery, extras, bool(config.get("include_all_liveries", False)), index)
    package_root = source
    for parent in (source, *source.parents):
        if parent.name.casefold() == "simobjects":
            package_root = parent.parent
            break
    if output.is_relative_to(package_root) or output.is_relative_to(aircraft):
        raise ValueError("output_dir должен быть вне каталога исходного пакета (включая SimObjects/Airplanes).")
    blender = str(resolve(base, config["blender"])) if "blender" in config else shutil.which("blender")
    if not blender or not Path(blender).is_file():
        raise ValueError("Укажите путь к blender.exe в параметре blender или добавьте Blender в PATH.")
    return {**config, "blender": blender, "output_dir": str(output), "aircraft_path": str(aircraft),
            "profile": profile, "skinning": skinning, "draw_mode": draw, "models": models, "livery": livery,
            "texture_dirs": list(map(str, paths)), "missing_fallback_dirs": fallback_missing,
            "converted_normal_dir": str(converted) if converted else None,
            "texture_overrides": {name: str(path) for name, path in overrides.items()}}


def process_running(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied is not proof of a dead owner.
        try:
            status = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(lock):
    for _ in range(2):
        try:
            with lock.open("x", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid()}, stream)
            return
        except FileExistsError as error:
            try:
                owner = json.loads(lock.read_text(encoding="utf-8"))
                pid = owner.get("pid") if isinstance(owner, dict) else owner
                child = owner.get("child_pid") if isinstance(owner, dict) else None
            except (OSError, ValueError):
                raise ValueError(f"Блокировка повреждена: {lock}. Закройте все сборки и переименуйте этот файл вручную.") from error
            if process_running(pid) or process_running(child):
                raise ValueError(f"Папка сборки занята: {lock.parent}. Дождитесь текущего запуска.") from error
            lock.unlink(missing_ok=True)
    raise ValueError(f"Не удалось занять папку сборки: {lock.parent}")


def build(config_file, selected, input_blend):
    plan = make_plan(config_file, selected)
    out = Path(plan["output_dir"])
    steps = list(STAGES) if selected == "all" else [selected]
    if input_blend and selected not in {"textures", "final"}:
        raise ValueError("--input-blend допустим для этапов textures и final.")
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".msfs_pipeline.lock"
    acquire_lock(lock)
    try:
        variant = plan.get("build_variant")
        sequence = choose_build_sequence(out, variant, selected, plan.get("build_sequence"))
        return run_stages(plan, out, steps, input_blend, sequence, lock)
    finally:
        lock.unlink(missing_ok=True)


def run_stages(plan, out, steps, input_blend, sequence, lock=None):
    variant = plan.get("build_variant")
    blends = {stage: out / f"{stage_stem(stage, variant, sequence)}.blend" for stage in STAGES}
    incomplete = False
    for stage in steps:
        if blends[stage].exists():
            raise ValueError(f"Файл уже существует: {blends[stage]}. Задайте новый output_dir.")
    run = uuid.uuid4().hex[:10]
    worker = Path(__file__).with_name("msfs_universal_worker.py").resolve()
    previous = {"geometry": None, "textures": "geometry", "final": "textures"}
    for stage in steps:
        dependency = previous[stage]
        source_blend = input_blend or blends.get(dependency)
        if source_blend and not source_blend.is_file() and dependency:
            source_blend = latest_stage_file(out, dependency, variant)
        if dependency and (source_blend is None or not source_blend.is_file()):
            raise ValueError(f"Сначала выполните {dependency} или задайте --input-blend. Отсутствует {source_blend}")
        report = out / f"{stage_stem(stage, variant, sequence)}.json"
        spec = out / f"{stage}-{run}.plan.json"
        log = out / f"{stage}-{run}.log"
        spec.write_text(json.dumps({**plan, "build_sequence": sequence, "stage": stage, "input_blend": str(source_blend) if source_blend else None,
                                    "output": str(blends[stage]), "report": str(report)}, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [plan["blender"], "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(worker), "--", str(spec)]
        print(f"[{stage}] {blends[stage]}", flush=True)
        with log.open("wb") as stream:
            completed = run_external(command, stdout=stream, lock=lock)
        if completed.returncode or not blends[stage].is_file() or not report.is_file():
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-16:])
            raise ValueError(f"Этап {stage} остановился. Журнал: {log}\n{tail}")
        data = json.loads(report.read_text(encoding="utf-8"))
        incomplete = incomplete or bool(data.get("incomplete"))
        print(f"  Отчёт: {report}")
        for warning in data["review"]:
            print(f"  Проверка: {warning}")
    return 2 if incomplete else 0


def run_external(command, stdout=None, lock=None):
    """Keep Blender attached to the CLI lifecycle, and preserve its diagnostics."""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(command, stdout=stdout or subprocess.PIPE, stderr=subprocess.STDOUT, **options)
    if lock:
        lock.write_text(json.dumps({"pid": os.getpid(), "child_pid": process.pid}), encoding="utf-8")
    old_handler = None
    if hasattr(signal, "SIGTERM"):
        def interrupt(*_):
            raise KeyboardInterrupt
        old_handler = signal.signal(signal.SIGTERM, interrupt)
    try:
        captured, _ = process.communicate()
        return subprocess.CompletedProcess(command, process.returncode, captured)
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        if old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)
        if lock:
            lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")


def audit_blend(blend, output, blender=None, print_summary=True, objects_only=False):
    blender = blender or shutil.which("blender")
    if not blender or not Path(blender).is_file():
        raise ValueError("Укажите --blender или добавьте Blender в PATH.")
    if not blend.is_file():
        raise ValueError(f"Blend не найден: {blend}")
    if output.exists():
        raise ValueError(f"Отчёт уже существует: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name("msfs_audit.py").resolve()
    command = [str(blender), "-b", "--factory-startup", "--python-exit-code", "1",
               "--python", str(worker), "--", str(blend), str(output)]
    if objects_only:
        command.append("--objects-only")
    completed = run_external(command)
    if completed.returncode or not output.is_file():
        tail = (completed.stdout or b"").decode("utf-8", errors="replace")[-3000:]
        raise ValueError(f"Аудит Blender завершился с кодом {completed.returncode}\n{tail}")
    data = json.loads(output.read_text(encoding="utf-8"))
    if print_summary:
        print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    return 0


def list_blend_objects(blend, blender=None):
    """Return the actual mesh objects from a generated Blender checkpoint."""
    with tempfile.TemporaryDirectory(prefix="msfs_objects_") as temporary:
        report = Path(temporary) / "objects.json"
        audit_blend(blend, report, blender, print_summary=False, objects_only=True)
        data = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps({"blend": str(blend.resolve()), "objects": data.get("objects", [])},
                         ensure_ascii=False))
        return 0


def list_skin_joints(gltf):
    """Offer the real joint names of a glTF skin to the split_by_skin editor."""
    report = skin_joints(Path(gltf))
    if report["read_error"]:
        raise ValueError(f"{gltf}: {report['read_error']}")
    if not report["skins"]:
        raise ValueError(f"{gltf}: в файле нет skin-узлов, разделять по костям нечего.")
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("inventory", help="диагностика ресурсов пакета до сборки")
    scan.add_argument("source", type=Path)
    scan.add_argument("--deep", action="store_true", help="также разобрать glTF: BIN-буферы и неподдерживаемые возможности")
    scan.add_argument("--root", type=Path, action="append", default=[], help="дополнительный корень Packages для поиска базовой модели")
    choices = sub.add_parser("models", help="кандидаты exterior/interior со всеми LOD для выбора состава вручную")
    choices.add_argument("source", type=Path)
    choices.add_argument("--root", type=Path, action="append", default=[], help="дополнительный корень Packages для поиска базовой модели")
    discover = sub.add_parser("catalog")
    discover.add_argument("--root", type=Path, action="append", default=[])
    discover.add_argument("--match", action="append", default=[])
    discover.add_argument("--deep", action="store_true",
                          help="проверить glTF/GLB, BIN и поддерживаемые primitive до создания проекта")
    packages = sub.add_parser("index", help="индекс установленных пакетов и наследования ливрей")
    packages.add_argument("--root", type=Path, action="append", default=[])
    packages.add_argument("--no-cache", action="store_true", help="перестроить индекс, не используя кэш")
    packages.add_argument("--aircraft", help="показать записи только этого самолёта (без учёта регистра)")
    locate = sub.add_parser("find-textures")
    locate.add_argument("report", type=Path)
    locate.add_argument("--root", type=Path, action="append", default=[])
    run = sub.add_parser("build")
    run.add_argument("config", type=Path)
    run.add_argument("--stage", choices=["all", *STAGES], default="all")
    run.add_argument("--input-blend", type=Path)
    audit = sub.add_parser("audit")
    audit.add_argument("blend", type=Path)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--blender", type=Path)
    objects = sub.add_parser("objects")
    objects.add_argument("blend", type=Path)
    objects.add_argument("--blender", type=Path)
    validate = sub.add_parser("validate", help="проверить правила редактирования проекта до запуска Blender")
    validate.add_argument("config", type=Path)
    bones = sub.add_parser("bones", help="имена костей skin-узлов glTF для разделения по костям")
    bones.add_argument("gltf", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            roots = installed_package_roots(args.root) if (args.deep or args.root) else ()
            index = build_index(args.root, near=args.source.resolve())
            print(json.dumps(inventory(args.source.resolve(), args.deep, roots, index), ensure_ascii=False, indent=2))
            return 0
        if args.command == "models":
            roots = installed_package_roots(args.root)
            index = build_index(args.root, near=args.source.resolve())
            print(json.dumps(model_choices(args.source.resolve(), roots=roots, index=index),
                             ensure_ascii=False, indent=2))
            return 0
        if args.command == "catalog":
            print(json.dumps(catalog(args.root, args.match, args.deep), ensure_ascii=False, indent=2))
            return 0
        if args.command == "index":
            index = build_index(args.root, cache=not args.no_cache)
            print(json.dumps({"searched_roots": [str(r) for r in index.roots],
                              "packages": len(index.packages), "aircraft_names": len(index.aircraft),
                              "cached": index.reused, "scanned": index.scanned, "errors": index.errors,
                              "cache_path": str(default_cache_path()),
                              "aircraft": index.describe(args.aircraft)},
                             ensure_ascii=False, indent=2))
            return 0
        if args.command == "find-textures":
            print(json.dumps(locate_report_textures(args.report.resolve(), args.root), ensure_ascii=False, indent=2))
            return 0
        if args.command == "audit":
            return audit_blend(args.blend.resolve(), args.output.resolve(), args.blender.resolve() if args.blender else None)
        if args.command == "objects":
            return list_blend_objects(args.blend.resolve(), args.blender.resolve() if args.blender else None)
        if args.command == "validate":
            return validate_rules(args.config.resolve())
        if args.command == "bones":
            return list_skin_joints(args.gltf.resolve())
        return build(args.config.resolve(), args.stage, args.input_blend.resolve() if args.input_blend else None)
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Операция остановлена пользователем.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

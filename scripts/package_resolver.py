"""MSFS package discovery and resource diagnosis (roadmap priority 1).

Everything here runs without Blender: the CLI and the GUI use it to explain
*why* a package cannot be built and which action would unblock it, instead of
returning one opaque "unavailable" flag.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

from msfs_gltf import load_gltf, read_document, unsupported_geometry_extensions


GENERATED_AIRCRAFT_DIRS = {"msfs_gui_build"}
MODEL_DIR = re.compile(r"model(?:\..+)?", re.I)
TEXTURE_DIR = re.compile(r"texture(?:\..+)?", re.I)
IMAGE_SUFFIXES = {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".hdr", ".ktx2"}

# code -> (short status, recommended user action)
REASONS = {
    "OK": ("Ресурсы найдены",
           "Можно собирать геометрию. Текстуры добавляются отдельным этапом."),
    "SUPPORTED_PARTIAL": ("Доступна только часть моделей",
                          "Подтвердите сборку доступной части (например, только экстерьера) либо подключите пакет, "
                          "в котором лежит недостающая модель."),
    "COMMON_RESOURCES_ONLY": ("Пакет содержит только общие ресурсы",
                              "В пакете нет собственной геометрии: только model XML, текстуры или звуки для других "
                              "самолётов. Подключите пакет с моделью этого самолёта или укажите папку, где он установлен."),
    "LIVERY_ONLY": ("Это ливрея без собственной модели",
                    "Выберите базовый самолёт из base_container или подключите его пакет в дополнительные корни поиска."),
    "UNRESOLVED_ALIAS": ("Не разрешена ссылка на базовую модель",
                         "Пакет ссылается на самолёт, которого нет рядом. Добавьте корень Packages с базовым самолётом "
                         "и повторите сканирование."),
    "NO_MODEL_FOLDER": ("Не найдена папка model",
                        "Укажите папку самолёта с SimObjects/Airplanes и model-каталогом либо задайте glTF вручную."),
    "MISSING_MODEL_CFG": ("Нет model.cfg",
                          "Выберите glTF вручную из списка кандидатов и сохраните его в параметре models проекта."),
    "INVALID_MODEL_CFG": ("model.cfg не указывает моделей",
                          "Проверьте секцию [models]: нужны exterior/normal и interior. Либо задайте glTF вручную."),
    "MISSING_GLTF": ("Не найден glTF модели",
                     "Ожидаемый файл отсутствует в установке. Проверьте целостность пакета или выберите другой LOD."),
    "MISSING_BUFFER": ("Не найден BIN буфера",
                       "glTF ссылается на отсутствующий .bin. Восстановите пакет; смена режима skinning не поможет."),
    "UNREADABLE_GLTF": ("glTF не читается",
                        "Файл повреждён или недоступен. Проверьте права доступа и целостность пакета."),
    "UNSUPPORTED_GLTF_FEATURE": ("glTF использует неподдерживаемые возможности",
                                 "Поддерживаются JSON/GLB, несколько BIN, data URI, sparse и triangle strip/fan. "
                                 "Проблема связана с Draco, points/lines или дополнительными skin-атрибутами; "
                                 "выберите другой LOD или сообщите о пакете разработчику."),
    "NO_TEXTURES": ("Карты не найдены",
                    "Геометрию собрать можно. Для текстур укажите ливрею или дополнительные папки с картами."),
    "PACKAGE_NOT_FOUND": ("Папка самолёта не найдена",
                          "Повторно просканируйте каталог MSFS или укажите исходную папку заново."),
    "ACCESS_DENIED": ("Нет доступа к файлам пакета",
                      "Проверьте права на папку Packages, работу антивируса и облачную синхронизацию."),
    "SCAN_FAILED": ("Пакет не удалось разобрать",
                    "Структура пакета отличается от ожидаемой. Откройте подробную диагностику и укажите папку "
                    "самолёта или glTF вручную."),
}


def reason_text(code):
    return REASONS.get(code, (code, "Проверьте пакет и журнал диагностики."))


def resolve(base, value):
    return (base / Path(os.path.expandvars(str(value))).expanduser()).resolve()


def rebase(path, aircraft, index, *, allow_global=False):
    """A livery's relative path is written for the merged VFS tree, so on disk
    it points inside the livery package where nothing exists. The index knows
    which installed package actually owns the named aircraft or folder."""
    if index is None or path.exists():
        return path, None, []
    found, origin, candidates = index.rebase(path, aircraft, allow_global=allow_global)
    if found is not None:
        return found, origin, []
    return path, None, candidates


def directories(path):
    try:
        return sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p: p.name.casefold())
    except OSError:
        return []


def by_case(path, name):
    direct = path / name
    if direct.exists():
        return direct
    if not path.is_dir():
        return direct
    return next((p for p in path.iterdir() if p.name.casefold() == name.casefold()), direct)


def sections(path):
    section = ""
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].casefold()
        elif "=" in line:
            key, value = line.split("=", 1)
            yield section, key.strip().casefold(), value.strip().strip('"')


def aircraft_folders(source):
    if not source.is_dir():
        raise ValueError(f"Укажите папку распакованного пакета. Путь не найден: {source}")
    children = directories(source)
    # A variation package may ship only textures and an aircraft.cfg; it is
    # still one aircraft folder and must reach the resolver, not raise here.
    # Package roots also carry top-level texture folders, so textures alone
    # are not enough to stop the descent into SimObjects/Airplanes.
    if (any(MODEL_DIR.fullmatch(p.name) for p in children)
            or by_case(source, "aircraft.cfg").is_file()):
        return [source]
    # A leaf below SimObjects/Airplanes is one aircraft even when the package
    # ships only shared resources there (gliders-common, a panel-only stub).
    if source.parent.name.casefold() == "airplanes":
        return [source]
    for root in (source, *children):
        sim = by_case(root, "SimObjects")
        if sim.is_dir():
            airplanes = by_case(sim, "Airplanes")
            if airplanes.is_dir():
                aircraft = [p for p in directories(airplanes)
                            if p.name.casefold() not in GENERATED_AIRCRAFT_DIRS]
                if aircraft:
                    return aircraft
    raise ValueError("Не найдена папка SimObjects/Airplanes. Укажите пакет, его папку самолёта или обёртку с одним пакетом.")


def installed_package_roots(extra_roots=()):
    """Find unpacked MSFS package roots from UserCfg.opt and common installs."""
    candidates = [Path(path).resolve() for path in extra_roots]
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    cfg_files = [appdata / "Microsoft Flight Simulator" / "UserCfg.opt"]
    try:
        cfg_files.extend(local.glob("Packages/Microsoft.FlightSimulator_*/LocalCache/UserCfg.opt"))
    except OSError:
        pass
    for cfg in cfg_files:
        if not cfg.is_file():
            continue
        try:
            lines = cfg.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = re.match(r'\s*InstalledPackagesPath\s+"([^"]+)"', line, re.I)
            if match:
                candidates.append(Path(os.path.expandvars(match.group(1))).expanduser().resolve())
    candidates.extend([
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\MicrosoftFlightSimulator\Packages"),
        local / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "Packages",
    ])
    roots = []
    for path in candidates:
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def find_aircraft(root, max_depth=4):
    """Find SimObjects/Airplanes entries without descending into aircraft assets."""
    found = []
    frontier = [root.resolve()]
    visited = set()
    for _ in range(max_depth + 1):
        following = []
        for folder in frontier:
            if folder in visited or not folder.is_dir():
                continue
            visited.add(folder)
            try:
                children = directories(folder)
                if any(MODEL_DIR.fullmatch(p.name) for p in children):
                    found.append(folder)
                    continue
                sim = by_case(folder, "SimObjects")
                airplanes = by_case(sim, "Airplanes") if sim.is_dir() else None
                if airplanes is not None and airplanes.is_dir():
                    found.extend(p for p in directories(airplanes)
                                 if p.name.casefold() not in GENERATED_AIRCRAFT_DIRS)
                    continue
            except OSError:
                continue
            name = folder.name.casefold()
            if name.startswith(("texture", "model", "sound")) or name in {"scenery", "html_ui", "effects", "localization"}:
                continue
            try:
                following.extend(p for p in children if not p.is_symlink())
            except OSError:
                continue
        frontier = following
    return found


def model_variants(folder):
    return [p for p in directories(folder) if MODEL_DIR.fullmatch(p.name)]


def texture_variants(folder):
    return [p for p in directories(folder) if TEXTURE_DIR.fullmatch(p.name)]


def read_model_xml(path):
    """Return (lod_paths, error). Only the LODS block is parsed: the Behaviors
    section of the same file may contain unescaped comparison operators."""
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        # strerror only: the full OSError repeats the filename already in the message.
        return [], f"Не удалось прочитать {path}: {exc.strerror or type(exc).__name__}"
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    block = re.search(r"<LODS\b[^>]*>.*?</LODS\s*>", source, flags=re.I | re.S)
    try:
        lods = ET.fromstring(block.group()) if block else ET.fromstring(source)
    except ET.ParseError as exc:
        return [], f"Не удалось разобрать {path}: {exc}"
    files = [attr for node in lods.iter() if node.tag.split("}")[-1].casefold() == "lod"
             for key, attr in node.attrib.items() if key.casefold() == "modelfile"]
    if not files:
        return [], f"В {path} не найден ModelFile."
    return [resolve(path.parent, value.replace("\\", "/")) for value in files], None


def model_from_cfg(folder, index=None, aircraft=None):
    """Declared exterior/interior glTF paths, exactly as model.cfg states them."""
    cfg = by_case(folder, "model.cfg")
    if not cfg.is_file():
        raise ValueError(f"Не найден {cfg}. Задайте models в JSON по результатам inventory.")
    owner = aircraft if aircraft is not None else (
        folder.parent if MODEL_DIR.fullmatch(folder.name) else folder)
    entries = {key: val for section, key, val in sections(cfg) if section == "models"}
    models = []
    for role, value in (("exterior", entries.get("exterior") or entries.get("normal")),
                        ("interior", entries.get("interior"))):
        if not value:
            continue
        path = resolve(folder, value.replace("\\", "/"))
        path, origin, _ = rebase(path, owner, index)
        if path.suffix.casefold() == ".xml":
            files, error = read_model_xml(path)
            if error:
                raise ValueError(f"{error} Задайте models вручную.")
            path = files[0]
        models.append({"path": str(path), "role": role, "origin": origin or "model.cfg"})
    if not models:
        raise ValueError(f"В {cfg} нет локальных exterior/normal/interior. Задайте models вручную.")
    return models


def _geometry_counts(document):
    """Vertex/triangle totals from the glTF JSON alone; the BIN is never read."""
    accessors = document.get("accessors") or []
    positions = set()
    triangles = 0
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            if primitive.get("mode", 4) != 4:
                continue
            attributes = primitive.get("attributes") or {}
            position = attributes.get("POSITION")
            source = primitive.get("indices", position)
            if not isinstance(source, int) or not 0 <= source < len(accessors):
                continue
            count = accessors[source].get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                triangles += count // 3
            if isinstance(position, int) and 0 <= position < len(accessors):
                positions.add(position)
    vertices = sum(accessors[index].get("count", 0) for index in sorted(positions)
                   if isinstance(accessors[index].get("count"), int))
    return (vertices or None), (triangles or None)


def inspect_gltf(path):
    """Deep check of one glTF/GLB using the shared container loader."""
    result = {"path": str(path), "available": path.is_file(), "missing_buffers": [], "unsupported": [],
              "read_error": None, "vertices": None, "triangles": None,
              "source_format": path.suffix.casefold().lstrip("."), "extensions_used": [],
              "extensions_required": [], "primitive_modes": [], "sparse_accessors": 0,
              "buffer_count": 0}
    if not result["available"]:
        return result
    try:
        asset = load_gltf(path)
        document = asset.document
        result["source_format"] = asset.source_format
    except FileNotFoundError as exc:
        result["missing_buffers"].append(str(exc).removeprefix("Не найден BIN/буфер модели: "))
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            document = None
        if document is None:
            result["available"] = False
            result["read_error"] = str(exc)
            return result
    except (OSError, ValueError) as exc:
        result["available"] = False
        result["read_error"] = str(exc)
        return result
    if not isinstance(document, dict):
        result["available"] = False
        result["read_error"] = "ожидался JSON-объект glTF"
        return result
    result["extensions_used"] = sorted(str(value) for value in (document.get("extensionsUsed") or []))
    result["extensions_required"] = sorted(str(value) for value in (document.get("extensionsRequired") or []))
    result["buffer_count"] = len(document.get("buffers") or [])
    result["sparse_accessors"] = sum(1 for accessor in document.get("accessors") or []
                                     if isinstance(accessor, dict) and "sparse" in accessor)
    result["unsupported"].extend(unsupported_geometry_extensions(document))
    modes = {primitive.get("mode", 4) for mesh in document.get("meshes") or []
             for primitive in mesh.get("primitives") or []}
    result["primitive_modes"] = sorted(mode for mode in modes if isinstance(mode, int))
    # The geometry adapter triangulates the standard strip/fan modes before
    # handing the document to Blender. Points/lines/line loops remain outside
    # the aircraft mesh contract and are reported before a worker is started.
    unsupported_modes = modes - {4, 5, 6}
    if unsupported_modes:
        result["unsupported"].append(f"primitive modes {sorted(unsupported_modes)}")
    result["vertices"], result["triangles"] = _geometry_counts(document)
    return result


def skin_joints(path):
    """Joint names per skinned node, read from the glTF JSON without Blender."""
    path = Path(path)
    result = {"path": str(path), "available": path.is_file(), "read_error": None, "skins": []}
    if not result["available"]:
        result["read_error"] = "файл не найден"
        return result
    try:
        # Joint metadata does not depend on vertex buffers. Keep this command
        # useful for minimal/partial JSON glTF and use the GLB JSON chunk when
        # the source is a binary container.
        document = read_document(path)
    except (OSError, ValueError) as exc:
        result["read_error"] = str(exc)
        return result
    if not isinstance(document, dict):
        result["read_error"] = "ожидался JSON-объект glTF"
        return result
    nodes = document.get("nodes") or []
    skins = document.get("skins") or []
    for node in nodes:
        if not isinstance(node, dict) or "skin" not in node or "mesh" not in node:
            continue
        index = node["skin"]
        joints = []
        if isinstance(index, int) and 0 <= index < len(skins) and isinstance(skins[index], dict):
            for joint in skins[index].get("joints") or []:
                if isinstance(joint, int) and 0 <= joint < len(nodes) and isinstance(nodes[joint], dict):
                    joints.append(nodes[joint].get("name"))
        result["skins"].append({"node": node.get("name"), "joints": joints})
    return result


def _lod_number(path):
    match = re.search(r"lod\s*(\d+)", Path(path).stem, re.I)
    return int(match.group(1)) if match else None


def _lod_index(path):
    number = _lod_number(path)
    return 0 if number is None else number


def _guess_role(path):
    # Token match, not substring: "int_LOD00" is an interior, "Print" is not.
    tokens = set(re.split(r"[^a-z0-9]+", path.stem.casefold()))
    return "interior" if tokens & {"int", "interior", "cockpit", "panel", "vc"} else "exterior"


def inspect_variant(folder, aircraft, deep=False, index=None):
    """Diagnose one model.* directory of an aircraft."""
    variant = {"folder": folder.name, "gltf": [], "models": [], "lods": [], "candidates": [],
               "missing_resources": [], "model_cfg_selection": [], "declared_roles": [], "reason_code": "OK"}
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        variant["reason_code"] = "ACCESS_DENIED"
        variant["model_cfg_selection"] = str(exc)
        return variant
    variant["gltf"] = sorted(str(p.relative_to(aircraft)) for p in entries
                             if p.suffix.casefold() in {".gltf", ".glb"})
    cfg = by_case(folder, "model.cfg")
    cfg_present = cfg.is_file()
    no_cfg_code = "INVALID_MODEL_CFG" if cfg_present else "MISSING_MODEL_CFG"
    declared = {}
    if cfg_present:
        try:
            values = {key: val for section, key, val in sections(cfg) if section == "models"}
            declared = {"exterior": values.get("exterior") or values.get("normal"),
                        "interior": values.get("interior")}
            declared = {role: value for role, value in declared.items() if value}
        except OSError as exc:
            variant["reason_code"] = "ACCESS_DENIED"
            variant["model_cfg_selection"] = str(exc)
            return variant
    else:
        variant["reason_code"] = "MISSING_MODEL_CFG"
        variant["model_cfg_selection"] = f"Не найден {cfg}."
        variant["missing_resources"].append({"kind": "model_cfg", "path": str(cfg), "variant": folder.name})

    if declared:
        variant["declared_roles"] = sorted(declared)
        for role, value in declared.items():
            path = resolve(folder, value.replace("\\", "/"))
            path, rebased, ambiguous = rebase(path, aircraft, index)
            origin = rebased or "model.cfg"
            if ambiguous:
                variant["missing_resources"].append({"kind": "ambiguous", "path": str(path), "role": role,
                                                     "variant": folder.name,
                                                     "detail": "несколько установленных пакетов: " + "; ".join(ambiguous)})
            if path.suffix.casefold() == ".xml":
                files, error = read_model_xml(path)
                if error:
                    variant["reason_code"] = "INVALID_MODEL_CFG"
                    variant["model_cfg_selection"] = error
                    variant["missing_resources"].append({"kind": "model_xml", "path": str(path),
                                                         "role": role, "variant": folder.name, "detail": error})
                    continue
                origin = rebased or "xml"
                for lod_index, lod in enumerate(files):
                    variant["lods"].append({"path": str(lod), "role": role, "index": lod_index,
                                            "role_source": "model.cfg", "available": lod.is_file(),
                                            "variant": folder.name})
                if not files:
                    continue
                missing_lods = [str(lod) for lod in files[1:] if not lod.is_file()]
                for lod in missing_lods:
                    variant["missing_resources"].append({"kind": "gltf_lod", "path": lod, "role": role,
                                                         "variant": folder.name})
                path = files[0]
            model = {"path": str(path), "role": role, "origin": origin, "variant": folder.name,
                     "available": path.is_file(), "missing_buffers": [], "unsupported": []}
            if not model["available"]:
                variant["missing_resources"].append({"kind": "gltf", "path": str(path), "role": role,
                                                     "variant": folder.name})
                model["reason_code"] = "MISSING_GLTF"
            elif deep:
                checked = inspect_gltf(path)
                for key in ("source_format", "extensions_used", "extensions_required", "primitive_modes",
                            "sparse_accessors", "buffer_count"):
                    model[key] = checked[key]
                model["missing_buffers"] = checked["missing_buffers"]
                model["unsupported"] = checked["unsupported"]
                model["available"] = checked["available"] and not checked["missing_buffers"] and not checked["unsupported"]
                if checked["read_error"]:
                    model["read_error"] = checked["read_error"]
                    model["reason_code"] = "UNREADABLE_GLTF"
                    variant["missing_resources"].append({"kind": "gltf_unreadable", "path": str(path),
                                                         "role": role, "variant": folder.name,
                                                         "detail": checked["read_error"]})
                elif checked["missing_buffers"]:
                    model["reason_code"] = "MISSING_BUFFER"
                    variant["missing_resources"].extend({"kind": "buffer", "path": item, "role": role,
                                                         "variant": folder.name} for item in checked["missing_buffers"])
                elif checked["unsupported"]:
                    model["reason_code"] = "UNSUPPORTED_GLTF_FEATURE"
                    variant["missing_resources"].append({"kind": "gltf_feature", "path": str(path), "role": role,
                                                         "variant": folder.name,
                                                         "detail": ", ".join(checked["unsupported"])})
            variant["models"].append(model)
            if model["available"]:
                variant["candidates"].append({"path": str(path), "role": role, "origin": origin,
                                              "role_source": "model.cfg", "variant": folder.name})
        if not variant["models"]:
            variant["reason_code"] = "INVALID_MODEL_CFG"
            variant["model_cfg_selection"] = f"В {cfg} нет локальных exterior/normal/interior."
        else:
            available = [m for m in variant["models"] if m["available"]]
            variant["model_cfg_selection"] = [{"path": m["path"], "role": m["role"]} for m in available]
            if not available:
                variant["reason_code"] = next((m.get("reason_code", "MISSING_GLTF") for m in variant["models"]), "MISSING_GLTF")
            elif len(available) < len(declared):
                variant["reason_code"] = "SUPPORTED_PARTIAL"

    if not variant["candidates"]:
        # Nothing declared is readable. Some packages ship the LOD glTF files
        # but not the XML/model.cfg that indexes them, so offer what is on disk
        # and let the user assign roles explicitly. A path that was declared
        # and already rejected (missing BIN, GLB, unreadable) is not offered
        # again just because its filename matched the scan.
        rejected = {m["path"] for m in variant["models"]}
        for xml in sorted((p for p in entries if p.suffix.casefold() == ".xml"), key=lambda p: p.name.casefold()):
            files, error = read_model_xml(xml)
            if error:
                continue
            role = _guess_role(xml)
            for lod_index, lod in enumerate(files):
                variant["lods"].append({"path": str(lod), "role": role, "index": lod_index,
                                        "role_source": "имя файла", "available": lod.is_file(),
                                        "variant": folder.name})
            if files and files[0].is_file() and str(files[0]) not in rejected:
                variant["candidates"].append({"path": str(files[0]), "role": role, "origin": "xml",
                                              "role_source": "имя файла", "variant": folder.name})
        scanned = {}
        for name in variant["gltf"]:
            path = aircraft / name
            if str(path) in rejected:
                continue
            key = (re.sub(r"[\s_.-]*lod\s*\d+", "", path.stem, flags=re.I).casefold(), _guess_role(path))
            if key not in scanned or _lod_index(path) < _lod_index(scanned[key]):
                scanned[key] = path
        for path in sorted(scanned.values(), key=lambda p: p.name.casefold()):
            if not any(c["path"] == str(path) for c in variant["candidates"]):
                variant["candidates"].append({"path": str(path), "role": _guess_role(path), "origin": "scan",
                                              "role_source": "имя файла", "variant": folder.name})
        if deep:
            # Discovered files were never declared, so nothing checked them yet.
            # Offering a GLB or a glTF without its BIN would move the failure
            # from the diagnosis into the worker.
            checked_candidates = []
            for candidate in variant["candidates"]:
                checked = inspect_gltf(Path(candidate["path"]))
                if checked["available"] and not checked["missing_buffers"] and not checked["unsupported"]:
                    checked_candidates.append(candidate)
                    continue
                detail = checked["read_error"] or ", ".join(checked["missing_buffers"] + checked["unsupported"])
                kind = "gltf_unreadable" if checked["read_error"] else ("buffer" if checked["missing_buffers"] else "gltf_feature")
                variant["missing_resources"].append({"kind": kind, "path": candidate["path"], "role": candidate["role"],
                                                     "variant": folder.name, "detail": detail})
            variant["candidates"] = checked_candidates
        if variant["candidates"]:
            variant["reason_code"] = no_cfg_code
            variant["model_cfg_selection"] = [{"path": c["path"], "role": c["role"]} for c in variant["candidates"]]
        elif variant["reason_code"] in {"OK", "MISSING_MODEL_CFG", "INVALID_MODEL_CFG"}:
            rejected_codes = {"gltf_unreadable": "UNREADABLE_GLTF", "buffer": "MISSING_BUFFER",
                              "gltf_feature": "UNSUPPORTED_GLTF_FEATURE", "gltf": "MISSING_GLTF"}
            variant["reason_code"] = next((rejected_codes[item["kind"]] for item in variant["missing_resources"]
                                           if item["kind"] in rejected_codes),
                                          next((m.get("reason_code") for m in variant["models"]
                                                if not m["available"] and m.get("reason_code")), no_cfg_code))

    if variant["reason_code"] == "OK" and not any(m["available"] for m in variant["models"]) and variant["candidates"]:
        variant["reason_code"] = no_cfg_code
    if not variant["gltf"] and not any(m["available"] for m in variant["models"]):
        xml_only = any(p.suffix.casefold() == ".xml" for p in entries)
        bin_present = any(p.suffix.casefold() == ".bin" for p in entries)
        if xml_only and not bin_present and not cfg_present:
            variant["reason_code"] = "COMMON_RESOURCES_ONLY"
            for lod in variant["lods"]:
                if not lod["available"]:
                    variant["missing_resources"].append({"kind": "gltf", "path": lod["path"], "role": lod["role"],
                                                         "variant": folder.name})
    return variant


def package_manifest(folder):
    for parent in (folder, *folder.parents):
        manifest = parent / "manifest.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return {}, parent
            return (data if isinstance(data, dict) else {}), parent
        if (parent / "layout.json").is_file():
            return {}, parent
    return {}, None


def locate_aircraft_folder(name, roots):
    """Bounded name lookup for a base_container that lives in another package."""
    wanted = name.casefold()
    for root in roots:
        for folder in find_aircraft(Path(root)):
            if folder.name.casefold() == wanted:
                return folder
    return None


def collect_dependencies(folder, roots=(), index=None):
    """Report every cross-package link the configs declare, resolved or not."""
    folder = Path(folder).resolve()
    dependencies = []
    manifest, package_root = package_manifest(folder)
    for item in manifest.get("dependencies") or []:
        name = item.get("name") if isinstance(item, dict) else item
        if name:
            entry = {"kind": "manifest", "name": str(name), "path": None,
                     "resolved": False, "source": "manifest.json"}
            if index is not None:
                matches = index.package_folders(name)
                if len(matches) == 1:
                    entry.update(path=str(matches[0]), resolved=True, origin="package_index")
                elif len(matches) > 1:
                    entry["problem_code"] = "ambiguous_owner"
                    entry["detail"] = "несколько установленных пакетов: " + "; ".join(map(str, matches))
                else:
                    entry["problem_code"] = "manifest_package_missing"
                    entry["detail"] = "пакет не найден среди установленных корней"
            dependencies.append(entry)
    cfg = by_case(folder, "aircraft.cfg")
    if cfg.is_file():
        try:
            for section, key, value in sections(cfg):
                if section == "variation" and key == "base_container" and value:
                    target = resolve(folder, value.replace("\\", "/"))
                    entry = {"kind": "base_container", "name": Path(value.replace("\\", "/")).name,
                             "path": str(target), "resolved": target.is_dir(), "source": str(cfg)}
                    if not entry["resolved"] and index is not None:
                        found, origin, ambiguous = rebase(target, folder, index, allow_global=True)
                        if ambiguous:
                            entry["problem_code"] = "ambiguous_owner"
                            entry["detail"] = "несколько установленных пакетов: " + "; ".join(ambiguous)
                        elif origin:
                            entry.update(path=str(found), resolved=True, origin=origin)
                        else:
                            entry["base_installed"] = False
                            entry["problem_code"] = "base_aircraft_missing"
                            entry["detail"] = "базовый самолёт не установлен"
                    if not entry["resolved"] and roots:
                        found = locate_aircraft_folder(entry["name"], roots)
                        if found is not None:
                            entry["path"] = str(found)
                            entry["resolved"] = True
                            entry["origin"] = "name_lookup"
                    dependencies.append(entry)
        except OSError:
            dependencies.append({"kind": "base_container", "name": None, "path": str(cfg),
                                 "resolved": False, "source": str(cfg), "detail": "файл не читается"})
    base_entry = next((d for d in dependencies if d["kind"] == "base_container"), None)
    for variant in model_variants(folder):
        cfg = by_case(variant, "model.cfg")
        if not cfg.is_file():
            continue
        try:
            values = [(key, value) for section, key, value in sections(cfg) if section == "models"]
        except OSError:
            continue
        for key, value in values:
            if not value:
                continue
            target = resolve(variant, value.replace("\\", "/"))
            if folder not in target.parents and target != folder:
                found, origin, ambiguous = rebase(target, folder, index)
                entry = {"kind": "model", "name": key,
                         "path": str(found if found is not None else target),
                         "resolved": bool(found is not None and found.exists()), "source": str(cfg)}
                if origin:
                    entry["origin"] = origin
                if ambiguous:
                    entry["problem_code"] = "ambiguous_owner"
                    entry["detail"] = "несколько установленных пакетов: " + "; ".join(ambiguous)
                elif not entry["resolved"] and base_entry is not None:
                    # The base folder can be installed while the file the livery
                    # declares inside it is not: those are different user actions.
                    if base_entry["resolved"]:
                        entry["problem_code"] = "declared_model_file_missing"
                        entry["detail"] = "базовый самолёт установлен, но объявленный файл в нём отсутствует"
                    else:
                        entry["problem_code"] = "base_aircraft_missing"
                        entry["detail"] = "базовый самолёт не установлен"
                dependencies.append(entry)
    for texture in texture_variants(folder):
        cfg = by_case(texture, "texture.cfg")
        if not cfg.is_file():
            continue
        try:
            values = [(key, value) for _, key, value in sections(cfg) if key.startswith("fallback.")]
        except OSError:
            continue
        for key, value in values:
            target = resolve(texture, value.replace("\\", "/"))
            if folder not in target.parents:
                found, origin, ambiguous = rebase(target, folder, index, allow_global=True)
                resolved_path = found if found is not None else target
                entry = {"kind": "texture_fallback", "name": key, "path": str(resolved_path),
                         "resolved": bool(found is not None and found.is_dir()), "optional": True,
                         "source": str(cfg)}
                if ambiguous:
                    entry["problem_code"] = "ambiguous_owner"
                    entry["detail"] = "несколько установленных пакетов: " + "; ".join(ambiguous)
                elif origin:
                    entry["origin"] = origin
                elif not entry["resolved"]:
                    entry["problem_code"] = "optional_texture_fallback_missing"
                    entry["detail"] = "папка fallback не найдена"
                dependencies.append(entry)
    unique = []
    seen = set()
    for item in dependencies:
        key = (item["kind"], item["name"], item["path"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, manifest, package_root


def has_texture_images(folder):
    try:
        return any(p.suffix.casefold() in IMAGE_SUFFIXES for p in folder.iterdir() if p.is_file())
    except OSError:
        return False


def resolve_aircraft(folder, *, roots=(), deep=False, index=None):
    """Full diagnosis of one aircraft folder. Never raises for a bad package."""
    folder = Path(folder)
    result = {"aircraft": folder.name, "path": str(folder), "profile": "generic", "variants": [],
              "textures": [], "texture_images": False, "can_build_geometry": False, "can_build_textures": False,
              "partial": False, "needs_model_selection": False, "cross_variant_models": False,
              "best_variant": None, "reason_code": "OK",
              "missing_resources": [], "candidates": [], "dependencies": [], "best_models": [], "deep": bool(deep)}
    if not folder.is_dir():
        result["reason_code"] = "PACKAGE_NOT_FOUND"
    else:
        try:
            result["dependencies"], manifest, package_root = collect_dependencies(folder, roots, index)
            result["manifest_title"] = manifest.get("title")
            result["package_version"] = manifest.get("package_version")
            if package_root is not None:
                result["package_path"] = str(package_root)
            folders = model_variants(folder)
            result["textures"] = [p.name for p in texture_variants(folder)]
            result["texture_images"] = any(has_texture_images(p) for p in texture_variants(folder))
            for variant_folder in folders:
                result["variants"].append(inspect_variant(variant_folder, folder, deep, index))
            if not folders:
                base = next((d for d in result["dependencies"] if d["kind"] == "base_container"), None)
                if base is not None:
                    result["reason_code"] = "UNRESOLVED_ALIAS" if not base["resolved"] else "LIVERY_ONLY"
                    result["missing_resources"].append({"kind": "base_container", "path": base["path"],
                                                        "name": base["name"]})
                    if base["resolved"]:
                        result["candidates"].append({"path": base["path"], "role": "aircraft",
                                                     "origin": "base_container", "variant": None})
                elif result["textures"] and by_case(folder, "aircraft.cfg").is_file():
                    result["reason_code"] = "LIVERY_ONLY"
                elif result["textures"]:
                    # Shared texture folders without an aircraft.cfg are resources
                    # for other packages, not a livery of their own.
                    result["reason_code"] = "COMMON_RESOURCES_ONLY"
                    result["missing_resources"].append({"kind": "model", "name": folder.name, "path": str(folder)})
                else:
                    result["reason_code"] = "NO_MODEL_FOLDER"
                    result["missing_resources"].append({"kind": "model", "name": folder.name, "path": str(folder)})
            else:
                usable = [v for v in result["variants"] if v["candidates"]]
                if usable:
                    # Prefer a complete exterior+interior variant, then the one
                    # with most available models, then the plain "model" folder.
                    best = max(usable, key=lambda v: (len(v["candidates"]),
                                                      v["reason_code"] == "OK",
                                                      v["folder"].casefold() == "model"))
                    result["best_variant"] = best["folder"]
                    # Discovery can offer several files for one role (fuselage,
                    # wings, ...). The default build takes one per role; the full
                    # candidate list stays available for manual selection.
                    result["best_models"] = []
                    for candidate in best["candidates"]:
                        if any(m["role"] == candidate["role"] for m in result["best_models"]):
                            continue
                        result["best_models"].append({"path": candidate["path"], "role": candidate["role"],
                                                      "origin": candidate["origin"], "variant": candidate["variant"]})
                    result["candidates"] = [c for v in result["variants"] for c in v["candidates"]]
                    # Some aircraft keep exterior and interior in separate
                    # model.* folders with no cfg linking them. Offer the
                    # complementary role, but keep its origin visible so the
                    # user confirms the assignment instead of trusting a name.
                    covered = {m["role"] for m in result["best_models"]}
                    for role in ("exterior", "interior"):
                        if role in covered:
                            continue
                        other = next((c for c in result["candidates"]
                                      if c["role"] == role and c["variant"] != best["folder"]), None)
                        if other is not None:
                            result["best_models"].append({"path": other["path"], "role": role,
                                                          "origin": other["origin"], "variant": other["variant"]})
                            result["cross_variant_models"] = True
                    result["can_build_geometry"] = True
                    declared_roles = set(best["declared_roles"])
                    # When nothing declared was usable the candidates came from
                    # discovery, so the declared roles say nothing about what is
                    # actually missing.
                    available_roles = ({m["role"] for m in best["models"] if m["available"]} if best["models"]
                                       else {c["role"] for c in best["candidates"]})
                    result["partial"] = bool(declared_roles - available_roles)
                    result["needs_model_selection"] = result["partial"] or result["cross_variant_models"] or best["reason_code"] in {
                        "MISSING_MODEL_CFG", "INVALID_MODEL_CFG", "SUPPORTED_PARTIAL"}
                    if result["partial"]:
                        result["reason_code"] = "SUPPORTED_PARTIAL"
                    elif best["reason_code"] in {"MISSING_MODEL_CFG", "INVALID_MODEL_CFG"}:
                        result["reason_code"] = best["reason_code"]
                    result["missing_resources"] = list(best["missing_resources"])
                else:
                    codes = [v["reason_code"] for v in result["variants"]]
                    result["missing_resources"] = [m for v in result["variants"] for m in v["missing_resources"]]
                    result["candidates"] = [c for v in result["variants"] for c in v["candidates"]]
                    if "COMMON_RESOURCES_ONLY" in codes:
                        result["reason_code"] = "COMMON_RESOURCES_ONLY"
                    elif all(code == "MISSING_MODEL_CFG" for code in codes):
                        result["reason_code"] = "MISSING_MODEL_CFG"
                    else:
                        result["reason_code"] = next((c for c in codes if c != "OK"), "MISSING_GLTF")
                    base = next((d for d in result["dependencies"] if d["kind"] == "base_container" and not d["resolved"]), None)
                    if base is not None and result["reason_code"] in {"MISSING_GLTF", "COMMON_RESOURCES_ONLY", "MISSING_MODEL_CFG"}:
                        result["reason_code"] = "UNRESOLVED_ALIAS"
                        result["missing_resources"].append({"kind": "base_container", "path": base["path"],
                                                            "name": base["name"]})
        except PermissionError:
            result["reason_code"] = "ACCESS_DENIED"
        except OSError:
            result["reason_code"] = "ACCESS_DENIED"
    result["can_build_textures"] = bool(result["can_build_geometry"] and result["texture_images"])
    if result["can_build_geometry"] and not result["texture_images"] and result["reason_code"] == "OK":
        result["reason_code"] = "NO_TEXTURES"
    known = {(item.get("kind"), item.get("path")) for item in result["missing_resources"]}
    for dependency in result["dependencies"]:
        if dependency["kind"] in {"base_container", "model"} and not dependency["resolved"]:
            key = (dependency["kind"], dependency["path"])
            if key not in known:
                known.add(key)
                result["missing_resources"].append({"kind": dependency["kind"], "path": dependency["path"],
                                                    "name": dependency["name"]})
    result["reason"], result["action"] = reason_text(result["reason_code"])
    return result


def _path_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def model_choices(folder, *, roots=(), index=None):
    """Per-role candidate list for the selection wizard, with LOD geometry counts.

    A livery can declare an interior XML that the installed base package does not
    ship while the base still holds the interior glTF under another LOD name. The
    declared path alone therefore cannot answer "what can be built": the base
    package is scanned as well whenever a role has no usable candidate.
    """
    folder = Path(folder)
    report = resolve_aircraft(folder, roots=roots, deep=True, index=index)
    entries = {}

    def add(path, role, role_source, lod, variant, origin, declared=False):
        path = Path(path)
        key = _path_key(path)
        # The chain position in the model XML is not the LOD number: a chain can
        # skip a level, so S1_LOD06 would otherwise be shown as "05".
        number = _lod_number(path)
        lod = number if number is not None else lod
        entry = entries.get(key)
        if entry is None:
            checked = inspect_gltf(path)
            entry = {"path": str(path), "name": path.name, "role": role, "role_source": role_source,
                     "lod": lod, "variant": variant, "origin": origin, "declared": declared, "default": False,
                     "available": checked["available"] and not checked["missing_buffers"] and not checked["unsupported"],
                     "vertices": checked["vertices"], "triangles": checked["triangles"],
                     "missing_buffers": checked["missing_buffers"], "unsupported": checked["unsupported"],
                     "read_error": checked["read_error"]}
            entry["status"] = ("UNREADABLE_GLTF" if checked["read_error"] else
                               "MISSING_BUFFER" if checked["missing_buffers"] else
                               "UNSUPPORTED_GLTF_FEATURE" if checked["unsupported"] else
                               "OK" if entry["available"] else "MISSING_GLTF")
            entries[key] = entry
        else:
            entry["declared"] = entry["declared"] or declared
            if entry["lod"] is None:
                entry["lod"] = lod
        return entry

    for variant in report["variants"]:
        for model in variant["models"]:
            add(model["path"], model["role"], "model.cfg", None, variant["folder"], model["origin"], True)
        for lod in variant["lods"]:
            add(lod["path"], lod["role"], lod["role_source"], lod["index"], variant["folder"],
                "xml" if lod["role_source"] == "model.cfg" else "scan")
        for candidate in variant["candidates"]:
            add(candidate["path"], candidate["role"], candidate["role_source"], None,
                variant["folder"], candidate["origin"])

    # A file rejected during discovery is dropped from the candidate list, but the
    # user can still see it on disk. Show it with the reason instead of silence.
    for item in report["missing_resources"]:
        if item["kind"] not in {"gltf_unreadable", "buffer", "gltf_feature"}:
            continue
        path = Path(item["path"])
        if path.suffix.casefold() not in {".gltf", ".glb"} or _path_key(path) in entries:
            continue
        add(path, item.get("role") or _guess_role(path), "имя файла", None, item.get("variant"), "scan")

    base = next((d for d in report["dependencies"] if d["kind"] == "base_container" and d["resolved"]), None)
    base_scanned = False
    if base is not None:
        covered = {entry["role"] for entry in entries.values() if entry["available"]}
        if report["partial"] or len(covered) < 2:
            base_scanned = True
            base_report = resolve_aircraft(Path(base["path"]), roots=roots, deep=True, index=index)
            for variant in base_report["variants"]:
                for lod in variant["lods"]:
                    add(lod["path"], lod["role"], lod["role_source"], lod["index"], variant["folder"], "base_package")
                for candidate in variant["candidates"]:
                    add(candidate["path"], candidate["role"], candidate["role_source"], None,
                        variant["folder"], "base_package")

    for model in report["best_models"]:
        entry = entries.get(_path_key(model["path"]))
        if entry is not None:
            entry["default"] = True

    roles = {}
    for role in ("exterior", "interior"):
        chosen = [entry for entry in entries.values() if entry["role"] == role]
        # A declared model is the package's own statement; a name is only a hint.
        # LOD00 is the nearest and most detailed level, so it sorts first.
        chosen.sort(key=lambda e: (not e["default"], not e["declared"], not e["available"],
                                   e["lod"] if e["lod"] is not None else 99, e["name"].casefold()))
        roles[role] = chosen
    source_gaps = [{"kind": item.get("kind"), "role": item.get("name"),
                    "path": item.get("path"), "problem_code": item.get("problem_code"),
                    "detail": item.get("detail")}
                   for item in report["dependencies"]
                   if not item.get("resolved") and item.get("kind") == "model"]
    return {"aircraft": report["aircraft"], "path": report["path"], "reason_code": report["reason_code"],
            "reason": report["reason"], "action": report["action"], "partial": report["partial"],
            "needs_model_selection": report["needs_model_selection"],
            "can_build_geometry": report["can_build_geometry"],
            "base_aircraft": None if base is None else {"name": base.get("name"), "path": base["path"],
                                                       "scanned": base_scanned},
            "roles": roles, "default_models": [{"path": m["path"], "role": m["role"]} for m in report["best_models"]],
            "source_gaps": source_gaps,
            "missing_resources": report["missing_resources"]}

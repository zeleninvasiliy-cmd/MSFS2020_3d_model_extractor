"""Portable desktop settings and project file operations (no Blender dependency)."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

# The shipped VERSION file is the single source of truth; PyInstaller places it
# in _internal, the source tree keeps it next to this module.
VERSION = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "VERSION").read_text(encoding="utf-8").strip()


def settings_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "MSFSModelBuilder"


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_settings():
    try:
        value = json.loads((settings_dir() / "settings.json").read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    atomic_json(settings_dir() / "settings.json", data)


def detect_blender():
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    candidates = []
    for root in (os.environ.get("PROGRAMFILES", "C:/Program Files"),
                 str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs")):
        candidates.extend(Path(root).glob("Blender Foundation/Blender*/blender.exe"))
    return str(sorted(candidates, reverse=True)[0]) if candidates else ""


def valid_filename(name):
    if not name or name in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((" ", ".")):
        raise ValueError("Имя должно быть обычным именем файла без / \\ : * ? и других служебных символов.")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("Это имя зарезервировано Windows.")
    return name


def literal_pattern(name):
    return "".join({"[": "[[]", "*": "[*]", "?": "[?]"}.get(char, char) for char in name)


def owned_blend_folder(project):
    project = Path(project).resolve()
    folder = project.parent / "blend"
    marker = project.parent / ".msfs-project.json"
    try:
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if owner.get("project") == project.name and folder.resolve().parent == project.parent and not folder.is_symlink() and not folder.is_junction():
            return folder
    except (OSError, ValueError):
        pass
    return None


def retire_project(project):
    """Recoverable delete. Legacy/shared folders never get moved implicitly."""
    project = Path(project).resolve(strict=True)
    if not project.is_file() or project.suffix.lower() != ".json":
        raise ValueError("Не выбран JSON проекта.")
    owned = owned_blend_folder(project)
    destination = settings_dir() / "DeletedProjects" / f"{project.stem}-{uuid.uuid4().hex[:10]}"
    destination.mkdir(parents=True, exist_ok=False)
    atomic_json(destination / "restore.json", {"original_project": str(project), "original_blend": str(owned) if owned else None})
    if owned and owned.is_dir():
        shutil.move(str(owned), str(destination / "blend"))
    shutil.move(str(project), str(destination / project.name))
    return destination

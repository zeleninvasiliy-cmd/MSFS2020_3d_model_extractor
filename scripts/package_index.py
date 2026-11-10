"""Index of installed MSFS packages and the aircraft they contain (roadmap priority 2).

Livery configs write relative paths for the simulator's virtual file system:
`..\\Asobo_208B_GRAND_CARAVAN_EX\\model\\...` lands in the *base* package once
MSFS merges the trees, but on disk it points inside the livery package where
nothing exists. The index lets the resolver rebase such a path onto the package
that actually owns the named aircraft.

No bpy, no Blender. Built once per catalog scan and shared by every aircraft.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from package_resolver import by_case, find_aircraft, package_manifest


# Version 3 includes the per-aircraft configuration files and canonical path
# keys that are stable across Windows 8.3 aliases.
# signature.  The index stores ``base_container`` from aircraft.cfg, so an
# in-place cfg edit must invalidate an otherwise unchanged package folder.
INDEX_VERSION = 3


def _key(path):
    # Path.resolve() hits _getfinalpathname on Windows for every call; the
    # catalog rebases thousands of paths, so compare normalized strings instead.
    value = os.path.normcase(os.path.abspath(os.fspath(path)))
    # A Windows runner may expose %TEMP% through an 8.3 alias (for example
    # RUNNER~1) while Path.resolve() returns the long spelling.  Canonicalize
    # only such paths; normal MSFS paths keep the fast string-only path.
    if os.name == "nt" and any("~" in part for part in Path(value).parts):
        value = os.path.normcase(os.path.realpath(value))
    return value


def _signature(package):
    """Cheap change detector for package topology and aircraft inheritance.

    The index does not parse model files, but it caches ``base_container``
    from every aircraft.cfg.  Directory mtimes are not a reliable signal for
    an in-place file edit on Windows, so each direct aircraft config is
    included explicitly.  This remains much cheaper than hashing or walking
    all glTF/BIN/texture assets.
    """
    parts = []
    airplanes = by_case(by_case(package, "SimObjects"), "Airplanes")
    paths = [package, package / "manifest.json", package / "layout.json", airplanes]
    try:
        paths.extend(
            by_case(folder, "aircraft.cfg")
            for folder in sorted(
                (item for item in airplanes.iterdir() if item.is_dir()),
                key=lambda item: item.name.casefold(),
            )
        )
    except OSError:
        # The package will be reported by the normal scan; a stable missing
        # marker here lets one inaccessible package coexist with the rest.
        pass
    for path in paths:
        try:
            stat = path.stat()
            # Lists, not tuples: JSON round-trips tuples as lists and the
            # cached signature has to compare equal to the recomputed one.
            parts.append([str(path), stat.st_mtime_ns, stat.st_size])
        except OSError:
            parts.append([str(path), None, None])
    return parts


def default_cache_path():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return Path(local) / "MSFSModelBuilder" / "package_index.json"


class PackageIndex:
    def __init__(self, roots=()):
        self.roots = [Path(root).resolve() for root in roots]
        self.aircraft = {}
        self.packages = {}
        self.errors = []
        self.reused = 0
        self.scanned = 0

    @classmethod
    def build(cls, roots, *, cache_path=None):
        index = cls(roots)
        cached = index._load(cache_path)
        grouped = {}
        for root in index.roots:
            if not root.is_dir():
                index.errors.append({"path": str(root), "detail": "каталог не найден"})
                continue
            try:
                folders = find_aircraft(root)
            except OSError as error:
                index.errors.append({"path": str(root), "detail": str(error)})
                continue
            for folder in folders:
                _, package = package_manifest(folder)
                if package is None:
                    package = folder
                grouped.setdefault(package, []).append(folder)
        for package, folders in grouped.items():
            key = _key(package)
            signature = _signature(package)
            previous = cached.get(key)
            if previous and previous.get("signature") == signature:
                record = previous["record"]
                index.reused += 1
            else:
                record = index._scan_package(package, folders)
                index.scanned += 1
            index.packages[key] = record
            for aircraft in record["aircraft"]:
                index.aircraft.setdefault(aircraft["name"].casefold(), []).append(aircraft)
        index._save(cache_path)
        return index

    def _scan_package(self, package, folders):
        manifest, _ = package_manifest(package)
        record = {"path": str(package), "name": package.name,
                  "version": manifest.get("package_version"),
                  "content_type": manifest.get("content_type"),
                  "title": manifest.get("title"), "aircraft": [], "signature": _signature(package)}
        for folder in folders:
            cfg = by_case(folder, "aircraft.cfg")
            record["aircraft"].append({"name": folder.name, "path": str(folder),
                                       "package": str(package),
                                       "base_container": _base_container(cfg)})
        return record

    def _load(self, cache_path):
        if not cache_path:
            return {}
        try:
            data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if data.get("index_version") != INDEX_VERSION:
            return {}
        if [str(r).casefold() for r in data.get("roots", [])] != [str(r).casefold() for r in self.roots]:
            return {}
        return {key: value for key, value in (data.get("packages") or {}).items()
                if isinstance(value, dict) and "record" in value}

    def _save(self, cache_path):
        if not cache_path:
            return
        payload = {"index_version": INDEX_VERSION, "roots": [str(r) for r in self.roots],
                   "packages": {key: {"signature": record["signature"], "record": record}
                                for key, record in self.packages.items()}}
        path = Path(cache_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass

    def aircraft_folders(self, name):
        return [Path(item["path"]) for item in self.aircraft.get(str(name).casefold(), [])]

    def package_of(self, folder):
        folder = Path(os.path.abspath(os.fspath(folder)))
        for parent in (folder, *folder.parents):
            record = self.packages.get(_key(parent))
            if record is not None:
                return Path(record["path"])
        # ``Path.parents`` can preserve a different spelling on Windows when
        # the caller used an 8.3 alias while the index was built from the long
        # spelling.  The indexed aircraft records are already canonicalized,
        # so use them as a final containment fallback.
        wanted = _key(folder)
        for record in self.packages.values():
            for item in record.get("aircraft", []):
                aircraft_path = _key(item.get("path", ""))
                if wanted == aircraft_path or wanted.startswith(aircraft_path + os.sep):
                    return Path(record["path"])
        return None

    def base_aircraft(self, folder):
        """Base aircraft folders declared by this aircraft's [VARIATION]."""
        name = Path(folder).name.casefold()
        wanted = _key(folder)
        for item in self.aircraft.get(name, []):
            if _key(item["path"]) != wanted:
                continue
            base = item.get("base_container")
            if not base:
                return []
            return self.aircraft_folders(Path(base.replace("\\", "/")).name)
        return []

    def describe(self, name=None):
        """Entries for the index view. The declared base is checked against the
        installed set: an absent base is the honest reason a livery stays partial."""
        result = {}
        for key, entries in sorted(self.aircraft.items()):
            if name is not None and name.casefold() != key:
                continue
            described = []
            for item in entries:
                base = item.get("base_container")
                described.append(dict(item, base_installed=bool(
                    self.aircraft_folders(Path(base.replace("\\", "/")).name)) if base else None))
            result[key] = described
        return result

    def rebase(self, target, owner):
        """Resolve a VFS-relative path that does not exist inside its own package.

        Returns (path, origin, candidates). `path` is None when nothing matched;
        `candidates` is non-empty when several packages could own the resource,
        which the user must decide instead of the resolver guessing.
        """
        target = Path(os.path.normpath(os.path.abspath(os.fspath(target))))
        owner_key = _key(owner)
        if target.exists():
            return target, None, []
        parts = target.parts
        matches = []
        for position, part in enumerate(parts):
            for folder in self.aircraft_folders(part):
                if _key(folder) == owner_key:
                    continue
                candidate = folder.joinpath(*parts[position + 1:])
                if candidate.exists():
                    matches.append((candidate, folder))
        if len(matches) == 1:
            return matches[0][0], "aircraft_index", []
        if len(matches) > 1:
            return None, "ambiguous", [str(candidate) for candidate, _ in matches]
        own_package = self.package_of(owner)
        if own_package is None:
            return None, None, []
        package_path = Path(os.path.normpath(os.fspath(own_package)))
        try:
            # Keep the original spelling where possible so the result follows
            # the real package tree on case-sensitive filesystems.
            tail = target.relative_to(package_path)
        except ValueError:
            # Normalize both sides before falling back to string-relative
            # handling.  This is important on Windows when the temporary root
            # is exposed as ``RUNNER~1`` but the indexed package uses the long
            # ``runneradmin`` spelling.
            tail = None
            try:
                canonical_target = Path(os.path.realpath(os.fspath(target)))
                canonical_package = Path(os.path.realpath(os.fspath(package_path)))
                tail = canonical_target.relative_to(canonical_package)
            except ValueError:
                pass
            if tail is None:
                # pathlib's Windows relative_to behaviour differs between
                # Python versions when one side came through an 8.3 alias.
                # relpath is explicitly case-insensitive on Windows and gives
                # us the same package-relative tail without guessing an
                # aircraft path.
                try:
                    relative = os.path.relpath(os.fspath(target), os.fspath(package_path))
                except ValueError:
                    return None, None, []
                if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                    return None, None, []
                tail = Path(relative)
        packages = []
        for base in self.base_aircraft(owner):
            package = self.package_of(base)
            if package is not None and package not in packages:
                packages.append(package)
        matches = [(package.joinpath(tail), package) for package in packages
                   if package.joinpath(tail).exists()]
        if len(matches) == 1:
            return matches[0][0], "base_package", []
        if len(matches) > 1:
            return None, "ambiguous", [str(candidate) for candidate, _ in matches]
        return None, None, []


def _base_container(cfg):
    if not cfg.is_file():
        return None
    try:
        lines = cfg.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    section = None
    for line in lines:
        stripped = line.split(";", 1)[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].casefold()
            continue
        if section != "variation" or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip().casefold() == "base_container":
            return value.strip().strip('"')
    return None

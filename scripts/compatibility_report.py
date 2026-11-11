"""Summarise a catalog JSON into a portable compatibility matrix.

The catalog itself contains machine-specific paths and hundreds of detailed
records.  This small, dependency-free utility keeps the measured coverage
reproducible while producing a report safe to commit: only counts, reason
codes, index statistics and blocker kinds are retained.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _as_records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _dependency_problem(dependency: dict[str, Any]) -> str:
    """Return a path-free blocker class for an unresolved dependency.

    New resolver output carries ``problem_code``. The text fallback is retained
    only for catalog JSON files produced by older program versions.
    """
    kind = str(dependency.get("kind") or "UNKNOWN")
    if kind == "texture_fallback" and dependency.get("target_aircraft_installed") is False:
        return "optional_texture_target_aircraft_missing"
    problem_code = dependency.get("problem_code")
    if problem_code:
        return str(problem_code)
    detail = str(dependency.get("detail") or "").casefold()
    if "несколько установленных пакетов" in detail:
        return "ambiguous_owner"
    if kind == "texture_fallback":
        return "optional_texture_fallback_missing"
    if kind in {"base_container", "model"} and "базовый самолёт не установлен" in detail:
        return "base_aircraft_missing"
    if kind == "model" and "объявленный файл в нём отсутствует" in detail:
        return "declared_model_file_missing"
    if kind == "manifest" and "пакет не найден" in detail:
        return "manifest_package_missing"
    return "unresolved_path"


def summarise(catalog: dict[str, Any], *, source_name: str | None = None) -> dict[str, Any]:
    aircraft = _as_records(catalog.get("aircraft"))
    reason_codes = Counter(str(item.get("reason_code") or "UNKNOWN") for item in aircraft)
    missing_kinds: Counter[str] = Counter()
    nested_reason_codes: Counter[str] = Counter()
    dependency_kinds: Counter[str] = Counter()
    unresolved_dependencies: Counter[str] = Counter()
    unresolved_dependency_problems: Counter[str] = Counter()
    unresolved_targets: dict[str, set[str]] = {}
    affected_dependency_aircraft: dict[str, set[int]] = {}
    affected_resource_aircraft: dict[str, set[int]] = {}
    ambiguous_dependencies = 0
    feature_models: dict[str, dict[str, Any]] = {}
    for aircraft_index, item in enumerate(aircraft):
        for dependency in _as_records(item.get("dependencies")):
            kind = str(dependency.get("kind") or "UNKNOWN")
            dependency_kinds[kind] += 1
            if not dependency.get("resolved"):
                unresolved_dependencies[kind] += 1
                problem = _dependency_problem(dependency)
                unresolved_dependency_problems[problem] += 1
                affected_dependency_aircraft.setdefault(kind, set()).add(aircraft_index)
                target = str(
                    dependency.get("target_aircraft")
                    or dependency.get("name")
                    or dependency.get("path")
                    or ""
                ).strip()
                if target:
                    unresolved_targets.setdefault(kind, set()).add(target.casefold())
            if (dependency.get("problem_code") == "ambiguous_owner"
                    or dependency.get("origin") == "ambiguous"
                    or "несколько установленных пакетов" in str(dependency.get("detail") or "")):
                ambiguous_dependencies += 1
        for resource in _as_records(item.get("missing_resources")):
            if resource.get("kind"):
                kind = str(resource["kind"])
                missing_kinds[kind] += 1
                affected_resource_aircraft.setdefault(kind, set()).add(aircraft_index)
        for variant in _as_records(item.get("variants")):
            for model in _as_records(variant.get("models")):
                path = str(model.get("path") or "")
                if path:
                    feature_models.setdefault(path.casefold(), model)
                code = model.get("reason_code")
                if code and str(code) not in {"OK", "SUPPORTED_PARTIAL"}:
                    nested_reason_codes[str(code)] += 1
            for resource in _as_records(variant.get("missing_resources")):
                if resource.get("kind"):
                    kind = str(resource["kind"])
                    missing_kinds[kind] += 1
                    affected_resource_aircraft.setdefault(kind, set()).add(aircraft_index)
    formats: Counter[str] = Counter()
    extensions_used: Counter[str] = Counter()
    extensions_required: Counter[str] = Counter()
    unsupported_features: Counter[str] = Counter()
    primitive_modes: Counter[str] = Counter()
    sparse_accessors = 0
    buffers = 0
    for model in feature_models.values():
        if model.get("source_format"):
            formats[str(model["source_format"]).casefold()] += 1
        extensions_used.update(str(value) for value in model.get("extensions_used") or [])
        extensions_required.update(str(value) for value in model.get("extensions_required") or [])
        unsupported_features.update(str(value) for value in model.get("unsupported") or [])
        primitive_modes.update(str(value) for value in model.get("primitive_modes") or [])
        sparse_accessors += int(model.get("sparse_accessors") or 0)
        buffers += int(model.get("buffer_count") or 0)
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {"kind": "catalog_json", "name": source_name or "catalog.json"},
        "counts": {
            "aircraft": len(aircraft),
            "geometry_buildable": sum(bool(item.get("can_build_geometry")) for item in aircraft),
            "textures_buildable": sum(bool(item.get("can_build_textures")) for item in aircraft),
            "partial": sum(bool(item.get("partial")) for item in aircraft),
            "needs_model_selection": sum(bool(item.get("needs_model_selection")) for item in aircraft),
            "with_texture_images": sum(bool(item.get("texture_images")) for item in aircraft),
            "duplicate_names": sum(bool(item.get("duplicate_name")) for item in aircraft),
            "suppressed_history_stubs": len(_as_records(catalog.get("suppressed_history_stubs"))),
        },
        "reason_codes": dict(sorted(reason_codes.items())),
        "missing_resource_kinds": dict(sorted(missing_kinds.items())),
        "affected_aircraft_by_missing_resource_kind": {
            kind: len(indices) for kind, indices in sorted(affected_resource_aircraft.items())},
        "nested_model_reason_codes": dict(sorted(nested_reason_codes.items())),
        "dependencies": {"by_kind": dict(sorted(dependency_kinds.items())),
                         "unresolved_by_kind": dict(sorted(unresolved_dependencies.items())),
                         "unresolved_by_reason": dict(sorted(unresolved_dependency_problems.items())),
                         "unresolved_unique_targets_by_kind": {
                             kind: len(targets) for kind, targets in sorted(unresolved_targets.items())},
                         "affected_aircraft_by_kind": {
                             kind: len(indices) for kind, indices in sorted(affected_dependency_aircraft.items())},
                         "ambiguous": ambiguous_dependencies},
        "format_features": {
            "unique_models": len(feature_models),
            "source_formats": dict(sorted(formats.items())),
            "extensions_used": dict(sorted(extensions_used.items())),
            "extensions_required": dict(sorted(extensions_required.items())),
            "unsupported_features": dict(sorted(unsupported_features.items())),
            "primitive_modes": dict(sorted(primitive_modes.items())),
            "sparse_accessors": sparse_accessors,
            "buffers": buffers,
        },
        "index": catalog.get("index") if isinstance(catalog.get("index"), dict) else {},
        "notes": [
            "Counts describe the selected local MSFS installation, not a guarantee for every third-party package.",
            "A shallow catalog checks structure and declared files; use catalog --deep for glTF/GLB and BIN validation.",
            "Missing source geometry is reported, not reconstructed or guessed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="JSON produced by msfs_universal.py catalog")
    parser.add_argument("--output", type=Path, help="write the matrix to this JSON file")
    args = parser.parse_args()
    data = json.loads(args.catalog.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit("catalog JSON must contain an object")
    report = summarise(data, source_name=args.catalog.name)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

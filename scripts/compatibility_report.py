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


def summarise(catalog: dict[str, Any], *, source_name: str | None = None) -> dict[str, Any]:
    aircraft = _as_records(catalog.get("aircraft"))
    reason_codes = Counter(str(item.get("reason_code") or "UNKNOWN") for item in aircraft)
    missing_kinds: Counter[str] = Counter()
    nested_reason_codes: Counter[str] = Counter()
    for item in aircraft:
        for resource in _as_records(item.get("missing_resources")):
            if resource.get("kind"):
                missing_kinds[str(resource["kind"])] += 1
        for variant in _as_records(item.get("variants")):
            for model in _as_records(variant.get("models")):
                code = model.get("reason_code")
                if code and str(code) not in {"OK", "SUPPORTED_PARTIAL"}:
                    nested_reason_codes[str(code)] += 1
            for resource in _as_records(variant.get("missing_resources")):
                if resource.get("kind"):
                    missing_kinds[str(resource["kind"])] += 1
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
        "nested_model_reason_codes": dict(sorted(nested_reason_codes.items())),
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

"""Regression tests for the portable compatibility matrix summariser."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compatibility_report.py"
spec = importlib.util.spec_from_file_location("compatibility_report", SCRIPT)
compatibility_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compatibility_report)


class CompatibilityReportTests(unittest.TestCase):
    def test_texture_fallback_reason_distinguishes_missing_target_package(self):
        catalog = {"aircraft": [{
            "dependencies": [{"kind": "texture_fallback", "resolved": False,
                              "problem_code": "optional_texture_fallback_missing",
                              "target_aircraft": "Base_Plane", "target_aircraft_installed": False}]
        }]}

        report = compatibility_report.summarise(catalog)

        self.assertEqual(report["dependencies"]["unresolved_by_reason"],
                         {"optional_texture_target_aircraft_missing": 1})

    def test_summary_counts_records_and_nested_blockers(self):
        catalog = {
            "index": {"packages": 2},
            "aircraft": [
                {"reason_code": "OK", "can_build_geometry": True, "can_build_textures": True,
                 "partial": False, "needs_model_selection": False, "texture_images": True,
                 "duplicate_name": True, "missing_resources": [], "variants": []},
                {"reason_code": "SUPPORTED_PARTIAL", "can_build_geometry": False,
                 "can_build_textures": False, "partial": True, "needs_model_selection": True,
                 "texture_images": False, "missing_resources": [{"kind": "base_container"}],
                 "dependencies": [{"kind": "manifest", "resolved": True, "origin": "package_index"},
                                  {"kind": "texture_fallback", "resolved": False,
                                   "problem_code": "ambiguous_owner",
                                   "target_aircraft": "Base_Plane",
                                   "detail": "несколько установленных пакетов: A; B"}],
                 "variants": [{"models": [{"path": "C:/pkg/a.gltf", "reason_code": "MISSING_BUFFER",
                                             "source_format": "gltf", "extensions_used": ["EXT_test"],
                                             "extensions_required": [], "unsupported": ["Meshopt compression"],
                                             "primitive_modes": [4, 5], "sparse_accessors": 1,
                                             "buffer_count": 2}],
                               "missing_resources": [{"kind": "buffer"}]}]},
            ],
        }
        report = compatibility_report.summarise(catalog, source_name="fixture.json")
        self.assertEqual(report["counts"]["aircraft"], 2)
        self.assertEqual(report["counts"]["suppressed_history_stubs"], 0)
        self.assertEqual(report["counts"]["geometry_buildable"], 1)
        self.assertEqual(report["reason_codes"]["SUPPORTED_PARTIAL"], 1)
        self.assertEqual(report["missing_resource_kinds"], {"base_container": 1, "buffer": 1})
        self.assertEqual(report["nested_model_reason_codes"], {"MISSING_BUFFER": 1})
        self.assertEqual(report["dependencies"]["by_kind"], {"manifest": 1, "texture_fallback": 1})
        self.assertEqual(report["dependencies"]["unresolved_by_kind"], {"texture_fallback": 1})
        self.assertEqual(report["dependencies"]["unresolved_by_reason"], {"ambiguous_owner": 1})
        self.assertEqual(report["dependencies"]["unresolved_unique_targets_by_kind"],
                         {"texture_fallback": 1})
        self.assertEqual(report["dependencies"]["affected_aircraft_by_kind"], {"texture_fallback": 1})
        self.assertEqual(report["dependencies"]["ambiguous"], 1)
        self.assertEqual(report["affected_aircraft_by_missing_resource_kind"], {"base_container": 1, "buffer": 1})
        self.assertEqual(report["format_features"]["unique_models"], 1)
        self.assertEqual(report["format_features"]["source_formats"], {"gltf": 1})
        self.assertEqual(report["format_features"]["extensions_used"], {"EXT_test": 1})
        self.assertEqual(report["format_features"]["unsupported_features"], {"Meshopt compression": 1})
        self.assertEqual(report["format_features"]["primitive_modes"], {"4": 1, "5": 1})
        self.assertEqual(report["format_features"]["sparse_accessors"], 1)
        self.assertEqual(report["format_features"]["buffers"], 2)
        self.assertEqual(report["source"]["name"], "fixture.json")

    def test_summary_does_not_copy_aircraft_paths(self):
        report = compatibility_report.summarise({"aircraft": [{"path": "C:/private/MSFS", "reason_code": "OK"}]})
        self.assertNotIn("path", report)
        self.assertNotIn("private", str(report))


if __name__ == "__main__":
    unittest.main()

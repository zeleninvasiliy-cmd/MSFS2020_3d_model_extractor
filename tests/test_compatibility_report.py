"""Regression tests for the portable compatibility matrix summariser."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compatibility_report.py"
spec = importlib.util.spec_from_file_location("compatibility_report", SCRIPT)
compatibility_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compatibility_report)


class CompatibilityReportTests(unittest.TestCase):
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
                 "variants": [{"models": [{"reason_code": "MISSING_BUFFER"}],
                               "missing_resources": [{"kind": "buffer"}]}]},
            ],
        }
        report = compatibility_report.summarise(catalog, source_name="fixture.json")
        self.assertEqual(report["counts"]["aircraft"], 2)
        self.assertEqual(report["counts"]["geometry_buildable"], 1)
        self.assertEqual(report["reason_codes"]["SUPPORTED_PARTIAL"], 1)
        self.assertEqual(report["missing_resource_kinds"], {"base_container": 1, "buffer": 1})
        self.assertEqual(report["nested_model_reason_codes"], {"MISSING_BUFFER": 1})
        self.assertEqual(report["source"]["name"], "fixture.json")

    def test_summary_does_not_copy_aircraft_paths(self):
        report = compatibility_report.summarise({"aircraft": [{"path": "C:/private/MSFS", "reason_code": "OK"}]})
        self.assertNotIn("path", report)
        self.assertNotIn("private", str(report))


if __name__ == "__main__":
    unittest.main()

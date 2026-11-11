"""Regression tests for orchestration; Blender is replaced only at the process boundary."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "msfs_universal.py"
spec = importlib.util.spec_from_file_location("pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_sequence_isolated_and_unbounded(self):
        for name in ("01_geometry_manual_auto_999.blend", "01_geometry_manual_auto_1000.blend",
                     "01_geometry_strip_auto_012.blend", "01_geometry_222.blend"):
            (self.root / name).touch()
        self.assertEqual(pipeline.choose_build_sequence(self.root, "manual_auto", "geometry"), 1001)
        self.assertEqual(pipeline.choose_build_sequence(self.root, "strip_auto", "geometry"), 13)
        self.assertEqual(pipeline.choose_build_sequence(self.root, "bake_auto", "geometry"), 1)

    def test_dependency_missing_rejected_before_blender(self):
        with patch.object(pipeline, "run_external") as runner:
            with self.assertRaisesRegex(ValueError, "Сначала выполните geometry"):
                pipeline.run_stages({"build_variant": "manual_auto"}, self.root, ["textures"], None, 1)
            runner.assert_not_called()

    def test_legacy_checkpoint_dependency(self):
        legacy = self.root / "01_geometry_strip_auto.blend"
        legacy.touch()
        self.assertEqual(pipeline.latest_stage_file(self.root, "geometry", "strip_auto"), legacy)

    def test_stale_lock_recovered_and_live_lock_respected(self):
        lock = self.root / ".msfs_pipeline.lock"
        lock.write_text(json.dumps({"pid": 2147483647}), encoding="utf-8")
        pipeline.acquire_lock(lock)
        self.assertEqual(json.loads(lock.read_text())["pid"], os.getpid())
        with self.assertRaisesRegex(ValueError, "занята"):
            pipeline.acquire_lock(lock)

    def test_invalid_config_rejected(self):
        for config in ({}, {"source": "a", "output_dir": "b", "exclude_objects": "*"},
                       {"source": "a", "output_dir": "b", "filter_runtime": "false"},
                       {"source": "a", "output_dir": "b", "skinning": "hybrid"},
                       {"source": "a", "output_dir": "b", "placements": {"wing": {"anchor": "body", "offset_m": [0, float("nan"), 0]}}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                pipeline.validate_config(config)
        for sequence in (True, 0, -1, "abc", 1.5):
            with self.assertRaises(ValueError):
                pipeline.choose_build_sequence(self.root, "strip_auto", "geometry", sequence)

    def config_with(self, key, value):
        return {"source": "a", "output_dir": "b", key: value}

    def test_editing_rules_rejected_before_blender(self):
        cases = {
            "mirror_objects": [
                [{"source": "Wing_L", "target": "Wing_R", "axis": "W"}],
                [{"source": "Wing_L", "target": "Wing_L"}],
                [{"source": "", "target": "Wing_R"}],
            ],
            "placements": [
                {"Wing": {"anchor": ""}},
                {"Wing": "body"},
                {"Wing": {"anchor": "body", "offset_m": [0, 0]}},
                {"Wing": {"anchor": "body", "offset_m": [0, True, 0]}},
                {"Wing": {"anchor": "body", "offset_m": [0, float("inf"), 0]}},
            ],
            "split_spatial": [
                [{"object": "Fuselage", "axis": "y", "cuts": [1, 0], "names": ["a", "b", "c"]}],
                [{"object": "Fuselage", "axis": "y", "cuts": [0, 0], "names": ["a", "b", "c"]}],
                [{"object": "Fuselage", "axis": "y", "cuts": [0], "names": ["a", "b", "c"]}],
                [{"object": "Fuselage", "axis": "y", "cuts": [], "names": ["a"]}],
                [{"object": "Fuselage", "axis": "y", "cuts": [0], "names": ["a", "a"]}],
                [{"object": "Fuselage", "default": "rest", "regions": []}],
                [{"object": "Fuselage", "default": "rest", "regions": [{"name": "nose", "bounds": {"X": [0, 1]}}]}],
                [{"object": "Fuselage", "default": "rest", "regions": [{"name": "nose", "bounds": {"x": [1, 0]}}]}],
                [{"object": "Fuselage", "default": "rest", "regions": [{"name": "nose", "bounds": {"x": [0]}}]}],
                [{"object": "Fuselage", "default": "rest", "regions": [{"name": "nose", "bounds": {}}]}],
                [{"object": "Fuselage", "default": "rest", "regions": [{"name": "rest", "bounds": {"x": [0, 1]}}]}],
            ],
            "split_by_skin": [
                [{"object": "Body", "parts": []}],
                [{"object": "Body", "parts": [{"name": "a", "bones": []}]}],
                [{"object": "Body", "parts": [{"name": "a", "bones": ["b1"]}, {"name": "a", "bones": ["b2"]}]}],
                [{"object": "Body", "parts": [{"name": "a", "bones": ["b1"]}, {"name": "b", "bones": ["b1"]}]}],
                [{"object": "Body", "parts": [{"name": "a", "bones": ["b1"], "collection": "A//B"}]}],
                [{"object": "Body", "parts": [{"name": "", "bones": ["b1"]}]}],
            ],
            "collection_overrides": [{"Fuselage*": "A//B"}, {"Fuselage*": "  "}, {"": "A"}],
            "texture_overrides": [{"body_albd.png": ""}, {"body_albd.png": None}],
        }
        for key, variants in cases.items():
            for value in variants:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    pipeline.validate_config(self.config_with(key, value))

    def test_valid_editing_rules_accepted(self):
        config = {
            "source": "a", "output_dir": "b",
            "mirror_objects": [{"source": "Wing_L", "target": "Wing_R", "axis": "x"}],
            "placements": {"Rudder": {"anchor": "Tail", "offset_m": [0, 1, 0]}, "Wing": {"anchor": "Body"}},
            "split_spatial": [
                {"object": "Fuselage", "axis": "y", "cuts": [-1, 1], "names": ["front", "mid", "rear"]},
                {"object": "Tail", "default": "rest",
                 "regions": [{"name": "tip", "bounds": {"x": [None, 2], "z": [0, None]}}]},
            ],
            "split_by_skin": [{"object": "Body", "parts": [
                {"name": "left", "bones": ["b_l"], "collection": "A/B", "pivot": "Body"},
                {"name": "right", "bones": ["b_r"]}]}],
            "collection_overrides": {"Fuselage*": "01_EXTERIOR/02_FUSELAGE"},
            "texture_overrides": {"body_albd.png": "textures/body_albd.png"},
        }
        pipeline.validate_config(config)

    def test_ad_hoc_scan_does_not_evict_the_installed_index_cache(self):
        cache = self.root / "package_index.json"
        original = {"index_version": 1, "roots": ["C:/installed"], "packages": {}}
        cache.write_text(json.dumps(original), encoding="utf-8")
        package = self.root / "mods" / "test-pkg"
        folder = package / "SimObjects" / "Airplanes" / "Test_Plane"
        folder.mkdir(parents=True)
        (package / "manifest.json").write_text("{}", encoding="utf-8")
        with patch.object(pipeline, "installed_package_roots", return_value=[Path("C:/installed")]), \
                patch.object(pipeline, "default_cache_path", return_value=cache):
            index = pipeline.build_index(near=folder)
        self.assertEqual(index.scanned, 1)
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), original)

    def test_installed_scan_reuses_the_shared_cache(self):
        installed = self.root / "Packages"
        package = installed / "Official" / "test-pkg"
        folder = package / "SimObjects" / "Airplanes" / "Test_Plane"
        folder.mkdir(parents=True)
        (package / "manifest.json").write_text("{}", encoding="utf-8")
        cache = self.root / "package_index.json"
        with patch.object(pipeline, "installed_package_roots", return_value=[installed]), \
                patch.object(pipeline, "default_cache_path", return_value=cache):
            first = pipeline.build_index(near=folder)
            second = pipeline.build_index(near=folder)
        self.assertEqual((first.scanned, first.reused), (1, 0))
        self.assertEqual((second.scanned, second.reused), (0, 1))
        self.assertTrue(cache.is_file())

    def test_catalog_marks_same_aircraft_name_from_multiple_packages(self):
        folders = []
        for package_name in ("first", "second"):
            folder = self.root / package_name / "SimObjects" / "Airplanes" / "Shared_Plane"
            model = folder / "model"
            model.mkdir(parents=True)
            (model / "model.cfg").write_text("[models]\nexterior=body.gltf\n", encoding="utf-8")
            (model / "body.gltf").write_text(json.dumps({"asset": {}, "meshes": []}), encoding="utf-8")
            folders.append(folder)
        with patch.object(pipeline, "installed_package_roots", return_value=[self.root]):
            result = pipeline.catalog()
        entries = [item for item in result["aircraft"] if item["aircraft"] == "Shared_Plane"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(item["duplicate_name"] for item in entries))
        self.assertEqual({item["duplicate_count"] for item in entries}, {2})

    def test_catalog_deep_reports_missing_buffers_before_project_creation(self):
        folder = self.root / "package" / "SimObjects" / "Airplanes" / "Broken_Plane"
        model = folder / "model"
        model.mkdir(parents=True)
        (model / "model.cfg").write_text("[models]\nexterior=body.gltf\n", encoding="utf-8")
        (model / "body.gltf").write_text(json.dumps({
            "asset": {"version": "2.0"},
            "buffers": [{"uri": "body.bin", "byteLength": 4}],
            "meshes": []
        }), encoding="utf-8")
        with patch.object(pipeline, "installed_package_roots", return_value=[self.root]):
            shallow = pipeline.catalog()
            deep = pipeline.catalog(deep=True)
        self.assertTrue(shallow["aircraft"][0]["can_build_geometry"])
        self.assertFalse(deep["aircraft"][0]["can_build_geometry"])
        self.assertEqual(deep["aircraft"][0]["reason_code"], "MISSING_BUFFER")

    def test_objects_stdout_is_clean_json(self):
        blend = self.root / "test.blend"
        blender = self.root / "blender.exe"
        blend.touch()
        blender.touch()

        def fake_blender(command, **_):
            report = Path(command[command.index("--") + 2])
            report.write_text(json.dumps({"objects": [{"name": "WING"}]}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"Blender banner\nFile loaded\n")

        capture = io.StringIO()
        with patch.object(pipeline, "run_external", side_effect=fake_blender), \
                patch.object(tempfile, "tempdir", str(self.root)), contextlib.redirect_stdout(capture):
            pipeline.list_blend_objects(blend, blender)
        self.assertEqual(json.loads(capture.getvalue())["objects"][0]["name"], "WING")


if __name__ == "__main__":
    unittest.main()

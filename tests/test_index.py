"""Package index and VFS path rebasing (roadmap priority 2). All fixtures synthetic."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import package_index as index_module
from package_index import PackageIndex
import package_resolver as resolver
from test_resolver import gltf, model_xml


def aircraft(root, package, name, base=None, content_type="AIRCRAFT"):
    folder = root / package / "SimObjects" / "Airplanes" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model").mkdir(exist_ok=True)
    cfg = "[VERSION]\nmajor = 1\n"
    if base:
        cfg += f'\n[VARIATION]\nbase_container = "..\\{base}"\n'
    (folder / "aircraft.cfg").write_text(cfg, encoding="utf-8")
    (root / package / "manifest.json").write_text(
        json.dumps({"content_type": content_type, "package_version": "1.0.0", "title": name}),
        encoding="utf-8")
    return folder


class _PathAssertions:
    def assert_path_equal(self, actual, expected):
        """Compare Windows paths by filesystem identity, not 8.3 spelling."""
        self.assertIsNotNone(actual)
        try:
            same = os.path.samefile(os.fspath(actual), os.fspath(expected))
        except OSError:
            same = os.path.normcase(os.path.abspath(os.fspath(actual))) == os.path.normcase(
                os.path.abspath(os.fspath(expected)))
        self.assertTrue(same, f"{actual!s} != {expected!s}")


class IndexTests(_PathAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def build(self, **kwargs):
        return PackageIndex.build([self.root], **kwargs)

    def test_module_does_not_need_blender(self):
        source = (SCRIPTS / "package_index.py").read_text(encoding="utf-8")
        self.assertNotIn("import bpy", source)

    def test_indexes_aircraft_and_package(self):
        folder = aircraft(self.root, "test-base", "Test_Plane")
        index = self.build()
        self.assertEqual(len(index.aircraft_folders("test_plane")), 1)
        self.assert_path_equal(index.aircraft_folders("test_plane")[0], folder)
        self.assert_path_equal(index.package_of(folder), self.root / "test-base")
        self.assertEqual(index.packages[index_module._key(self.root / "test-base")]["content_type"], "AIRCRAFT")

    def test_name_lookup_is_case_insensitive(self):
        folder = aircraft(self.root, "test-base", "Test_Plane")
        index = self.build()
        self.assertEqual(len(index.aircraft_folders("TEST_PLANE")), 1)
        self.assert_path_equal(index.aircraft_folders("TEST_PLANE")[0], folder)

    def test_describe_marks_installed_and_absent_bases(self):
        aircraft(self.root, "test-base", "Test_Plane")
        aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane", content_type="LIVERY")
        aircraft(self.root, "test-orphan", "Test_Plane_Orphan", base="Test_Absent", content_type="LIVERY")
        described = self.build().describe()
        self.assertIsNone(described["test_plane"][0]["base_installed"])
        self.assertTrue(described["test_plane_livery"][0]["base_installed"])
        self.assertFalse(described["test_plane_orphan"][0]["base_installed"])
        self.assertEqual(list(described), ["test_plane", "test_plane_livery", "test_plane_orphan"])

    def test_describe_filters_by_exact_name_without_case(self):
        aircraft(self.root, "test-base", "Test_Plane")
        aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane", content_type="LIVERY")
        described = self.build().describe("TEST_PLANE")
        self.assertEqual(list(described), ["test_plane"])
        self.assertEqual(self.build().describe("Test"), {})

    def test_rebase_aircraft_segment_onto_base_package(self):
        base = aircraft(self.root, "test-base", "Test_Plane")
        (base / "model" / "int.xml").write_text("<ModelInfo/>", encoding="utf-8")
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane",
                          content_type="LIVERY")
        index = self.build()
        target = livery / "model" / ".." / ".." / "Test_Plane" / "model" / "int.xml"
        path, origin, candidates = index.rebase(target, livery)
        self.assert_path_equal(path, base / "model" / "int.xml")
        self.assertEqual(origin, "aircraft_index")
        self.assertEqual(candidates, [])

    def test_rebase_package_tail_onto_base_package(self):
        aircraft(self.root, "test-base", "Test_Plane")
        package_texture = self.root / "test-base" / "texture" / "Gauges"
        package_texture.mkdir(parents=True)
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane",
                          content_type="LIVERY")
        index = self.build()
        target = livery / "model" / ".." / ".." / ".." / ".." / "texture" / "Gauges"
        path, origin, _ = index.rebase(target, livery)
        self.assert_path_equal(path, package_texture)
        self.assertEqual(origin, "base_package")

    def test_existing_path_is_returned_without_origin(self):
        folder = aircraft(self.root, "test-base", "Test_Plane")
        index = self.build()
        path, origin, candidates = index.rebase(folder / "model", folder)
        self.assert_path_equal(path, folder / "model")
        self.assertIsNone(origin)
        self.assertEqual(candidates, [])

    def test_absent_base_is_not_invented(self):
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane",
                          content_type="LIVERY")
        index = self.build()
        path, origin, candidates = index.rebase(livery / ".." / "Test_Plane" / "model", livery)
        self.assertIsNone(path)
        self.assertEqual(candidates, [])
        self.assertEqual(index.base_aircraft(livery), [])

    def test_ambiguous_name_requires_user_choice(self):
        first = aircraft(self.root, "base-one", "Test_Plane")
        second = aircraft(self.root, "base-two", "Test_Plane")
        for folder in (first, second):
            (folder / "model" / "int.xml").write_text("<ModelInfo/>", encoding="utf-8")
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane",
                          content_type="LIVERY")
        index = self.build()
        path, origin, candidates = index.rebase(livery / ".." / "Test_Plane" / "model" / "int.xml", livery)
        self.assertIsNone(path)
        self.assertEqual(origin, "ambiguous")
        self.assertEqual(len(candidates), 2)

    def test_owner_folder_is_not_its_own_base(self):
        folder = aircraft(self.root, "test-base", "Test_Plane")
        (folder / "model" / "int.xml").write_text("<ModelInfo/>", encoding="utf-8")
        index = self.build()
        path, origin, _ = index.rebase(folder / ".." / "Test_Plane" / "model" / "int.xml", folder)
        self.assert_path_equal(path, folder / "model" / "int.xml")
        self.assertIsNone(origin)

    def test_cache_reuses_unchanged_packages(self):
        aircraft(self.root, "test-base", "Test_Plane")
        cache = self.root / "cache" / "index.json"
        first = self.build(cache_path=cache)
        second = self.build(cache_path=cache)
        self.assertEqual(first.scanned, 1)
        self.assertEqual(second.scanned, 0)
        self.assertEqual(second.reused, 1)
        self.assertTrue(cache.is_file())

    def test_cache_invalidates_when_aircraft_added(self):
        aircraft(self.root, "test-base", "Test_Plane")
        cache = self.root / "cache" / "index.json"
        self.build(cache_path=cache)
        time.sleep(0.01)
        added = aircraft(self.root, "test-base", "Test_Plane_Two")
        os.utime(added.parent, None)
        second = self.build(cache_path=cache)
        self.assertEqual(second.scanned, 1)
        self.assertEqual(len(second.aircraft_folders("test_plane_two")), 1)

    def test_cache_invalidates_when_aircraft_cfg_changes_in_place(self):
        folder = aircraft(self.root, "test-base", "Livery")
        cfg = folder / "aircraft.cfg"
        cfg.write_text("[VARIATION]\nbase_container=Base_A\n", encoding="utf-8")
        cache = self.root / "cache" / "index.json"
        self.build(cache_path=cache)

        cfg.write_text("[VARIATION]\nbase_container=Base_B\n", encoding="utf-8")
        refreshed = self.build(cache_path=cache)

        self.assertEqual(refreshed.scanned, 1)
        self.assertEqual(refreshed.reused, 0)
        self.assertEqual(refreshed.aircraft["livery"][0]["base_container"], "Base_B")

    def test_cache_ignores_different_roots(self):
        aircraft(self.root, "test-base", "Test_Plane")
        cache = self.root / "cache" / "index.json"
        self.build(cache_path=cache)
        other = self.root / "other"
        other.mkdir()
        aircraft(other, "test-base", "Test_Plane")
        index = PackageIndex.build([other], cache_path=cache)
        self.assertEqual(index.scanned, 1)
        self.assertEqual(index.reused, 0)

    def test_corrupt_cache_is_ignored(self):
        aircraft(self.root, "test-base", "Test_Plane")
        cache = self.root / "index.json"
        cache.write_text("{ not json", encoding="utf-8")
        index = self.build(cache_path=cache)
        self.assertEqual(index.scanned, 1)
        self.assertEqual(len(index.aircraft), 1)

    def test_unreadable_root_does_not_stop_other_roots(self):
        good = self.root / "good"
        aircraft(good, "test-base", "Test_Plane")
        index = PackageIndex.build([self.root / "missing", good])
        self.assertEqual(len(index.aircraft), 1)
        self.assertEqual(len(index.errors), 1)

    def test_base_container_comment_and_quotes_are_stripped(self):
        folder = aircraft(self.root, "test-base", "Test_Plane")
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery")
        (livery / "aircraft.cfg").write_text('[VARIATION]\nbase_container = "..\\Test_Plane" ; comment\n',
                                             encoding="utf-8")
        index = self.build()
        self.assertEqual(len(index.base_aircraft(livery)), 1)
        self.assert_path_equal(index.base_aircraft(livery)[0], folder)


class ResolverIndexTests(_PathAssertions, unittest.TestCase):
    """A livery inherits the base aircraft's models through the index."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def base_and_livery(self, base_package="test-base", livery_package="test-livery"):
        base = aircraft(self.root, base_package, "Test_Plane")
        model_xml(base / "model" / "int.xml", ["int_LOD00.gltf"])
        gltf(base / "model" / "int_LOD00.gltf", ("int_LOD00.bin",))
        (base / "model" / "model.cfg").write_text("[models]\ninterior=int.xml\n", encoding="utf-8")
        livery = aircraft(self.root, livery_package, "Test_Plane_Livery", base="Test_Plane",
                          content_type="LIVERY")
        model_xml(livery / "model" / "ext.xml", ["ext_LOD00.gltf"])
        gltf(livery / "model" / "ext_LOD00.gltf", ("ext_LOD00.bin",))
        (livery / "model" / "model.cfg").write_text(
            "[models]\nexterior=ext.xml\ninterior=..\\..\\Test_Plane\\model\\int.xml\n", encoding="utf-8")
        texture = livery / "texture.TEST"
        texture.mkdir()
        (texture / "BODY_ALBD.PNG.DDS").write_bytes(b"dds")
        return base, livery

    def test_livery_inherits_interior_and_becomes_complete(self):
        base, livery = self.base_and_livery()
        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)
        self.assertEqual(result["reason_code"], "OK")
        self.assertFalse(result["partial"])
        self.assertFalse(result["needs_model_selection"])
        self.assertTrue(result["can_build_geometry"])
        roles = {m["role"]: m for m in result["best_models"]}
        self.assertEqual(set(roles), {"exterior", "interior"})
        self.assertEqual(roles["interior"]["origin"], "aircraft_index")
        self.assert_path_equal(Path(roles["interior"]["path"]), base / "model" / "int_LOD00.gltf")

    def test_without_index_the_same_livery_is_partial(self):
        _, livery = self.base_and_livery()
        result = resolver.resolve_aircraft(livery)
        self.assertEqual(result["reason_code"], "SUPPORTED_PARTIAL")
        self.assertTrue(result["partial"])

    def test_absent_base_stays_partial_with_unresolved_dependency(self):
        _, livery = self.base_and_livery()
        shutil.rmtree(self.root / "test-base")
        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)
        self.assertEqual(result["reason_code"], "SUPPORTED_PARTIAL")
        base = next(d for d in result["dependencies"] if d["kind"] == "base_container")
        self.assertFalse(base["resolved"])
        self.assertFalse(base["base_installed"])
        self.assertEqual(base["detail"], "базовый самолёт не установлен")

    def test_installed_base_without_the_declared_file_is_distinguished(self):
        base, livery = self.base_and_livery()
        (base / "model" / "int.xml").unlink()
        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)
        self.assertEqual(result["reason_code"], "SUPPORTED_PARTIAL")
        entry = next(d for d in result["dependencies"] if d["kind"] == "base_container")
        self.assertTrue(entry["resolved"])
        model = next(d for d in result["dependencies"] if d["kind"] == "model" and not d["resolved"])
        self.assertEqual(model["detail"], "базовый самолёт установлен, но объявленный файл в нём отсутствует")

    def test_ambiguous_base_is_reported_not_guessed(self):
        _, livery = self.base_and_livery()
        second = aircraft(self.root, "test-base-copy", "Test_Plane")
        model_xml(second / "model" / "int.xml", ["int_LOD00.gltf"])
        gltf(second / "model" / "int_LOD00.gltf", ("int_LOD00.bin",))
        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)
        self.assertTrue(result["partial"])
        self.assertTrue(any(m["kind"] == "ambiguous" for m in result["missing_resources"]))

    def test_cyclic_base_declaration_does_not_hang(self):
        first = aircraft(self.root, "package-one", "Plane_One", base="Plane_Two")
        second = aircraft(self.root, "package-two", "Plane_Two", base="Plane_One")
        index = PackageIndex.build([self.root])
        self.assertEqual(len(index.base_aircraft(first)), 1)
        self.assert_path_equal(index.base_aircraft(first)[0], second)
        self.assertEqual(len(index.base_aircraft(second)), 1)
        self.assert_path_equal(index.base_aircraft(second)[0], first)
        self.assertIsNone(index.rebase(first / ".." / "Plane_Two" / "absent.xml", first)[0])

    def test_model_from_cfg_returns_rebased_path_for_the_build(self):
        base, livery = self.base_and_livery()
        index = PackageIndex.build([self.root])
        models = resolver.model_from_cfg(livery / "model", index=index, aircraft=livery)
        interior = next(m for m in models if m["role"] == "interior")
        self.assert_path_equal(Path(interior["path"]), base / "model" / "int_LOD00.gltf")
        self.assertEqual(interior["origin"], "aircraft_index")

    def test_texture_fallback_resolves_through_base_package(self):
        base, livery = self.base_and_livery()
        gauges = self.root / "test-base" / "texture" / "Gauges"
        gauges.mkdir(parents=True)
        (livery / "texture.TEST" / "texture.cfg").write_text(
            "[fltsim]\nfallback.1=..\\..\\..\\..\\texture\\Gauges\n", encoding="utf-8")
        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)
        entry = next(d for d in result["dependencies"] if d["kind"] == "texture_fallback")
        self.assertTrue(entry["resolved"])
        self.assertEqual(entry["origin"], "base_package")
        self.assert_path_equal(Path(entry["path"]), gauges)


if __name__ == "__main__":
    unittest.main()

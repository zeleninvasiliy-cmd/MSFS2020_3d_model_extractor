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

    def test_shadowed_history_stub_does_not_make_livery_base_ambiguous(self):
        official = self.root / "Official" / "Steam"
        real = aircraft(official, "asobo-aircraft-da62", "Asobo_DA62")
        model_xml(real / "model" / "int.xml", ["int_LOD00.gltf"])
        gltf(real / "model" / "int_LOD00.gltf", ("int_LOD00.bin",))
        (real / "model" / "model.cfg").write_text("[models]\ninterior=int.xml\n", encoding="utf-8")
        stub = aircraft(official, "fs-base-history", "Asobo_DA62")
        livery = aircraft(official, "da62-livery", "Asobo_DA62_Livery", base="Asobo_DA62",
                          content_type="LIVERY")
        model_xml(livery / "model" / "ext.xml", ["ext_LOD00.gltf"])
        gltf(livery / "model" / "ext_LOD00.gltf", ("ext_LOD00.bin",))
        (livery / "model" / "model.cfg").write_text(
            "[models]\nexterior=ext.xml\ninterior=..\\..\\Asobo_DA62\\model\\int.xml\n", encoding="utf-8")

        index = PackageIndex.build([self.root])
        result = resolver.resolve_aircraft(livery, index=index)

        self.assertEqual(len(index.aircraft_folders("Asobo_DA62")), 1)
        self.assert_path_equal(index.aircraft_folders("Asobo_DA62")[0], real)
        base = next(item for item in result["dependencies"] if item["kind"] == "base_container")
        interior = next(item for item in result["dependencies"]
                        if item["kind"] == "model" and item["name"] == "interior")
        self.assertTrue(base["resolved"])
        self.assertTrue(interior["resolved"])
        interior_model = next(item for item in result["best_models"] if item["role"] == "interior")
        self.assert_path_equal(Path(interior_model["path"]), real / "model" / "int_LOD00.gltf")
        self.assertEqual(len(index.packages[index_module._key(official / "fs-base-history")]["aircraft"]), 1)

    def test_history_entry_remains_when_no_buildable_peer_exists(self):
        official = self.root / "Official" / "Steam"
        aircraft(official, "fs-base-history", "Legacy_Plane")

        index = PackageIndex.build([self.root])

        self.assertEqual(len(index.aircraft_folders("Legacy_Plane")), 1)

    def test_history_stub_is_not_suppressed_by_a_nonbuildable_peer(self):
        official = self.root / "Official" / "Steam"
        aircraft(official, "vendor-placeholder", "Legacy_Plane")
        aircraft(official, "fs-base-history", "Legacy_Plane")

        index = PackageIndex.build([self.root])

        self.assertEqual(len(index.aircraft_folders("Legacy_Plane")), 2)

    def test_indexes_resource_only_packages_and_nested_install_roots(self):
        installed = self.root / "Installed"
        resource = installed / "Official" / "Steam" / "shared-resources"
        resource.mkdir(parents=True)
        (resource / "manifest.json").write_text(json.dumps({"content_type": "CORE"}), encoding="utf-8")
        (resource / "layout.json").write_text("{}", encoding="utf-8")
        index = PackageIndex.build([installed])
        self.assert_path_equal(index.package_folders("SHARED-RESOURCES")[0], resource)
        self.assertEqual(index.packages[index_module._key(resource)]["aircraft"], [])
        self.assertEqual(index.packages[index_module._key(resource)]["content_type"], "CORE")

    def test_index_finds_nested_community_and_official_resource_packages(self):
        installed = self.root / "Packages"
        official = installed / "Official" / "Steam" / "base-assets"
        community = installed / "Community" / "addon-assets"
        for package in (official, community):
            package.mkdir(parents=True)
            (package / "manifest.json").write_text("{}", encoding="utf-8")
        index = PackageIndex.build([installed])
        self.assertEqual(len(index.package_folders("base-assets")), 1)
        self.assertEqual(len(index.package_folders("addon-assets")), 1)

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
        self.assertEqual(base["problem_code"], "base_aircraft_missing")
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
        self.assertEqual(model["problem_code"], "declared_model_file_missing")
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

    def test_missing_texture_target_reports_absent_aircraft_package(self):
        _, livery = self.base_and_livery()
        (livery / "texture.TEST" / "texture.cfg").write_text(
            "[fltsim]\nfallback.1=..\\..\\Ghost_Plane\\texture\\", encoding="utf-8")
        result = resolver.resolve_aircraft(livery, index=PackageIndex.build([self.root]))
        entry = next(d for d in result["dependencies"] if d["kind"] == "texture_fallback")
        self.assertFalse(entry["resolved"])
        self.assertEqual(entry["target_aircraft"], "Ghost_Plane")
        self.assertFalse(entry["target_aircraft_installed"])
        self.assertEqual(entry["problem_code"], "optional_texture_fallback_missing")

    def test_manifest_dependency_resolves_to_resource_only_package(self):
        folder = aircraft(self.root, "owner-package", "Owner_Plane")
        owner_manifest = self.root / "owner-package" / "manifest.json"
        owner_manifest.write_text(json.dumps({"dependencies": [{"name": "shared-resources"}]}), encoding="utf-8")
        shared = self.root / "shared-resources"
        shared.mkdir()
        (shared / "manifest.json").write_text(json.dumps({"content_type": "CORE"}), encoding="utf-8")
        (shared / "layout.json").write_text("{}", encoding="utf-8")

        result = resolver.resolve_aircraft(folder, index=PackageIndex.build([self.root]))

        dependency = next(d for d in result["dependencies"] if d["kind"] == "manifest")
        self.assertTrue(dependency["resolved"])
        self.assertEqual(dependency["origin"], "package_index")
        self.assert_path_equal(Path(dependency["path"]), shared)

    def test_ambiguous_manifest_dependency_requires_package_choice(self):
        folder = aircraft(self.root, "owner-package", "Owner_Plane")
        (self.root / "owner-package" / "manifest.json").write_text(
            json.dumps({"dependencies": [{"name": "shared-resources"}]}), encoding="utf-8")
        candidates = []
        for parent in ("Official", "Community"):
            package = self.root / parent / "shared-resources"
            package.mkdir(parents=True)
            (package / "manifest.json").write_text("{}", encoding="utf-8")
            candidates.append(package)

        result = resolver.resolve_aircraft(folder, index=PackageIndex.build([self.root]))

        dependency = next(d for d in result["dependencies"] if d["kind"] == "manifest")
        self.assertFalse(dependency["resolved"])
        self.assertIn("несколько установленных пакетов", dependency["detail"])
        for candidate in candidates:
            self.assertIn(str(candidate), dependency["detail"])

    def test_vfs_rebase_searches_unique_resource_package(self):
        owner = aircraft(self.root, "owner-package", "Owner_Plane")
        shared = self.root / "shared-resources"
        gauges = shared / "texture" / "Gauges"
        gauges.mkdir(parents=True)
        (shared / "manifest.json").write_text("{}", encoding="utf-8")
        index = PackageIndex.build([self.root])

        found, origin, candidates = index.rebase(self.root / "owner-package" / "texture" / "Gauges", owner)

        self.assert_path_equal(found, gauges)
        self.assertEqual(origin, "package_index")
        self.assertEqual(candidates, [])

    def test_vfs_rebase_uses_shared_resource_after_missing_base_copy(self):
        _, livery = self.base_and_livery()
        shared = self.root / "shared-resources"
        gauges = shared / "texture" / "Gauges"
        gauges.mkdir(parents=True)
        (shared / "manifest.json").write_text("{}", encoding="utf-8")
        index = PackageIndex.build([self.root])

        found, origin, _ = index.rebase(
            self.root / "test-livery" / "texture" / "Gauges", livery, allow_global=True)

        self.assert_path_equal(found, gauges)
        self.assertEqual(origin, "package_index")

    def test_vfs_rebase_reports_ambiguous_resource_packages(self):
        owner = aircraft(self.root, "owner-package", "Owner_Plane")
        packages = []
        for name in ("shared-one", "shared-two"):
            package = self.root / name
            (package / "texture" / "Gauges").mkdir(parents=True)
            (package / "manifest.json").write_text("{}", encoding="utf-8")
            packages.append(package)
        index = PackageIndex.build([self.root])

        found, origin, candidates = index.rebase(self.root / "owner-package" / "texture" / "Gauges", owner)

        self.assertIsNone(found)
        self.assertEqual(origin, "ambiguous")
        self.assertEqual(len(candidates), 2)
        for package in packages:
            self.assertTrue(any(str(package) in candidate for candidate in candidates))

    def test_ambiguous_model_dependency_is_reported_without_crashing(self):
        _, livery = self.base_and_livery()
        for package_name in ("test-base", "test-base-copy"):
            base = self.root / package_name / "SimObjects" / "Airplanes" / "Test_Base"
            (base / "model").mkdir(parents=True)
            (base / "aircraft.cfg").write_text("[fltsim.0]\ntitle=Test Base\n", encoding="utf-8")
            (base / "model" / "interior.xml").write_text("<Model/>", encoding="utf-8")
        (livery / "aircraft.cfg").write_text(
            "[VARIATION]\nbase_container=..\\Test_Base\n", encoding="utf-8")
        model = livery / "model" / "model.cfg"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("[models]\ninterior=..\\..\\Test_Base\\model\\interior.xml\n", encoding="utf-8")

        result = resolver.resolve_aircraft(livery, index=PackageIndex.build([self.root]))

        dependency = next(d for d in result["dependencies"] if d["kind"] == "model")
        self.assertFalse(dependency["resolved"])
        self.assertNotEqual(dependency["path"], "None")
        self.assertIn("несколько установленных пакетов", dependency["detail"])

    def test_ambiguous_texture_fallback_is_reported_without_none_path(self):
        _, livery = self.base_and_livery()
        aircraft(self.root, "test-base-copy", "Test_Plane")
        first_gauges = self.root / "test-base" / "texture" / "Gauges"
        second_gauges = self.root / "test-base-copy" / "texture" / "Gauges"
        first_gauges.mkdir(parents=True)
        second_gauges.mkdir(parents=True)
        cfg = livery / "texture.TEST" / "texture.cfg"
        cfg.write_text("[fltsim]\nfallback.1=..\\..\\..\\..\\texture\\Gauges\n", encoding="utf-8")

        result = resolver.resolve_aircraft(livery, index=PackageIndex.build([self.root]))

        entry = next(d for d in result["dependencies"] if d["kind"] == "texture_fallback")
        self.assertFalse(entry["resolved"])
        self.assertNotEqual(entry["path"], "None")
        self.assertIn("несколько установленных пакетов", entry["detail"])
        self.assertIn(str(first_gauges), entry["detail"])
        self.assertIn(str(second_gauges), entry["detail"])


if __name__ == "__main__":
    unittest.main()

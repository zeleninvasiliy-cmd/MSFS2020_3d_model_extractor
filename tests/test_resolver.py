"""Pre-build package diagnosis. Every fixture is synthetic: no game assets."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import package_resolver as resolver

spec = importlib.util.spec_from_file_location("pipeline", SCRIPTS / "msfs_universal.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def aircraft(root, package="test-package", name="Test_Plane"):
    folder = root / package / "SimObjects" / "Airplanes" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def model_xml(path, lods):
    # The Behaviors block deliberately contains a raw "<": only LODS is parsed.
    body = "".join(f'<LOD minSize="{80 - index * 10}" ModelFile="{lod}"/>' for index, lod in enumerate(lods))
    path.write_text(f'<?xml version="1.0"?><ModelInfo><LODS>{body}</LODS>'
                    '<Behaviors><Condition>1 < 2</Condition></Behaviors></ModelInfo>', encoding="utf-8")


def gltf(path, buffers=("model.bin",), create_buffers=True, **extra):
    document = {"asset": {"version": "2.0"},
                "buffers": [{"uri": uri, "byteLength": 4} for uri in buffers],
                "accessors": [], "meshes": []}
    document.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    if create_buffers:
        for uri in buffers:
            if not uri.startswith("data:"):
                (path.parent / uri).write_bytes(b"\0\0\0\0")
    return path


def complete_aircraft(root, **kwargs):
    folder = aircraft(root, **kwargs)
    model = folder / "model"
    model.mkdir()
    model_xml(model / "ext.xml", ["ext_LOD00.gltf", "ext_LOD01.gltf"])
    model_xml(model / "int.xml", ["int_LOD00.gltf"])
    gltf(model / "ext_LOD00.gltf", ("ext_LOD00.bin",))
    gltf(model / "ext_LOD01.gltf", ("ext_LOD01.bin",))
    gltf(model / "int_LOD00.gltf", ("int_LOD00.bin",))
    (model / "model.cfg").write_text("[models]\nexterior=ext.xml\ninterior=int.xml\n", encoding="utf-8")
    texture = folder / "texture.TEST"
    texture.mkdir()
    (texture / "BODY_ALBD.PNG.DDS").write_bytes(b"dds")
    return folder


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_module_does_not_need_blender(self):
        self.assertNotIn("bpy", sys.modules)
        self.assertNotIn("import bpy", (SCRIPTS / "package_resolver.py").read_text(encoding="utf-8"))

    def test_complete_package_is_buildable(self):
        report = resolver.resolve_aircraft(complete_aircraft(self.root), deep=True)
        self.assertEqual(report["reason_code"], "OK")
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["can_build_textures"])
        self.assertFalse(report["partial"])
        self.assertFalse(report["needs_model_selection"])
        self.assertEqual({m["role"] for m in report["best_models"]}, {"exterior", "interior"})
        self.assertEqual(report["missing_resources"], [])

    def test_common_resources_only(self):
        folder = aircraft(self.root, package="test-aircraft-common", name="Test_Common")
        model = folder / "model"
        model.mkdir()
        model_xml(model / "EXT.XML", ["Test_LOD00.gltf", "Test_LOD01.gltf"])
        model_xml(model / "INT.XML", ["Test_Interior_LOD00.gltf"])
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "COMMON_RESOURCES_ONLY")
        self.assertFalse(report["can_build_geometry"])
        self.assertFalse(report["can_build_textures"])
        self.assertEqual(report["best_models"], [])
        missing = {Path(item["path"]).name for item in report["missing_resources"] if item["kind"] == "gltf"}
        self.assertEqual(missing, {"Test_LOD00.gltf", "Test_LOD01.gltf", "Test_Interior_LOD00.gltf"})
        self.assertTrue(report["action"])

    def test_unresolved_base_container_alias(self):
        folder = aircraft(self.root, name="Test_Livery")
        (folder / "aircraft.cfg").write_text('[VARIATION]\nbase_container = "..\\Test_Base"\n', encoding="utf-8")
        texture = folder / "texture.LIVERY"
        texture.mkdir()
        (texture / "BODY.PNG.DDS").write_bytes(b"dds")
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "UNRESOLVED_ALIAS")
        self.assertFalse(report["can_build_geometry"])
        self.assertEqual(report["dependencies"][0]["kind"], "base_container")
        self.assertFalse(report["dependencies"][0]["resolved"])

    def test_alias_resolved_by_name_lookup_in_another_root(self):
        base = complete_aircraft(self.root / "other-root", package="base-package", name="Test_Base")
        folder = aircraft(self.root, name="Test_Livery")
        (folder / "aircraft.cfg").write_text('[VARIATION]\nbase_container = "..\\Test_Base"\n', encoding="utf-8")
        report = resolver.resolve_aircraft(folder, roots=[self.root / "other-root"])
        dependency = next(d for d in report["dependencies"] if d["kind"] == "base_container")
        self.assertTrue(dependency["resolved"])
        self.assertEqual(Path(dependency["path"]), base)
        self.assertEqual(report["reason_code"], "LIVERY_ONLY")
        self.assertEqual(report["candidates"][0]["origin"], "base_container")

    def test_missing_interior_is_partial_not_unavailable(self):
        folder = complete_aircraft(self.root)
        (folder / "model" / "int_LOD00.gltf").unlink()
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "SUPPORTED_PARTIAL")
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["partial"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual([m["role"] for m in report["best_models"]], ["exterior"])
        self.assertIn("int_LOD00.gltf", json.dumps(report["missing_resources"], ensure_ascii=False))

    def test_cross_package_interior_reference_is_reported(self):
        folder = complete_aircraft(self.root)
        cfg = folder / "model" / "model.cfg"
        cfg.write_text("[models]\nexterior=ext.xml\ninterior=..\\..\\Other_Plane\\model\\int.xml\n", encoding="utf-8")
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "SUPPORTED_PARTIAL")
        dependency = next(d for d in report["dependencies"] if d["kind"] == "model")
        self.assertFalse(dependency["resolved"])
        self.assertEqual([m["role"] for m in report["best_models"]], ["exterior"])

    def test_model_cfg_without_models_section(self):
        folder = complete_aircraft(self.root)
        (folder / "model" / "model.cfg").write_text("[model.options]\nwithInterior_forceFirstLod=true\n", encoding="utf-8")
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "INVALID_MODEL_CFG")
        # The glTF files are present, so the user can still pick them manually.
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual({Path(m["path"]).name for m in report["best_models"]},
                         {"ext_LOD00.gltf", "int_LOD00.gltf"})

    def test_xml_lods_without_model_cfg_offer_candidates(self):
        folder = complete_aircraft(self.root)
        (folder / "model" / "model.cfg").unlink()
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "MISSING_MODEL_CFG")
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual({Path(c["path"]).name for c in report["best_models"]},
                         {"ext_LOD00.gltf", "int_LOD00.gltf"})
        self.assertTrue(all(c["origin"] in {"xml", "scan"} for c in report["candidates"]))

    def test_missing_bin_only_in_deep_mode(self):
        folder = complete_aircraft(self.root)
        (folder / "model" / "ext_LOD00.bin").unlink()
        shallow = resolver.resolve_aircraft(folder)
        self.assertEqual(shallow["reason_code"], "OK")
        deep = resolver.resolve_aircraft(folder, deep=True)
        # The interior is still readable, so the package degrades to a partial
        # build rather than becoming unavailable.
        self.assertEqual(deep["reason_code"], "SUPPORTED_PARTIAL")
        self.assertTrue(deep["can_build_geometry"])
        self.assertEqual([m["role"] for m in deep["best_models"]], ["interior"])
        self.assertIn("buffer", {item["kind"] for item in deep["missing_resources"]})

    def test_missing_bin_of_the_only_model_blocks_geometry(self):
        folder = aircraft(self.root)
        model = folder / "model"
        model.mkdir()
        gltf(model / "ext_LOD00.gltf", ("ext_LOD00.bin",), create_buffers=False)
        (model / "model.cfg").write_text("[models]\nexterior=ext_LOD00.gltf\n", encoding="utf-8")
        report = resolver.resolve_aircraft(folder, deep=True)
        self.assertEqual(report["reason_code"], "MISSING_BUFFER")
        self.assertFalse(report["can_build_geometry"])
        self.assertIn("ext_LOD00.bin", json.dumps(report["missing_resources"]))

    def test_unsupported_gltf_features(self):
        cases = [
            ({"extensionsUsed": ["KHR_draco_mesh_compression"]}, ("model.bin",)),
            ({"meshes": [{"primitives": [{"mode": 1}]}]}, ("model.bin",)),
        ]
        for index, (extra, buffers) in enumerate(cases):
            with self.subTest(case=index):
                extra = {key: value for key, value in extra.items() if key != "buffers"}
                folder = complete_aircraft(self.root / f"case{index}")
                gltf(folder / "model" / "ext_LOD00.gltf", buffers, **extra)
                report = resolver.resolve_aircraft(folder, deep=True)
                self.assertIn(report["reason_code"], {"UNSUPPORTED_GLTF_FEATURE", "SUPPORTED_PARTIAL"})
                self.assertTrue(report["variants"][0]["models"][0]["unsupported"])
                self.assertIn("gltf_feature", {item["kind"] for item in report["missing_resources"]})

    def test_sparse_accessor_is_supported_by_geometry_adapter(self):
        path = self.root / "sparse.gltf"
        gltf(path, ("sparse.bin",), accessors=[{"sparse": {"count": 1}}])
        result = resolver.inspect_gltf(path)
        self.assertEqual(result["unsupported"], [])

    def test_triangle_strip_is_supported_by_geometry_adapter(self):
        path = self.root / "strip.gltf"
        gltf(path, ("strip.bin",), meshes=[{"primitives": [{"mode": 5}]}])
        result = resolver.inspect_gltf(path)
        self.assertEqual(result["unsupported"], [])

    def test_invalid_glb_container_is_reported_as_unreadable(self):
        folder = aircraft(self.root)
        model = folder / "model"
        model.mkdir()
        (model / "ext_LOD00.glb").write_bytes(b"glTF")
        (model / "model.cfg").write_text("[models]\nexterior=ext_LOD00.glb\n", encoding="utf-8")
        report = resolver.resolve_aircraft(folder, deep=True)
        self.assertEqual(report["reason_code"], "UNREADABLE_GLTF")
        self.assertFalse(report["can_build_geometry"])

    def test_geometry_without_maps(self):
        folder = complete_aircraft(self.root)
        for path in (folder / "texture.TEST").iterdir():
            path.unlink()
        report = resolver.resolve_aircraft(folder)
        self.assertTrue(report["can_build_geometry"])
        self.assertFalse(report["can_build_textures"])
        self.assertEqual(report["reason_code"], "NO_TEXTURES")

    def test_absent_folder_and_unreadable_gltf(self):
        absent = resolver.resolve_aircraft(self.root / "missing")
        self.assertEqual(absent["reason_code"], "PACKAGE_NOT_FOUND")
        self.assertFalse(absent["can_build_geometry"])
        folder = complete_aircraft(self.root)
        (folder / "model" / "ext_LOD00.gltf").write_text("{not json", encoding="utf-8")
        broken = resolver.resolve_aircraft(folder, deep=True)
        self.assertEqual(broken["reason_code"], "SUPPORTED_PARTIAL")
        self.assertIn("gltf_unreadable", {item["kind"] for item in broken["missing_resources"]})
        (folder / "model" / "int_LOD00.gltf").write_text("{not json", encoding="utf-8")
        # LOD01 is still readable, so discovery offers it instead of blocking.
        rescued = resolver.resolve_aircraft(folder, deep=True)
        self.assertEqual(rescued["reason_code"], "SUPPORTED_PARTIAL")
        self.assertTrue(rescued["needs_model_selection"])
        self.assertIn("ext_LOD01.gltf", {Path(m["path"]).name for m in rescued["best_models"]})
        for path in (folder / "model").glob("*.gltf"):
            path.write_text("{not json", encoding="utf-8")
        both = resolver.resolve_aircraft(folder, deep=True)
        self.assertEqual(both["reason_code"], "UNREADABLE_GLTF")
        self.assertFalse(both["can_build_geometry"])

    def test_declared_xml_missing_but_lod_gltf_present(self):
        folder = complete_aircraft(self.root)
        model = folder / "model"
        (model / "ext.xml").unlink()
        (model / "int.xml").unlink()
        report = resolver.resolve_aircraft(folder)
        self.assertEqual(report["reason_code"], "INVALID_MODEL_CFG")
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual({Path(m["path"]).name for m in report["best_models"]},
                         {"ext_LOD00.gltf", "int_LOD00.gltf"})
        self.assertTrue(all(m["origin"] == "scan" for m in report["best_models"]))

    def test_exterior_and_interior_in_separate_model_folders(self):
        folder = aircraft(self.root)
        exterior = folder / "model.Pax"
        exterior.mkdir()
        gltf(exterior / "A310_EXTERIOR_LOD1.gltf", ("A310_EXTERIOR_LOD1.bin",))
        interior = folder / "model.Interior"
        interior.mkdir()
        gltf(interior / "A310_INTERIOR_LOD01.gltf", ("A310_INTERIOR_LOD01.bin",))
        texture = folder / "texture.TEST"
        texture.mkdir()
        (texture / "BODY.PNG.DDS").write_bytes(b"dds")
        report = resolver.resolve_aircraft(folder)
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["cross_variant_models"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual({m["role"] for m in report["best_models"]}, {"exterior", "interior"})
        self.assertEqual({m["variant"] for m in report["best_models"]}, {"model.Pax", "model.Interior"})

    def test_discovered_invalid_glb_is_reported_in_deep_mode(self):
        folder = aircraft(self.root)
        model = folder / "model"
        model.mkdir()
        (model / "ext_LOD00.glb").write_bytes(b"glTF")
        report = resolver.resolve_aircraft(folder, deep=True)
        self.assertFalse(report["can_build_geometry"])
        self.assertEqual(report["reason_code"], "UNREADABLE_GLTF")
        self.assertIn("gltf_unreadable", {item["kind"] for item in report["missing_resources"]})

    def test_discovery_offers_one_model_per_role(self):
        folder = aircraft(self.root)
        model = folder / "model"
        model.mkdir()
        for name in ("fuselage_LOD00.gltf", "wings_LOD00.gltf", "int_LOD00.gltf"):
            gltf(model / name, (name.replace(".gltf", ".bin"),))
        report = resolver.resolve_aircraft(folder, deep=True)
        self.assertTrue(report["can_build_geometry"])
        self.assertTrue(report["needs_model_selection"])
        self.assertEqual(len(report["best_models"]), 2)
        self.assertEqual({m["role"] for m in report["best_models"]}, {"exterior", "interior"})
        self.assertEqual(len(report["candidates"]), 3)

    def test_shared_resource_leaf_below_airplanes_is_diagnosed(self):
        shared = aircraft(self.root, name="Test_Common")
        (shared / "texture").mkdir()
        (shared / "texture" / "SHARED.PNG.DDS").write_bytes(b"dds")
        [entry] = pipeline.inventory(shared)
        self.assertEqual(entry["reason_code"], "COMMON_RESOURCES_ONLY")
        self.assertFalse(entry["can_build_geometry"])
        stub = aircraft(self.root, name="Test_Stub")
        (stub / "panel").mkdir()
        [entry] = pipeline.inventory(stub)
        self.assertEqual(entry["reason_code"], "NO_MODEL_FOLDER")
        self.assertFalse(entry["can_build_geometry"])

    def test_generated_build_folder_is_not_an_aircraft(self):
        package = self.root / "package"
        generated = package / "SimObjects" / "Airplanes" / "msfs_gui_build"
        generated.mkdir(parents=True)
        real = aircraft(self.root, package="package", name="Real_Plane")
        self.assertEqual(resolver.aircraft_folders(package), [real])

    def test_livery_only_folder_reaches_inventory(self):
        folder = aircraft(self.root, name="Test_Livery")
        (folder / "aircraft.cfg").write_text('[VARIATION]\nbase_container = "..\\Test_Base"\n', encoding="utf-8")
        [entry] = pipeline.inventory(folder)
        self.assertEqual(entry["reason_code"], "UNRESOLVED_ALIAS")
        self.assertFalse(entry["can_build_geometry"])

    def test_package_root_with_shared_texture_still_descends(self):
        package = self.root / "package"
        (package / "texture").mkdir(parents=True)
        real = aircraft(self.root, package="package", name="Real_Plane")
        self.assertEqual(resolver.aircraft_folders(package), [real])


class PlanDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def config(self, folder, **extra):
        data = {"source": str(folder), "output_dir": str(self.project / "blend"),
                "blender": sys.executable, "aircraft": folder.name, "livery": "TEST", **extra}
        path = self.project / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_partial_package_needs_explicit_models(self):
        folder = complete_aircraft(self.root / "src")
        (folder / "model" / "int_LOD00.gltf").unlink()
        with self.assertRaises(ValueError) as failure:
            pipeline.make_plan(self.config(folder, model_folder="model"), "geometry")
        self.assertIn("Диагностика пакета", str(failure.exception))
        self.assertIn("SUPPORTED_PARTIAL", str(failure.exception))
        exterior = str(folder / "model" / "ext_LOD00.gltf")
        plan = pipeline.make_plan(self.config(folder, model_folder="model",
                                              models=[{"path": exterior, "role": "exterior"}]), "geometry")
        self.assertEqual([m["role"] for m in plan["models"]], ["exterior"])

    def test_common_only_package_is_rejected_with_reason(self):
        folder = aircraft(self.root / "src", name="Test_Common")
        model = folder / "model"
        model.mkdir()
        model_xml(model / "EXT.XML", ["Test_LOD00.gltf"])
        with self.assertRaises(ValueError) as failure:
            pipeline.make_plan(self.config(folder, model_folder="model"), "geometry")
        self.assertIn("COMMON_RESOURCES_ONLY", str(failure.exception))


if __name__ == "__main__":
    unittest.main()

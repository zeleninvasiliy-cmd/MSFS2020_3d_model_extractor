"""Model-selection wizard payload (roadmap priority 3). All fixtures synthetic."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import package_resolver as resolver
from package_index import PackageIndex
from test_index import aircraft
from test_resolver import complete_aircraft, gltf, model_xml


def counted_gltf(path, vertices=12, triangles=4, **kwargs):
    """A glTF whose accessor counts are readable without opening the BIN."""
    return gltf(path, accessors=[{"count": vertices, "type": "VEC3", "componentType": 5126},
                                 {"count": triangles * 3, "type": "SCALAR", "componentType": 5125}],
                meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}], **kwargs)


class GeometryCountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_counts_come_from_json_without_the_bin(self):
        path = counted_gltf(self.folder / "m.gltf", vertices=30, triangles=7, create_buffers=False)
        checked = resolver.inspect_gltf(path)
        self.assertEqual(checked["vertices"], 30)
        self.assertEqual(checked["triangles"], 7)
        self.assertEqual(len(checked["missing_buffers"]), 1)

    def test_shared_position_accessor_is_counted_once(self):
        path = self.folder / "m.gltf"
        gltf(path, accessors=[{"count": 9}, {"count": 6}, {"count": 3}],
             meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1},
                                     {"attributes": {"POSITION": 0}, "indices": 2}]}])
        checked = resolver.inspect_gltf(path)
        self.assertEqual(checked["vertices"], 9)
        self.assertEqual(checked["triangles"], 3)

    def test_non_triangle_primitive_is_not_counted_as_triangles(self):
        path = self.folder / "m.gltf"
        gltf(path, accessors=[{"count": 8}],
             meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "mode": 1}]}])
        checked = resolver.inspect_gltf(path)
        self.assertIsNone(checked["triangles"])
        self.assertIn("primitive modes [1]", checked["unsupported"])

    def test_missing_file_has_no_counts(self):
        checked = resolver.inspect_gltf(self.folder / "absent.gltf")
        self.assertIsNone(checked["vertices"])
        self.assertIsNone(checked["triangles"])
        self.assertFalse(checked["available"])


class ModelChoicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_complete_package_lists_every_lod_with_counts(self):
        folder = complete_aircraft(self.root)
        counted_gltf(folder / "model" / "ext_LOD00.gltf", vertices=100, triangles=40)
        choices = resolver.model_choices(folder)
        exterior = choices["roles"]["exterior"]
        self.assertEqual([Path(e["path"]).name for e in exterior], ["ext_LOD00.gltf", "ext_LOD01.gltf"])
        self.assertEqual([e["lod"] for e in exterior], [0, 1])
        self.assertEqual(exterior[0]["vertices"], 100)
        self.assertEqual(exterior[0]["triangles"], 40)
        self.assertTrue(exterior[0]["default"])
        self.assertFalse(exterior[1]["default"])
        self.assertEqual({e["role_source"] for e in exterior}, {"model.cfg"})
        self.assertEqual(len(choices["roles"]["interior"]), 1)
        self.assertFalse(choices["partial"])

    def test_lod_number_comes_from_the_filename_not_the_chain_position(self):
        folder = aircraft(self.root, "test-package", "Test_Plane")
        names = ["ext_LOD00.gltf", "ext_LOD01.gltf", "ext_LOD06.gltf"]
        for name in names:
            counted_gltf(folder / "model" / name)
        model_xml(folder / "model" / "ext.xml", names)
        (folder / "model" / "model.cfg").write_text("[models]\nexterior=ext.xml\n", encoding="utf-8")
        exterior = resolver.model_choices(folder)["roles"]["exterior"]
        self.assertEqual([Path(e["path"]).name for e in exterior], names)
        # The chain skips a level, so its third position is 2 while the file is LOD06.
        self.assertEqual([e["lod"] for e in exterior], [0, 1, 6])

    def test_file_without_a_lod_number_has_no_lod(self):
        folder = aircraft(self.root, "test-package", "Test_Plane")
        counted_gltf(folder / "model" / "body.gltf")
        exterior = resolver.model_choices(folder)["roles"]["exterior"]
        self.assertEqual([Path(e["path"]).name for e in exterior], ["body.gltf"])
        self.assertIsNone(exterior[0]["lod"])

    def test_missing_bin_is_visible_and_not_selectable_by_default(self):
        folder = complete_aircraft(self.root)
        (folder / "model" / "ext_LOD00.bin").unlink()
        choices = resolver.model_choices(folder)
        first = choices["roles"]["exterior"][0]
        self.assertEqual(first["status"], "MISSING_BUFFER")
        self.assertFalse(first["available"])
        self.assertFalse(first["default"])
        self.assertTrue(first["missing_buffers"])
        self.assertTrue(choices["roles"]["exterior"][1]["available"])

    def test_role_from_filename_is_labelled_as_a_hint(self):
        folder = aircraft(self.root, "test-package", "Test_Plane")
        counted_gltf(folder / "model" / "int_LOD00.gltf")
        counted_gltf(folder / "model" / "body_LOD00.gltf")
        choices = resolver.model_choices(folder)
        self.assertEqual(choices["reason_code"], "MISSING_MODEL_CFG")
        interior = choices["roles"]["interior"]
        self.assertEqual([Path(e["path"]).name for e in interior], ["int_LOD00.gltf"])
        self.assertEqual(interior[0]["role_source"], "имя файла")
        self.assertEqual(choices["roles"]["exterior"][0]["role_source"], "имя файла")
        # The resolver reports what an automatic build would take; the wizard is
        # what refuses to pre-check a role that only a filename suggested.
        self.assertTrue(all(e["role_source"] == "имя файла" for e in interior))

    def test_one_path_is_offered_once(self):
        folder = complete_aircraft(self.root)
        choices = resolver.model_choices(folder)
        paths = [e["path"] for role in choices["roles"].values() for e in role]
        self.assertEqual(len(paths), len({Path(p).resolve() for p in paths}))

    def livery_with_absent_declared_interior(self):
        base = aircraft(self.root, "test-base", "Test_Plane")
        # The base ships the interior glTF but not the XML the livery declares.
        counted_gltf(base / "model" / "int_LOD01.gltf", vertices=50, triangles=20)
        (base / "model" / "model.cfg").write_text("[models]\ninterior=int.xml\n", encoding="utf-8")
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane", content_type="LIVERY")
        model_xml(livery / "model" / "ext.xml", ["ext_LOD00.gltf"])
        counted_gltf(livery / "model" / "ext_LOD00.gltf", vertices=100, triangles=40)
        (livery / "model" / "model.cfg").write_text(
            "[models]\nexterior=ext.xml\ninterior=..\\..\\Test_Plane\\model\\int.xml\n", encoding="utf-8")
        return base, livery

    def test_base_package_offers_the_interior_the_declared_xml_does_not(self):
        base, livery = self.livery_with_absent_declared_interior()
        index = PackageIndex.build([self.root])
        choices = resolver.model_choices(livery, index=index)
        self.assertTrue(choices["partial"])
        self.assertTrue(choices["base_aircraft"]["scanned"])
        self.assertEqual(choices["base_aircraft"]["name"], "Test_Plane")
        interior = choices["roles"]["interior"]
        self.assertEqual([Path(e["path"]).name for e in interior], ["int_LOD01.gltf"])
        self.assertEqual(Path(interior[0]["path"]), base / "model" / "int_LOD01.gltf")
        self.assertEqual(interior[0]["origin"], "base_package")
        self.assertEqual(interior[0]["role_source"], "имя файла")
        self.assertEqual(interior[0]["vertices"], 50)
        self.assertTrue(interior[0]["available"])
        # The composition stays unconfirmed until the user assigns the role.
        self.assertFalse(interior[0]["default"])
        self.assertEqual([m["role"] for m in choices["default_models"]], ["exterior"])

    def test_complete_package_does_not_scan_the_base(self):
        base = aircraft(self.root, "test-base", "Test_Plane")
        counted_gltf(base / "model" / "int_LOD00.gltf")
        model_xml(base / "model" / "int.xml", ["int_LOD00.gltf"])
        (base / "model" / "model.cfg").write_text("[models]\ninterior=int.xml\n", encoding="utf-8")
        livery = aircraft(self.root, "test-livery", "Test_Plane_Livery", base="Test_Plane", content_type="LIVERY")
        model_xml(livery / "model" / "ext.xml", ["ext_LOD00.gltf"])
        counted_gltf(livery / "model" / "ext_LOD00.gltf")
        (livery / "model" / "model.cfg").write_text(
            "[models]\nexterior=ext.xml\ninterior=..\\..\\Test_Plane\\model\\int.xml\n", encoding="utf-8")
        choices = resolver.model_choices(livery, index=PackageIndex.build([self.root]))
        self.assertFalse(choices["partial"])
        self.assertFalse(choices["base_aircraft"]["scanned"])
        self.assertEqual(choices["roles"]["interior"][0]["origin"], "aircraft_index")

    def test_unreadable_candidate_reports_the_reason(self):
        folder = aircraft(self.root, "test-package", "Test_Plane")
        (folder / "model" / "broken_LOD00.gltf").write_text("{not json", encoding="utf-8")
        choices = resolver.model_choices(folder)
        entry = choices["roles"]["exterior"][0]
        self.assertEqual(entry["status"], "UNREADABLE_GLTF")
        self.assertTrue(entry["read_error"])
        self.assertFalse(entry["available"])

    def test_cli_models_returns_roles(self):
        folder = complete_aircraft(self.root)
        result = subprocess.run([sys.executable, str(SCRIPTS / "msfs_universal.py"), "models", str(folder)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data["roles"]), {"exterior", "interior"})
        self.assertEqual(data["aircraft"], "Test_Plane")


if __name__ == "__main__":
    unittest.main()
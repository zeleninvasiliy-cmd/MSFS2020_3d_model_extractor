"""Regression coverage for project isolation and the desktop workflow."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app_support
import msfs_builder_gui as gui


class DesktopRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.folder = Path(self.temporary.name)
        self.app = gui.BuilderApp()
        self.app.withdraw()

    def tearDown(self):
        self.app.destroy()
        self.temporary.cleanup()

    def project(self):
        source = self.folder / "source"
        source.mkdir()
        self.app.project_open = True
        self.app.project_var.set(str(self.folder / "project.json"))
        self.app.selected_aircraft = {"aircraft": "Test", "path": str(source)}
        self.app.model_var.set("model")
        self.app.blender_var.set(sys.executable)

    def test_detail_summarizes_optional_texture_fallbacks(self):
        report = {"dependencies": [
            {"kind": "texture_fallback", "name": f"fallback.{i}", "resolved": i < 7,
             "optional": True, "path": f"C:/pkg/texture/{i}"}
            for i in range(10)
        ]}

        detail = self.app.format_detail(report)

        self.assertIn("найдено папок 7 из 10", detail)
        self.assertIn("отчёте текстурирования", detail)
        self.assertNotIn("fallback.1", detail)

    def test_save_preserves_tab_and_advanced_operations(self):
        self.project()
        self.app.project_extra = {"placements": {"Rudder": {"anchor": "Tail", "offset_m": [0, 1, 0]}}}
        self.app._set_project_state(True)
        self.app.notebook.select(self.app.build_tab)
        path = self.app.save_project()
        self.assertEqual(self.app.notebook.select(), str(self.app.build_tab))
        self.assertIn("placements", json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(self.app.output_var.get(), str(self.folder / "blend"))

    def test_glob_excluded_object_can_be_restored_and_refresh_keeps_changes(self):
        self.app.exclude_patterns = ["Wheel*"]
        self.app.populate_object_groups({"Gear": ["Wheel[1]", "Wheel[2]"]}, silent=True)
        self.app.object_include["Wheel[1]"] = True
        self.app.populate_object_groups({"Gear": ["Wheel[1]", "Wheel[2]"]}, silent=True)
        patterns = self.app.current_exclusions()
        self.assertEqual(patterns, [app_support.literal_pattern("Wheel[2]")])
        self.assertTrue(self.app.object_include["Wheel[1]"])

    def test_new_project_selection_is_transient(self):
        self.app.new_project()
        self.assertIn(str(self.app.catalog_tab), self.app.notebook.tabs())
        self.app._set_project_state(True)
        self.assertNotIn(str(self.app.catalog_tab), self.app.notebook.tabs())

    def test_delete_legacy_project_keeps_shared_blend(self):
        project = self.folder / "legacy.json"
        app_support.atomic_json(project, {"source": "plane"})
        shared = self.folder / "blend"
        shared.mkdir()
        (shared / "unrelated.txt").write_text("keep", encoding="utf-8")
        with patch.object(app_support, "settings_dir", return_value=self.folder / "settings"):
            archived = app_support.retire_project(project)
        self.assertTrue((shared / "unrelated.txt").is_file())
        self.assertTrue((archived / project.name).is_file())

    def test_busy_guard_prevents_second_job(self):
        self.app.busy = True
        with patch.object(gui.messagebox, "showinfo"):
            self.assertFalse(self.app.run_command(["should-never-run"]))
        self.assertIsNone(self.app.process)

    def test_deep_catalog_toggle_is_forwarded_to_cli(self):
        self.app.catalog_deep_var.set(True)
        self.app.settings["msfs_root"] = str(self.folder)
        with patch.object(self.app, "run_command") as runner:
            self.app.scan_installed()
        command = runner.call_args.args[0]
        self.assertEqual(command[-1], "--deep")

    def test_normal_decode_is_saved_from_texture_controls(self):
        self.project()
        self.app.normal_decode_var.set("dxt5n")
        self.assertEqual(self.app.make_config()["normal_decode"], "dxt5n")

    def test_skin_pose_controls_are_saved_from_geometry_controls(self):
        self.project()
        self.app.pose_position_var.set("POSE")
        self.app.repair_skin_roots_var.set(True)
        config = self.app.make_config()
        self.assertEqual(config["pose_position"], "POSE")
        self.assertTrue(config["repair_skin_roots"])

    def test_converted_normal_directory_is_saved_from_texture_controls(self):
        self.project()
        normal_dir = self.folder / "normal_png"
        normal_dir.mkdir()
        self.app.converted_normal_var.set(str(normal_dir))
        self.assertEqual(Path(self.app.make_config()["converted_normal_dir"]), normal_dir.resolve())

    def test_report_object_catalog_survives_exclusions(self):
        self.app._populate_catalog([
            {"name": "Wheel_Left", "type": "MESH", "collections": ["05_LANDING_GEAR"], "included": False},
            {"name": "Rudder", "type": "MESH", "collections": []},
        ])
        self.assertIn("Wheel_Left", self.app.object_include)

    def test_partial_marker_survives_mode_change_and_rebuild(self):
        self.project()
        self.app.selected_aircraft = {"aircraft": "Test", "path": str(self.folder / "source"),
                                      "needs_model_selection": True}
        self.app.project_extra["models"] = [{"path": "model/ext_LOD00.gltf", "role": "exterior"}]
        self.app._sync_build_variant()
        self.assertEqual(self.app.build_variant_var.get(), "strip_auto_partial")
        self.app.skinning_var.set("manual")
        self.app._on_setting_changed()
        self.assertEqual(self.app.build_variant_var.get(), "manual_auto_partial")
        self.app._sync_build_variant()
        self.assertEqual(self.app.build_variant_var.get(), "manual_auto_partial")
        self.app.project_extra.pop("models")
        self.app._sync_build_variant()
        self.assertEqual(self.app.build_variant_var.get(), "manual_auto")

    def test_diagnosis_is_readable_without_json(self):
        report = {
            "aircraft": "Test_Plane", "path": "C:/pkg/Test_Plane", "reason_code": "SUPPORTED_PARTIAL",
            "reason": "Доступна только часть моделей", "action": "Подтвердите сборку.",
            "can_build_geometry": True, "can_build_textures": False, "deep": True,
            "missing_resources": [{"kind": "model_xml", "path": "C:/pkg/Test_Plane/model/int.xml"}],
            "best_models": [{"path": "C:/pkg/Test_Plane/model/ext_LOD00.gltf", "role": "exterior",
                             "origin": "scan", "variant": "model"}],
            "cross_variant_models": True,
            "dependencies": [{"kind": "base_container", "name": "Test_Base", "resolved": False}],
            "textures": ["texture.TEST"],
            "variants": [{"folder": "model", "reason_code": "SUPPORTED_PARTIAL", "model_cfg_selection": "нет interior",
                          "models": [{"path": "C:/pkg/Test_Plane/model/ext_LOD00.gltf", "role": "exterior",
                                      "origin": "xml", "available": False, "missing_buffers": ["ext_LOD00.bin"],
                                      "unsupported": ["GLB container"], "read_error": "bad json"}],
                          "candidates": [{"path": "C:/pkg/Test_Plane/model/ext_LOD01.gltf", "role": "exterior",
                                          "origin": "scan", "variant": "model"}],
                          "lods": [{"path": "C:/pkg/Test_Plane/model/ext_LOD02.gltf", "available": False}]}],
        }
        summary = self.app.format_diagnosis(report)
        self.assertIn("SUPPORTED_PARTIAL", summary)
        self.assertIn("int.xml", summary)
        self.assertIn("ext_LOD00.gltf", summary)
        self.assertIn("разных model-папок", summary)
        self.assertIn("Базовый самолёт: Test_Base", summary)
        self.assertIn("Карты не найдены", summary)
        detail = self.app.format_detail(report)
        self.assertIn("ext_LOD00.bin", detail)
        self.assertIn("GLB container", detail)
        self.assertIn("bad json", detail)
        self.assertIn("ext_LOD01.gltf", detail)
        self.assertIn("LOD без файла: 1", detail)
        self.assertIn("НЕ разрешена", detail)
        self.assertNotIn('"aircraft"', detail)

    def test_index_provenance_is_visible_without_json(self):
        report = {
            "aircraft": "Test_Livery", "reason_code": "OK", "reason": "Пакет готов",
            "can_build_geometry": True, "can_build_textures": True,
            "best_models": [{"path": "C:/base/Test_Base/model/int_LOD00.gltf", "role": "interior",
                             "origin": "aircraft_index", "variant": None}],
            "dependencies": [{"kind": "base_container", "name": "Test_Base", "resolved": True,
                              "origin": "aircraft_index", "path": "C:/base/Test_Base"}],
            "variants": [{"folder": "model", "models": [
                {"path": "C:/base/Test_Base/model/int_LOD00.gltf", "role": "interior",
                 "origin": "aircraft_index", "available": True}]}],
        }
        summary = self.app.format_diagnosis(report)
        self.assertIn("Базовый самолёт: Test_Base", summary)
        self.assertIn("источник: пакет базового самолёта", summary)
        self.assertNotIn("aircraft_index", summary)
        detail = self.app.format_detail(report)
        self.assertIn("источник: C:\\base\\Test_Base\\model", detail.replace("/", "\\"))
        self.assertIn("OK, источник: пакет базового самолёта", detail)

    def test_ambiguous_base_lists_candidate_packages(self):
        report = {
            "aircraft": "Test_Livery", "reason_code": "SUPPORTED_PARTIAL",
            "missing_resources": [{"kind": "ambiguous", "path": "C:/own/model/int.xml",
                                   "detail": "несколько установленных пакетов: C:/a; C:/b"}],
            "dependencies": [{"kind": "model", "name": "interior", "resolved": False,
                              "path": "C:/own/model/int.xml",
                              "detail": "несколько установленных пакетов: C:/a; C:/b"}],
        }
        summary = self.app.format_diagnosis(report)
        self.assertIn("несколько установленных пакетов: C:/a; C:/b", summary)
        self.assertIn("несколько установленных пакетов", self.app.format_detail(report))

    def test_absent_base_is_named_instead_of_a_long_path(self):
        report = {"aircraft": "Test_Livery", "dependencies": [
            {"kind": "base_container", "name": "Test_Base", "resolved": False, "base_installed": False,
             "path": "C:/very/long/path/Test_Base", "detail": "базовый самолёт не установлен"},
            {"kind": "model", "name": "interior", "resolved": False, "path": "C:/very/long/path/int.xml"}]}
        summary = self.app.format_diagnosis(report)
        self.assertIn("Базовый самолёт: Test_Base — базовый самолёт не установлен", summary)
        self.assertNotIn("C:/very/long/path/Test_Base", summary)
        self.assertIn("int.xml", summary)

    def test_read_error_detail_stays_out_of_the_summary(self):
        report = {"aircraft": "Test", "missing_resources": [
            {"kind": "model_xml", "path": "C:/pkg/model/int.xml",
             "detail": "Не удалось прочитать C:/pkg/model/int.xml: No such file or directory"}]}
        summary = self.app.format_diagnosis(report)
        self.assertIn("C:/pkg/model/int.xml", summary)
        self.assertNotIn("No such file or directory", summary)
        self.assertIn("No such file or directory", self.app.format_detail(report))

    def test_index_view_marks_absent_base(self):
        text = self.app.format_index({
            "packages": 2, "aircraft_names": 2, "cached": 2, "scanned": 0,
            "cache_path": "C:/cache/package_index.json",
            "searched_roots": ["C:/Packages"], "errors": [{"path": "C:/missing", "detail": "каталог не найден"}],
            "aircraft": {"test_livery": [{"name": "Test_Livery", "path": "C:/mods/Test_Livery",
                                          "package": "C:/mods", "base_container": "..\\..\\Test_Base",
                                          "base_installed": False}],
                         "test_base": [{"name": "Test_Base", "path": "C:/base/Test_Base",
                                        "package": "C:/base", "base_container": None, "base_installed": None}]},
        })
        self.assertIn("Пакетов: 2", text)
        self.assertIn("Из кэша: 2", text)
        self.assertIn("C:/cache/package_index.json", text)
        self.assertIn("C:/missing: каталог не найден", text)
        self.assertIn("база: ..\\..\\Test_Base — НЕ установлена", text)
        self.assertNotIn('"base_container"', text)

    def test_index_view_reports_empty_result(self):
        text = self.app.format_index({"packages": 0, "aircraft_names": 0, "aircraft": {}})
        self.assertIn("Самолёты не найдены", text)

    def test_catalog_status_separates_full_from_partial(self):
        self.app.populate_aircraft([
            {"aircraft": "Full", "can_build_geometry": True, "can_build_textures": True},
            {"aircraft": "Partial", "can_build_geometry": True, "needs_model_selection": True},
            {"aircraft": "Blocked", "can_build_geometry": False},
        ])
        self.assertEqual(self.app.status_var.get(),
                         "Найдено самолётов: 3 — полных: 1, частичных: 1, недоступно: 1")

    def test_catalog_status_reports_suppressed_history_stubs(self):
        payload = {"aircraft": [
            {"aircraft": "Asobo_DA62", "path": "C:/official/DA62", "can_build_geometry": True,
             "can_build_textures": True},
        ], "suppressed_history_stubs": [{"aircraft": "Asobo_DA62", "path": "C:/history/DA62"}],
            "index": {"packages": 1, "aircraft_names": 1, "cached": 1, "scanned": 0, "errors": []}}
        self.app.on_catalog_result(0, json.dumps(payload))
        self.assertIn("скрыто history-заглушек: 1", self.app.status_var.get())

    def test_catalog_groups_liveries_and_filters_by_availability(self):
        entries = [
            {"aircraft": "Asobo_C152", "path": "C:/base/C152", "can_build_geometry": True,
             "can_build_textures": True},
            {"aircraft": "Asobo_C152_Livery_Kenmore", "path": "C:/livery/Kenmore", "can_build_geometry": True,
             "can_build_textures": True},
            {"aircraft": "Asobo_C172", "path": "C:/partial/C172", "can_build_geometry": True,
             "can_build_textures": False},
            {"aircraft": "Asobo_L39", "path": "C:/blocked/L39", "can_build_geometry": False},
        ]
        self.app.populate_aircraft(entries)
        groups = self.app.aircraft_list.get_children("")
        self.assertEqual(len(groups), 3)
        c152_group = next(group for group in groups
                          if self.app.aircraft_list.item(group, "text").startswith("Asobo_C152"))
        self.assertEqual(len(self.app.aircraft_list.get_children(c152_group)), 2)

        self.app.aircraft_filter_var.set("Недоступные")
        self.app.populate_aircraft()
        self.assertEqual([entry["aircraft"] for entry in self.app.active_entries], ["Asobo_L39"])
        self.assertEqual(len(self.app.aircraft_list.get_children("")), 1)

        self.app.aircraft_filter_var.set("Все")
        self.app.populate_aircraft()
        group = next(iter(self.app.aircraft_list.get_children("")))
        child = self.app.aircraft_list.get_children(group)[0]
        self.app.aircraft_list.selection_set(child)
        self.app.on_aircraft_select()
        self.assertIsNotNone(self.app.selected_aircraft)

    def test_index_summary_reaches_the_log(self):
        self.app.report_index({"packages": 5, "aircraft_names": 7, "cached": 5, "scanned": 0,
                               "errors": [{"path": "C:/missing", "detail": "каталог не найден"}]})
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("Индекс пакетов: 5 пакетов, 7 имён самолётов", log)
        self.assertIn("C:/missing", log)

    def checkpoints(self, *names):
        output = self.folder / "blend"
        output.mkdir(exist_ok=True)
        paths = []
        for name in names:
            path = output / name
            path.write_bytes(b"")
            paths.append(path)
        self.app.output_var.set(str(output))
        return paths

    def test_latest_geometry_ignores_a_touched_older_build(self):
        old, new = self.checkpoints("01_geometry_strip_auto_002.blend", "01_geometry_strip_auto_010.blend")
        os.utime(old, (2_000_000_000, 2_000_000_000))
        os.utime(new, (1_000_000_000, 1_000_000_000))
        self.assertEqual(self.app.latest_geometry_file(), new)

    def test_checkpoint_list_orders_by_number_and_puts_legacy_last(self):
        first, second, legacy, textured = self.checkpoints(
            "01_geometry_strip_auto_001.blend", "01_geometry_strip_auto_002.blend",
            "01_geometry.blend", "02_textured_strip_auto_002.blend")
        os.utime(legacy, (2_000_000_000, 2_000_000_000))
        os.utime(first, (1_500_000_000, 1_500_000_000))
        self.app.refresh_blend_list()
        self.assertEqual(self.app.blend_paths[-1], legacy)
        self.assertEqual(self.app.blend_paths[0], textured)
        self.assertGreater(self.app.blend_paths.index(first), self.app.blend_paths.index(second))
        self.assertEqual(self.app.last_blend_path, textured)

    def test_equal_numbers_fall_back_to_modification_time(self):
        older, newer = self.checkpoints("01_geometry_manual_auto_003.blend", "01_geometry_strip_auto_003.blend")
        os.utime(older, (1_000_000_000, 1_000_000_000))
        os.utime(newer, (1_500_000_000, 1_500_000_000))
        self.assertEqual(self.app.latest_geometry_file(), newer)

    def model_window(self, payload):
        self.app._build_model_window()
        self.app.model_window.withdraw()
        self.app.populate_model_choices(payload)
        return self.app.model_window

    @staticmethod
    def choice(name, role, **extra):
        entry = {"path": f"C:/synthetic/{name}", "name": name, "role": role, "role_source": "model.cfg",
                 "lod": 0, "variant": "model", "origin": "xml", "declared": True, "default": True,
                 "available": True, "vertices": 171230, "triangles": 851344,
                 "missing_buffers": [], "unsupported": [], "read_error": None, "status": "OK"}
        entry.update(extra)
        return entry

    def payload(self, exterior, interior):
        return {"aircraft": "Test_Plane", "reason": "Доступна только часть моделей",
                "reason_code": "SUPPORTED_PARTIAL", "action": "Подтвердите состав.", "partial": True,
                "base_aircraft": None, "roles": {"exterior": exterior, "interior": interior},
                "default_models": [], "missing_resources": []}

    def test_wizard_shows_lod_counts_and_preselects_only_declared_roles(self):
        declared = self.choice("ext_LOD00.gltf", "exterior")
        guessed = self.choice("int_LOD01.gltf", "interior", role_source="имя файла",
                              origin="base_package", declared=False, default=False, lod=None)
        self.model_window(self.payload([declared], [guessed]))
        exterior_tree = self.app.model_trees["exterior"]
        row = exterior_tree.get_children()[0]
        self.assertEqual(exterior_tree.set(row, "vertices"), "171 230")
        self.assertEqual(exterior_tree.set(row, "triangles"), "851 344")
        self.assertEqual(exterior_tree.set(row, "include"), "☑")
        interior_tree = self.app.model_trees["interior"]
        inner = interior_tree.get_children()[0]
        self.assertEqual(interior_tree.set(inner, "include"), "☐")
        self.assertEqual(interior_tree.set(inner, "lod"), "—")
        self.assertEqual(interior_tree.set(inner, "origin"), "из пакета базового самолёта")
        self.assertEqual([e["name"] for e in self.app.chosen_models()], ["ext_LOD00.gltf"])
        self.assertIn("интерьер: 0", self.app.model_summary.cget("text"))

    def test_unavailable_row_cannot_be_checked(self):
        broken = self.choice("ext_LOD00.gltf", "exterior", available=False, default=False,
                             status="MISSING_BUFFER", missing_buffers=["C:/synthetic/ext_LOD00.bin"])
        self.model_window(self.payload([broken], []))
        tree = self.app.model_trees["exterior"]
        row = tree.get_children()[0]
        self.assertEqual(tree.set(row, "include"), "☐")
        self.assertEqual(tree.set(row, "status"), "нет BIN (1)")
        self.assertFalse(self.app.model_selected[("exterior", row)])
        self.assertEqual(str(self.app.model_confirm.cget("state")), "disabled")

    def test_saved_composition_overrides_the_suggestion(self):
        first = self.choice("ext_LOD00.gltf", "exterior")
        second = self.choice("ext_LOD01.gltf", "exterior", lod=1, default=False, declared=False)
        self.app.project_extra = {"models": [{"path": second["path"], "role": "exterior"}]}
        self.model_window(self.payload([first, second], []))
        self.assertEqual([e["name"] for e in self.app.chosen_models()], ["ext_LOD01.gltf"])

    def test_confirm_writes_models_and_keeps_partial_suffix(self):
        self.project()
        self.app.selected_aircraft = {"aircraft": "Test", "path": str(self.folder / "source"),
                                      "needs_model_selection": True}
        exterior = self.choice("ext_LOD00.gltf", "exterior")
        interior = self.choice("int_LOD01.gltf", "interior", role_source="имя файла",
                               origin="base_package", declared=False, default=False)
        window = self.model_window(self.payload([exterior], [interior]))
        tree = self.app.model_trees["interior"]
        row = tree.get_children()[0]
        self.app.model_selected[("interior", row)] = True
        self.app.update_model_summary()
        self.assertIn("int_LOD01.gltf", self.app.model_summary.cget("text"))
        self.app.confirm_model_choices()
        self.assertEqual(self.app.project_extra["models"],
                         [{"path": exterior["path"], "role": "exterior"},
                          {"path": interior["path"], "role": "interior"}])
        self.assertEqual(self.app.build_variant_var.get(), "strip_auto_partial")
        self.assertTrue(self.app.project_dirty)
        self.assertFalse(window.winfo_exists())
        self.assertIn("ext_LOD00.gltf", self.app.models_summary.cget("text"))

    def test_wizard_asks_the_models_command(self):
        self.app.selected_aircraft = {"aircraft": "Test", "path": "C:/synthetic/Test"}
        with patch.object(self.app, "run_command", return_value=True) as run:
            self.app.choose_models()
        command = run.call_args[0][0]
        self.assertIn("models", command)
        self.assertIn("C:/synthetic/Test", command)
        self.assertTrue(self.app.model_window.winfo_exists())
        self.app.model_window.destroy()


if __name__ == "__main__":
    unittest.main()

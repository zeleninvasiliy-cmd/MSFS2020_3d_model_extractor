"""Stage D: graphical rule editors, the texture table and their CLI support.

Every fixture is synthetic. The editors are driven through their real widgets
and the real CLI, so a broken button or a wrong override key fails here.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))
import msfs_builder_gui as gui
import package_resolver as resolver
import rule_editor
from rule_editor import RULE_TYPES, RuleEditor, referenced_names, rows_of, value_of
from texture_table import TextureTable, build_rows, map_name

CLI = [sys.executable, str(SCRIPTS / "msfs_universal.py")]


def run_cli(*arguments):
    return subprocess.run([*CLI, *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace")


def widgets(window, kind):
    """ttk.Combobox subclasses ttk.Entry, so match the exact widget class."""
    found = []

    def walk(parent):
        for child in parent.winfo_children():
            if type(child) is kind:
                found.append(child)
            walk(child)

    walk(window)
    return found


def click(window, text):
    for button in widgets(window, ttk.Button):
        if button.cget("text") == text:
            button.invoke()
            return
    raise AssertionError(f"кнопка не найдена: {text}")


def set_combo(combo, value):
    combo.set(value)


def set_entry(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)


def skin_gltf(path, node="Wing_L", joints=("wing_root", "aileron_bone")):
    nodes = [{"name": node, "mesh": 0, "skin": 0}, *[{"name": name} for name in joints]]
    path.write_text(json.dumps({"nodes": nodes, "skins": [{"joints": list(range(1, len(joints) + 1))}],
                                "meshes": [{"primitives": []}]}), encoding="utf-8")
    return path


class SkinJointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_joints_are_read_without_blender_or_bin(self):
        path = skin_gltf(self.folder / "ext.gltf")
        report = resolver.skin_joints(path)
        self.assertIsNone(report["read_error"])
        self.assertEqual(report["skins"], [{"node": "Wing_L", "joints": ["wing_root", "aileron_bone"]}])

    def test_nodes_without_a_skin_are_not_offered(self):
        path = self.folder / "ext.gltf"
        path.write_text(json.dumps({"nodes": [{"name": "Empty", "mesh": 0}, {"name": "Bone"}],
                                    "skins": [], "meshes": []}), encoding="utf-8")
        self.assertEqual(resolver.skin_joints(path)["skins"], [])

    def test_unreadable_sources_are_reported_not_guessed(self):
        missing = resolver.skin_joints(self.folder / "absent.gltf")
        self.assertFalse(missing["available"])
        self.assertEqual(missing["read_error"], "файл не найден")
        glb = self.folder / "model.glb"
        glb.write_bytes(b"")
        self.assertTrue(resolver.skin_joints(glb)["read_error"])
        broken = self.folder / "broken.gltf"
        broken.write_text("{not json", encoding="utf-8")
        self.assertIsNotNone(resolver.skin_joints(broken)["read_error"])

    def test_bones_command_prints_json_and_refuses_a_file_without_skins(self):
        path = skin_gltf(self.folder / "ext.gltf")
        completed = run_cli("bones", str(path))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["skins"][0]["joints"], ["wing_root", "aileron_bone"])
        empty = self.folder / "empty.gltf"
        empty.write_text(json.dumps({"nodes": [], "meshes": []}), encoding="utf-8")
        rejected = run_cli("bones", str(empty))
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("нет skin-узлов", rejected.stderr)

    def test_validate_command_accepts_rules_and_rejects_a_typo(self):
        config = self.folder / "project.json"
        config.write_text(json.dumps({"source": "a", "output_dir": "b",
                                      "placements": {"Rudder": {"anchor": "Tail", "offset_m": [0, 1, 0]}},
                                      "mirror_objects": [{"source": "L", "target": "R", "axis": "X"}]}),
                          encoding="utf-8")
        accepted = run_cli("validate", str(config))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        counts = json.loads(accepted.stdout)["rules"]
        self.assertEqual(counts["placements"], 1)
        self.assertEqual(counts["mirror_objects"], 1)
        config.write_text(json.dumps({"source": "a", "output_dir": "b",
                                      "split_spatial": [{"object": "F", "axis": "y", "cuts": [1, 0],
                                                         "names": ["a", "b", "c"]}]}), encoding="utf-8")
        rejected = run_cli("validate", str(config))
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("по возрастанию", rejected.stderr)


class EditorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "source"
        self.source.mkdir()
        self.output = self.folder / "blend"
        self.output.mkdir()
        self.app = gui.BuilderApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app.project_open = True
        self.app.project_var.set(str(self.folder / "project.json"))
        self.app.selected_aircraft = {"aircraft": "Test", "path": str(self.source)}
        self.app.model_var.set("model")
        self.app.blender_var.set(sys.executable)
        self.app.output_var.set(str(self.output))
        self.app._populate_catalog([
            {"name": "Wing_L", "type": "MESH", "collections": ["02_WINGS"],
             "group_path": ["01_EXTERIOR", "02_WINGS"], "source": str(self.source / "ext.gltf"),
             "source_node": "Wing_L", "bounds": [[-4, -1, 0], [0, 1, 2]]},
            {"name": "Wing_R", "type": "MESH", "collections": ["02_WINGS"], "bounds": [[0, -1, 0], [4, 1, 2]]},
            {"name": "Fuselage", "type": "MESH", "collections": ["01_FUSELAGE_AND_GLAZING"],
             "bounds": [[-1, -6, 0], [1, 6, 3]]},
            {"name": "Rudder", "type": "MESH", "collections": []},
            {"name": "Tail", "type": "EMPTY", "collections": []},
        ])
        self.app._set_project_state(True)

    def wait_idle(self, timeout=40):
        deadline = time.time() + timeout
        while self.app.busy and time.time() < deadline:
            self.app.update()
            time.sleep(0.02)
        self.app.update()
        self.assertFalse(self.app.busy, "операция не завершилась")

    def editor(self):
        editor = RuleEditor(self.app, gui.cli_command)
        editor.withdraw()
        self.addCleanup(editor.destroy)
        return editor

    def top(self, parent):
        windows = [w for w in parent.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists()]
        self.assertTrue(windows, "дочернее окно не открылось")
        window = windows[-1]
        window.withdraw()
        return window

    def choose_kind(self, editor, title):
        editor.kind_var.set(title)
        editor.on_kind_changed()
        editor.refresh()


class RuleStorageTests(unittest.TestCase):
    def test_rows_round_trip_for_every_rule_type(self):
        samples = {
            "split_by_skin": [{"object": "Wing", "parts": [{"name": "tip", "bones": ["b"]}]}],
            "split_spatial": [{"object": "Fus", "axis": "Y", "cuts": [0], "names": ["a", "b"]}],
            "mirror_objects": [{"source": "L", "target": "R", "axis": "X"}],
            "placements": {"Rudder": {"anchor": "Tail", "offset_m": [0, 1, 0]}},
            "collection_overrides": {"Wing*": "01_EXTERIOR/02_WINGS"},
            "manual_keep_pivots": ["Wing_L"],
        }
        for kind, value in samples.items():
            with self.subTest(kind=kind):
                self.assertEqual(value_of(kind, rows_of(kind, value)), value)

    def test_referenced_names_cover_every_object_field(self):
        self.assertEqual(referenced_names("mirror_objects", [{"source": "L", "target": "R"}]), {"L", "R"})
        self.assertEqual(referenced_names("placements", [{"object": "A", "anchor": "B"}]), {"A", "B"})
        self.assertEqual(referenced_names("split_by_skin", [{"object": "W", "parts": [{"pivot": "P"}]}]), {"W", "P"})
        self.assertEqual(referenced_names("collection_overrides", [{"pattern": "W*", "collection": "A/B"}]), set())


class RuleEditorTests(EditorTestCase):
    def test_editor_lists_saved_rules_and_switches_type(self):
        self.app.project_extra = {"mirror_objects": [{"source": "Wing_L", "target": "Wing_R", "axis": "X"}],
                                  "placements": {"Rudder": {"anchor": "Tail", "offset_m": [0, 1, 0]}}}
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        self.assertEqual(len(editor.tree.get_children()), 1)
        self.assertEqual(editor.tree.item(editor.tree.get_children()[0], "values")[0], "Wing_L")
        self.choose_kind(editor, "Привязка к якорю")
        self.assertEqual(editor.tree.item(editor.tree.get_children()[0], "values")[1], "Tail")
        self.assertIn("Правил в проекте", editor.summary.cget("text"))

    def test_mirror_rule_is_saved_through_the_real_cli_check(self):
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        self.assertIn("Wing_L", combos[0].cget("values"))
        set_combo(combos[0], "Wing_L")
        set_combo(combos[1], "Wing_R")
        set_combo(combos[2], "X")
        click(dialog, "Сохранить")
        self.wait_idle()
        self.assertEqual(self.app.project_extra["mirror_objects"],
                         [{"source": "Wing_L", "target": "Wing_R", "axis": "X"}])
        self.assertTrue(self.app.project_dirty)
        self.assertFalse(dialog.winfo_exists())

    def test_same_source_and_target_is_rejected_before_the_cli(self):
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Wing_L")
        set_combo(combos[1], "Wing_L")
        with patch.object(gui.messagebox, "showwarning") as warning, \
                patch.object(self.app, "run_command") as run:
            click(dialog, "Сохранить")
        self.assertTrue(warning.called)
        run.assert_not_called()
        self.assertNotIn("mirror_objects", self.app.project_extra)

    def test_bad_axis_is_rejected_by_the_pipeline_and_keeps_the_dialog_open(self):
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Wing_L")
        set_combo(combos[1], "Wing_R")
        combos[2].set("W")
        with patch.object(gui.messagebox, "showerror") as error:
            click(dialog, "Сохранить")
            self.wait_idle()
        self.assertIn("ось должна быть X, Y или Z", error.call_args[0][1])
        self.assertTrue(dialog.winfo_exists())
        self.assertNotIn("mirror_objects", self.app.project_extra)

    def test_unknown_object_name_warns_and_can_be_declined(self):
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Wing_L")
        set_combo(combos[1], "Wing_X.001")
        with patch.object(gui.messagebox, "askyesno", return_value=False) as ask, \
                patch.object(self.app, "run_command") as run:
            click(dialog, "Сохранить")
        self.assertIn("Wing_X.001", ask.call_args[0][1])
        run.assert_not_called()
        self.assertNotIn("mirror_objects", self.app.project_extra)

    def test_object_rule_warns_when_checkpoint_inventory_is_not_loaded(self):
        self.app.object_include.clear()
        self.app.object_details.clear()
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Wing_L")
        set_combo(combos[1], "Wing_R")
        with patch.object(gui.messagebox, "askyesno", return_value=False) as ask, \
                patch.object(self.app, "run_command") as run:
            click(dialog, "Сохранить")
        self.assertEqual(ask.call_args[0][0], "Список объектов не загружен")
        run.assert_not_called()
        self.assertNotIn("mirror_objects", self.app.project_extra)

    def test_placement_offset_accepts_a_comma_decimal(self):
        editor = self.editor()
        self.choose_kind(editor, "Привязка к якорю")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Rudder")
        set_combo(combos[1], "Tail")
        for entry, value in zip(widgets(dialog, ttk.Entry), ("0", "1,5", "0")):
            set_entry(entry, value)
        click(dialog, "Сохранить")
        self.wait_idle()
        self.assertEqual(self.app.project_extra["placements"],
                         {"Rudder": {"anchor": "Tail", "offset_m": [0.0, 1.5, 0.0]}})

    def test_collection_override_rejects_an_empty_path_segment(self):
        editor = self.editor()
        self.choose_kind(editor, "Коллекция по шаблону")
        editor.add_rule()
        dialog = self.top(editor)
        set_entry(widgets(dialog, ttk.Entry)[0], "Wing*")
        set_combo(widgets(dialog, ttk.Combobox)[0], "01_EXTERIOR//02_WINGS")
        with patch.object(gui.messagebox, "showwarning") as warning:
            click(dialog, "Сохранить")
        self.assertIn("пустой уровень", warning.call_args[0][1])
        self.assertNotIn("collection_overrides", self.app.project_extra)

    def test_remove_and_reorder_rules(self):
        self.app.project_extra = {"manual_keep_pivots": ["Wing_L", "Wing_R"]}
        editor = self.editor()
        self.choose_kind(editor, "Сохранить pivot (manual)")
        rows = editor.tree.get_children()
        editor.tree.selection_set(rows[1])
        editor.move_rule(-1)
        self.assertEqual(self.app.project_extra["manual_keep_pivots"], ["Wing_R", "Wing_L"])
        editor.tree.selection_set(editor.tree.get_children()[0])
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            editor.remove_rule()
        self.assertEqual(self.app.project_extra["manual_keep_pivots"], ["Wing_L"])
        editor.tree.selection_set(editor.tree.get_children()[0])
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            editor.remove_rule()
        self.assertNotIn("manual_keep_pivots", self.app.project_extra)

    def test_check_all_rules_does_not_mark_the_project_dirty(self):
        self.app.project_extra = {"mirror_objects": [{"source": "Wing_L", "target": "Wing_R", "axis": "X"}]}
        self.app.project_dirty = False
        editor = self.editor()
        self.choose_kind(editor, "Зеркальная копия")
        with patch.object(gui.messagebox, "showinfo") as info:
            editor.check_rules()
            self.wait_idle()
        self.assertIn("Зеркальная копия: 1", info.call_args[0][1])
        self.assertFalse(self.app.project_dirty)

    def test_spatial_axis_names_follow_the_cut_count(self):
        editor = self.editor()
        self.choose_kind(editor, "Разделение по координатам")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Fuselage")
        self.assertIn("Y: -6 … 6", widgets(dialog, ttk.Label)[1].cget("text"))
        with patch.object(rule_editor.simpledialog, "askstring", return_value="0"):
            click(dialog, "Добавить границу...")
        lists = widgets(dialog, tk.Listbox)
        self.assertEqual(lists[0].get(0, "end"), ("0",))
        self.assertEqual(len(lists[1].get(0, "end")), 2)
        with patch.object(rule_editor.simpledialog, "askstring", return_value="2"):
            click(dialog, "Добавить границу...")
        self.assertEqual(len(lists[1].get(0, "end")), 3)
        lists[1].selection_clear(0, "end")
        lists[1].selection_set(0)
        with patch.object(rule_editor.simpledialog, "askstring", return_value="Fuselage_nose"):
            click(dialog, "Переименовать часть...")
        click(dialog, "Сохранить")
        self.wait_idle()
        rule = self.app.project_extra["split_spatial"][0]
        self.assertEqual(rule["cuts"], [0.0, 2.0])
        self.assertEqual(rule["names"][0], "Fuselage_nose")
        self.assertEqual(len(rule["names"]), 3)

    def test_spatial_suggests_cuts_inside_the_object_bounds(self):
        editor = self.editor()
        self.choose_kind(editor, "Разделение по координатам")
        editor.add_rule()
        dialog = self.top(editor)
        set_combo(widgets(dialog, ttk.Combobox)[0], "Fuselage")
        click(dialog, "Предложить границы")
        cuts = widgets(dialog, tk.Listbox)[0].get(0, "end")
        self.assertEqual(len(cuts), 1)
        self.assertTrue(-6 < float(cuts[0]) < 6)

    def test_spatial_regions_keep_an_open_bound_as_none(self):
        editor = self.editor()
        self.choose_kind(editor, "Разделение по координатам")
        editor.add_rule()
        dialog = self.top(editor)
        combos = widgets(dialog, ttk.Combobox)
        set_combo(combos[0], "Fuselage")
        set_combo(combos[1], "По областям")
        combos[1].event_generate("<<ComboboxSelected>>")
        self.app.update()
        click(dialog, "Добавить область...")
        region = self.top(dialog)
        entries = widgets(region, ttk.Entry)
        set_entry(entries[0], "Fuselage_nose")
        set_entry(entries[1], "")
        set_entry(entries[2], "-2")
        click(region, "Сохранить")
        self.app.update()
        set_entry(widgets(dialog, ttk.Entry)[0], "Fuselage_rest")
        click(dialog, "Сохранить")
        self.wait_idle()
        rule = self.app.project_extra["split_spatial"][0]
        self.assertEqual(rule["default"], "Fuselage_rest")
        self.assertEqual(rule["regions"], [{"name": "Fuselage_nose", "bounds": {"x": [None, -2.0]}}])

    def test_skin_parts_are_chosen_from_the_real_joint_list(self):
        skin_gltf(self.source / "ext.gltf")
        editor = self.editor()
        self.choose_kind(editor, "Разделение по костям")
        editor.add_rule()
        dialog = self.top(editor)
        set_combo(widgets(dialog, ttk.Combobox)[0], "Wing_L")
        click(dialog, "Загрузить кости из glTF")
        self.wait_idle()
        click(dialog, "Добавить часть...")
        part = self.top(dialog)
        set_entry(widgets(part, ttk.Entry)[0], "Wing_L_fixed")
        bones = widgets(part, tk.Listbox)[0]
        self.assertEqual(bones.get(0, "end"), ("wing_root", "aileron_bone"))
        bones.selection_set(0)
        click(part, "Сохранить")
        self.app.update()
        click(dialog, "Добавить часть...")
        part = self.top(dialog)
        set_entry(widgets(part, ttk.Entry)[0], "Wing_L_aileron")
        bones = widgets(part, tk.Listbox)[0]
        bones.selection_set(1)
        click(part, "Сохранить")
        self.app.update()
        click(dialog, "Сохранить")
        self.wait_idle()
        rule = self.app.project_extra["split_by_skin"][0]
        self.assertEqual(rule["object"], "Wing_L")
        self.assertEqual([part["bones"] for part in rule["parts"]], [["wing_root"], ["aileron_bone"]])

    def test_a_bone_already_taken_by_another_part_is_refused(self):
        skin_gltf(self.source / "ext.gltf")
        self.app.project_extra = {"split_by_skin": [{"object": "Wing_L", "parts": [
            {"name": "fixed", "bones": ["wing_root"]}]}]}
        editor = self.editor()
        self.choose_kind(editor, "Разделение по костям")
        editor.tree.selection_set(editor.tree.get_children()[0])
        editor.edit_rule()
        dialog = self.top(editor)
        click(dialog, "Загрузить кости из glTF")
        self.wait_idle()
        click(dialog, "Добавить часть...")
        part = self.top(dialog)
        set_entry(widgets(part, ttk.Entry)[0], "second")
        bones = widgets(part, tk.Listbox)[0]
        bones.selection_set(0)
        with patch.object(gui.messagebox, "showwarning") as warning:
            click(part, "Сохранить")
        self.assertIn("уже назначены", warning.call_args[0][1])
        self.assertTrue(part.winfo_exists())


class TextureTableTests(EditorTestCase):
    def report(self, data, name="02_textured_strip_auto_001.json"):
        path = self.output / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        path.with_suffix(".blend").write_bytes(b"")
        return path

    def payload(self):
        return {
            "missing_textures": [{"material": "BODY", "map": "albd", "filename": "..\\TEXTURE\\BODY_ALBD.PNG"}],
            "unreadable_images": {str(self.folder / "broken.png"): "нулевой размер"},
            "applied_materials": ["BODY", "WING"], "skipped_materials": ["OLD"],
            "compressed_normals_to_review": {str(self.folder / "wing_norm.dds"): "BC5S"},
            "decoded_normals": {}, "duplicate_content": [],
            "ambiguous_textures": {"body_albd.png": [str(self.folder / "a.png"), str(self.folder / "b.png")]},
            "resolved_textures": {"albd:wing_albd.png": str(self.folder / "wing_albd.png")},
            "texture_search_order": [], "missing_fallback_dirs": [],
        }

    def table(self):
        table = TextureTable(self.app, gui.cli_command)
        table.withdraw()
        self.addCleanup(table.destroy)
        return table

    def select(self, table, name):
        children = table.tree.get_children()
        for index, item in enumerate(table.rows):
            if item["name"] == name:
                table.tree.selection_set(children[index])
                table.on_select()
                return
        raise AssertionError(name)

    def test_map_name_matches_the_worker_basename(self):
        self.assertEqual(map_name("..\\TEXTURE\\BODY_ALBD.PNG"), "body_albd.png")
        self.assertEqual(map_name("textures/My%20Map.png"), "my map.png")

    def test_rows_carry_status_kinds_and_materials(self):
        rows = {row["name"]: row for row in build_rows(self.payload())}
        self.assertEqual(rows["body_albd.png"]["kinds"], {"albd"})
        self.assertEqual(rows["body_albd.png"]["materials"], {"BODY"})
        self.assertIn("отсутствует", rows["body_albd.png"]["problems"])
        self.assertIn("кандидатов: 2", rows["body_albd.png"]["problems"])
        self.assertIn("не читается", rows["broken.png"]["problems"])
        self.assertIn("сжатая нормаль BC5S", rows["wing_norm.dds"]["problems"])
        self.assertEqual(rows["wing_albd.png"]["problems"], [])
        self.assertEqual(rows["wing_albd.png"]["path"], str(self.folder / "wing_albd.png"))

    def test_path_keyed_fields_merge_into_the_same_map_row(self):
        data = self.payload()
        data["resolved_textures"]["norm:wing_norm.dds"] = str(self.folder / "WING_NORM.DDS")
        data["compressed_normals_to_review"] = {str(self.folder / "WING_NORM.DDS"): "BC5S"}
        data["decoded_normals"] = {str(self.folder / "WING_NORM.DDS"): {"png": str(self.folder / "decoded.png")}}
        data["duplicate_content"] = [[str(self.folder / "WING_NORM.DDS"), str(self.folder / "other.png")]]
        rows = {row["name"]: row for row in build_rows(data)}
        self.assertNotIn("WING_NORM.DDS", rows)
        item = rows["wing_norm.dds"]
        self.assertEqual(item["kinds"], {"norm"})
        self.assertIn("сжатая нормаль BC5S", item["problems"])
        self.assertIn("нормаль распакована", item["problems"])
        self.assertIn("одинаковое содержимое", item["problems"])
        self.assertEqual(item["decoded"], str(self.folder / "decoded.png"))

    def test_geometry_only_final_report_does_not_hide_the_maps(self):
        self.report({"mesh_objects": 3, "triangles": 12}, "03_model_strip_auto_010.json")
        self.report(self.payload(), "02_textured_strip_auto_009.json")
        self.report(self.payload(), "02_textured_strip_auto_002.json")
        self.assertEqual(self.app.latest_texture_report().name, "02_textured_strip_auto_009.json")

    def test_report_order_follows_the_build_number_not_the_modification_time(self):
        older = self.report(self.payload(), "02_textured_strip_auto_009.json")
        self.report(self.payload(), "02_textured_strip_auto_010.json")
        os.utime(older, (time.time() + 3600, time.time() + 3600))
        self.assertEqual(self.app.latest_texture_report().name, "02_textured_strip_auto_010.json")

    def test_table_without_a_report_explains_what_to_do(self):
        table = self.table()
        self.assertIn("Отчёт текстур не найден", table.headline.cget("text"))
        self.assertEqual(table.tree.get_children(), ())

    def test_replacement_is_keyed_by_the_map_not_by_the_new_file(self):
        self.report(self.payload())
        replacement = self.folder / "renamed_copy.png"
        replacement.write_bytes(b"synthetic")
        table = self.table()
        self.select(table, "body_albd.png")
        with patch.object(gui.filedialog, "askopenfilename", return_value=str(replacement)):
            table.replace_selected()
        self.assertEqual(self.app.project_extra["texture_overrides"], {"body_albd.png": str(replacement)})
        self.assertTrue(self.app.project_dirty)
        self.assertIn("заменена вручную", table.tree.set(table.tree.selection()[0], "status"))

    def test_refresh_keeps_the_selected_map(self):
        self.report(self.payload())
        table = self.table()
        self.select(table, "body_albd.png")
        table.refresh()
        self.assertEqual(table.selected()["name"], "body_albd.png")

    def test_reset_removes_the_override_and_the_empty_key(self):
        self.report(self.payload())
        self.app.project_extra = {"texture_overrides": {"body_albd.png": str(self.folder / "a.png")}}
        table = self.table()
        self.select(table, "body_albd.png")
        table.reset_override()
        self.assertNotIn("texture_overrides", self.app.project_extra)
        self.assertTrue(self.app.project_dirty)

    def test_candidate_list_writes_the_chosen_path(self):
        self.report(self.payload())
        table = self.table()
        self.select(table, "body_albd.png")
        table.choose_candidate()
        picker = self.top(table)
        listing = widgets(picker, tk.Listbox)[0]
        listing.selection_clear(0, "end")
        listing.selection_set(1)
        click(picker, "Использовать этот файл")
        self.assertEqual(self.app.project_extra["texture_overrides"]["body_albd.png"], str(self.folder / "b.png"))

    def test_package_search_uses_find_textures_and_applies_a_match(self):
        report = self.report(self.payload())
        table = self.table()
        found = self.folder / "found"
        found.mkdir()
        payload = {"matches": {"..\\TEXTURE\\BODY_ALBD.PNG": [str(found / "body_albd.png")]},
                   "searched_roots": ["C:/Packages"], "suggested_extra_texture_dirs": [str(found)],
                   "missing": []}
        captured = {}

        def fake_run(command, callback):
            captured["command"] = command
            callback(0, json.dumps(payload, ensure_ascii=False))
            return True

        with patch.object(self.app, "run_command", side_effect=fake_run):
            table.search_packages()
        self.assertIn("find-textures", captured["command"])
        self.assertIn(str(report), captured["command"])
        window = self.top(table)
        box = widgets(window, ttk.Frame)[0]
        tree = widgets(box, ttk.Treeview)[0]
        tree.selection_set(tree.get_children()[0])
        click(window, "Использовать выбранный файл")
        self.assertEqual(self.app.project_extra["texture_overrides"]["body_albd.png"], str(found / "body_albd.png"))
        with patch.object(gui.messagebox, "showinfo"):
            click(window, "Добавить найденные папки в поиск")
        self.assertIn(str(found), self.app.extra_text.get("1.0", "end"))
        with patch.object(gui.messagebox, "showinfo") as info:
            click(window, "Добавить найденные папки в поиск")
        self.assertIn("уже есть", info.call_args[0][1])
        self.assertEqual(self.app.extra_text.get("1.0", "end").count(str(found)), 1)

    def test_package_search_labels_ambiguity_and_requires_choice_before_adding_folders(self):
        self.report(self.payload())
        table = self.table()
        found = self.folder / "found"
        found.mkdir()
        first, second = found / "first.png", found / "second.png"
        payload = {"matches": {"BODY_ALBD.PNG": [str(first), str(second)]},
                   "searched_roots": ["C:/Packages"], "suggested_extra_texture_dirs": [str(found)],
                   "missing": []}

        with patch.object(self.app, "run_command", side_effect=lambda _command, callback:
                          (callback(0, json.dumps(payload)), True)[1]):
            table.search_packages()

        window = self.top(table)
        box = widgets(window, ttk.Frame)[0]
        tree = widgets(box, ttk.Treeview)[0]
        rows = tree.get_children()
        self.assertEqual(len(rows), 2)
        self.assertEqual(tree.item(rows[0], "values")[2], "Неоднозначно (2)")
        self.assertEqual(tree.item(rows[1], "values")[2], "Неоднозначно (2)")
        labels = widgets(window, ttk.Label)
        self.assertIn("неоднозначно: 1", labels[0].cget("text"))

        with patch.object(gui.messagebox, "askyesno", return_value=False) as ask:
            click(window, "Добавить найденные папки в поиск")
        ask.assert_called_once()
        self.assertNotIn(str(found), self.app.extra_text.get("1.0", "end"))

        tree.selection_set(rows[1])
        click(window, "Использовать выбранный файл")
        self.assertEqual(self.app.project_extra["texture_overrides"]["body_albd.png"], str(second))

    def test_saved_project_keeps_the_replacement(self):
        self.report(self.payload())
        replacement = self.folder / "copy.png"
        replacement.write_bytes(b"synthetic")
        table = self.table()
        self.select(table, "body_albd.png")
        with patch.object(gui.filedialog, "askopenfilename", return_value=str(replacement)):
            table.replace_selected()
        path = self.app.save_project()
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["texture_overrides"]["body_albd.png"], str(replacement))


if __name__ == "__main__":
    unittest.main()

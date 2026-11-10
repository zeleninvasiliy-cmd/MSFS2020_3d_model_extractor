"""Graphical editors for the pipeline's geometry rules.

Values are picked from lists or typed into labelled fields; the project JSON is
never edited by hand. Structural checks go through the CLI `validate` command so
the editor and the pipeline share one definition of a valid rule, and a typo is
reported before Blender starts.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

RULE_TYPES = (
    ("split_by_skin", "Разделение по костям"),
    ("split_spatial", "Разделение по координатам"),
    ("mirror_objects", "Зеркальная копия"),
    ("placements", "Привязка к якорю"),
    ("collection_overrides", "Коллекция по шаблону"),
    ("manual_keep_pivots", "Сохранить pivot (manual)"),
)
TITLES = dict(RULE_TYPES)
AXES = ("X", "Y", "Z")
DEFAULT_COLLECTION = "01_EXTERIOR/03_TAIL_AND_CONTROL_SURFACES"
COLUMNS = {
    "split_by_skin": (("object", "Объект", 260), ("parts", "Частей", 70), ("node", "Исходный узел", 240)),
    "split_spatial": (("object", "Объект", 220), ("mode", "Способ", 260), ("names", "Результаты", 320)),
    "mirror_objects": (("source", "Источник", 260), ("target", "Цель", 260), ("axis", "Ось", 60)),
    "placements": (("object", "Объект", 260), ("anchor", "Якорь", 260), ("offset", "Смещение, м", 200)),
    "collection_overrides": (("pattern", "Шаблон имени", 300), ("collection", "Коллекция", 420)),
    "manual_keep_pivots": (("object", "Узел glTF", 400),),
}
HELP = {
    "split_by_skin": "Делит один mesh на части по костям исходного skin-узла glTF. "
                     "Каждая кость принадлежит ровно одной части; смешанные веса программа не разделяет.",
    "split_spatial": "Делит объект по координатам центров граней: либо границами по одной оси, "
                     "либо областями с пределами по x/y/z. Кости и UV не меняются.",
    "mirror_objects": "Заменяет геометрию цели отражённой копией источника относительно мировой плоскости. "
                      "Нормали, UV и положение цели пересчитываются.",
    "placements": "Ставит объект в точку якоря плюс смещение в метрах. Наследуется только положение якоря, "
                  "не его поворот и масштаб.",
    "collection_overrides": "Переносит объекты, чьё имя подходит под шаблон (* и ?), в указанную коллекцию. "
                            "Путь задаётся через «/», например 01_EXTERIOR/02_WINGS.",
    "manual_keep_pivots": "Только для skinning=manual: перечисленные узлы glTF сохраняют родительский pivot, "
                          "а не отсоединяются. Имена берутся из исходного узла, а не из имени Blender.",
}


def number_text(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def parse_number(text, where):
    try:
        value = float(str(text).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"{where}: введите число, например 0.25 или -1,5.") from None
    if not math.isfinite(value):
        raise ValueError(f"{where}: число должно быть конечным.")
    return value


def parse_optional(text, where):
    return None if not str(text).strip() else parse_number(text, where)


def text_of(value, where):
    value = str(value).strip()
    if not value:
        raise ValueError(f"{where}: поле не может быть пустым.")
    return value


def result_names(row):
    if "axis" in row:
        return list(row.get("names", []))
    return [row.get("default", ""), *(region.get("name", "") for region in row.get("regions", []))]


def rows_of(kind, value):
    if kind == "placements":
        return [{"object": name, **placement} for name, placement in (value or {}).items()]
    if kind == "collection_overrides":
        return [{"pattern": pattern, "collection": path} for pattern, path in (value or {}).items()]
    if kind == "manual_keep_pivots":
        return [{"object": name} for name in (value or [])]
    return [dict(row) for row in (value or [])]


def value_of(kind, rows):
    if kind == "placements":
        return {row["object"]: {key: value for key, value in row.items() if key != "object"} for row in rows}
    if kind == "collection_overrides":
        return {row["pattern"]: row["collection"] for row in rows}
    if kind == "manual_keep_pivots":
        return [row["object"] for row in rows]
    return rows


def referenced_names(kind, rows):
    names = set()
    for row in rows:
        if kind == "mirror_objects":
            names.update((row.get("source"), row.get("target")))
        elif kind == "placements":
            names.update((row.get("object"), row.get("anchor")))
        elif kind == "split_by_skin":
            names.add(row.get("object"))
            names.update(part.get("pivot") for part in row.get("parts", []))
        elif kind in {"split_spatial", "manual_keep_pivots"}:
            names.add(row.get("object"))
    return {name for name in names if name}


def describe(kind, row):
    if kind == "split_by_skin":
        return (row.get("object", ""), str(len(row.get("parts", []))),
                row.get("source_node") or row.get("object", ""))
    if kind == "split_spatial":
        if "axis" in row:
            mode = f"ось {str(row['axis']).upper()}: " + ", ".join(number_text(cut) for cut in row.get("cuts", []))
        else:
            mode = f"областей: {len(row.get('regions', []))}, остальное — {row.get('default', '')}"
        return (row.get("object", ""), mode, ", ".join(result_names(row)))
    if kind == "mirror_objects":
        return (row.get("source", ""), row.get("target", ""), str(row.get("axis", "X")).upper())
    if kind == "placements":
        offset = row.get("offset_m", [0, 0, 0])
        return (row.get("object", ""), row.get("anchor", ""), ", ".join(number_text(value) for value in offset))
    if kind == "collection_overrides":
        return (row.get("pattern", ""), row.get("collection", ""))
    return (row.get("object", ""),)


class RuleEditor(tk.Toplevel):
    """One window for every geometry rule, with a list and Add/Edit/Remove."""

    def __init__(self, app, command_factory):
        super().__init__(app)
        self.app = app
        self.command = command_factory
        self.title("Правила редактирования геометрии")
        self.geometry("980x620")
        self.transient(app)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.kind_var = tk.StringVar(value=TITLES[RULE_TYPES[0][0]])
        self.kind = RULE_TYPES[0][0]
        self.rows = []
        picker = ttk.Frame(self, padding=(10, 10, 10, 4))
        picker.grid(row=0, column=0, sticky="ew")
        ttk.Label(picker, text="Тип правила:").pack(side="left")
        self.kind_combo = ttk.Combobox(picker, textvariable=self.kind_var, state="readonly",
                                       values=[title for _key, title in RULE_TYPES], width=34)
        self.kind_combo.pack(side="left", padx=8)
        self.kind_combo.bind("<<ComboboxSelected>>", self.on_kind_changed)
        ttk.Button(picker, text="Прочитать объекты из checkpoint", command=self.read_objects).pack(side="left", padx=8)
        self.help_label = ttk.Label(self, text="", wraplength=940, justify="left", foreground="#555")
        self.help_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        box = ttk.Frame(self, padding=(10, 0))
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, show="headings", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-Button-1>", lambda _event: self.edit_rule())
        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=3, column=0, sticky="ew")
        ttk.Button(buttons, text="Добавить...", command=self.add_rule).pack(side="left")
        ttk.Button(buttons, text="Изменить...", command=self.edit_rule).pack(side="left", padx=6)
        ttk.Button(buttons, text="Удалить", command=self.remove_rule).pack(side="left")
        ttk.Button(buttons, text="Выше", command=lambda: self.move_rule(-1)).pack(side="left", padx=(12, 0))
        ttk.Button(buttons, text="Ниже", command=lambda: self.move_rule(1)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Проверить все правила", command=self.check_rules).pack(side="left", padx=(12, 0))
        ttk.Button(buttons, text="Закрыть", command=self.destroy).pack(side="right")
        self.summary = ttk.Label(self, text="", wraplength=940, justify="left", padding=(10, 0, 10, 10))
        self.summary.grid(row=4, column=0, sticky="ew")
        self.load_kind(self.kind)

    # -- data ------------------------------------------------------------

    def object_names(self):
        return sorted(self.app.object_include, key=str.casefold)

    def node_names(self):
        names = set(self.app.object_include)
        for item in self.app.object_details.values():
            if item.get("source_node"):
                names.add(item["source_node"])
        return sorted(names, key=str.casefold)

    def collection_paths(self):
        paths = {DEFAULT_COLLECTION}
        for item in self.app.object_details.values():
            group = item.get("group_path") or []
            if group:
                paths.add("/".join(group))
        for row in rows_of("collection_overrides", self.app.project_extra.get("collection_overrides")):
            paths.add(row["collection"])
        return sorted(paths)

    def object_bounds(self, name):
        item = self.app.object_details.get(name) or {}
        bounds = item.get("bounds")
        if isinstance(bounds, dict):
            bounds = [bounds.get("min"), bounds.get("max")]
        if not bounds or not bounds[0] or not bounds[1]:
            return None
        return [list(bounds[0]), list(bounds[1])]

    def bounds_text(self, name):
        bounds = self.object_bounds(name)
        if bounds is None:
            return "Границы неизвестны: нажмите «Прочитать объекты из checkpoint»."
        low, high = bounds
        return "Границы объекта, м: " + "; ".join(
            f"{axis}: {number_text(low[index])} … {number_text(high[index])}"
            for index, axis in enumerate(AXES))

    def load_kind(self, kind):
        self.kind = kind
        self.rows = rows_of(kind, self.app.project_extra.get(kind))
        self.help_label.configure(text=HELP[kind])
        columns = COLUMNS[kind]
        self.tree.configure(columns=[key for key, _title, _width in columns])
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=True)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            self.tree.insert("", "end", values=describe(self.kind, row))
        counts = ", ".join(f"{TITLES[key].lower()}: {len(rows_of(key, self.app.project_extra.get(key)))}"
                           for key, _title in RULE_TYPES)
        self.summary.configure(text=f"Правил в проекте — {counts}. Изменения применяются к следующей сборке.")

    def on_kind_changed(self, _event=None):
        title = self.kind_var.get()
        for key, label in RULE_TYPES:
            if label == title:
                self.load_kind(key)
                return

    def selected_index(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.tree.index(selection[0])

    def store(self):
        value = value_of(self.kind, self.rows)
        if value:
            self.app.project_extra[self.kind] = value
        else:
            self.app.project_extra.pop(self.kind, None)
        self.app.project_dirty = True
        self.refresh()

    # -- commands --------------------------------------------------------

    def read_objects(self):
        blend = self.app.latest_geometry_file()
        if blend is None:
            messagebox.showinfo("Нет geometry", "Сначала соберите geometry: имена и границы объектов "
                                                "читаются из checkpoint.", parent=self)
            return
        self.app.scan_blend_objects(blend, silent=True)

    def add_rule(self):
        self.open_dialog(None)

    def edit_rule(self):
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Правило не выбрано", "Выберите правило в списке.", parent=self)
            return
        self.open_dialog(index)

    def remove_rule(self):
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Правило не выбрано", "Выберите правило в списке.", parent=self)
            return
        if not messagebox.askyesno("Удалить правило", f"Удалить правило №{index + 1}?", parent=self):
            return
        del self.rows[index]
        self.store()

    def move_rule(self, delta):
        index = self.selected_index()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.rows):
            return
        self.rows[index], self.rows[target] = self.rows[target], self.rows[index]
        self.store()
        self.tree.selection_set(self.tree.get_children()[target])

    def open_dialog(self, index):
        row = dict(self.rows[index]) if index is not None else {}
        getattr(self, f"_dialog_{self.kind}")(row, index)

    def candidate(self, index, row):
        rows = [dict(item) for item in self.rows]
        if index is None:
            rows.append(row)
        else:
            rows[index] = row
        return rows

    def check_rules(self):
        self.validate_rows(None, None, self.rows, close=False)

    def validate_rows(self, window, ok_button, rows, close=True):
        try:
            config = dict(self.app.make_config())
        except ValueError as exc:
            messagebox.showwarning("Неполная настройка", str(exc), parent=self)
            if ok_button is not None:
                ok_button.configure(state="normal")
            return False
        config[self.kind] = value_of(self.kind, rows)
        known = set(self.node_names() if self.kind == "manual_keep_pivots" else self.object_names())
        unknown = sorted(referenced_names(self.kind, rows) - known) if known else []
        if close and unknown and not messagebox.askyesno(
                "Имя не найдено",
                "В загруженном списке объектов нет имён: " + ", ".join(unknown) + ".\n\n"
                "Blender мог добавить суффикс .001 к повторяющемуся имени, либо имя введено вручную. "
                "Правило с несуществующим именем остановит сборку. Сохранить правило?", parent=self):
            if ok_button is not None:
                ok_button.configure(state="normal")
            return False
        folder = Path(tempfile.mkdtemp(prefix="msfs_rules_"))
        path = folder / "rules.json"
        try:
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            messagebox.showerror("Проверка правил", str(exc), parent=self)
            if ok_button is not None:
                ok_button.configure(state="normal")
            return False

        def checked(code, output):
            shutil.rmtree(folder, ignore_errors=True)
            if code:
                messagebox.showerror("Правило отклонено", output[-1200:] or "Проверка не выполнена.", parent=self)
                if ok_button is not None and ok_button.winfo_exists():
                    ok_button.configure(state="normal")
                return
            if not close:
                try:
                    counts = json.loads(output).get("rules", {})
                except (json.JSONDecodeError, AttributeError):
                    counts = {}
                lines = [f"{TITLES[key]}: {counts.get(key, 0)}" for key, _title in RULE_TYPES]
                lines.append(f"Замен текстур: {counts.get('texture_overrides', 0)}")
                messagebox.showinfo("Правила корректны",
                                    "Программа приняла все значения до запуска Blender.\n\n" + "\n".join(lines),
                                    parent=self)
                return
            self.rows = rows
            self.store()
            self.app.append_log(f"Правила проверены: {TITLES[self.kind]} — {len(rows)}.")
            if window is not None and window.winfo_exists():
                window.destroy()

        if not self.app.run_command(self.command("validate", str(path)), checked):
            shutil.rmtree(folder, ignore_errors=True)
            if ok_button is not None:
                ok_button.configure(state="normal")
            return False
        return False

    # -- form scaffold ---------------------------------------------------

    def _form(self, title, build, collect, on_ok, parent=None):
        host = parent or self
        window = tk.Toplevel(host)
        window.title(title)
        window.transient(host)
        window.columnconfigure(0, weight=1)
        body = ttk.Frame(window, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        state = {}
        build(body, state, window)
        bar = ttk.Frame(window, padding=(12, 0, 12, 12))
        bar.grid(row=1, column=0, sticky="e")
        ok = ttk.Button(bar, text="Сохранить")
        ok.pack(side="right")
        ttk.Button(bar, text="Отмена", command=window.destroy).pack(side="right", padx=6)

        def accept():
            try:
                row = collect(state)
            except ValueError as exc:
                messagebox.showwarning(title, str(exc), parent=window)
                return
            ok.configure(state="disabled")
            if on_ok(row, window, ok):
                window.destroy()

        ok.configure(command=accept)
        window.grab_set()
        return window

    def _object_field(self, body, state, row, label, names, key="object", row_index=0, hint=None):
        ttk.Label(body, text=label).grid(row=row_index, column=0, sticky="w", pady=3)
        variable = tk.StringVar(value=row.get(key, ""))
        combo = ttk.Combobox(body, textvariable=variable, values=names)
        combo.grid(row=row_index, column=1, sticky="ew", padx=(8, 0), pady=3)
        state[key] = variable
        if hint:
            ttk.Label(body, text=hint, foreground="#555", wraplength=420,
                      justify="left").grid(row=row_index + 1, column=0, columnspan=2, sticky="w", pady=(0, 6))

    def _submit(self, index):
        def on_ok(row, window, ok):
            return self.validate_rows(window, ok, self.candidate(index, row))
        return on_ok

    # -- simple dialogs --------------------------------------------------

    def _dialog_mirror_objects(self, row, index):
        names = self.object_names()

        def build(body, state, window):
            self._object_field(body, state, row, "Источник (целая деталь):", names, "source", 0)
            self._object_field(body, state, row, "Цель (повреждённая деталь):", names, "target", 1)
            ttk.Label(body, text="Ось отражения:").grid(row=2, column=0, sticky="w", pady=3)
            state["axis"] = tk.StringVar(value=str(row.get("axis", "X")).upper())
            ttk.Combobox(body, textvariable=state["axis"], values=AXES, state="readonly",
                         width=6).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=3)
            ttk.Label(body, text="Источник и цель должны быть разными mesh-объектами. Отражение идёт "
                                 "относительно мировой плоскости, а не локальных осей объекта.",
                      foreground="#555", wraplength=440, justify="left").grid(row=3, column=0, columnspan=2,
                                                                             sticky="w", pady=(8, 0))

        def collect(state):
            source = text_of(state["source"].get(), "Источник")
            target = text_of(state["target"].get(), "Цель")
            if source == target:
                raise ValueError("Источник и цель должны быть разными объектами.")
            return {"source": source, "target": target, "axis": state["axis"].get()}

        self._form("Зеркальная копия", build, collect, self._submit(index))

    def _dialog_placements(self, row, index):
        names = self.object_names()

        def build(body, state, window):
            self._object_field(body, state, row, "Перемещаемый объект:", names, "object", 0)
            self._object_field(body, state, row, "Якорь:", names, "anchor", 1)
            offset = row.get("offset_m", [0, 0, 0])
            state["offset"] = []
            for column, axis in enumerate(AXES):
                ttk.Label(body, text=f"Смещение {axis}, м:").grid(row=2, column=column * 2, sticky="w", pady=(8, 3))
                variable = tk.StringVar(value=number_text(offset[column]))
                ttk.Entry(body, textvariable=variable, width=10).grid(row=2, column=column * 2 + 1,
                                                                      sticky="w", padx=(4, 10), pady=(8, 3))
                state["offset"].append(variable)
            ttk.Label(body, text="Наследуется только положение якоря. Поворот и масштаб объекта сохраняются.",
                      foreground="#555", wraplength=460, justify="left").grid(row=3, column=0, columnspan=6,
                                                                             sticky="w", pady=(8, 0))

        def collect(state):
            return {"object": text_of(state["object"].get(), "Объект"),
                    "anchor": text_of(state["anchor"].get(), "Якорь"),
                    "offset_m": [parse_number(variable.get(), f"Смещение {axis}")
                                 for axis, variable in zip(AXES, state["offset"])]}

        self._form("Привязка к якорю", build, collect, self._submit(index))

    def _dialog_collection_overrides(self, row, index):
        def build(body, state, window):
            ttk.Label(body, text="Шаблон имени:").grid(row=0, column=0, sticky="w", pady=3)
            state["pattern"] = tk.StringVar(value=row.get("pattern", ""))
            ttk.Entry(body, textvariable=state["pattern"]).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
            ttk.Label(body, text="Коллекция:").grid(row=1, column=0, sticky="w", pady=3)
            state["collection"] = tk.StringVar(value=row.get("collection", DEFAULT_COLLECTION))
            ttk.Combobox(body, textvariable=state["collection"],
                         values=self.collection_paths()).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)
            ttk.Label(body, text="Шаблон сравнивается без учёта регистра: * — любая последовательность, "
                                 "? — один символ. Путь коллекции задаётся через «/»; пустые уровни запрещены. "
                                 "Применяется первое подходящее правило.",
                      foreground="#555", wraplength=460, justify="left").grid(row=2, column=0, columnspan=2,
                                                                             sticky="w", pady=(8, 0))

        def collect(state):
            path = text_of(state["collection"].get(), "Коллекция")
            if not all(path.split("/")):
                raise ValueError("Путь коллекции содержит пустой уровень: проверьте «/».")
            return {"pattern": text_of(state["pattern"].get(), "Шаблон имени"), "collection": path}

        self._form("Коллекция по шаблону", build, collect, self._submit(index))

    def _dialog_manual_keep_pivots(self, row, index):
        def build(body, state, window):
            self._object_field(body, state, row, "Узел glTF:", self.node_names(), "object", 0,
                               hint="Имя исходного узла glTF (source_node), а не имя объекта Blender. "
                                    "Правило работает только при skinning=manual.")

        def collect(state):
            return {"object": text_of(state["object"].get(), "Узел glTF")}

        self._form("Сохранить pivot", build, collect, self._submit(index))

    # -- spatial split ---------------------------------------------------

    def _dialog_split_spatial(self, row, index):
        mode = "axis" if "axis" in row or not row.get("regions") else "regions"

        def build(body, state, window):
            self._object_field(body, state, row, "Объект:", self.object_names(), "object", 0)
            state["bounds"] = ttk.Label(body, text=self.bounds_text(row.get("object", "")), foreground="#555",
                                        wraplength=460, justify="left")
            state["bounds"].grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
            state["object"].trace_add("write", lambda *_args: state["bounds"].configure(
                text=self.bounds_text(state["object"].get())))
            ttk.Label(body, text="Способ:").grid(row=2, column=0, sticky="w", pady=3)
            state["mode"] = tk.StringVar(value="По оси (границы)" if mode == "axis" else "По областям")
            mode_combo = ttk.Combobox(body, textvariable=state["mode"], state="readonly",
                                      values=("По оси (границы)", "По областям"))
            mode_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=3)
            axis_frame = ttk.LabelFrame(body, text="Разделение по оси", padding=8)
            axis_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
            axis_frame.columnconfigure(1, weight=1)
            regions_frame = ttk.LabelFrame(body, text="Разделение по областям", padding=8)
            regions_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
            regions_frame.columnconfigure(0, weight=1)
            state["cuts"] = list(row.get("cuts", []))
            state["names"] = list(row.get("names", []))
            state["regions"] = [dict(region) for region in row.get("regions", [])]
            state["default"] = tk.StringVar(value=row.get("default", ""))
            state["axis"] = tk.StringVar(value=str(row.get("axis", "Y")).upper())

            ttk.Label(axis_frame, text="Ось:").grid(row=0, column=0, sticky="w")
            ttk.Combobox(axis_frame, textvariable=state["axis"], values=AXES, state="readonly",
                         width=6).grid(row=0, column=1, sticky="w", padx=(8, 0))
            ttk.Button(axis_frame, text="Предложить границы", command=lambda: suggest()).grid(row=0, column=2, padx=8)
            state["cut_list"] = tk.Listbox(axis_frame, height=4, exportselection=False)
            state["cut_list"].grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
            cut_bar = ttk.Frame(axis_frame)
            cut_bar.grid(row=2, column=0, columnspan=3, sticky="w")
            ttk.Button(cut_bar, text="Добавить границу...", command=lambda: add_cut()).pack(side="left")
            ttk.Button(cut_bar, text="Удалить границу", command=lambda: remove_cut()).pack(side="left", padx=6)
            state["name_list"] = tk.Listbox(axis_frame, height=4, exportselection=False)
            state["name_list"].grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)
            name_bar = ttk.Frame(axis_frame)
            name_bar.grid(row=4, column=0, columnspan=3, sticky="w")
            ttk.Button(name_bar, text="Переименовать часть...", command=lambda: rename()).pack(side="left")
            ttk.Label(axis_frame, text="Частей всегда на одну больше, чем границ. Пустая часть — ошибка сборки.",
                      foreground="#555", wraplength=440, justify="left").grid(row=5, column=0, columnspan=3,
                                                                             sticky="w", pady=(6, 0))

            ttk.Label(regions_frame, text="Имя остатка (default):").grid(row=0, column=0, sticky="w")
            ttk.Entry(regions_frame, textvariable=state["default"]).grid(row=0, column=1, sticky="ew", padx=8)
            state["region_tree"] = ttk.Treeview(regions_frame, columns=("name", "bounds"), show="headings", height=4)
            state["region_tree"].heading("name", text="Имя части")
            state["region_tree"].heading("bounds", text="Пределы (пусто — без предела)")
            state["region_tree"].column("name", width=160, anchor="w")
            state["region_tree"].column("bounds", width=300, anchor="w")
            state["region_tree"].grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
            region_bar = ttk.Frame(regions_frame)
            region_bar.grid(row=2, column=0, columnspan=2, sticky="w")
            ttk.Button(region_bar, text="Добавить область...", command=lambda: edit_region(None)).pack(side="left")
            ttk.Button(region_bar, text="Изменить область...", command=lambda: edit_region("selected")).pack(side="left", padx=6)
            ttk.Button(region_bar, text="Удалить область", command=lambda: remove_region()).pack(side="left")

            def sync_names():
                needed = len(state["cuts"]) + 1
                base = text_of(state["object"].get(), "Объект") if state["object"].get().strip() else "Part"
                while len(state["names"]) < needed:
                    state["names"].append(f"{base}_{len(state['names']) + 1}")
                del state["names"][needed:]
                state["name_list"].delete(0, "end")
                for name in state["names"]:
                    state["name_list"].insert("end", name)

            def sync_cuts():
                state["cut_list"].delete(0, "end")
                for cut in state["cuts"]:
                    state["cut_list"].insert("end", number_text(cut))
                sync_names()

            def add_cut():
                value = simpledialog.askstring("Новая граница", "Координата границы, м:", parent=window)
                if value is None:
                    return
                try:
                    number = parse_number(value, "Граница")
                except ValueError as exc:
                    messagebox.showwarning("Граница", str(exc), parent=window)
                    return
                state["cuts"].append(number)
                state["cuts"].sort()
                sync_cuts()

            def remove_cut():
                selection = state["cut_list"].curselection()
                if not selection:
                    return
                del state["cuts"][selection[0]]
                sync_cuts()

            def rename():
                selection = state["name_list"].curselection()
                if not selection:
                    return
                position = selection[0]
                value = simpledialog.askstring("Имя части", "Новое имя результата:",
                                               initialvalue=state["names"][position], parent=window)
                if value is None:
                    return
                try:
                    state["names"][position] = text_of(value, "Имя части")
                except ValueError as exc:
                    messagebox.showwarning("Имя части", str(exc), parent=window)
                    return
                sync_names()

            def suggest():
                bounds = self.object_bounds(state["object"].get())
                if bounds is None:
                    messagebox.showinfo("Границы неизвестны", self.bounds_text(state["object"].get()),
                                        parent=window)
                    return
                axis = AXES.index(state["axis"].get())
                low, high = bounds[0][axis], bounds[1][axis]
                count = len(state["cuts"]) or 1
                state["cuts"] = [round(low + (high - low) * step / (count + 1), 4) for step in range(1, count + 1)]
                sync_cuts()

            def sync_regions():
                tree = state["region_tree"]
                tree.delete(*tree.get_children())
                for region in state["regions"]:
                    tree.insert("", "end", values=(region.get("name", ""), bounds_text(region.get("bounds", {}))))

            def edit_region(position):
                if position == "selected":
                    selection = state["region_tree"].selection()
                    if not selection:
                        return
                    position = state["region_tree"].index(selection[0])
                current = dict(state["regions"][position]) if position is not None else {}

                def region_build(region_body, region_state, _region_window):
                    ttk.Label(region_body, text="Имя части:").grid(row=0, column=0, sticky="w", pady=3)
                    region_state["name"] = tk.StringVar(value=current.get("name", ""))
                    ttk.Entry(region_body, textvariable=region_state["name"]).grid(row=0, column=1, columnspan=3,
                                                                                   sticky="ew", padx=8, pady=3)
                    region_state["limits"] = {}
                    for row_number, axis in enumerate(("x", "y", "z"), start=1):
                        limits = (current.get("bounds") or {}).get(axis, [None, None])
                        ttk.Label(region_body, text=f"{axis}: от").grid(row=row_number, column=0, sticky="w", pady=3)
                        low = tk.StringVar(value="" if limits[0] is None else number_text(limits[0]))
                        ttk.Entry(region_body, textvariable=low, width=12).grid(row=row_number, column=1,
                                                                               sticky="w", padx=6, pady=3)
                        ttk.Label(region_body, text="до").grid(row=row_number, column=2, sticky="w", pady=3)
                        high = tk.StringVar(value="" if limits[1] is None else number_text(limits[1]))
                        ttk.Entry(region_body, textvariable=high, width=12).grid(row=row_number, column=3,
                                                                                sticky="w", padx=6, pady=3)
                        region_state["limits"][axis] = (low, high)
                    ttk.Label(region_body, text="Пустое поле — предела нет. Хотя бы одна ось должна быть задана; "
                                                "ключи осей строчные: x, y, z.",
                              foreground="#555", wraplength=420, justify="left").grid(row=4, column=0, columnspan=4,
                                                                                     sticky="w", pady=(8, 0))

                def region_collect(region_state):
                    name = text_of(region_state["name"].get(), "Имя части")
                    bounds = {}
                    for axis, (low, high) in region_state["limits"].items():
                        if not low.get().strip() and not high.get().strip():
                            continue
                        lower = parse_optional(low.get(), f"{axis} от")
                        upper = parse_optional(high.get(), f"{axis} до")
                        if lower is not None and upper is not None and lower >= upper:
                            raise ValueError(f"{axis}: нижний предел должен быть меньше верхнего.")
                        bounds[axis] = [lower, upper]
                    if not bounds:
                        raise ValueError("Задайте пределы хотя бы по одной оси.")
                    return {"name": name, "bounds": bounds}

                def region_ok(region, region_window, _ok):
                    if position is None:
                        state["regions"].append(region)
                    else:
                        state["regions"][position] = region
                    sync_regions()
                    region_window.destroy()
                    return False

                self._form("Область", region_build, region_collect, region_ok, parent=window)

            def remove_region():
                selection = state["region_tree"].selection()
                if not selection:
                    return
                del state["regions"][state["region_tree"].index(selection[0])]
                sync_regions()

            def switch_mode(_event=None):
                if state["mode"].get() == "По оси (границы)":
                    axis_frame.grid()
                    regions_frame.grid_remove()
                else:
                    axis_frame.grid_remove()
                    regions_frame.grid()

            mode_combo.bind("<<ComboboxSelected>>", switch_mode)
            state["sync"] = sync_cuts
            sync_cuts()
            sync_regions()
            switch_mode()

        def collect(state):
            row = {"object": text_of(state["object"].get(), "Объект")}
            if state["mode"].get() == "По оси (границы)":
                if not state["cuts"]:
                    raise ValueError("Добавьте хотя бы одну границу.")
                row["axis"] = state["axis"].get()
                row["cuts"] = list(state["cuts"])
                row["names"] = list(state["names"])
            else:
                if not state["regions"]:
                    raise ValueError("Добавьте хотя бы одну область.")
                row["default"] = text_of(state["default"].get(), "Имя остатка")
                row["regions"] = [dict(region) for region in state["regions"]]
            names = result_names(row)
            if len(set(names)) != len(names):
                raise ValueError("Имена результатов повторяются.")
            return row

        self._form("Разделение по координатам", build, collect, self._submit(index))

    # -- skin split ------------------------------------------------------

    def _dialog_split_by_skin(self, row, index):
        def build(body, state, window):
            self._object_field(body, state, row, "Объект:", self.object_names(), "object", 0)
            ttk.Label(body, text="Исходный skin-узел:").grid(row=1, column=0, sticky="w", pady=3)
            state["source_node"] = tk.StringVar(value=row.get("source_node", row.get("object", "")))
            state["node_combo"] = ttk.Combobox(body, textvariable=state["source_node"], values=[])
            state["node_combo"].grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)
            state["parts"] = [dict(part) for part in row.get("parts", [])]
            state["joints"] = []
            state["source"] = tk.StringVar(value=self.gltf_source(row.get("object", "")))
            bar = ttk.Frame(body)
            bar.grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
            ttk.Button(bar, text="Загрузить кости из glTF", command=lambda: load_bones()).pack(side="left")
            ttk.Button(bar, text="Выбрать glTF...", command=lambda: choose_gltf()).pack(side="left", padx=6)
            state["status"] = ttk.Label(body, text="Кости не загружены: нажмите «Загрузить кости из glTF».",
                                        foreground="#555", wraplength=460, justify="left")
            state["status"].grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 6))
            state["part_tree"] = ttk.Treeview(body, columns=("name", "bones", "collection", "pivot"),
                                              show="headings", height=5)
            for key, title, width in (("name", "Часть", 150), ("bones", "Кости", 220),
                                      ("collection", "Коллекция", 200), ("pivot", "Pivot", 120)):
                state["part_tree"].heading(key, text=title)
                state["part_tree"].column(key, width=width, anchor="w")
            state["part_tree"].grid(row=4, column=0, columnspan=2, sticky="nsew", pady=4)
            body.rowconfigure(4, weight=1)
            part_bar = ttk.Frame(body)
            part_bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
            ttk.Button(part_bar, text="Добавить часть...", command=lambda: edit_part(None)).pack(side="left")
            ttk.Button(part_bar, text="Изменить часть...", command=lambda: edit_part("selected")).pack(side="left", padx=6)
            ttk.Button(part_bar, text="Удалить часть", command=lambda: remove_part()).pack(side="left")
            ttk.Label(body, text="Каждая кость принадлежит ровно одной части. Кости, не назначенные ни одной "
                                 "части, остаются в исходном объекте. И каждая часть, и остаток должны быть непустыми.",
                      foreground="#555", wraplength=480, justify="left").grid(row=6, column=0, columnspan=2,
                                                                             sticky="w", pady=(6, 0))
            state["object"].trace_add("write", lambda *_args: state["source"].set(
                self.gltf_source(state["object"].get())))

            def sync_parts():
                tree = state["part_tree"]
                tree.delete(*tree.get_children())
                for part in state["parts"]:
                    tree.insert("", "end", values=(part.get("name", ""), ", ".join(part.get("bones", [])),
                                                   part.get("collection", DEFAULT_COLLECTION), part.get("pivot", "")))

            def used_bones(exclude=None):
                return {bone for position, part in enumerate(state["parts"]) if position != exclude
                        for bone in part.get("bones", [])}

            def load_bones():
                source = state["source"].get().strip()
                if not source:
                    messagebox.showinfo("Нет glTF", "Не удалось определить исходный glTF объекта. "
                                                    "Выберите файл кнопкой «Выбрать glTF...».", parent=window)
                    return

                def loaded(code, output):
                    if not window.winfo_exists():
                        return
                    if code:
                        messagebox.showerror("Кости", output[-800:], parent=window)
                        return
                    try:
                        data = json.loads(output)
                    except json.JSONDecodeError:
                        messagebox.showerror("Кости", "Не удалось разобрать ответ bones.", parent=window)
                        return
                    skins = data.get("skins", [])
                    state["skins"] = skins
                    state["node_combo"].configure(values=[skin.get("node") or "" for skin in skins])
                    current = state["source_node"].get()
                    match = next((skin for skin in skins if skin.get("node") == current), skins[0] if skins else None)
                    if match is not None:
                        state["source_node"].set(match.get("node") or "")
                        state["joints"] = [joint for joint in match.get("joints", []) if joint]
                    state["status"].configure(text=f"Узлов со skin: {len(skins)}. Костей в выбранном узле: "
                                                   f"{len(state['joints'])}.")
                    state["node_combo"].bind("<<ComboboxSelected>>", switch_node)
                    sync_parts()

                if not self.app.run_command(self.command("bones", source), loaded):
                    return

            def switch_node(_event=None):
                for skin in state.get("skins", []):
                    if skin.get("node") == state["source_node"].get():
                        state["joints"] = [joint for joint in skin.get("joints", []) if joint]
                        state["status"].configure(text=f"Костей в выбранном узле: {len(state['joints'])}.")
                        return

            def choose_gltf():
                path = filedialog.askopenfilename(title="Исходный glTF объекта", parent=window,
                                                  filetypes=(("glTF", "*.gltf"), ("Все файлы", "*.*")))
                if path:
                    state["source"].set(path)
                    load_bones()

            def edit_part(position):
                if position == "selected":
                    selection = state["part_tree"].selection()
                    if not selection:
                        return
                    position = state["part_tree"].index(selection[0])
                if not state["joints"]:
                    messagebox.showinfo("Кости не загружены",
                                        "Сначала загрузите кости из glTF: части выбираются из списка костей.",
                                        parent=window)
                    return
                current = dict(state["parts"][position]) if position is not None else {}
                taken = used_bones(position)

                def part_build(part_body, part_state, _part_window):
                    ttk.Label(part_body, text="Имя части:").grid(row=0, column=0, sticky="w", pady=3)
                    part_state["name"] = tk.StringVar(value=current.get("name", ""))
                    ttk.Entry(part_body, textvariable=part_state["name"]).grid(row=0, column=1, sticky="ew",
                                                                              padx=8, pady=3)
                    ttk.Label(part_body, text="Кости части:").grid(row=1, column=0, sticky="nw", pady=3)
                    part_state["bones"] = tk.Listbox(part_body, selectmode="extended", height=8, exportselection=False)
                    part_state["bones"].grid(row=1, column=1, sticky="nsew", padx=8, pady=3)
                    part_body.rowconfigure(1, weight=1)
                    part_body.columnconfigure(1, weight=1)
                    for joint in state["joints"]:
                        part_state["bones"].insert("end", joint)
                        if joint in current.get("bones", []):
                            part_state["bones"].selection_set("end")
                        if joint in taken:
                            part_state["bones"].itemconfigure("end", foreground="#999")
                    ttk.Label(part_body, text="Серым показаны кости, уже назначенные другой части.",
                              foreground="#555").grid(row=2, column=1, sticky="w", padx=8)
                    ttk.Label(part_body, text="Коллекция:").grid(row=3, column=0, sticky="w", pady=3)
                    part_state["collection"] = tk.StringVar(value=current.get("collection", DEFAULT_COLLECTION))
                    ttk.Combobox(part_body, textvariable=part_state["collection"],
                                 values=self.collection_paths()).grid(row=3, column=1, sticky="ew", padx=8, pady=3)
                    ttk.Label(part_body, text="Pivot (необязательно):").grid(row=4, column=0, sticky="w", pady=3)
                    part_state["pivot"] = tk.StringVar(value=current.get("pivot", ""))
                    ttk.Combobox(part_body, textvariable=part_state["pivot"],
                                 values=["", *self.object_names()]).grid(row=4, column=1, sticky="ew", padx=8, pady=3)

                def part_collect(part_state):
                    name = text_of(part_state["name"].get(), "Имя части")
                    bones = [part_state["bones"].get(index) for index in part_state["bones"].curselection()]
                    if not bones:
                        raise ValueError("Выберите хотя бы одну кость.")
                    clash = sorted(set(bones) & taken)
                    if clash:
                        raise ValueError("Кости уже назначены другой части: " + ", ".join(clash))
                    part = {"name": name, "bones": bones}
                    collection = part_state["collection"].get().strip()
                    if collection:
                        if not all(collection.split("/")):
                            raise ValueError("Путь коллекции содержит пустой уровень.")
                        part["collection"] = collection
                    pivot = part_state["pivot"].get().strip()
                    if pivot:
                        part["pivot"] = pivot
                    return part

                def part_ok(part, part_window, _ok):
                    if position is None:
                        state["parts"].append(part)
                    else:
                        state["parts"][position] = part
                    sync_parts()
                    part_window.destroy()
                    return False

                self._form("Часть по костям", part_build, part_collect, part_ok, parent=window)

            def remove_part():
                selection = state["part_tree"].selection()
                if not selection:
                    return
                del state["parts"][state["part_tree"].index(selection[0])]
                sync_parts()

            sync_parts()

        def collect(state):
            if not state["parts"]:
                raise ValueError("Добавьте хотя бы одну часть.")
            row = {"object": text_of(state["object"].get(), "Объект"),
                   "parts": [dict(part) for part in state["parts"]]}
            node = state["source_node"].get().strip()
            if node and node != row["object"]:
                row["source_node"] = node
            return row

        self._form("Разделение по костям", build, collect, self._submit(index))

    def gltf_source(self, name):
        item = self.app.object_details.get(name) or {}
        source = item.get("source")
        if source and Path(source).is_file():
            return str(source)
        for model in self.app.project_extra.get("models", []):
            path = model.get("path")
            if path and Path(path).is_file():
                return str(path)
        return ""


def bounds_text(bounds):
    parts = []
    for axis in ("x", "y", "z"):
        if axis not in bounds:
            continue
        low, high = bounds[axis]
        parts.append(f"{axis}: {'без нижнего предела' if low is None else number_text(low)} … "
                     f"{'без верхнего предела' if high is None else number_text(high)}")
    return "; ".join(parts) or "пределы не заданы"
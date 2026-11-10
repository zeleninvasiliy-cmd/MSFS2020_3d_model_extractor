"""Texture table built from the pipeline's own report, with graphical replacement.

The table never guesses: every row comes from `02_textured`/`03_model` report
fields, and a replacement is written to `texture_overrides` exactly as the
worker expects it. Searching installed packages reuses the `find-textures`
command instead of walking the disk here.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import unquote

MAP_TITLES = {"albd": "Цвет", "comp": "COMP", "norm": "Нормаль", "emissive": "Свечение"}
IMAGE_TYPES = (("Изображения", "*.png *.dds *.jpg *.jpeg *.tif *.tiff *.tga *.bmp"), ("Все файлы", "*.*"))


def map_name(uri):
    """The worker keys overrides by the casefolded basename of the glTF URI."""
    return Path(unquote(str(uri)).replace("\\", "/")).name.casefold()


def build_rows(report):
    rows = {}

    def row(name, kind=""):
        key = map_name(name)
        item = rows.setdefault(key, {"name": key, "kinds": set(), "materials": set(), "path": "",
                                     "candidates": [], "problems": []})
        if kind:
            item["kinds"].add(kind)
        return item

    for key, path in (report.get("resolved_textures") or {}).items():
        kind, _, name = str(key).partition(":")
        item = row(name, kind)
        item["path"] = str(path)
    for entry in report.get("missing_textures") or []:
        if not entry.get("filename"):
            continue
        item = row(entry["filename"], entry.get("map", ""))
        if entry.get("material"):
            item["materials"].add(entry["material"])
        if "отсутствует" not in item["problems"]:
            item["problems"].append("отсутствует")
    for name, candidates in (report.get("ambiguous_textures") or {}).items():
        item = row(name)
        item["candidates"] = [str(path) for path in candidates]
        item["problems"].append(f"кандидатов: {len(item['candidates'])}")
    for path, error in (report.get("unreadable_images") or {}).items():
        item = row(map_name(path))
        item["problems"].append("не читается")
        item["error"] = str(error)
    for path, codec in (report.get("compressed_normals_to_review") or {}).items():
        item = row(map_name(path))
        item["problems"].append(f"сжатая нормаль {codec}")
    for path, info in (report.get("decoded_normals") or {}).items():
        item = row(map_name(path))
        item["decoded"] = str((info or {}).get("png", ""))
        item["problems"].append("нормаль распакована")
    for group in report.get("duplicate_content") or []:
        for path in group:
            item = row(map_name(path))
            item["duplicates"] = [str(other) for other in group if str(other) != str(path)]
            if "одинаковое содержимое" not in item["problems"]:
                item["problems"].append("одинаковое содержимое")
    return sorted(rows.values(), key=lambda item: (not item["problems"], item["name"]))


def status_text(item, override):
    parts = list(item["problems"])
    if override:
        parts.insert(0, "заменена вручную")
    elif not parts and item["path"]:
        parts.append("найдена")
    return "; ".join(parts) or "—"


def path_text(item, override):
    if override:
        return str(override)
    if item.get("decoded"):
        return item["decoded"]
    if item["path"]:
        return item["path"]
    if item["candidates"]:
        return item["candidates"][0]
    return "—"


class TextureTable(tk.Toplevel):
    def __init__(self, app, command_factory):
        super().__init__(app)
        self.app = app
        self.command = command_factory
        self.title("Таблица карт текстур")
        self.geometry("1120x640")
        self.transient(app)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rows = []
        self.report_path = None
        self.headline = ttk.Label(self, text="", wraplength=1080, justify="left", padding=(10, 10, 10, 4))
        self.headline.grid(row=0, column=0, sticky="ew")
        ttk.Label(self, text="Замена попадает в texture_overrides и применяется при следующей сборке textures. "
                             "Имя карты берётся из отчёта, а не из имени материала.",
                  wraplength=1080, justify="left", foreground="#555", padding=(10, 0, 10, 6)).grid(row=1, column=0, sticky="ew")
        box = ttk.Frame(self, padding=(10, 0))
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        columns = (("kind", "Карта", 120), ("name", "Файл", 240), ("status", "Состояние", 230),
                   ("path", "Путь / замена", 380), ("materials", "Материалы", 200))
        self.tree = ttk.Treeview(box, columns=[key for key, _title, _width in columns], show="headings",
                                 selectmode="browse")
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=key in {"path", "status"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("problem", foreground="#a00")
        self.tree.tag_configure("override", foreground="#060")
        self.detail = tk.Text(self, height=4, wrap="word", state="disabled")
        self.detail.grid(row=3, column=0, sticky="ew", padx=10, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        bar = ttk.Frame(self, padding=10)
        bar.grid(row=4, column=0, sticky="ew")
        ttk.Button(bar, text="Обновить", command=self.reload).pack(side="left")
        ttk.Button(bar, text="Заменить...", command=self.replace_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="Выбрать из кандидатов...", command=self.choose_candidate).pack(side="left", padx=6)
        ttk.Button(bar, text="Найти в установленных пакетах", command=self.search_packages).pack(side="left", padx=6)
        ttk.Button(bar, text="Сбросить замену", command=self.reset_override).pack(side="left", padx=6)
        ttk.Button(bar, text="Закрыть", command=self.destroy).pack(side="right")
        self.summary = ttk.Label(self, text="", wraplength=1080, justify="left", padding=(10, 0, 10, 10))
        self.summary.grid(row=5, column=0, sticky="ew")
        self.reload()

    # -- data ------------------------------------------------------------

    def overrides(self):
        return self.app.project_extra.get("texture_overrides") or {}

    def override_for(self, name):
        for key, value in self.overrides().items():
            if map_name(key) == name:
                return value
        return None

    def reload(self):
        self.report_path = self.app.latest_texture_report()
        self.rows = []
        if self.report_path is None:
            self.headline.configure(text="Отчёт текстур не найден: сначала выполните «Добавить textures» или «Собрать final».")
            self.tree.delete(*self.tree.get_children())
            self.summary.configure(text="")
            return
        try:
            report = json.loads(self.report_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            self.tree.delete(*self.tree.get_children())
            self.headline.configure(text=f"Не удалось прочитать отчёт: {exc}")
            return
        self.rows = build_rows(report)
        self.report = report
        self.headline.configure(text=f"Отчёт: {self.report_path.name}. Карт в отчёте: {len(self.rows)}. "
                                     f"Материалов применено: {len(report.get('applied_materials') or [])}, "
                                     f"без сопоставления: {len(report.get('skipped_materials') or [])}.")
        self.refresh()

    def refresh(self):
        selected = self.selected()
        keep = selected["name"] if selected else None
        self.tree.delete(*self.tree.get_children())
        overrides = self.overrides()
        replaced = 0
        restored = None
        for item in self.rows:
            override = self.override_for(item["name"])
            replaced += bool(override)
            kinds = ", ".join(MAP_TITLES.get(kind, kind) for kind in sorted(item["kinds"])) or "—"
            item_id = self.tree.insert("", "end", values=(kinds, item["name"], status_text(item, override),
                                                          path_text(item, override),
                                                          ", ".join(sorted(item["materials"])) or "—"))
            if override:
                self.tree.item(item_id, tags=("override",))
            elif item["problems"]:
                self.tree.item(item_id, tags=("problem",))
            if item["name"] == keep:
                restored = item_id
        # Rebuilding the tree drops the selection; keep the user on the same map
        # so a replacement can be undone without hunting for the row again.
        if restored is not None:
            self.tree.selection_set(restored)
        problems = sum(1 for item in self.rows if item["problems"])
        self.summary.configure(text=f"Карт с замечаниями: {problems}. Задано замен: {len(overrides)} "
                                    f"(из них в этом отчёте: {replaced}). После замены повторите сборку textures.")

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            return None
        index = self.tree.index(selection[0])
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def on_select(self, _event=None):
        item = self.selected()
        if item is None:
            self.set_detail("")
            return
        lines = [f"Файл карты: {item['name']}",
                 f"Карта: {', '.join(MAP_TITLES.get(kind, kind) for kind in sorted(item['kinds'])) or '—'}",
                 f"Состояние: {status_text(item, self.override_for(item['name']))}"]
        if item.get("error"):
            lines.append("Ошибка чтения: " + item["error"])
        if item["candidates"]:
            lines.append("Кандидаты: " + "; ".join(item["candidates"]))
        if item.get("duplicates"):
            lines.append("Такое же содержимое: " + "; ".join(item["duplicates"]))
        if item["materials"]:
            lines.append("Материалы: " + ", ".join(sorted(item["materials"])))
        lines.append("Путь: " + path_text(item, self.override_for(item["name"])))
        self.set_detail("\n".join(lines))

    def set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    # -- replacement -----------------------------------------------------

    def set_override(self, name, path):
        overrides = dict(self.overrides())
        # The worker looks the override up by the glTF map's basename, not by the
        # replacement file's name: a renamed copy must still bind to the material.
        overrides[name] = str(path)
        self.app.project_extra["texture_overrides"] = overrides
        self.app.project_dirty = True
        self.app.append_log(f"Замена карты: {name} -> {path}")
        self.refresh()
        self.on_select()

    def replace_selected(self):
        item = self.selected()
        if item is None:
            messagebox.showinfo("Карта не выбрана", "Выберите карту в таблице.", parent=self)
            return
        path = filedialog.askopenfilename(title=f"Файл для карты {item['name']}", parent=self, filetypes=IMAGE_TYPES)
        if path:
            self.set_override(item["name"], path)

    def reset_override(self):
        item = self.selected()
        if item is None:
            messagebox.showinfo("Карта не выбрана", "Выберите карту в таблице.", parent=self)
            return
        override = self.override_for(item["name"])
        if not override:
            messagebox.showinfo("Замены нет", "Для этой карты замена не задана.", parent=self)
            return
        overrides = {key: value for key, value in self.overrides().items() if map_name(key) != item["name"]}
        if overrides:
            self.app.project_extra["texture_overrides"] = overrides
        else:
            self.app.project_extra.pop("texture_overrides", None)
        self.app.project_dirty = True
        self.app.append_log(f"Замена карты сброшена: {item['name']}")
        self.refresh()
        self.on_select()

    def pick_path(self, name, paths, title):
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        listing = tk.Listbox(window, width=110, height=12, exportselection=False)
        listing.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        for path in paths:
            listing.insert("end", path)
        if paths:
            listing.selection_set(0)
        bar = ttk.Frame(window, padding=(10, 0, 10, 10))
        bar.grid(row=1, column=0, sticky="e")

        def use():
            selection = listing.curselection()
            if not selection:
                return
            self.set_override(name, paths[selection[0]])
            window.destroy()

        ttk.Button(bar, text="Использовать этот файл", command=use).pack(side="right")
        ttk.Button(bar, text="Отмена", command=window.destroy).pack(side="right", padx=6)
        window.grab_set()

    def choose_candidate(self):
        item = self.selected()
        if item is None:
            messagebox.showinfo("Карта не выбрана", "Выберите карту в таблице.", parent=self)
            return
        if not item["candidates"]:
            messagebox.showinfo("Кандидатов нет", "Отчёт не перечисляет несколько файлов для этой карты. "
                                                  "Используйте «Заменить...» или «Найти в установленных пакетах».",
                                parent=self)
            return
        self.pick_path(item["name"], item["candidates"], f"Кандидаты для {item['name']}")

    # -- package search --------------------------------------------------

    def search_packages(self):
        if self.report_path is None:
            messagebox.showinfo("Нет отчёта", "Сначала соберите textures: поиск идёт по отсутствующим картам отчёта.",
                                parent=self)
            return
        window = tk.Toplevel(self)
        window.title("Поиск карт в установленных пакетах")
        window.geometry("1000x560")
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        label = ttk.Label(window, text="Ищу отсутствующие карты по всем установленным пакетам MSFS...",
                          wraplength=960, justify="left", padding=(10, 10, 10, 4))
        label.grid(row=0, column=0, sticky="ew")
        box = ttk.Frame(window, padding=(10, 0))
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        tree = ttk.Treeview(box, columns=("name", "path"), show="headings", selectmode="browse")
        tree.heading("name", text="Карта")
        tree.heading("path", text="Найденный файл")
        tree.column("name", width=240, anchor="w")
        tree.column("path", width=700, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        bar = ttk.Frame(window, padding=10)
        bar.grid(row=2, column=0, sticky="ew")
        use_button = ttk.Button(bar, text="Использовать выбранный файл")
        use_button.pack(side="left")
        folders_button = ttk.Button(bar, text="Добавить найденные папки в поиск")
        folders_button.pack(side="left", padx=6)
        ttk.Button(bar, text="Закрыть", command=window.destroy).pack(side="right")
        found = {}
        state = {"data": None}

        def loaded(code, output):
            if not window.winfo_exists():
                return
            if code:
                label.configure(text="Поиск не выполнен: " + (output[-600:] or "нет ответа."))
                return
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                label.configure(text="Не удалось разобрать ответ find-textures.")
                return
            state["data"] = data
            matches = data.get("matches") or {}
            tree.delete(*tree.get_children())
            for name, paths in sorted(matches.items(), key=lambda pair: str.casefold(pair[0])):
                for path in paths:
                    item_id = tree.insert("", "end", values=(map_name(name), path))
                    found[item_id] = (map_name(name), path)
            missing = data.get("missing") or []
            label.configure(text=f"Просмотрено корней: {len(data.get('searched_roots') or [])}. "
                                 f"Карт найдено: {sum(len(paths) for paths in matches.values())} "
                                 f"для {sum(1 for paths in matches.values() if paths)} имён. "
                                 f"Не найдено: {len(missing)}." + (" Не найдены: " + ", ".join(missing[:8]) if missing else ""))
            use_button.configure(state="normal" if found else "disabled")
            folders_button.configure(state="normal" if data.get("suggested_extra_texture_dirs") else "disabled")

        def use_selected():
            selection = tree.selection()
            if not selection or selection[0] not in found:
                return
            name, path = found[selection[0]]
            self.set_override(name, path)

        def add_folders():
            data = state["data"] or {}
            folders = data.get("suggested_extra_texture_dirs") or []
            if not folders:
                return
            current = self.app.extra_text.get("1.0", "end").splitlines()
            known = {line.strip().casefold() for line in current if line.strip()}
            added = [folder for folder in folders if folder.casefold() not in known]
            if not added:
                messagebox.showinfo("Папки уже добавлены", "Все найденные папки уже есть в списке дополнительных каталогов.",
                                    parent=window)
                return
            text = "\n".join(line for line in current if line.strip())
            self.app.extra_text.configure(state="normal")
            self.app.extra_text.delete("1.0", "end")
            self.app.extra_text.insert("1.0", "\n".join([text, *added]).strip() + "\n")
            self.app.project_dirty = True
            self.app.append_log(f"Добавлены каталоги текстур: {len(added)}.")
            messagebox.showinfo("Каталоги добавлены",
                                f"Добавлено папок: {len(added)}. Они сохранятся в проекте и будут просмотрены "
                                "при следующей сборке textures.", parent=window)

        use_button.configure(command=use_selected, state="disabled")
        folders_button.configure(command=add_folders, state="disabled")
        window.grab_set()
        if not self.app.run_command(self.command("find-textures", str(self.report_path)), loaded):
            window.destroy()
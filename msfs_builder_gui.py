"""Small Tkinter front-end for MSFS Universal Pipeline v1.

The GUI deliberately stays thin: it scans packages, writes a project JSON,
launches the existing CLI in a background process, and opens checkpoints in
the user's Blender installation. Geometry/material algorithms remain in the
universal pipeline scripts.
"""

from __future__ import annotations

import json
import fnmatch
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from app_support import (VERSION, atomic_json, detect_blender, literal_pattern, load_settings,
                         owned_blend_folder, retire_project, save_settings, settings_dir, valid_filename)
from rule_editor import RULE_TYPES, RuleEditor
from texture_table import TextureTable


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CLI = ROOT / "scripts" / "msfs_universal.py"

ORIGIN_LABELS = {
    "model.cfg": "объявление в model.cfg",
    "xml": "объявление в XML модели",
    "scan": "поиск рядом с пакетом",
    "base_container": "наследование базового самолёта",
    "aircraft_index": "пакет базового самолёта",
    "base_package": "базовый пакет",
    "package_index": "индекс пакетов MSFS",
    "name_lookup": "поиск по имени в каталоге MSFS",
}

# A livery that borrows files must not look self-contained: show the supplying package.
FOREIGN_ORIGINS = {"scan", "base_container", "aircraft_index", "base_package", "name_lookup"}

AIRCRAFT_FILTERS = ("Все", "Полностью доступные", "Частично доступные", "Недоступные")


def aircraft_group_name(name):
    """Return a stable base name for livery/physical variants in the catalog."""
    text = str(name or "?").strip() or "?"
    match = re.match(r"^(.*?)(?:_livery(?:_|$).*)$", text, re.IGNORECASE)
    return (match.group(1) or text) if match else text


def aircraft_status(entry):
    """Classify availability for the user-facing catalog filter."""
    if not entry.get("can_build_geometry"):
        return "Недоступные"
    if (not entry.get("can_build_textures", True)
            or entry.get("partial")
            or entry.get("needs_model_selection")):
        return "Частично доступные"
    return "Полностью доступные"


def origin_text(origin):
    return f"источник: {ORIGIN_LABELS.get(origin or '', origin or 'не указан')}"


def cli_command(*arguments):
    bundled = Path(sys.executable).parent / "MSFSBuilderCLI.exe"
    return ([str(bundled)] if getattr(sys, "frozen", False) else [sys.executable, str(CLI)]) + list(arguments)


def checkpoint_order(path):
    """The trailing number is the build counter. Modification time is only a
    tie-break: copying, unpacking or cloud sync must not promote an old build."""
    match = re.search(r"_(\d{3,})$", path.stem)
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return (int(match.group(1)) if match else 0), modified, path.name.casefold()


class BuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title(f"MSFS Model Builder {VERSION}")
        self.geometry("1120x760")
        self.minsize(920, 640)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.catalog_entries: list[dict] = []
        self.suppressed_history_stub_count = 0
        self.inventory_entries: list[dict] = []
        self.active_entries: list[dict] = []
        self._aircraft_tree_entries: dict[str, dict] = {}
        self._aircraft_tree_paths: dict[str, str] = {}
        self.selected_aircraft: dict | None = None
        self.selected_inventory: dict | None = None
        self.project_open = False
        self.project_dirty = False
        self._loading_project = False
        self.active_stage = None
        self.catalog_step_open = False
        self.busy = False
        self.cancel_requested = False
        self.project_extra = {}
        self.active_build_config = None
        self._disabled_widgets = []
        self._drain_after_id = None
        self._build_vars()
        self._build_ui()
        self._set_project_state(False)
        self.protocol("WM_DELETE_WINDOW", self.close_application)
        self.bind("<Control-s>", lambda _event: self.save_project() if self.project_open and not self.busy else None)
        self._schedule_drain()

    def _schedule_drain(self):
        """Schedule the queue poll while keeping a cancellable Tk handle."""
        try:
            self._drain_after_id = self.after(120, self._drain_events)
        except tk.TclError:
            # The window may already be in the final destruction phase.
            self._drain_after_id = None

    def _build_vars(self):
        self.source_var = tk.StringVar()
        self.catalog_root_var = tk.StringVar()
        self.catalog_deep_var = tk.BooleanVar(value=False)
        self.aircraft_filter_var = tk.StringVar(value=AIRCRAFT_FILTERS[0])
        self.aircraft_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.livery_var = tk.StringVar(value="base")
        self.output_var = tk.StringVar()
        self.blender_var = tk.StringVar(value=self.settings.get("blender") or detect_blender())
        self.skinning_var = tk.StringVar(value="strip")
        self.draw_var = tk.StringVar(value="auto")
        self.pose_position_var = tk.StringVar(value="REST")
        self.normal_decode_var = tk.StringVar(value="auto")
        self.converted_normal_var = tk.StringVar(value="")
        self.filter_runtime_var = tk.BooleanVar(value=True)
        self.repair_skin_roots_var = tk.BooleanVar(value=False)
        self.all_liveries_var = tk.BooleanVar(value=False)
        self.exclude_var = tk.StringVar()
        self.extra_texture_var = tk.StringVar()
        self.project_var = tk.StringVar()
        roots = self.package_roots()
        self.catalog_root_var.set(roots[0] if roots else "")
        self.status_var = tk.StringVar(value="Готово. Выберите каталог или выполните сканирование MSFS.")
        self.build_stage_var = tk.StringVar(value="Этап не запущен")
        self.build_detail_var = tk.StringVar(value="Перейдите по шагам и запустите нужный этап сборки.")
        self.build_result_var = tk.StringVar(value="")
        self.build_variant_var = tk.StringVar(value="")
        self.last_blend_path: Path | None = None
        self.audit_report_path: Path | None = None
        self.explorer_button_visible = False
        self.object_include: dict[str, bool] = {}
        self.object_details: dict[str, dict] = {}
        self.object_group_items: dict[str, list[str]] = {}
        self.exclude_patterns: list[str] = []
        self.blend_paths: list[Path] = []

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_menu()
        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Сканировать MSFS", command=self.scan_installed).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Проверить планы", command=self.audit_geometry_plans).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Выбрать каталог", command=self.choose_catalog).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Каталоги Packages...", command=self.manage_package_roots).pack(side="left", padx=3)
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=16)

        notebook = ttk.Notebook(self)
        self.notebook = notebook
        notebook.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        notebook.bind("<<NotebookTabChanged>>", lambda _event: self._update_navigation())
        self.catalog_tab = ttk.Frame(notebook, padding=10)
        self.welcome_tab = ttk.Frame(notebook, padding=10)
        self.setup_tab = ttk.Frame(notebook, padding=10)
        self.build_tab = ttk.Frame(notebook, padding=10)
        self.texture_tab = ttk.Frame(notebook, padding=10)
        self.log_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.welcome_tab, text="Проекты")
        notebook.add(self.setup_tab, text="2. Настройка")
        notebook.add(self.build_tab, text="3. Геометрия")
        notebook.add(self.texture_tab, text="4. Текстуры")
        notebook.add(self.log_tab, text="Журнал")
        self._build_catalog_tab()
        self._build_welcome_tab()
        self._build_setup_tab()
        self._build_build_tab()
        self._build_texture_tab()
        self._build_log_tab()
        navigation = ttk.Frame(self, padding=(8, 0, 8, 8))
        navigation.grid(row=2, column=0, sticky="ew")
        navigation.columnconfigure(1, weight=1)
        self.nav_back = ttk.Button(navigation, text="← Назад", command=self.go_back)
        self.nav_back.grid(row=0, column=0, sticky="w")
        self.nav_hint = ttk.Label(navigation, text="")
        self.nav_hint.grid(row=0, column=1, sticky="w", padx=12)
        self.nav_next = ttk.Button(navigation, text="Далее →", command=self.go_next)
        self.nav_next.grid(row=0, column=2, sticky="e")
        for variable in (
            self.model_var,
            self.livery_var,
            self.output_var,
            self.blender_var,
            self.skinning_var,
            self.draw_var,
            self.normal_decode_var,
            self.converted_normal_var,
            self.filter_runtime_var,
            self.pose_position_var,
            self.repair_skin_roots_var,
            self.all_liveries_var,
        ):
            variable.trace_add("write", lambda *_args: self._on_setting_changed())
        self._sync_build_variant()

    def _build_welcome_tab(self):
        tab = self.welcome_tab
        tab.columnconfigure(0, weight=1)
        ttk.Label(tab, text="Проект не открыт", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=(70, 12))
        ttk.Label(tab, text="Для работы сначала создайте новый проект или откройте существующий.", foreground="#555").grid(row=1, column=0, pady=(0, 18))
        buttons = ttk.Frame(tab)
        buttons.grid(row=2, column=0)
        ttk.Button(buttons, text="Новый проект", command=self.new_project).pack(side="left", padx=6)
        ttk.Button(buttons, text="Открыть проект...", command=self.open_project).pack(side="left", padx=6)

    def _build_menu(self):
        menu = tk.Menu(self)
        files = tk.Menu(menu, tearoff=False)
        files.add_command(label="Новый проект", command=self.new_project)
        files.add_command(label="Открыть проект...", command=self.open_project)
        files.add_separator()
        files.add_command(label="Сохранить", command=self.save_project)
        files.add_command(label="Сохранить как...", command=self.save_project_as)
        files.add_command(label="Закрыть проект", command=self.close_project)
        files.add_command(label="Удалить проект...", command=self.delete_project)
        files.add_separator()
        files.add_command(label="Выход", command=self.close_application)
        menu.add_cascade(label="Файлы", menu=files)
        self.file_menu = files
        menu.add_command(label="Пути и настройки...", command=self.configure_paths)
        menu.add_command(label="Каталоги Packages...", command=self.manage_package_roots)
        menu.add_command(label="Индекс пакетов...", command=self.show_package_index)
        menu.add_command(label="Руководство", command=self.open_help)
        self.config(menu=menu)

    def report_callback_exception(self, exception, value, tb):
        detail = "".join(traceback.format_exception(exception, value, tb))
        try:
            folder = settings_dir()
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "gui-errors.log").open("a", encoding="utf-8") as stream:
                stream.write(detail + "\n")
        except OSError:
            pass
        messagebox.showerror("Ошибка интерфейса", f"{value}\n\nПодробности: {settings_dir() / 'gui-errors.log'}")

    def configure_paths(self):
        if self.busy:
            return
        directory = self.directory_dialog("Папка Packages MSFS (Official/Community) или каталог модов", self.catalog_root_var.get())
        if directory:
            self.catalog_root_var.set(directory)
            self._remember_package_root(directory)
        self.choose_blender()
        self._save_user_settings()

    def package_roots(self):
        """Return configured extra roots, including the legacy single-root setting."""
        values = self.settings.get("msfs_roots", [])
        if not isinstance(values, list):
            values = []
        legacy = self.settings.get("msfs_root")
        if legacy:
            values = [*values, legacy]
        roots = []
        seen = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            path = os.path.abspath(os.path.expandvars(os.path.expanduser(value.strip())))
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                roots.append(path)
        return roots

    @staticmethod
    def append_package_roots(command, roots):
        for root in roots:
            command.extend(["--root", str(root)])
        return command

    def save_package_roots(self, roots):
        normalized = []
        seen = set()
        for value in roots:
            raw = os.path.expandvars(os.path.expanduser(str(value).strip()))
            if not raw:
                continue
            path = os.path.abspath(raw)
            key = os.path.normcase(path)
            if path and key not in seen:
                seen.add(key)
                normalized.append(path)
        self.settings["msfs_roots"] = normalized
        # Preserve compatibility with v1 settings and command-line setup.
        self.settings["msfs_root"] = normalized[0] if normalized else ""
        if not self.project_open:
            self.catalog_root_var.set(normalized[0] if normalized else "")
        self._save_user_settings()
        if hasattr(self, "package_roots_custom_list") and self.package_roots_window.winfo_exists():
            self.render_package_roots(getattr(self, "package_roots_data", {}))

    def _remember_package_root(self, path):
        roots = self.package_roots()
        candidate = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path).strip())))
        if candidate and os.path.normcase(candidate) not in {os.path.normcase(item) for item in roots}:
            roots.append(candidate)
            self.save_package_roots(roots)

    def manage_package_roots(self):
        if self.busy:
            return
        window = getattr(self, "package_roots_window", None)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            self.refresh_package_roots()
            return
        window = tk.Toplevel(self)
        window.title("Каталоги MSFS и модов")
        window.geometry("980x590")
        window.minsize(760, 460)
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)
        window.rowconfigure(1, weight=1)
        self.package_roots_window = window
        ttk.Label(window, text="Автоматически найденные корни Packages (UserCfg.opt и стандартные расположения):",
                  wraplength=920, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4))
        auto_box = ttk.LabelFrame(window, text="Найдены автоматически", padding=6)
        auto_box.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
        auto_box.columnconfigure(0, weight=1)
        auto_box.rowconfigure(0, weight=1)
        self.package_roots_auto_list = tk.Listbox(auto_box, exportselection=False)
        self.package_roots_auto_list.grid(row=0, column=0, sticky="nsew")
        auto_scroll = ttk.Scrollbar(auto_box, command=self.package_roots_auto_list.yview)
        auto_scroll.grid(row=0, column=1, sticky="ns")
        self.package_roots_auto_list.configure(yscrollcommand=auto_scroll.set)
        custom_box = ttk.LabelFrame(window, text="Добавлены вручную", padding=6)
        custom_box.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
        custom_box.columnconfigure(0, weight=1)
        custom_box.rowconfigure(0, weight=1)
        self.package_roots_custom_list = tk.Listbox(custom_box, exportselection=False)
        self.package_roots_custom_list.grid(row=0, column=0, sticky="nsew")
        custom_scroll = ttk.Scrollbar(custom_box, command=self.package_roots_custom_list.yview)
        custom_scroll.grid(row=0, column=1, sticky="ns")
        self.package_roots_custom_list.configure(yscrollcommand=custom_scroll.set)
        controls = ttk.Frame(window, padding=(10, 4))
        controls.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(controls, text="Добавить каталог...", command=self.add_package_root).pack(side="left")
        ttk.Button(controls, text="Убрать выбранный", command=self.remove_package_root).pack(side="left", padx=6)
        ttk.Button(controls, text="Обновить список", command=self.refresh_package_roots).pack(side="left", padx=6)
        ttk.Button(controls, text="Закрыть", command=window.destroy).pack(side="right")
        self.package_roots_summary_var = tk.StringVar(value="Проверка каталогов...")
        ttk.Label(window, textvariable=self.package_roots_summary_var, wraplength=940,
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 10))
        self.package_roots_data = {}
        self.render_package_roots({})
        self.refresh_package_roots()

    def render_package_roots(self, data):
        if not hasattr(self, "package_roots_auto_list") or not self.package_roots_window.winfo_exists():
            return
        data = data if isinstance(data, dict) else {}
        self.package_roots_data = data
        automatic = self.package_roots_data.get("automatic_roots", [])
        if not isinstance(automatic, list):
            automatic = []
        custom = self.package_roots()
        custom_keys = {os.path.normcase(os.path.abspath(path)) for path in custom}
        automatic = [path for path in automatic if os.path.normcase(os.path.abspath(path)) not in custom_keys]
        self.package_roots_auto_list.delete(0, "end")
        self.package_roots_custom_list.delete(0, "end")
        for path in automatic:
            self.package_roots_auto_list.insert("end", path)
        missing_values = data.get("missing_additional_roots", [])
        if not isinstance(missing_values, list):
            missing_values = []
        missing = {os.path.normcase(os.path.abspath(path)) for path in missing_values if isinstance(path, str)}
        for path in custom:
            label = f"⚠ {path} — каталог не найден" if os.path.normcase(os.path.abspath(path)) in missing else path
            self.package_roots_custom_list.insert("end", label)
        if not automatic:
            self.package_roots_auto_list.insert("end", "MSFS не обнаружен автоматически")
        if not custom:
            self.package_roots_custom_list.insert("end", "Дополнительные каталоги не добавлены")
        missing_count = len(missing)
        searched_values = data.get("searched_roots", [])
        searched_count = (len(searched_values) if isinstance(searched_values, list) and searched_values
                          else len(automatic) + len(custom))
        self.package_roots_summary_var.set(
            f"Каталогов в поиске: {searched_count}; автоматически найдено: "
            f"{len(automatic)}; добавлено вручную: {len(custom)}; отсутствует: {missing_count}. "
            "Отсутствующие пути отмечены значком ⚠."
        )

    def refresh_package_roots(self):
        if not hasattr(self, "package_roots_window") or not self.package_roots_window.winfo_exists():
            return
        command = self.append_package_roots(cli_command("roots"), self.package_roots())

        def loaded(code, output):
            if not self.package_roots_window.winfo_exists():
                return
            if code:
                self.append_log("Ошибка проверки каталогов Packages: " + output[-1200:])
                self.package_roots_summary_var.set(
                    "Не удалось обновить список каталогов. Проверьте вкладку «Журнал» и повторите проверку."
                )
                messagebox.showerror(
                    "Каталоги Packages",
                    "Не удалось проверить список. Технические подробности записаны во вкладку «Журнал».",
                    parent=self.package_roots_window,
                )
                return
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                self.append_log("Не удалось разобрать ответ команды roots: " + output[-1200:])
                self.package_roots_summary_var.set(
                    "Ответ проверки каталогов повреждён. Подробности записаны во вкладку «Журнал»."
                )
                messagebox.showerror(
                    "Каталоги Packages",
                    "Программа не смогла прочитать ответ проверки. Подробности записаны во вкладку «Журнал».",
                    parent=self.package_roots_window,
                )
                return
            self.render_package_roots(data)

        self.run_command(command, loaded)

    def add_package_root(self):
        path = self.directory_dialog("Добавить папку Packages, Community или каталог пакета", self.catalog_root_var.get())
        if path:
            roots = self.package_roots()
            if os.path.normcase(os.path.abspath(path)) not in {os.path.normcase(item) for item in roots}:
                roots.append(path)
                self.save_package_roots(roots)
                self.catalog_root_var.set(path)
            self.refresh_package_roots()

    def remove_package_root(self):
        selection = self.package_roots_custom_list.curselection()
        roots = self.package_roots()
        index = selection[0] if selection else None
        if index is None or index >= len(roots):
            return
        roots.pop(index)
        self.save_package_roots(roots)
        self.refresh_package_roots()

    def _save_user_settings(self):
        self.settings["blender"] = self.blender_var.get().strip()
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.append_log(f"Не удалось сохранить настройки: {exc}")

    def open_help(self):
        guide = Path(sys.executable).parent / "docs" / "USER_MANUAL_RU.html" if getattr(sys, "frozen", False) else ROOT / "release" / "docs" / "USER_MANUAL_RU.html"
        if not guide.is_file():
            guide = ROOT / "USER_GUIDE.md"
        try:
            os.startfile(str(guide))
        except OSError as exc:
            messagebox.showerror("Руководство", str(exc))

    def _on_setting_changed(self):
        if self.project_open and not self._loading_project:
            self.project_dirty = True
        self._sync_build_variant()
        self._update_navigation()

    def _sync_build_variant(self):
        if hasattr(self, "build_variant_var"):
            variant = f"{self.skinning_var.get()}_{self.draw_var.get()}"
            # A confirmed partial model set must stay visible in the checkpoint
            # name and report, including after a mode change or a rebuild.
            if self.project_extra.get("models") and (self.selected_aircraft or {}).get("needs_model_selection"):
                variant += "_partial"
            self.build_variant_var.set(variant)

    def _build_catalog_tab(self):
        tab = self.catalog_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        row = ttk.Frame(tab)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Корень каталога:").grid(row=0, column=0, sticky="w")
        ttk.Entry(row, textvariable=self.catalog_root_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(row, text="Обзор", command=self.choose_catalog).grid(row=0, column=2)
        ttk.Button(row, text="Сканировать", command=self.scan_custom).grid(row=0, column=3, padx=(6, 0))
        ttk.Checkbutton(row, text="Глубокая проверка glTF/BIN", variable=self.catalog_deep_var).grid(
            row=0, column=4, padx=(10, 0), sticky="w")
        list_header = ttk.Frame(tab)
        list_header.grid(row=1, column=0, sticky="ew", pady=(12, 4))
        list_header.columnconfigure(1, weight=1)
        ttk.Label(list_header, text="Найденные самолёты:").grid(row=0, column=0, sticky="w")
        ttk.Label(list_header, text="Фильтр:").grid(row=0, column=2, sticky="e", padx=(12, 6))
        filter_combo = ttk.Combobox(list_header, textvariable=self.aircraft_filter_var,
                                    values=AIRCRAFT_FILTERS, state="readonly", width=25)
        filter_combo.grid(row=0, column=3, sticky="e")
        filter_combo.bind("<<ComboboxSelected>>", lambda _event: self.populate_aircraft())
        self.aircraft_list = ttk.Treeview(tab, show="tree", selectmode="browse")
        self.aircraft_list.grid(row=2, column=0, sticky="nsew")
        self.aircraft_list.heading("#0", text="Самолёт / вариант")
        self.aircraft_list.column("#0", width=980, anchor="w")
        self.aircraft_list.bind("<<TreeviewSelect>>", self.on_aircraft_select)
        diagnose = ttk.Frame(tab)
        diagnose.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        diagnose.columnconfigure(0, weight=1)
        self.aircraft_reason = ttk.Label(diagnose, text="Выберите самолёт, чтобы увидеть диагностику пакета.",
                                         wraplength=900, justify="left")
        self.aircraft_reason.grid(row=0, column=0, sticky="ew")
        ttk.Button(diagnose, text="Проверить пакет подробно", command=self.diagnose_selected).grid(row=0, column=1, padx=(8, 0))
        self.package_root_recovery_button = ttk.Button(
            diagnose, text="Добавить каталог базы…", command=self.open_package_root_recovery)
        self.package_root_recovery_button.grid(row=0, column=2, padx=(8, 0))
        self.package_root_recovery_button.grid_remove()
        self.aircraft_detail = tk.Text(tab, height=8, wrap="word", state="disabled")
        self.aircraft_detail.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _build_setup_tab(self):
        tab = self.setup_tab
        tab.columnconfigure(1, weight=1)
        fields = [
            ("Самолёт", self.aircraft_var, "readonly"),
            ("Model-вариант", self.model_var, "readonly"),
            ("Ливрея", self.livery_var, "readonly"),
            ("Папка blend проекта", self.output_var, "readonly"),
            ("Blender", self.blender_var, "normal"),
        ]
        for row, (label, variable, state) in enumerate(fields):
            ttk.Label(tab, text=f"{label}:").grid(row=row, column=0, sticky="w", pady=4)
            if label == "Самолёт":
                widget = ttk.Entry(tab, textvariable=variable, state="readonly")
            elif label == "Model-вариант":
                widget = ttk.Combobox(tab, textvariable=variable, state=state)
                self.model_combo = widget
                widget.bind("<<ComboboxSelected>>", self.on_model_changed)
            elif label == "Ливрея":
                widget = ttk.Combobox(tab, textvariable=variable, state=state)
                self.livery_combo = widget
            else:
                widget = ttk.Entry(tab, textvariable=variable, state=state)
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            if label == "Blender":
                ttk.Button(tab, text="Обзор", command=self.choose_blender).grid(row=row, column=2, pady=4)
        models_box = ttk.LabelFrame(tab, text="Состав моделей", padding=8)
        models_box.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        models_box.columnconfigure(0, weight=1)
        self.models_summary = ttk.Label(models_box, text="", wraplength=840, justify="left")
        self.models_summary.grid(row=0, column=0, sticky="ew")
        ttk.Button(models_box, text="Выбрать модели...", command=self.choose_models).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(tab, text="Общие параметры проекта. Режимы сборки и состав объектов задаются на шаге 3.", foreground="#555").grid(row=7, column=0, columnspan=3, sticky="w", pady=(18, 0))
        ttk.Button(tab, text="Указать новое расположение исходного самолёта...", command=self.relocate_source).grid(row=8, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(tab, textvariable=self.source_var, wraplength=850, foreground="#555").grid(row=9, column=0, columnspan=3, sticky="w")
        self.update_model_summary_label()

    def _build_build_tab(self):
        tab = self.build_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        ttk.Label(tab, text="Этапы выполняются последовательно и сохраняются отдельными checkpoint-файлами.").grid(row=0, column=0, sticky="w")
        status_box = ttk.LabelFrame(tab, text="Состояние сборки", padding=12)
        status_box.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        status_box.columnconfigure(0, weight=1)
        ttk.Label(status_box, textvariable=self.build_stage_var, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(status_box, textvariable=self.build_detail_var, wraplength=900).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(status_box, textvariable=self.build_result_var, wraplength=900).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.build_progress = ttk.Progressbar(status_box, mode="indeterminate")
        self.build_progress.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        params = ttk.LabelFrame(tab, text="Параметры текущей сборки", padding=8)
        params.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        params.columnconfigure(1, weight=1)
        ttk.Label(params, text="Skinning:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.skinning_combo = ttk.Combobox(params, textvariable=self.skinning_var,
                                           values=("strip", "manual", "hybrid", "bake"), state="readonly", width=16)
        self.skinning_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(params, text="Draw mode:").grid(row=0, column=2, sticky="w", padx=(18, 8))
        self.draw_combo = ttk.Combobox(params, textvariable=self.draw_var,
                                       values=("auto", "msfs", "standard"), state="readonly", width=14)
        self.draw_combo.grid(row=0, column=3, sticky="w")
        ttk.Label(params, text="Имя варианта:").grid(row=0, column=4, sticky="w", padx=(18, 8))
        ttk.Label(params, textvariable=self.build_variant_var, foreground="#555").grid(row=0, column=5, sticky="w")
        ttk.Checkbutton(params, text="Удалять runtime/collision/occluder", variable=self.filter_runtime_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(params, text="Поза: ").grid(row=1, column=2, sticky="w", padx=(18, 4), pady=(8, 0))
        self.pose_combo = ttk.Combobox(params, textvariable=self.pose_position_var,
                                       values=("REST", "POSE"), state="readonly", width=10)
        self.pose_combo.grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(params, text="Восстанавливать skeleton roots", variable=self.repair_skin_roots_var).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(params, text="Draw mode влияет на draw ranges; поза и skeleton roots применяются в bake/hybrid.",
                  foreground="#555").grid(row=2, column=3, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(params, text="Параметры применяются только к следующей сборке; результаты сохраняются отдельными файлами.", foreground="#555").grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))

        object_box = ttk.LabelFrame(tab, text="Объекты и группы (снимите галочку, чтобы исключить из geometry)", padding=8)
        object_box.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        object_box.columnconfigure(0, weight=1)
        object_box.rowconfigure(0, weight=1)
        self.object_tree = ttk.Treeview(object_box, columns=("include",), show="tree headings", selectmode="browse")
        self.object_tree.heading("#0", text="Группа / объект")
        self.object_tree.heading("include", text="Включён")
        self.object_tree.column("#0", width=600, anchor="w")
        self.object_tree.column("include", width=90, anchor="center")
        self.object_tree.grid(row=0, column=0, sticky="nsew")
        object_scroll = ttk.Scrollbar(object_box, orient="vertical", command=self.object_tree.yview)
        object_scroll.grid(row=0, column=1, sticky="ns")
        self.object_tree.configure(yscrollcommand=object_scroll.set)
        self.object_tree.bind("<Button-1>", self.on_object_tree_click)
        object_buttons = ttk.Frame(object_box)
        object_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(object_buttons, text="Загрузить список объектов", command=self.load_object_catalog).pack(side="left", padx=(0, 8))
        ttk.Button(object_buttons, text="Включить всё", command=lambda: self.set_all_objects(True)).pack(side="left", padx=(0, 8))
        ttk.Button(object_buttons, text="Исключить всё", command=lambda: self.set_all_objects(False)).pack(side="left")
        ttk.Button(object_buttons, text="Hybrid: выбранная деталь", command=self.select_hybrid_target).pack(side="left", padx=8)
        self.hybrid_label = ttk.Label(object_box, text="Hybrid: детали не выбраны", foreground="#555")
        self.hybrid_label.grid(row=2, column=0, sticky="w", pady=(5, 0))
        rules_bar = ttk.Frame(object_box)
        rules_bar.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(rules_bar, text="Правила редактирования...", command=self.open_rule_editor).pack(side="left")
        self.rules_label = ttk.Label(rules_bar, text="", foreground="#555")
        self.rules_label.pack(side="left", padx=10)

        buttons = ttk.Frame(tab)
        buttons.grid(row=4, column=0, sticky="w", pady=12)
        ttk.Button(buttons, text="Собрать geometry", command=lambda: self.start_build("geometry")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Открыть checkpoint", command=self.open_checkpoint).pack(side="left", padx=8)
        ttk.Button(buttons, text="Проверить checkpoint", command=self.audit_geometry_checkpoint).pack(side="left", padx=8)
        ttk.Button(buttons, text="Открыть отчёт аудита", command=self.open_geometry_audit_report).pack(side="left", padx=8)
        self.geometry_explorer_button = ttk.Button(buttons, text="Перейти к .blend в проводнике", command=self.open_blend_in_explorer)
        ttk.Button(buttons, text="Остановить", command=self.stop_build).pack(side="left", padx=8)
        ttk.Label(tab, text="Повторная сборка того же режима создаёт новый пронумерованный checkpoint.", foreground="#555").grid(row=5, column=0, sticky="w", pady=(2, 0))

    def _build_texture_tab(self):
        tab = self.texture_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(4, weight=1)
        ttk.Label(tab, text="Текстуры и финальная упаковка работают с выбранной геометрией.").grid(row=0, column=0, sticky="w")
        status_box = ttk.LabelFrame(tab, text="Состояние сборки", padding=12)
        status_box.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        status_box.columnconfigure(0, weight=1)
        ttk.Label(status_box, textvariable=self.build_stage_var, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(status_box, textvariable=self.build_detail_var, wraplength=900).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(status_box, textvariable=self.build_result_var, wraplength=900).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.texture_progress = ttk.Progressbar(status_box, mode="indeterminate")
        self.texture_progress.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        texture_params = ttk.LabelFrame(tab, text="Параметры текстур", padding=8)
        texture_params.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        texture_params.columnconfigure(4, weight=1)
        ttk.Checkbutton(texture_params, text="Подключать все texture.* варианты", variable=self.all_liveries_var).grid(row=0, column=0, sticky="w")
        ttk.Label(texture_params, text="Нормали:").grid(row=0, column=1, sticky="w", padx=(18, 6))
        self.normal_decode_combo = ttk.Combobox(texture_params, textvariable=self.normal_decode_var,
                                                values=("auto", "dxt5n", "off"), state="readonly", width=10)
        self.normal_decode_combo.grid(row=0, column=2, sticky="w")
        ttk.Button(texture_params, text="Таблица карт...", command=self.open_texture_table).grid(row=0, column=3, sticky="w", padx=12)
        ttk.Label(texture_params, text="auto: BC5 автоматически, DXT5 отмечается для проверки; dxt5n декодирует DXT5.",
                  foreground="#555").grid(row=1, column=0, columnspan=5, sticky="w", pady=(5, 0))

        extra_frame = ttk.LabelFrame(tab, text="Дополнительные каталоги текстур", padding=8)
        extra_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        extra_frame.columnconfigure(0, weight=1)
        self.extra_text = tk.Text(extra_frame, height=3, wrap="none")
        self.extra_text.grid(row=0, column=0, sticky="ew")
        self.extra_text.bind("<<Modified>>", self.on_extra_text_modified)
        ttk.Label(extra_frame, text="По одному каталогу на строку; эти пути сохраняются в проекте.", foreground="#555").grid(row=1, column=0, sticky="w", pady=(5, 0))
        converted_row = ttk.Frame(extra_frame)
        converted_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        converted_row.columnconfigure(1, weight=1)
        ttk.Label(converted_row, text="PNG нормалей:").grid(row=0, column=0, sticky="w")
        ttk.Entry(converted_row, textvariable=self.converted_normal_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(converted_row, text="Выбрать каталог", command=self.choose_converted_normal_dir).grid(row=0, column=2)
        ttk.Label(extra_frame, text="Необязательно: каталог уже декодированных PNG с именами исходных NORM-карт.",
                  foreground="#555").grid(row=3, column=0, sticky="w", pady=(4, 0))

        variants = ttk.LabelFrame(tab, text="Собранные варианты для сравнения", padding=8)
        variants.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        variants.columnconfigure(0, weight=1)
        variants.rowconfigure(0, weight=1)
        self.blend_list = tk.Listbox(variants, height=5, exportselection=False)
        self.blend_list.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(variants, command=self.blend_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.blend_list.configure(yscrollcommand=scroll.set)
        self.blend_list.bind("<Double-Button-1>", lambda _event: self.open_selected_blend())
        variant_buttons = ttk.Frame(variants)
        variant_buttons.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(variant_buttons, text="Обновить список", command=self.refresh_blend_list).pack(side="left", padx=(0, 8))
        ttk.Button(variant_buttons, text="Открыть выбранный", command=self.open_selected_blend).pack(side="left", padx=(0, 8))
        ttk.Button(variant_buttons, text="Показать в проводнике", command=self.show_selected_blend).pack(side="left")

        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, sticky="w", pady=12)
        ttk.Button(buttons, text="Добавить textures", command=lambda: self.start_build("textures")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Собрать final", command=lambda: self.start_build("final")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Весь цикл", command=lambda: self.start_build("all")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Открыть checkpoint", command=self.open_checkpoint).pack(side="left", padx=8)
        self.explorer_button = ttk.Button(buttons, text="Перейти к .blend в проводнике", command=self.open_blend_in_explorer)
        ttk.Button(buttons, text="Остановить", command=self.stop_build).pack(side="left", padx=8)
        ttk.Label(tab, text="Подробный журнал находится во вкладке «Журнал».", foreground="#555").grid(row=6, column=0, sticky="w", pady=(2, 0))

    def _build_log_tab(self):
        self.log_text = tk.Text(self.log_tab, wrap="none", state="disabled")
        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(0, weight=1)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self.log_tab, command=self.log_text.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self.log_tab, orient="horizontal", command=self.log_text.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        ttk.Button(self.log_tab, text="Сохранить журнал...", command=self.export_log).grid(row=2, column=0, sticky="w", pady=8)

    def export_log(self):
        path = filedialog.asksaveasfilename(title="Сохранить журнал", defaultextension=".log", filetypes=(("Журнал", "*.log"),))
        if path:
            try:
                Path(path).write_text(self.log_text.get("1.0", "end"), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Журнал", str(exc))

    def on_extra_text_modified(self, _event=None):
        if self.extra_text.edit_modified():
            if self.project_open and not self._loading_project:
                self.project_dirty = True
            self.extra_text.edit_modified(False)

    def on_model_changed(self, _event=None):
        self.project_extra.pop("models", None)
        self.object_include.clear()
        self.object_details.clear()
        self.object_tree.delete(*self.object_tree.get_children())
        self.update_model_summary_label()
        self.project_dirty = True

    @staticmethod
    def object_group_for(name, role):
        upper = name.upper()
        if role == "interior":
            if any(token in upper for token in ("GAUGE", "INSTRUMENT", "DIAL_", "ALTIMETER", "AIRSPEED", "RPM_", "VSI_", "COMPASS")):
                return "Интерьер / Приборы"
            if any(token in upper for token in ("PANEL", "DASH", "CONSOLE", "RADIO", "GTN", "COM_", "NAV_", "GPS")):
                return "Интерьер / Панель и радио"
            if any(token in upper for token in ("SEAT", "CUSHION", "BELT", "HARNESS")):
                return "Интерьер / Сиденья"
            if any(token in upper for token in ("YOKE", "PEDAL", "THROTTLE", "MIXTURE", "CONTROL", "SWITCH", "LEVER", "TRIM", "CABLE")):
                return "Интерьер / Управление"
            return "Интерьер / Детали"
        if any(token in upper for token in ("DOOR", "DOOR_")):
            return "Экстерьер / Двери"
        if any(token in upper for token in ("ELEVATOR", "RUDDER", "AILERON", "FLAP", "SLAT", "STABILIZER", "TAILPLANE", "TRIM_TAB", "TRIMTAB")):
            return "Экстерьер / Рули и механизация"
        if any(token in upper for token in ("WING", "WINGTIP")):
            return "Экстерьер / Крылья"
        if any(token in upper for token in ("GEAR", "WHEEL", "TIRE", "BRAKE", "STRUT", "SKID")):
            return "Экстерьер / Шасси"
        if any(token in upper for token in ("PROP", "ENGINE", "EXHAUST", "CYLINDER", "OIL_", "CARB", "MANIFOLD")):
            return "Экстерьер / Двигатель и винт"
        if any(token in upper for token in ("LIGHT", "BEACON", "NAV_", "LANDING")):
            return "Экстерьер / Свет"
        if any(token in upper for token in ("GLASS", "WINDOW", "WINDSHIELD", "CANOPY", "FUSE", "BODY", "NOSE", "TAILCONE")):
            return "Экстерьер / Фюзеляж и остекление"
        return "Экстерьер / Прочие детали"

    def load_object_catalog(self, silent=False):
        if self.busy or not self.project_open:
            return
        self.object_details.clear()
        blend = self.latest_geometry_file()
        if blend is not None:
            report = blend.with_suffix(".json")
            try:
                data = json.loads(report.read_text(encoding="utf-8-sig"))
                if data.get("object_catalog"):
                    self._populate_catalog(data["object_catalog"])
                    return
            except (OSError, ValueError):
                pass
            self.scan_blend_objects(blend, silent=silent)
            return
        try:
            config = self.make_config()
        except ValueError as exc:
            if not silent:
                messagebox.showwarning("Неполная настройка", str(exc))
            return
        groups = {}
        seen = set()
        try:
            models = list(config.get("models", []))
            if not models and self.selected_aircraft:
                for variant in self.selected_aircraft.get("variants", []):
                    if variant.get("folder") != self.model_var.get():
                        continue
                    suggested = variant.get("model_cfg_selection")
                    if isinstance(suggested, list):
                        models = suggested
                    elif isinstance(suggested, dict):
                        models = [{"path": path, "role": role} for role, path in suggested.items() if path]
                    break
            for model in models:
                path = Path(model["path"])
                document = json.loads(path.read_text(encoding="utf-8-sig"))
                role = model.get("role", "exterior")
                for index, node in enumerate(document.get("nodes", [])):
                    name = str(node.get("name") or f"Node_{index}")
                    # Blender disambiguates duplicate names; retain one logical
                    # exclusion key and show the source role in the tree.
                    key = name
                    if key in seen:
                        continue
                    seen.add(key)
                    groups.setdefault(self.object_group_for(name, role), []).append(name)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            if not silent:
                messagebox.showerror("Список объектов", f"Не удалось прочитать glTF:\n{exc}")
            return

        self.populate_object_groups(groups, silent=silent)

    def _populate_catalog(self, items):
        groups = {}
        for item in items:
            name = item.get("name")
            if not name:
                continue
            # The report gives group_path/source_node, the objects command gives
            # world bounds: keep both so the rule editors can show either.
            self.object_details.setdefault(name, {}).update(item)
            role = "interior" if any("INTERIOR" in str(value).upper() or "COCKPIT" in str(value).upper()
                                     for value in [*item.get("collections", []), *item.get("group_path", [])]) else "exterior"
            group = "Служебные узлы" if item.get("type") == "EMPTY" else self.object_group_for(name, role)
            groups.setdefault(group, []).append(name)
        self.populate_object_groups(groups)

    def select_hybrid_target(self):
        selection = self.object_tree.selection()
        if not selection:
            return
        item = selection[0]
        names = self.object_group_items.get(item, []) or [getattr(self, "object_tree_items", {}).get(item)]
        names = [name for name in names if name]
        current = set(self.project_extra.get("hybrid_bake_objects", []))
        for name in names:
            pattern = literal_pattern(name)
            if pattern in current:
                current.remove(pattern)
            else:
                current.add(pattern)
        self.project_extra["hybrid_bake_objects"] = sorted(current)
        self.hybrid_label.configure(text=f"Hybrid: выбрано деталей {len(current)}")
        self.project_dirty = True

    def open_rule_editor(self):
        if self.busy or not self.project_open:
            return
        editor = RuleEditor(self, cli_command)
        editor.bind("<Destroy>", lambda event: self.update_rules_label() if event.widget is editor else None)
        self.update_rules_label()

    def update_rules_label(self):
        if not hasattr(self, "rules_label"):
            return
        counts = {key: len(self.project_extra.get(key) or []) for key, _title in RULE_TYPES}
        total = sum(counts.values())
        if not total:
            self.rules_label.configure(text="Правила не заданы: объект собирается как есть.")
            return
        self.rules_label.configure(text="Правил: " + str(total) + " — " + ", ".join(
            f"{title.lower()}: {counts[key]}" for key, title in RULE_TYPES if counts[key]))

    def latest_geometry_file(self):
        output = Path(self.output_var.get().strip())
        if not output.is_dir():
            return None
        candidates = list(output.glob("01_geometry*.blend"))
        return max(candidates, key=checkpoint_order) if candidates else None

    def latest_texture_report(self):
        output = Path(self.output_var.get().strip())
        if not output.is_dir():
            return None
        candidates = sorted([*output.glob("03_model*.json"), *output.glob("02_textured*.json")],
                            key=checkpoint_order, reverse=True)
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            # The final checkpoint reports geometry only: the maps of that build
            # live in its textured report, so a newer 03_model must not hide them.
            if isinstance(data, dict) and ("resolved_textures" in data or "missing_textures" in data):
                return path
        return None

    def open_texture_table(self):
        if self.busy or not self.project_open:
            return
        command_factory = lambda *parts: self.append_package_roots(cli_command(*parts), self.package_roots())
        TextureTable(self, command_factory)

    def scan_blend_objects(self, blend, silent=False):
        blender = self.blender_var.get().strip()
        if not blender or not Path(blender).is_file():
            if not silent:
                messagebox.showwarning("Blender не найден", "Укажите путь к blender.exe, чтобы прочитать список объектов из geometry checkpoint.")
            return
        self.run_command(cli_command("objects", str(blend), "--blender", blender),
                         self.on_object_inventory_result)

    def on_object_inventory_result(self, code, output):
        if code != 0:
            self.append_log("Не удалось получить список объектов из geometry checkpoint.")
            return
        try:
            data = json.loads(output)
            self._populate_catalog(data.get("objects", []))
            self.status_var.set(f"Загружено объектов из geometry: {len(self.object_include)}")
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            self.append_log(f"Не удалось разобрать список объектов: {exc}")

    def populate_object_groups(self, groups, silent=False):
        previous = dict(self.object_include)
        self.object_tree.delete(*self.object_tree.get_children())
        self.object_include.clear()
        self.object_group_items.clear()
        self.object_tree_items = {}
        for group in sorted(groups):
            group_id = self.object_tree.insert("", "end", text=group, values=("☑",), open=True)
            self.object_group_items[group_id] = []
            for name in sorted(groups[group], key=str.casefold):
                included = previous.get(name, not any(fnmatch.fnmatchcase(name.casefold(), pattern.casefold()) for pattern in self.exclude_patterns))
                self.object_include[name] = included
                item_id = self.object_tree.insert(group_id, "end", text=name, values=("☑" if included else "☐",))
                self.object_tree_items[item_id] = name
                self.object_group_items[group_id].append(name)
            self._update_group_check(group_id)
        if not silent:
            self.status_var.set(f"Загружено объектов: {len(self.object_include)}")

    def _update_group_check(self, group_id):
        names = self.object_group_items.get(group_id, [])
        included = all(self.object_include.get(name, True) for name in names)
        self.object_tree.set(group_id, "include", "☑" if included else "☐")

    def on_object_tree_click(self, event):
        if self.busy:
            return "break"
        if self.object_tree.identify_column(event.x) != "#1":
            return
        item_id = self.object_tree.identify_row(event.y)
        if not item_id:
            return
        if item_id in self.object_group_items:
            names = self.object_group_items[item_id]
            target = not all(self.object_include.get(name, True) for name in names)
            for name in names:
                self.object_include[name] = target
            for child in self.object_tree.get_children(item_id):
                self.object_tree.set(child, "include", "☑" if target else "☐")
            self.object_tree.set(item_id, "include", "☑" if target else "☐")
        else:
            name = getattr(self, "object_tree_items", {}).get(item_id)
            if not name:
                return
            self.object_include[name] = not self.object_include.get(name, True)
            self.object_tree.set(item_id, "include", "☑" if self.object_include[name] else "☐")
            parent = self.object_tree.parent(item_id)
            if parent:
                self._update_group_check(parent)
        self.project_dirty = True

    def set_all_objects(self, included):
        if self.busy:
            return
        if included:
            self.exclude_patterns = []
        for name in self.object_include:
            self.object_include[name] = included
        for item_id in self.object_tree.get_children(""):
            self.object_tree.set(item_id, "include", "☑" if included else "☐")
            for child in self.object_tree.get_children(item_id):
                self.object_tree.set(child, "include", "☑" if included else "☐")
        self.project_dirty = True

    def append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start_progress(self):
        self.build_progress.start(12)
        self.texture_progress.start(12)

    def stop_progress(self):
        self.build_progress.stop()
        self.texture_progress.stop()

    def choose_catalog(self):
        if self.busy or self.project_open:
            return
        self._show_catalog_step()
        path = self.directory_dialog("Выберите каталог MSFS или каталог с самолётами", self.catalog_root_var.get())
        if path:
            self.catalog_root_var.set(path)
            self._remember_package_root(path)
            self.scan_custom()

    def choose_output(self):
        if not self.project_open:
            messagebox.showinfo("Нет проекта", "Сначала создайте или откройте проект через меню «Файлы».")
            return
        path = self.directory_dialog("Папка для рабочих данных и результата", self.output_var.get())
        if path:
            self.output_var.set(path)

    def choose_blender(self):
        path = filedialog.askopenfilename(title="Выберите blender.exe", filetypes=(("Blender", "blender.exe"), ("Все файлы", "*.*")))
        if path:
            self.blender_var.set(path)
            self._save_user_settings()

    def choose_converted_normal_dir(self):
        if not self.project_open or self.busy:
            return
        path = self.directory_dialog("Каталог PNG нормалей", self.converted_normal_var.get() or self.output_var.get())
        if path:
            self.converted_normal_var.set(path)

    def scan_installed(self):
        if self.busy or self.project_open:
            return
        self._show_catalog_step()
        command = cli_command("catalog")
        self.append_package_roots(command, self.package_roots())
        if self.catalog_deep_var.get():
            command.append("--deep")
        self.run_command(command, self.on_catalog_result)

    def audit_geometry_plans(self):
        """Run a package-wide geometry preflight; no Blender process is started."""
        if self.busy:
            return
        command = self.append_package_roots(cli_command("audit-plans"), self.package_roots())
        if self.run_command(command, self.on_geometry_plan_audit_result):
            self.status_var.set("Проверка build-plan для доступных самолётов: анализ glTF и ресурсов…")

    def on_geometry_plan_audit_result(self, code, output):
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            detail = output[-1200:] if output else "Ответ команды пуст."
            self.append_log("Не удалось прочитать результат проверки планов: " + detail)
            self.status_var.set("Ошибка проверки планов геометрии")
            messagebox.showerror("Проверка планов", "Не удалось прочитать результат. Подробности во вкладке «Журнал».")
            return
        if not isinstance(data, dict):
            self.append_log("Ответ проверки планов имеет неверную структуру JSON.")
            self.status_var.set("Не удалось обработать ответ: неверная структура JSON")
            messagebox.showerror("Проверка планов", "Ответ имеет неверную структуру. Подробности во вкладке «Журнал».")
            return
        validated = int(data.get("plans_validated") or 0)
        buildable = int(data.get("geometry_buildable") or 0)
        failure_values = data.get("failures") if isinstance(data.get("failures"), list) else []
        failures = [item for item in failure_values if isinstance(item, dict)]
        missing_roots = data.get("missing_roots") if isinstance(data.get("missing_roots"), list) else []
        if code == 0 and not failures and not missing_roots:
            summary = (f"Планы геометрии проверены: {validated}/{buildable}. "
                       "Blender не запускался, файлы не создавались.")
            self.status_var.set(summary)
            self.append_log(summary)
            messagebox.showinfo("Проверка планов геометрии", summary)
            return
        examples = [f"• {item.get('aircraft', '?')}: {item.get('problem', 'ошибка')}" for item in failures[:8]]
        examples.extend(f"• Каталог не найден: {path}" for path in missing_roots[:4])
        more = f"\n…и ещё {len(failures) - 8}" if len(failures) > 8 else ""
        if len(missing_roots) > 4:
            more += f"\n…и ещё отсутствующих каталогов: {len(missing_roots) - 4}"
        summary = (f"Прошли: {validated}/{buildable}; отклонено планов: {len(failures)}; "
                   f"не найдено корней: {len(missing_roots)}.")
        detail = "\n".join(examples) + more
        if failures and missing_roots:
            status = "Есть отклонённые планы и отсутствующие корни; подробности в журнале."
        elif missing_roots:
            status = "Не все каталоги проверены; исправьте отсутствующие корни."
        else:
            status = "Есть отклонённые планы геометрии; подробности в журнале."
        self.status_var.set(status)
        self.append_log(summary + ("\n" + detail if detail else ""))
        advice = ("Проверьте пути в окне «Каталоги Packages…» и повторите проверку."
                  if missing_roots else
                  "Откройте диагностику соответствующего пакета через каталог самолётов.")
        messagebox.showwarning(
            "Проверка планов геометрии",
            summary + ("\n\n" + detail if detail else "")
            + "\n\n" + advice,
        )
        if missing_roots:
            if messagebox.askyesno("Исправить корни Packages?", "Открыть окно каталогов, чтобы убрать или заменить отсутствующий путь?"):
                self.manage_package_roots()
        elif failures and messagebox.askyesno(
                "Открыть диагностику самолёта?",
                f"Перейти к первому отклонённому самолёту: {failures[0].get('aircraft', '?')}?"):
            self.focus_audited_aircraft(failures[0])

    def focus_audited_aircraft(self, failure):
        """Select an audit failure in the catalog and open its package details."""
        if self.project_open:
            messagebox.showinfo("Проект открыт", "Сначала закройте текущий проект, чтобы перейти к другому самолёту.")
            return
        self._show_catalog_step()
        self.aircraft_filter_var.set(AIRCRAFT_FILTERS[0])
        self.populate_aircraft()
        source_path = str(failure.get("path") or "")
        item_id = self._aircraft_tree_paths.get(source_path) if source_path else None
        if item_id is None:
            name = str(failure.get("aircraft") or "").casefold()
            matches = [candidate_id for candidate_id, entry in self._aircraft_tree_entries.items()
                       if str(entry.get("aircraft", "")).casefold() == name]
            item_id = matches[0] if len(matches) == 1 else None
        if item_id:
            self._select_catalog_entry(item_id)
            return

        command = self.append_package_roots(cli_command("catalog"), self.package_roots())

        def scanned(code, output):
            self.on_catalog_result(code, output)
            if code == 0:
                fresh_id = self._aircraft_tree_paths.get(source_path) if source_path else None
                if fresh_id:
                    self._select_catalog_entry(fresh_id)
                    return
            messagebox.showinfo("Самолёт не найден", "Обновите корни Packages и повторите проверку планов.")

        self.run_command(command, scanned)

    def _select_catalog_entry(self, item_id):
        group_id = self.aircraft_list.parent(item_id)
        if group_id:
            self.aircraft_list.item(group_id, open=True)
        self.aircraft_list.selection_set(item_id)
        self.aircraft_list.focus(item_id)
        self.aircraft_list.see(item_id)
        self.on_aircraft_select()
        self.diagnose_selected()

    def scan_custom(self):
        if self.busy or self.project_open:
            return
        root = self.catalog_root_var.get().strip()
        if not root:
            messagebox.showwarning("Нет каталога", "Сначала выберите каталог MSFS или каталог самолёта.")
            return
        # A chosen Packages/Community root may contain many packages. All saved
        # roots are scanned together so cross-package links can resolve.
        self._remember_package_root(root)
        command = self.append_package_roots(cli_command("catalog"), self.package_roots())
        if self.catalog_deep_var.get():
            command.append("--deep")
        self.run_command(command, self.on_catalog_result)

    def run_command(self, command, callback=None):
        if self.busy:
            messagebox.showinfo("Занято", "Дождитесь завершения текущей операции или остановите её.")
            return False
        self.busy = True
        self.cancel_requested = False
        self._set_busy_widgets(True)
        self.append_log("$ " + " ".join(f'\"{part}\"' if " " in part else part for part in command))
        self.status_var.set("Выполняется...")
        machine_readable = any(part in {"catalog", "inventory", "objects", "index", "roots", "models", "validate", "bones", "audit-plans", "audit",
                                        "find-textures"} for part in command)

        def worker():
            process = None
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.process = process
                if self.cancel_requested:
                    self._kill_process_tree(process)
                # stderr stays separate so JSON responses remain parseable.
                errors = []
                def stderr_reader():
                    for line in process.stderr:
                        errors.append(line.rstrip())
                        self.events.put(("line", line.rstrip()))
                stderr_thread = threading.Thread(target=stderr_reader, daemon=True)
                stderr_thread.start()
                output = []
                assert process.stdout is not None
                for line in process.stdout:
                    output.append(line.rstrip())
                    if not machine_readable:
                        self.events.put(("line", line.rstrip()))
                code = process.wait()
                stderr_thread.join()
                if code:
                    output.extend(errors)
                self.events.put(("done", (code, "\n".join(output), callback)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                if process is not None:
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _set_busy_widgets(self, busy):
        if busy:
            self._disabled_widgets = []
            def disable(parent):
                for widget in parent.winfo_children():
                    if isinstance(widget, (ttk.Button, ttk.Combobox, ttk.Entry, ttk.Checkbutton, tk.Text, tk.Listbox)):
                        if isinstance(widget, ttk.Button) and widget.cget("text") == "Остановить":
                            continue
                        self._disabled_widgets.append((widget, widget.cget("state")))
                        widget.configure(state="disabled")
                    disable(widget)
            for tab in (self.catalog_tab, self.setup_tab, self.build_tab, self.texture_tab):
                disable(tab)
        else:
            for widget, state in self._disabled_widgets:
                if widget.winfo_exists():
                    widget.configure(state=state)
            self._disabled_widgets = []

    def _drain_events(self):
        self._drain_after_id = None
        try:
            while True:
                try:
                    kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "line":
                    self.append_log(str(value))
                    self._update_build_activity(str(value))
                elif kind == "done":
                    code, output, callback = value
                    self.process = None
                    self.busy = False
                    self._set_busy_widgets(False)
                    if self.active_stage:
                        self.stop_progress()
                    self.status_var.set("Готово" if code == 0 else f"Ошибка, код {code}")
                    if callback:
                        callback(code, output)
                else:
                    self.process = None
                    self.busy = False
                    self._set_busy_widgets(False)
                    self.stop_progress()
                    self.status_var.set("Ошибка")
                    self.append_log("ERROR: " + str(value))
                    if self.active_stage:
                        self.build_stage_var.set(f"Этап {self.active_stage}: ошибка")
                        self.build_result_var.set("Сборка остановлена. Тип ошибки: запуск процесса.")
                        self.build_detail_var.set("Проверьте Python, Blender и доступ к файлам во вкладке «Журнал».")
                        self.active_stage = None
                    messagebox.showerror("Ошибка", str(value))
        finally:
            if self.winfo_exists():
                self._schedule_drain()

    def on_catalog_result(self, code, output):
        if code != 0:
            return
        try:
            data = json.loads(output)
            self.catalog_entries = data.get("aircraft", [])
            self.suppressed_history_stub_count = len(data.get("suppressed_history_stubs", []))
            self.active_entries = self.catalog_entries
            self.populate_aircraft(self.active_entries)
            if self.suppressed_history_stub_count:
                self.append_log(f"Скрыты пустые записи fs-base-history: {self.suppressed_history_stub_count}; "
                                "рабочий одноимённый пакет оставлен в списке.")
            self.report_index(data.get("index"))
        except json.JSONDecodeError:
            self.append_log("Не удалось разобрать JSON catalog. Проверьте журнал.")

    def report_index(self, stats):
        if not stats:
            return
        self.append_log(f"Индекс пакетов: {stats.get('packages', 0)} пакетов, "
                        f"{stats.get('aircraft_names', 0)} имён самолётов; "
                        f"из кэша {stats.get('cached', 0)}, просканировано {stats.get('scanned', 0)}.")
        for error in stats.get("errors", []):
            self.append_log(f"Индекс: каталог недоступен — {error.get('path')}: {error.get('detail')}")

    def show_package_index(self):
        if self.busy:
            return
        window = getattr(self, "index_window", None)
        if window is None or not window.winfo_exists():
            self._build_index_window()
        self.index_window.deiconify()
        self.index_window.lift()
        self._run_index(False)

    def _build_index_window(self):
        window = tk.Toplevel(self)
        window.title("Индекс установленных пакетов")
        window.geometry("940x620")
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        bar = ttk.Frame(window, padding=8)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(bar, text="Имя самолёта (точно):").pack(side="left")
        self.index_filter_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.index_filter_var, width=42)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _event: self._run_index(False))
        ttk.Button(bar, text="Показать", command=lambda: self._run_index(False)).pack(side="left")
        ttk.Button(bar, text="Перестроить индекс", command=lambda: self._run_index(True)).pack(side="left", padx=6)
        text = tk.Text(window, wrap="word", state="disabled")
        text.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        scroll = ttk.Scrollbar(window, command=text.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        text.configure(yscrollcommand=scroll.set)
        self.index_window = window
        self.index_text = text

    def _run_index(self, rebuild):
        if self.busy:
            return
        command = cli_command("index")
        self.append_package_roots(command, self.package_roots())
        name = self.index_filter_var.get().strip()
        if name:
            command += ["--aircraft", name]
        if rebuild:
            command += ["--no-cache"]

        def indexed(code, output):
            if code:
                messagebox.showerror("Индекс пакетов", output[-1500:], parent=self.index_window)
                return
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                messagebox.showerror("Индекс пакетов", "Не удалось разобрать ответ index.", parent=self.index_window)
                return
            self._set_text(self.index_text, self.format_index(data))
            self.append_log(f"Индекс пакетов: {data.get('packages', 0)} пакетов, "
                            f"из кэша {data.get('cached', 0)}, просканировано {data.get('scanned', 0)}.")

        self.run_command(command, indexed)

    @staticmethod
    def format_index(data):
        lines = [f"Пакетов: {data.get('packages', 0)}. Имён самолётов: {data.get('aircraft_names', 0)}.",
                 f"Из кэша: {data.get('cached', 0)}. Просканировано заново: {data.get('scanned', 0)}.",
                 f"Файл кэша: {data.get('cache_path', '')}",
                 "Каталоги поиска:"]
        lines.extend(f"  • {root}" for root in data.get("searched_roots", []))
        for error in data.get("errors", []):
            lines.append(f"  ⚠ {error.get('path')}: {error.get('detail')}")
        aircraft = data.get("aircraft", {})
        if not aircraft:
            lines.extend(["", "Самолёты не найдены. Проверьте каталог поиска или имя в фильтре."])
        for name, entries in aircraft.items():
            lines.extend(["", f"[{name}]"])
            for item in entries:
                lines.append(f"  • {item.get('path')}")
                base = item.get("base_container")
                if not base:
                    continue
                state = {True: "установлена", False: "НЕ установлена", None: "проверка недоступна"}[item.get("base_installed")]
                lines.append(f"      база: {base} — {state}")
        return "\n".join(lines)

    MODEL_ROLE_TITLES = {"exterior": "Экстерьер", "interior": "Интерьер"}
    MODEL_ORIGIN_TITLES = {"model.cfg": "объявлен в model.cfg", "xml": "объявлен в model XML",
                           "scan": "найден в папке", "aircraft_index": "из пакета базового самолёта",
                           "base_package": "из пакета базового самолёта", "base_container": "базовый самолёт",
                           "ambiguous": "несколько пакетов-кандидатов"}

    def choose_models(self):
        if self.busy:
            return
        entry = self.selected_aircraft
        path = entry.get("path") if entry else None
        if not path:
            messagebox.showinfo("Состав моделей", "Сначала выберите самолёт в списке.")
            return
        self._build_model_window()
        command = cli_command("models", path)
        self.append_package_roots(command, self.package_roots())

        def loaded(code, output):
            if not self.model_window.winfo_exists():
                return
            if code:
                messagebox.showerror("Состав моделей", output[-1500:], parent=self.model_window)
                self.model_window.destroy()
                return
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                messagebox.showerror("Состав моделей", "Не удалось разобрать ответ models.", parent=self.model_window)
                self.model_window.destroy()
                return
            self.populate_model_choices(data)

        self.run_command(command, loaded)

    def _build_model_window(self):
        previous = getattr(self, "model_window", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        window = tk.Toplevel(self)
        window.title("Состав моделей самолёта")
        window.geometry("1080x720")
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        window.rowconfigure(3, weight=1)
        self.model_window = window
        self.model_headline = ttk.Label(window, text="Читаю пакет...", wraplength=1020, justify="left")
        self.model_headline.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ttk.Label(window, text="Отметьте файлы галочкой. Роль «по имени файла» — подсказка, а не проверенный факт: "
                              "подтвердите её сами. LOD00 — ближайший и самый подробный уровень.",
                  wraplength=1020, justify="left", foreground="#555").grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.model_trees = {}
        self.model_tree_roles = {}
        self.model_items = {}
        self.model_selected = {}
        for row, role in enumerate(("exterior", "interior"), start=2):
            box = ttk.LabelFrame(window, text=self.MODEL_ROLE_TITLES[role], padding=6)
            box.grid(row=row, column=0, sticky="nsew", padx=10, pady=4)
            box.columnconfigure(0, weight=1)
            box.rowconfigure(0, weight=1)
            columns = ("include", "lod", "vertices", "triangles", "role_source", "origin", "status")
            tree = ttk.Treeview(box, columns=columns, show="tree headings", selectmode="browse", height=6)
            tree.heading("#0", text="Файл")
            tree.column("#0", width=260, stretch=True)
            titles = {"include": "Взять", "lod": "LOD", "vertices": "Вершин", "triangles": "Треугольников",
                      "role_source": "Роль по", "origin": "Источник", "status": "Состояние"}
            widths = {"include": 50, "lod": 50, "vertices": 90, "triangles": 110,
                      "role_source": 100, "origin": 210, "status": 150}
            for name in columns:
                tree.heading(name, text=titles[name])
                tree.column(name, width=widths[name], stretch=name in {"origin", "status"},
                            anchor="w" if name in {"role_source", "origin", "status"} else "e")
            tree.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(box, command=tree.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=scroll.set)
            tree.bind("<Button-1>", self.on_model_tree_click)
            tree.bind("<<TreeviewSelect>>", self.on_model_row_selected)
            self.model_trees[role] = tree
            # Item ids restart at I001 in every Treeview, so a row is identified
            # by its role as well as by its id.
            self.model_tree_roles[tree] = role
        self.model_detail = tk.Text(window, height=4, wrap="word", state="disabled")
        self.model_detail.grid(row=4, column=0, sticky="ew", padx=10, pady=4)
        bar = ttk.Frame(window, padding=(10, 4))
        bar.grid(row=5, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.model_summary = ttk.Label(bar, text="", wraplength=760, justify="left")
        self.model_summary.grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Отмена", command=window.destroy).grid(row=0, column=1, padx=6)
        self.model_confirm = ttk.Button(bar, text="Подтвердить состав", command=self.confirm_model_choices)
        self.model_confirm.grid(row=0, column=2)

    def populate_model_choices(self, data):
        self.model_data = data
        self.model_items.clear()
        self.model_selected.clear()
        saved = {os.path.normcase(item.get("path", "")): item.get("role")
                 for item in self.project_extra.get("models", []) if isinstance(item, dict)}
        headline = [f"{data.get('aircraft', '')}: {data.get('reason', '')} [{data.get('reason_code', '')}].",
                    data.get("action", "")]
        base = data.get("base_aircraft")
        if base:
            headline.append(f"Базовый самолёт: {base.get('name')} — "
                            f"{'просканирован, его модели предложены ниже' if base.get('scanned') else 'установлен'}.")
        for gap in data.get("source_gaps", []):
            if gap.get("problem_code") == "declared_model_file_missing":
                role = {"exterior": "экстерьера", "interior": "интерьера"}.get(
                    gap.get("role"), gap.get("role", "модели"))
                headline.append(f"В пакете отсутствует объявленный model-файл {role}: {Path(gap.get('path') or '').name}. "
                                "Если подходящая модель базы есть ниже, отметьте её вручную; программа сохранит выбор в проект.")
            elif gap.get("problem_code") == "base_aircraft_missing":
                role = {"exterior": "экстерьера", "interior": "интерьера"}.get(
                    gap.get("role"), gap.get("role", "модели"))
                headline.append(f"Для роли {role} отсутствует базовый самолёт. Установите базовый пакет или выберите другой источник.")
        self.model_headline.configure(text="\n".join(line for line in headline if line))
        for role, tree in self.model_trees.items():
            tree.delete(*tree.get_children())
            entries = data.get("roles", {}).get(role, [])
            if not entries:
                tree.insert("", "end", text="Кандидатов нет", values=("—", "", "", "", "", "", "нет файлов"))
                continue
            for entry in entries:
                key = os.path.normcase(entry["path"])
                # A role guessed from a filename is a hint: pre-checking it would
                # decide the interior for the user. Only declared roles start checked.
                suggested = bool(entry.get("default")) and entry.get("role_source") == "model.cfg"
                selected = (saved.get(key) == role if saved else suggested) and entry["available"]
                lod = "—" if entry.get("lod") is None else f"{entry['lod']:02d}"
                item_id = tree.insert("", "end", text=entry["name"], values=(
                    "☑" if selected else "☐", lod,
                    "—" if entry.get("vertices") is None else f"{entry['vertices']:,}".replace(",", " "),
                    "—" if entry.get("triangles") is None else f"{entry['triangles']:,}".replace(",", " "),
                    entry.get("role_source", ""), self.MODEL_ORIGIN_TITLES.get(entry.get("origin"), entry.get("origin", "")),
                    self.model_status_text(entry)))
                self.model_items[(role, item_id)] = entry
                self.model_selected[(role, item_id)] = selected
                if not entry["available"]:
                    tree.item(item_id, tags=("unavailable",))
            tree.tag_configure("unavailable", foreground="#a00")
        self.update_model_summary()

    @staticmethod
    def model_status_text(entry):
        if entry.get("read_error"):
            return "не читается"
        if entry.get("missing_buffers"):
            return f"нет BIN ({len(entry['missing_buffers'])})"
        if entry.get("unsupported"):
            return "не поддержано: " + ", ".join(entry["unsupported"])
        return "готов" if entry.get("available") else "файл отсутствует"

    def on_model_tree_click(self, event):
        if self.busy:
            return "break"
        tree = event.widget
        if tree.identify_column(event.x) != "#1":
            return
        item_id = tree.identify_row(event.y)
        key = (self.model_tree_roles[tree], item_id)
        if not item_id or key not in self.model_items:
            return
        if not self.model_items[key]["available"]:
            return "break"
        self.model_selected[key] = not self.model_selected.get(key, False)
        tree.set(item_id, "include", "☑" if self.model_selected[key] else "☐")
        self.update_model_summary()

    def on_model_row_selected(self, event):
        tree = event.widget
        selection = tree.selection()
        entry = self.model_items.get((self.model_tree_roles[tree], selection[0])) if selection else None
        if entry is None:
            self._set_text(self.model_detail, "")
            return
        lines = [entry["path"],
                 f"Роль: {self.MODEL_ROLE_TITLES.get(entry['role'], entry['role'])} "
                 f"(определена по: {entry.get('role_source', 'неизвестно')}). "
                 f"Model-вариант: {entry.get('variant') or '—'}."]
        substitute = next((gap for gap in self.model_data.get("source_gaps", [])
                           if gap.get("role") == entry.get("role")
                           and gap.get("problem_code") == "declared_model_file_missing"), None)
        if substitute:
            expected = Path(substitute.get("path") or "").name
            lines.append(f"Кандидат заменяет отсутствующую ссылку {expected} для этой роли. "
                         "Проверьте, что его геометрия подходит.")
        if entry.get("missing_buffers"):
            lines.append("Отсутствуют буферы: " + "; ".join(entry["missing_buffers"]))
        if entry.get("unsupported"):
            lines.append("Неподдерживаемые возможности: " + ", ".join(entry["unsupported"]))
        if entry.get("read_error"):
            lines.append("Ошибка чтения: " + entry["read_error"])
        self._set_text(self.model_detail, "\n".join(lines))

    def chosen_models(self):
        return [entry for key, entry in self.model_items.items() if self.model_selected.get(key)]

    def update_model_summary(self):
        chosen = self.chosen_models()
        counts = {role: sum(1 for entry in chosen if entry["role"] == role) for role in self.MODEL_ROLE_TITLES}
        parts = [f"{self.MODEL_ROLE_TITLES[role].lower()}: {counts[role]}" for role in counts]
        missing = [self.MODEL_ROLE_TITLES[role].lower() for role, count in counts.items()
                   if not count and self.model_trees[role].get_children()]
        text = "Выбрано — " + ", ".join(parts) + "."
        if missing:
            text += " Не выбрано: " + ", ".join(missing) + ". Эти части собраны не будут."
        guessed = [entry["name"] for entry in chosen if entry.get("role_source") == "имя файла"]
        if guessed:
            text += " Роль по имени файла подтверждаете вы: " + ", ".join(guessed) + "."
        self.model_summary.configure(text=text)
        self.model_confirm.configure(state="normal" if chosen else "disabled")

    def confirm_model_choices(self):
        if self.busy:
            return
        chosen = self.chosen_models()
        if not chosen:
            messagebox.showwarning("Состав моделей", "Отметьте хотя бы один файл.", parent=self.model_window)
            return
        roles = {entry["role"] for entry in chosen}
        if "exterior" not in roles and not messagebox.askyesno(
                "Только интерьер", "Экстерьер не выбран: планера в сборке не будет. Продолжить?",
                parent=self.model_window):
            return
        self.project_extra["models"] = [{"path": entry["path"], "role": entry["role"]} for entry in chosen]
        self._sync_build_variant()
        self.object_include.clear()
        self.exclude_patterns = []
        if hasattr(self, "object_tree"):
            self.object_tree.delete(*self.object_tree.get_children())
        self.project_dirty = True
        self.model_window.destroy()
        self.update_model_summary_label()
        self.status_var.set("Состав моделей подтверждён: " + ", ".join(
            f"{entry['name']} ({self.MODEL_ROLE_TITLES[entry['role']].lower()})" for entry in chosen))
        self.append_log("Состав моделей: " + "; ".join(f"{entry['role']} — {entry['path']}" for entry in chosen))
        self._update_navigation()

    def update_model_summary_label(self):
        if not hasattr(self, "models_summary"):
            return
        models = self.project_extra.get("models", [])
        if not models:
            self.models_summary.configure(text="Состав не задан: программа возьмёт объявленный в model.cfg.")
            return
        counts = {role: sum(1 for item in models if item.get("role") == role) for role in self.MODEL_ROLE_TITLES}
        self.models_summary.configure(text="Подтверждённый состав: " + ", ".join(
            f"{self.MODEL_ROLE_TITLES[role].lower()} — {count}" for role, count in counts.items()) +
            ". Файлы: " + ", ".join(Path(item["path"]).name for item in models))

    def on_inventory_result(self, code, output):
        if code != 0:
            return
        try:
            data = json.loads(output)
            self.inventory_entries = data if isinstance(data, list) else data.get("aircraft", [])
            self.catalog_entries = list(self.inventory_entries)
            self.populate_aircraft()
        except json.JSONDecodeError:
            self.append_log("Не удалось разобрать JSON inventory. Проверьте журнал.")

    @staticmethod
    def format_diagnosis(entry):
        """Human-readable pre-build diagnosis produced by package_resolver."""
        lines = [f"{entry.get('reason', 'Нет данных')} [{entry.get('reason_code', '?')}]",
                 entry.get("action", "")]
        missing = entry.get("missing_resources", [])
        if missing:
            lines.append(f"Отсутствует ресурсов: {len(missing)}")
            for item in missing[:6]:
                # Only ambiguity needs a decision here; read errors belong to the deep view.
                detail = f" — {item['detail']}" if item.get("kind") == "ambiguous" and item.get("detail") else ""
                lines.append(f"  • {item.get('kind')}: {item.get('path') or item.get('name')}{detail}")
        dependencies = entry.get("dependencies", [])
        base = next((d for d in dependencies if d.get("kind") == "base_container"), None)
        if base:
            state = (origin_text(base.get("origin")) if base.get("resolved")
                     else base.get("detail") or "ссылка не разрешена")
            lines.append(f"Базовый самолёт: {base.get('name')} — {state}")
        models = entry.get("best_models", [])
        if models:
            lines.append("Доступные модели:")
            for model in models:
                origin = model.get("origin")
                parts = [part for part in (f"в {model['variant']}" if model.get("variant") else "",
                                           origin_text(origin) if origin in FOREIGN_ORIGINS else "") if part]
                suffix = f" — {', '.join(parts)}" if parts else ""
                lines.append(f"  • {Path(model['path']).name} ({model['role']}){suffix}")
        if entry.get("cross_variant_models"):
            lines.append("Внимание: exterior и interior взяты из разных model-папок. Проверьте назначение ролей.")
        unresolved = [d for d in dependencies if d.get("kind") == "model" and not d.get("resolved")]
        for dependency in unresolved[:4]:
            detail = f" — {dependency['detail']}" if dependency.get("detail") else ""
            lines.append(f"  • ссылка {dependency['kind']} не разрешена: "
                         f"{dependency.get('path') or dependency.get('name')}{detail}")
        if entry.get("can_build_geometry") and not entry.get("can_build_textures"):
            lines.append("Карты не найдены: геометрию собрать можно, текстуры потребуют отдельных папок.")
        return "\n".join(line for line in lines if line)

    @staticmethod
    def format_detail(report):
        """Readable deep diagnosis: per-variant models, buffers, LODs and links."""
        lines = [f"Пакет: {report.get('aircraft', '?')}", f"Путь: {report.get('path', '')}"]
        if report.get("package_path"):
            lines.append(f"Корень пакета: {report['package_path']}")
        if report.get("manifest_title"):
            lines.append(f"Manifest: {report['manifest_title']} {report.get('package_version') or ''}".rstrip())
        lines.append(f"Геометрия: {'да' if report.get('can_build_geometry') else 'нет'}. "
                     f"Текстуры: {'да' if report.get('can_build_textures') else 'нет'}. "
                     f"Режим проверки: {'подробный' if report.get('deep') else 'быстрый'}.")
        for variant in report.get("variants", []):
            lines.append("")
            lines.append(f"[{variant.get('folder')}] {variant.get('reason_code', '')}")
            selection = variant.get("model_cfg_selection")
            if isinstance(selection, str) and selection:
                lines.append(f"  model.cfg: {selection}")
            for model in variant.get("models", []):
                state = "доступна" if model.get("available") else "НЕдоступна"
                lines.append(f"  • {model.get('role')}: {Path(model.get('path', '')).name} — {state} "
                             f"({origin_text(model.get('origin'))})")
                if model.get("origin") in FOREIGN_ORIGINS:
                    lines.append(f"      источник: {Path(model.get('path', '')).parent}")
                for buffer in model.get("missing_buffers", []):
                    lines.append(f"      нет BIN: {buffer}")
                for feature in model.get("unsupported", []):
                    lines.append(f"      не поддерживается: {feature}")
                if model.get("read_error"):
                    lines.append(f"      ошибка чтения: {model['read_error']}")
            for candidate in variant.get("candidates", []):
                if any(m.get("path") == candidate.get("path") for m in variant.get("models", [])):
                    continue
                lines.append(f"  • кандидат {candidate.get('role')}: {Path(candidate.get('path', '')).name} "
                             f"— найдена в {candidate.get('variant')} ({origin_text(candidate.get('origin'))})")
            missing_lods = [lod for lod in variant.get("lods", []) if not lod.get("available")]
            if missing_lods:
                lines.append(f"  LOD без файла: {len(missing_lods)}")
        missing = report.get("missing_resources", [])
        if missing:
            lines.append("")
            lines.append(f"Отсутствует ресурсов: {len(missing)}")
            for item in missing:
                detail = f" — {item['detail']}" if item.get("detail") else ""
                lines.append(f"  • {item.get('kind')}: {item.get('path') or item.get('name')}{detail}")
        if report.get("textures"):
            lines.append("")
            lines.append("Texture-варианты: " + ", ".join(report["textures"]))
        dependencies = report.get("dependencies", [])
        fallback_dependencies = [item for item in dependencies if item.get("kind") == "texture_fallback"]
        other_dependencies = [item for item in dependencies if item.get("kind") != "texture_fallback"]
        if other_dependencies or fallback_dependencies:
            lines.append("")
            lines.append("Зависимости:")
            labels = {"manifest": "Пакеты-зависимости", "base_container": "Базовый самолёт",
                      "model": "Ссылки на модели", "texture_fallback": "texture.cfg fallback"}
            grouped = {}
            for dependency in other_dependencies:
                grouped.setdefault(dependency.get("kind", "other"), []).append(dependency)
            for kind, items in sorted(grouped.items()):
                resolved = [item for item in items if item.get("resolved")]
                unresolved = [item for item in items if not item.get("resolved")]
                lines.append(f"  • {labels.get(kind, kind)}: найдено {len(resolved)} из {len(items)}")
                for dependency in resolved[:2]:
                    source = dependency.get("path") or dependency.get("name")
                    origin = f", {origin_text(dependency['origin'])}" if dependency.get("origin") else ""
                    lines.append(f"      ✓ {dependency.get('name') or kind}: {source} — OK{origin}")
                for dependency in unresolved[:4]:
                    source = dependency.get("path") or dependency.get("name") or "путь не указан"
                    detail = f" — {dependency['detail']}" if dependency.get("detail") else ""
                    lines.append(f"      ! {dependency.get('name') or kind}: {source}{detail}")
                    advice = BuilderApp._dependency_next_step(dependency)
                    if advice:
                        lines.append(f"        Следующий шаг: {advice}")
                if len(unresolved) > 4:
                    lines.append(f"      … ещё не разрешено: {len(unresolved) - 4}")
            if fallback_dependencies:
                found = sum(bool(item.get("resolved")) for item in fallback_dependencies)
                lines.append(f"  • texture.cfg fallback: найдено папок {found} из {len(fallback_dependencies)}; "
                             "проверяйте отсутствующие карты в отчёте текстурирования.")
                absent_targets = {}
                for item in fallback_dependencies:
                    target = item.get("target_aircraft")
                    if target and item.get("target_aircraft_installed") is False:
                        absent_targets[target] = absent_targets.get(target, 0) + 1
                if absent_targets:
                    examples = list(sorted(absent_targets.items(), key=lambda pair: pair[0].casefold()))
                    summary = ", ".join(f"{name} ({count})" for name, count in examples[:4])
                    if len(examples) > 4:
                        summary += f" и ещё {len(examples) - 4}"
                    lines.append("      Целевые самолёты не найдены в выбранных Packages-каталогах: " + summary + ".")
                for dependency in [item for item in fallback_dependencies if not item.get("resolved")][:4]:
                    advice = BuilderApp._dependency_next_step(dependency)
                    if advice:
                        lines.append(f"      Следующий шаг: {advice}")
                ambiguous = [item for item in fallback_dependencies
                             if "несколько установленных пакетов" in str(item.get("detail") or "")]
                for dependency in ambiguous[:3]:
                    lines.append(f"      {dependency.get('name')}: {dependency['detail']}")
        return "\n".join(lines)

    @staticmethod
    def _dependency_next_step(dependency):
        """Give a concrete user action for unresolved package links."""
        kind = dependency.get("kind")
        detail = str(dependency.get("detail") or "")
        if "несколько установленных пакетов" in detail:
            if kind == "model":
                return "сравните кандидатов; назначьте найденный файл через «Выбрать модели…» в настройках проекта."
            return "уточните корень Packages или убедитесь, что выбран нужный пакет/вариант."
        if kind == "manifest":
            return "проверьте, установлен ли этот пакет, и добавлен ли его Packages-каталог в «Пути и настройки»."
        if kind == "base_container":
            return "установите базовый самолёт и добавьте его Packages-каталог в «Пути и настройки»."
        if kind == "model":
            if "базовый самолёт установлен" in detail:
                return "проверьте вариант самолёта; если нужный glTF найден, назначьте его кнопкой «Выбрать модели…»."
            return "если это ливрея, установите её базовый самолёт; затем повторите подробную проверку."
        if kind == "texture_fallback" and dependency.get("target_aircraft_installed") is False:
            target = dependency.get("target_aircraft")
            return (f"папка {target} не найдена в выбранных Packages-каталогах; "
                    "установите пакет с этой текстурой или добавьте его каталог в настройках. "
                    "Fallback необязателен для геометрии.")
        if kind == "texture_fallback" and dependency.get("target_aircraft_installed") is True:
            return "самолёт найден, но целевая fallback-папка отсутствует; проверьте имя и состав texture-варианта."
        return "проверьте выбранные каталоги MSFS и повторите диагностику."

    def diagnose_selected(self):
        if self.busy:
            return
        entry = self.selected_aircraft
        path = entry.get("path") if entry else None
        if not path:
            selection = self.aircraft_list.selection()
            if selection:
                selected = self._aircraft_tree_entries.get(selection[0])
                path = selected.get("path") if selected else None
        if not path:
            messagebox.showinfo("Диагностика", "Сначала выберите самолёт в списке.")
            return
        command = cli_command("inventory", path, "--deep")
        self.append_package_roots(command, self.package_roots())

        def diagnosed(code, output):
            if code:
                messagebox.showerror("Диагностика пакета", output[-1500:])
                return
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                messagebox.showerror("Диагностика пакета", "Не удалось разобрать ответ inventory.")
                return
            if not data:
                return
            report = data[0]
            self._set_text(self.aircraft_detail, self.format_detail(report))
            self.aircraft_reason.configure(text=self.format_diagnosis(report))
            self.update_package_root_recovery(report)
            if self.selected_aircraft and self.selected_aircraft.get("path") == report.get("path"):
                self.selected_aircraft.update(report)
            self.append_log(f"Диагностика {report.get('aircraft')}: {report.get('reason_code')}")

        self.run_command(command, diagnosed)

    @staticmethod
    def has_unresolved_base_package(entry):
        if not isinstance(entry, dict):
            return False
        if entry.get("reason_code") == "UNRESOLVED_ALIAS":
            return True
        dependencies = [*(entry.get("dependencies") or []), *(entry.get("missing_resources") or []),
                        *(entry.get("source_gaps") or [])]
        return any(isinstance(item, dict) and item.get("resolved") is False and (
            item.get("kind") == "base_container" or item.get("problem_code") == "base_aircraft_missing"
        ) for item in dependencies)

    def update_package_root_recovery(self, entry):
        button = getattr(self, "package_root_recovery_button", None)
        if button is None:
            return
        if self.has_unresolved_base_package(entry):
            button.grid()
        else:
            button.grid_remove()

    def open_package_root_recovery(self):
        if not self.busy:
            self.manage_package_roots()

    @staticmethod
    def _aircraft_marker(entry):
        status = aircraft_status(entry)
        if status == "Недоступные":
            marker = f"  ⚠ {entry.get('reason', 'недоступен')}"
        elif entry.get("needs_model_selection"):
            marker = f"  ◐ {entry.get('reason', 'нужен выбор моделей')}"
        elif not entry.get("can_build_textures", True):
            marker = "  ◐ карты не найдены"
        else:
            marker = ""
        if entry.get("duplicate_name"):
            marker += f"  ⚠ дубликат имени ({entry.get('duplicate_count', 2)})"
        return marker

    def populate_aircraft(self, entries=None):
        """Render the catalog as expandable base-name groups."""
        if entries is not None:
            self.catalog_entries = list(entries)
        visible = [entry for entry in self.catalog_entries
                   if self.aircraft_filter_var.get() in {AIRCRAFT_FILTERS[0], aircraft_status(entry)}]
        self.active_entries = visible
        tree = self.aircraft_list
        self.update_package_root_recovery(None)
        was_disabled = "disabled" in tree.state()
        tree.state(["!disabled"])
        tree.delete(*tree.get_children())
        self._aircraft_tree_entries.clear()
        self._aircraft_tree_paths.clear()
        grouped = {}
        for entry in visible:
            name = entry.get("aircraft", entry.get("name", "?"))
            grouped.setdefault(aircraft_group_name(name), []).append(entry)
        group_counter = 0
        child_counter = 0
        for group_name in sorted(grouped, key=str.casefold):
            group_entries = sorted(grouped[group_name],
                                   key=lambda item: (str(item.get("aircraft", "")).casefold(),
                                                     str(item.get("path", "")).casefold()))
            group_counter += 1
            group_iid = f"aircraft-group-{group_counter}"
            suffix = f" ({len(group_entries)} варианта)" if len(group_entries) > 1 else ""
            tree.insert("", "end", iid=group_iid, text=f"{group_name}{suffix}", open=False)
            for entry in group_entries:
                child_counter += 1
                child_iid = f"aircraft-entry-{child_counter}"
                name = entry.get("aircraft", entry.get("name", "?"))
                label = f"{name}{self._aircraft_marker(entry)}  —  {entry.get('path', '')}"
                tree.insert(group_iid, "end", iid=child_iid, text=label)
                self._aircraft_tree_entries[child_iid] = entry
                path = str(entry.get("path", ""))
                if path:
                    self._aircraft_tree_paths[path] = child_iid
        if was_disabled:
            tree.state(["disabled"])
        counts = {status: sum(1 for entry in self.catalog_entries if aircraft_status(entry) == status)
                  for status in AIRCRAFT_FILTERS[1:]}
        filter_text = self.aircraft_filter_var.get()
        shown = len(visible)
        total = len(self.catalog_entries)
        prefix = f"Показано: {shown} из {total}" if filter_text != AIRCRAFT_FILTERS[0] else f"Найдено самолётов: {total}"
        self.status_var.set(prefix + f" — полных: {counts['Полностью доступные']}, "
                            f"частичных: {counts['Частично доступные']}, "
                            f"недоступно: {counts['Недоступные']}" +
                            (f"; скрыто history-заглушек: {self.suppressed_history_stub_count}"
                             if self.suppressed_history_stub_count else ""))
        self._update_navigation()

    def on_aircraft_select(self, _event=None):
        selection = self.aircraft_list.selection()
        if not selection or selection[0] not in self._aircraft_tree_entries:
            self.update_package_root_recovery(None)
            return
        if self.project_open:
            return
        entry = self._aircraft_tree_entries[selection[0]]
        self.update_package_root_recovery(entry)
        self.aircraft_reason.configure(text=self.format_diagnosis(entry))
        self._set_text(self.aircraft_detail, self.format_detail(entry))
        if not entry.get("can_build_geometry"):
            self.selected_aircraft = None
            self.aircraft_var.set("")
            messagebox.showwarning("Пакет недоступен",
                                   f"{entry.get('reason', 'Пакет нельзя собрать')}\n\n{entry.get('action', '')}\n\n"
                                   f"{self.format_diagnosis(entry)}")
            self._update_navigation()
            return
        self.project_extra.pop("models", None)
        self.selected_aircraft = entry
        self._sync_build_variant()
        self.object_include.clear()
        self.exclude_patterns = []
        self.model_var.set("")
        if hasattr(self, "object_tree"):
            self.object_tree.delete(*self.object_tree.get_children())
        self.aircraft_var.set(entry.get("aircraft", ""))
        self.source_var.set(entry.get("path", ""))
        variants = entry.get("variants", [])
        names = [v.get("folder", "") for v in variants]
        self.model_combo["values"] = names
        best = entry.get("best_variant")
        if best and best in names:
            self.model_var.set(best)
        elif names:
            self.model_var.set(names[0])
        self.livery_combo["values"] = self.available_liveries(entry) or ["base"]
        if self.livery_combo["values"]:
            self.livery_var.set(self.livery_combo["values"][0])
        if not self.output_var.get():
            # The definitive project repository is chosen in the New Project
            # dialog; its dedicated blend subfolder is assigned there.
            self.output_var.set(str(Path.home() / "Documents" / "MSFS_Projects" / entry.get("aircraft", "aircraft") / "blend"))
        self.update_model_summary_label()
        self._update_navigation()
        if entry.get("needs_model_selection"):
            self.choose_models()

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def make_config(self):
        if not self.project_open:
            raise ValueError("Работа без открытого проекта запрещена. Создайте или откройте проект через меню «Файлы».")
        if not self.selected_aircraft:
            raise ValueError("В проекте не выбран самолёт.")
        if not self.selected_aircraft.get("can_build_geometry", True):
            raise ValueError(f"Выбранный пакет недоступен: {self.selected_aircraft.get('reason', '')}. "
                             f"{self.selected_aircraft.get('action', '')}")
        source = Path(self.selected_aircraft["path"])
        if not source.is_dir():
            raise ValueError(f"Папка самолёта не найдена: {source}. Повторно просканируйте каталог MSFS и создайте проект заново.")
        project_path = self.project_path()
        output = (project_path.parent / "blend") if project_path else Path(self.output_var.get().strip())
        # Setting the same value still fires the trace, so a read-only check
        # would mark the project modified.
        if str(output) != self.output_var.get():
            self.output_var.set(str(output))
        if not output:
            raise ValueError("Укажите папку результата.")
        blender = self.blender_var.get().strip()
        build_variant = self.build_variant_var.get().strip() or f"{self.skinning_var.get()}_{self.draw_var.get()}"
        # Preserve advanced operations configured by previous program versions.
        config = {**self.project_extra,
            "source": str(source),
            "aircraft": self.selected_aircraft.get("aircraft", source.name),
            "blender": blender,
            "output_dir": str(output),
            "profile": "generic",
            "model_folder": self.model_var.get().strip(),
            "livery": self.livery_var.get().strip() or "base",
            "build_variant": build_variant,
            "skinning": self.skinning_var.get(),
            "draw_mode": self.draw_var.get(),
            "pose_position": self.pose_position_var.get(),
            "repair_skin_roots": bool(self.repair_skin_roots_var.get()),
            "normal_decode": self.normal_decode_var.get(),
            "converted_normal_dir": self.converted_normal_var.get().strip() or None,
            "filter_runtime": bool(self.filter_runtime_var.get()),
            "include_all_liveries": bool(self.all_liveries_var.get()),
            "exclude_objects": self.current_exclusions(),
            "extra_texture_dirs": [x.strip() for x in self.extra_text.get("1.0", "end").splitlines() if x.strip()],
        }
        base = project_path.parent if project_path else Path.cwd()
        def absolute(value):
            return str((base / Path(os.path.expandvars(value)).expanduser()).resolve())
        config["extra_texture_dirs"] = [absolute(value) for value in config["extra_texture_dirs"]]
        if config.get("converted_normal_dir"):
            config["converted_normal_dir"] = absolute(config["converted_normal_dir"])
        if config.get("texture_overrides"):
            config["texture_overrides"] = {name: absolute(value) for name, value in config["texture_overrides"].items()}
        if self.selected_aircraft.get("needs_model_selection") and not config.get("models"):
            raise ValueError(f"{self.selected_aircraft.get('reason')}. {self.selected_aircraft.get('action')} "
                             "Нажмите «Выбрать модели...» на шаге 2 и подтвердите состав.")
        return config

    def current_exclusions(self):
        # Resolve patterns against the visible catalog so checking a previously
        # excluded item really restores it, even when its old rule was a glob.
        unmatched = [pattern for pattern in self.exclude_patterns if not any(
            fnmatch.fnmatchcase(name.casefold(), pattern.casefold()) for name in self.object_include)]
        return sorted(set(unmatched) | {literal_pattern(name) for name, included in self.object_include.items() if not included})

    def project_path(self):
        path = self.project_var.get().strip()
        return Path(path) if path else None

    def save_project(self, path=None):
        if self.busy:
            return None
        old_path = self.project_var.get()
        old_output = self.output_var.get()
        path = Path(path) if path else self.project_path()
        if path is None:
            path = self.project_path_dialog("Сохранить проект")
        if not path:
            return None
        self.project_var.set(str(path))
        try:
            config = self.make_config()
        except ValueError as exc:
            self.project_var.set(old_path)
            self.output_var.set(old_output)
            messagebox.showwarning("Неполная настройка", str(exc))
            return None
        path = Path(path)
        try:
            atomic_json(path, config)
        except OSError as exc:
            self.project_var.set(old_path)
            self.output_var.set(old_output)
            messagebox.showerror("Не удалось сохранить проект", f"{path}\n\n{exc}")
            return None
        self.project_var.set(str(path))
        self.project_open = True
        self.project_dirty = False
        self.exclude_patterns = list(config["exclude_objects"])
        self._set_project_state(True)
        self.status_var.set(f"Проект сохранён: {path}")
        return path

    def save_project_as(self):
        if not self.project_open:
            messagebox.showinfo("Нет проекта", "Сначала создайте или откройте проект.")
            return None
        path = self.project_path_dialog("Сохранить проект как")
        return self.save_project(path) if path else None

    def new_project(self):
        if self.busy:
            return
        if self.project_open:
            if not self.confirm_close_project():
                return
            self.close_project(force=True)
        self.selected_aircraft = None
        self._show_catalog_step()

    def _create_project_from_selection(self):
        if not self.selected_aircraft:
            self._show_catalog_step()
            return
        path = self.project_path_dialog("Новый проект", default_name=self.selected_aircraft.get("aircraft", "msfs_project"))
        if not path:
            return
        path = Path(path)
        self.project_var.set(str(path))
        self.project_open = True
        self.project_dirty = True
        self._set_project_state(True)
        self.output_var.set(str(path.parent / "blend"))
        if self.save_project(path) is None:
            self.project_open = False
            self._set_project_state(False)
            return
        atomic_json(path.parent / ".msfs-project.json", {"project": path.name, "version": VERSION})
        self.status_var.set(f"Создан проект: {path}")
        self._update_navigation()

    def confirm_close_project(self):
        if not self.project_open or not self.project_dirty:
            return True
        answer = messagebox.askyesnocancel("Проект изменён", "Сохранить текущий проект перед закрытием?")
        if answer is None:
            return False
        if answer:
            return self.save_project() is not None
        return True

    def close_project(self, force=False):
        if self.busy:
            return
        if not force and not self.confirm_close_project():
            return
        self.project_open = False
        self.project_dirty = False
        self.project_var.set("")
        self.audit_report_path = None
        self.selected_aircraft = None
        self.selected_inventory = None
        self.aircraft_var.set("")
        self.model_var.set("")
        self.livery_var.set("base")
        self.output_var.set("")
        self.exclude_patterns = []
        self.project_extra = {}
        self.object_include.clear()
        self.object_details.clear()
        self.update_model_summary_label()
        if hasattr(self, "object_tree"):
            self.object_tree.delete(*self.object_tree.get_children())
        self.blend_list.delete(0, "end")
        self.blend_paths = []
        self._set_explorer_target(None)
        self.extra_text.configure(state="normal")
        self.extra_text.delete("1.0", "end")
        self.build_stage_var.set("Этап не запущен")
        self.build_detail_var.set("Создайте или откройте проект.")
        self.build_result_var.set("")
        self._sync_build_variant()
        self._set_project_state(False)
        self.status_var.set("Проект закрыт. Выберите самолёт и создайте новый проект.")
        self._update_navigation()

    def delete_project(self):
        if not self.project_open:
            messagebox.showinfo("Нет проекта", "Сначала откройте проект, который нужно удалить.")
            return
        if self.busy:
            messagebox.showwarning("Сборка выполняется", "Сначала дождитесь завершения или остановите текущую операцию.")
            return
        project = self.project_path()
        if project is None:
            return
        project = project.resolve()
        blend_dir = owned_blend_folder(project)
        answer = messagebox.askyesno(
            "Удалить проект",
            "Проект будет перенесён в архив удалённых проектов:\n\n"
            f"JSON проекта:\n{project}\n\n"
            + (f"рабочая подпапка blend:\n{blend_dir}\n\n" if blend_dir else "Общая папка blend старого проекта останется на месте.\n\n") +
            "Остальные файлы в папке проекта останутся. Продолжить?",
        )
        if not answer:
            return
        try:
            archived = retire_project(project)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Удаление проекта", str(exc))
            return
        self.close_project(force=True)
        self.status_var.set(f"Проект перенесён в {archived}")

    def close_application(self):
        if self.busy:
            if not messagebox.askyesno("Операция выполняется", "Остановить операцию и закрыть программу?"):
                return
            self.stop_build()
            self.after(150, self._close_after_stop)
            return
        if not self.confirm_close_project():
            return
        self.destroy()

    def destroy(self):
        """Cancel the queue poll before Tk destroys its command table."""
        after_id = getattr(self, "_drain_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
            self._drain_after_id = None
        super().destroy()

    def _close_after_stop(self):
        if self.busy:
            self.after(150, self._close_after_stop)
        else:
            self.close_application()

    def open_project(self):
        if self.busy:
            return
        if self.project_open and not self.confirm_close_project():
            return
        path = filedialog.askopenfilename(title="Открыть проект", filetypes=(("MSFS project", "*.json"), ("Все файлы", "*.*")))
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("source"), str) or not isinstance(data.get("aircraft"), str):
                raise ValueError("Проект не содержит source/aircraft и не может быть открыт.")
            self._loading_project = True
            if self.project_open:
                self.close_project(force=True)
            self.project_extra = dict(data)
            self.audit_report_path = None
            source = (Path(path).parent / os.path.expandvars(data["source"])).resolve()
            self.project_var.set(path)
            self.project_open = True
            self.source_var.set(str(source))
            self.aircraft_var.set(data.get("aircraft", ""))
            # Keep a minimal entry until the asynchronous inventory scan
            # replaces it with the complete aircraft metadata.
            self.selected_aircraft = {
                "aircraft": data.get("aircraft", ""),
                "path": str(source),
                "variants": [],
                "textures": [],
            }
            self.output_var.set(str(Path(path).parent / "blend"))
            configured_blender = data.get("blender", "")
            self.blender_var.set(configured_blender if Path(configured_blender).is_file() else self.settings.get("blender") or detect_blender())
            self.model_var.set(data.get("model_folder", ""))
            self.livery_var.set(data.get("livery", "base"))
            self.skinning_var.set(data.get("skinning", "strip"))
            self.draw_var.set(data.get("draw_mode", "auto"))
            self.pose_position_var.set(data.get("pose_position", "REST"))
            self.repair_skin_roots_var.set(data.get("repair_skin_roots", False))
            self.normal_decode_var.set(data.get("normal_decode", "auto"))
            self.converted_normal_var.set(data.get("converted_normal_dir", "") or "")
            self.build_variant_var.set(data.get("build_variant", f"{self.skinning_var.get()}_{self.draw_var.get()}"))
            self.filter_runtime_var.set(data.get("filter_runtime", True))
            self.all_liveries_var.set(data.get("include_all_liveries", False))
            self.exclude_patterns = list(data.get("exclude_objects", []))
            self._set_text(self.extra_text, "\n".join(data.get("extra_texture_dirs", [])))
            self.extra_text.configure(state="normal")
            self.update_model_summary_label()
            self._set_project_state(True)
            self.project_dirty = False
            self.catalog_root_var.set(data.get("source", ""))
            command = self.append_package_roots(cli_command("inventory", str(source)), self.package_roots())
            self.run_command(command, self.on_open_project_inventory)
            self.status_var.set("Проект загружен. Обновляю список самолётов...")
        except Exception as exc:
            self._set_project_state(False)
            messagebox.showerror("Ошибка проекта", str(exc))
        finally:
            self._loading_project = False

    def on_open_project_inventory(self, code, output):
        if code != 0:
            return
        try:
            data = json.loads(output)
            self.catalog_entries = data if isinstance(data, list) else data.get("aircraft", [])
            self.suppressed_history_stub_count = (len(data.get("suppressed_history_stubs", []))
                                                  if isinstance(data, dict) else 0)
            self.aircraft_filter_var.set(AIRCRAFT_FILTERS[0])
            self.populate_aircraft()
        except json.JSONDecodeError:
            self.append_log("Не удалось разобрать inventory открытого проекта.")
            return
        for entry in self.active_entries:
            if entry.get("aircraft") == self.aircraft_var.get():
                self.selected_aircraft = entry
                self._sync_build_variant()
                self.source_var.set(entry.get("path", self.source_var.get()))
                self.model_combo["values"] = [variant["folder"] for variant in entry.get("variants", [])]
                self.livery_combo["values"] = self.available_liveries(entry)
                self.aircraft_reason.configure(text=self.format_diagnosis(entry))
                self.update_package_root_recovery(entry)
                item_id = self._aircraft_tree_paths.get(str(entry.get("path", "")))
                if item_id:
                    self.aircraft_list.selection_set(item_id)
                self.aircraft_list.state(["disabled"])
                if not entry.get("can_build_geometry"):
                    self.status_var.set(f"Пакет недоступен: {entry.get('reason')}")
                break
        self.refresh_blend_list()
        self._update_navigation()

    @staticmethod
    def available_liveries(entry):
        folders = entry.get("textures", [])
        return (["base"] if "texture" in [name.casefold() for name in folders] else []) + [name.split(".", 1)[1] for name in folders if "." in name]

    def relocate_source(self):
        if self.busy or not self.project_open:
            return
        folder = self.directory_dialog("Выберите исходную папку самолёта", self.source_var.get())
        if not folder:
            return
        def relocated(code, output):
            if code:
                messagebox.showerror("Исходный самолёт", output[-1000:])
                return
            data = json.loads(output)
            if len(data) != 1 or not data[0].get("can_build_geometry"):
                detail = self.format_diagnosis(data[0]) if data else "В папке не найден самолёт."
                messagebox.showerror("Исходный самолёт", f"Укажите папку одного самолёта с доступными glTF-моделями.\n\n{detail}")
                return
            self.selected_aircraft = data[0]
            self.source_var.set(data[0]["path"])
            self.aircraft_var.set(data[0]["aircraft"])
            self.model_combo["values"] = [item["folder"] for item in data[0].get("variants", [])]
            self.livery_combo["values"] = self.available_liveries(data[0])
            # Explicit model paths from an older machine cannot be retained.
            self.project_extra.pop("models", None)
            self._sync_build_variant()
            self.update_model_summary_label()
            self.project_dirty = True
            if data[0].get("needs_model_selection"):
                self.choose_models()
        command = self.append_package_roots(cli_command("inventory", folder), self.package_roots())
        self.run_command(command, relocated)

    def _set_project_state(self, enabled):
        self.project_open = bool(enabled)
        state = "normal" if enabled else "disabled"
        selected_before = self.notebook.select()
        self.notebook.tab(self.setup_tab, state=state)
        self.notebook.tab(self.build_tab, state=state)
        self.notebook.tab(self.texture_tab, state=state)
        self.notebook.tab(self.log_tab, state=state)
        self.file_menu.entryconfigure("Сохранить", state=state)
        self.file_menu.entryconfigure("Сохранить как...", state=state)
        self.file_menu.entryconfigure("Закрыть проект", state=state)
        self.file_menu.entryconfigure("Удалить проект...", state=state)
        if enabled:
            self.aircraft_list.state(["disabled"])
            self._hide_welcome_tab()
            self._hide_catalog_step()
            if selected_before in {str(self.welcome_tab), str(self.catalog_tab), ""}:
                self.notebook.select(self.setup_tab)
        else:
            self.aircraft_list.state(["!disabled"])
            self._show_welcome_tab()
            self._hide_catalog_step()
            self.notebook.select(self.welcome_tab)
        self.status_var.set("Проект открыт." if enabled else "Нет открытого проекта.")
        self._update_navigation()

    def _tab_visible(self, tab):
        return str(tab) in self.notebook.tabs()

    def _show_catalog_step(self):
        if self.project_open:
            return
        if not self._tab_visible(self.catalog_tab):
            self.notebook.insert(1, self.catalog_tab, text="1. Самолёт")
        self.catalog_step_open = True
        self.notebook.select(self.catalog_tab)
        self._update_navigation()

    def _show_welcome_tab(self):
        if not self._tab_visible(self.welcome_tab):
            self.notebook.insert(0, self.welcome_tab, text="Проекты")

    def _hide_welcome_tab(self):
        if self._tab_visible(self.welcome_tab):
            self.notebook.forget(self.welcome_tab)

    def _hide_catalog_step(self):
        if self._tab_visible(self.catalog_tab):
            self.notebook.forget(self.catalog_tab)
        self.catalog_step_open = False

    def setup_ready(self):
        blender = Path(self.blender_var.get().strip())
        return bool(self.project_open and self.selected_aircraft and self.model_var.get().strip()
                    and self.livery_var.get().strip() and self.output_var.get().strip()
                    and blender.is_file())

    def _update_navigation(self):
        if not hasattr(self, "notebook"):
            return
        self.update_rules_label()
        selected = self.notebook.select()
        if selected == str(self.welcome_tab):
            self.nav_back.configure(state="disabled")
            self.nav_next.configure(state="disabled")
            self.nav_hint.configure(text="Создайте новый проект или откройте существующий через меню «Файлы».")
        elif selected == str(self.catalog_tab):
            can_next = bool(self.selected_aircraft)
            self.nav_back.configure(state="normal")
            self.nav_next.configure(state="normal" if can_next else "disabled")
            self.nav_hint.configure(text="Выберите самолёт и нажмите «Далее», чтобы создать проект.")
        elif selected == str(self.setup_tab):
            self.nav_back.configure(state="disabled")
            self.nav_next.configure(state="normal" if self.setup_ready() else "disabled")
            self.nav_hint.configure(text="Укажите model, Blender и ливрею; blend-папка проекта создаётся автоматически.")
        elif selected == str(self.build_tab):
            self.nav_back.configure(state="normal")
            self.nav_next.configure(state="normal")
            self.nav_hint.configure(text="Выберите режим и соберите geometry, затем перейдите к текстурам.")
        elif selected == str(self.texture_tab):
            self.nav_back.configure(state="normal")
            self.nav_next.configure(state="disabled")
            self.nav_hint.configure(text="Выберите геометрию, добавьте textures или соберите final.")
        else:
            self.nav_back.configure(state="normal")
            self.nav_next.configure(state="disabled")
            self.nav_hint.configure(text="Подробный журнал операций.")

    def go_back(self):
        selected = self.notebook.select()
        if selected == str(self.catalog_tab):
            self.notebook.select(self.welcome_tab)
        elif selected == str(self.setup_tab):
            return
        elif selected == str(self.build_tab):
            self.notebook.select(self.setup_tab)
        elif selected == str(self.texture_tab):
            self.notebook.select(self.build_tab)
        elif selected == str(self.log_tab):
            self.notebook.select(self.texture_tab)
        self._update_navigation()

    def go_next(self):
        selected = self.notebook.select()
        if selected == str(self.catalog_tab):
            self._create_project_from_selection()
        elif selected == str(self.setup_tab) and self.setup_ready():
            if self.save_project() is None:
                return
            self.notebook.select(self.build_tab)
            self.after(50, lambda: self.load_object_catalog(silent=True))
        elif selected == str(self.build_tab):
            self.notebook.select(self.texture_tab)
        self._update_navigation()

    def _update_build_activity(self, line):
        if not self.active_stage:
            return
        text = line.strip()
        if text.startswith("[") or "Отчёт:" in text or "Проверка:" in text:
            self.build_detail_var.set(text)

    def directory_dialog(self, title, initial=""):
        result = {"path": None}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        variable = tk.StringVar(value=initial or str(Path.cwd()))
        ttk.Label(dialog, text="Папка:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ttk.Entry(dialog, textvariable=variable, width=70).grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        ttk.Button(dialog, text="Обзор", command=lambda: self._browse_into(variable)).grid(row=0, column=2, padx=10, pady=10)
        def create_folder():
            name = simpledialog.askstring("Новая папка", "Имя новой папки:", parent=dialog)
            if not name:
                return
            try:
                target = Path(variable.get()).expanduser() / valid_filename(name.strip())
                target.mkdir(parents=True, exist_ok=True)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Новая папка", str(exc), parent=dialog)
                return
            variable.set(str(target))
        ttk.Button(dialog, text="Создать папку", command=create_folder).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, columnspan=3, pady=10)
        def accept():
            path = Path(variable.get()).expanduser()
            if not path.is_dir():
                messagebox.showwarning("Нет папки", "Указанная папка не существует.", parent=dialog)
                return
            result["path"] = str(path.resolve())
            dialog.destroy()
        ttk.Button(buttons, text="Выбрать", command=accept).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side="left", padx=5)
        self.wait_window(dialog)
        return result["path"]

    def _browse_into(self, variable):
        path = filedialog.askdirectory(title="Выберите папку", initialdir=variable.get() if Path(variable.get()).is_dir() else str(Path.cwd()))
        if path:
            variable.set(path)

    def project_path_dialog(self, title, default_name="project"):
        result = {"path": None}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        folder = tk.StringVar(value=str(Path.home() / "Documents" / "MSFS_Projects"))
        name = tk.StringVar(value=default_name if default_name.endswith(".json") else default_name + ".json")
        ttk.Label(dialog, text="Папка проекта:").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        ttk.Entry(dialog, textvariable=folder, width=70).grid(row=0, column=1, padx=6, pady=8, sticky="ew")
        ttk.Button(dialog, text="Обзор", command=lambda: self._browse_into(folder)).grid(row=0, column=2, padx=10, pady=8)
        ttk.Label(dialog, text="Имя проекта:").grid(row=1, column=0, padx=10, pady=8, sticky="w")
        ttk.Entry(dialog, textvariable=name, width=50).grid(row=1, column=1, padx=6, pady=8, sticky="ew")
        def create_folder():
            new_name = simpledialog.askstring("Новая папка", "Имя новой папки проекта:", parent=dialog)
            if not new_name:
                return
            try:
                target = Path(folder.get()).expanduser() / valid_filename(new_name.strip())
                target.mkdir(parents=True, exist_ok=True)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Новая папка", str(exc), parent=dialog)
                return
            folder.set(str(target))
        ttk.Button(dialog, text="Создать папку", command=create_folder).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=3, column=0, columnspan=3, pady=10)
        def accept():
            directory = Path(folder.get()).expanduser()
            filename = name.get().strip()
            if not filename:
                messagebox.showwarning("Нет имени", "Укажите имя проекта.", parent=dialog)
                return
            if not filename.lower().endswith(".json"):
                filename += ".json"
            try:
                valid_filename(filename)
                repository = (directory / Path(filename).stem).resolve()
                if self.selected_aircraft:
                    package = Path(self.selected_aircraft["path"]).resolve()
                    for ancestor in package.parents:
                        if ancestor.name.casefold() == "simobjects":
                            package = ancestor.parent
                            break
                    if repository.is_relative_to(package):
                        raise ValueError("Создайте проект вне исходного пакета MSFS, например в Documents/MSFS_Projects.")
                if repository.exists():
                    raise ValueError("Папка такого проекта уже существует. Введите новое имя или откройте существующий проект.")
                repository.mkdir(parents=True, exist_ok=False)
                result["path"] = str(repository / filename)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Папка проекта", str(exc), parent=dialog)
                return
            dialog.destroy()
        ttk.Button(buttons, text="Создать", command=accept).pack(side="left", padx=5)
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side="left", padx=5)
        self.wait_window(dialog)
        return result["path"]

    def start_build(self, stage):
        if self.busy:
            messagebox.showinfo("Занято", "Дождитесь текущей операции или остановите её.")
            return
        if not self.project_open:
            messagebox.showinfo("Нет проекта", "Создайте или откройте проект через меню «Файлы».")
            return
        if not self.setup_ready():
            messagebox.showwarning("Неполная настройка", "Перед сборкой укажите model, Blender, ливрею и папку результатов.")
            return
        self._sync_build_variant()
        project = self.save_project()
        if project is None:
            return
        config = self.make_config()
        source_blend = None
        if stage in {"textures", "final"}:
            source_blend = self.selected_blend_path()
            expected = "01_geometry" if stage == "textures" else "02_textured"
            if source_blend is None or not source_blend.name.startswith(expected) or not source_blend.is_file():
                messagebox.showwarning("Выберите исходный файл", f"Выберите в списке файл {expected}*.blend для этого этапа.")
                return
            try:
                metadata = json.loads(source_blend.with_suffix(".json").read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                metadata = {}
            if metadata.get("models"):
                config["models"] = metadata["models"]
            match = re.match(r"(?:01_geometry|02_textured)_(.+)_\d{3,}$", source_blend.stem)
            config["build_variant"] = metadata.get("build_variant") or (match.group(1) if match else config["build_variant"])
        # Freeze settings for this run: edits/saves cannot change a running job.
        self.active_build_config = config
        snapshot = Path(config["output_dir"]).parent / "work" / f"run-{__import__('uuid').uuid4().hex}.json"
        try:
            atomic_json(snapshot, config)
        except OSError as exc:
            messagebox.showerror("Папка проекта", str(exc))
            return
        self.active_stage = stage
        self._set_explorer_target(None)
        self.build_stage_var.set(f"Этап: {stage}")
        self.build_detail_var.set("Запускаю универсальный pipeline...")
        self.build_result_var.set("")
        self.start_progress()
        command = cli_command("build", str(snapshot), "--stage", stage)
        if source_blend:
            command += ["--input-blend", str(source_blend)]
        self.run_command(command, self.on_build_finished)

    def on_build_finished(self, code, output):
        stage = self.active_stage or "сборка"
        if code in {0, 2} and not self.cancel_requested:
            produced = re.findall(r"\[(?:geometry|textures|final)\]\s+(.+?\.blend)", output, flags=re.IGNORECASE)
            blend = Path(produced[-1].strip()) if produced else Path(self.output_var.get().strip()) / self.checkpoint_name(stage)
            checkpoint = blend.name
            self._set_explorer_target(blend)
            self.refresh_blend_list()
            self.build_stage_var.set(f"Этап {stage}: завершён")
            self.build_result_var.set(f"{'Готово с замечаниями' if code == 2 else 'Сборка выполнена успешно'}. Создан файл {checkpoint}.")
            if stage in {"geometry", "all"}:
                self.build_detail_var.set("Геометрия готова. Список объектов обновлён; проверьте модель в Blender.")
                self.load_object_catalog(silent=True)
            else:
                self.build_detail_var.set("Проверьте результат в Blender. Подробный журнал сохранён во вкладке «Журнал».")
        elif self.cancel_requested:
            self.build_stage_var.set("Операция остановлена")
            self.build_result_var.set("Сборка отменена пользователем. Следующий запуск получит новый номер.")
            self.build_detail_var.set("Подробности остановки сохранены в журнале.")
        else:
            error_type = self.classify_build_error(output)
            self.build_stage_var.set(f"Этап {stage}: ошибка")
            self.build_result_var.set(f"Сборка остановлена. Тип ошибки: {error_type}.")
            if error_type == "выходной checkpoint уже существует":
                self.build_detail_var.set("Выберите новую папку результата или удалите/перенесите старый checkpoint вручную; существующие файлы программа не перезаписывает.")
            elif error_type == "папка сборки занята другим процессом":
                self.build_detail_var.set("Дождитесь завершения другого запуска или нажмите «Остановить» в том окне, где он выполняется.")
            else:
                self.build_detail_var.set("Откройте вкладку «Журнал» и последний *.log для подробностей.")
        self.active_stage = None
        self.active_build_config = None
        self._update_navigation()

    def _set_explorer_target(self, path):
        candidate = Path(path) if path else None
        self.last_blend_path = candidate if candidate and candidate.is_file() else None
        buttons = [self.explorer_button, self.geometry_explorer_button]
        if self.last_blend_path and not self.explorer_button_visible:
            for button in buttons:
                button.pack(side="left", padx=8)
            self.explorer_button_visible = True
        elif not self.last_blend_path and self.explorer_button_visible:
            for button in buttons:
                button.pack_forget()
            self.explorer_button_visible = False

    def open_blend_in_explorer(self):
        blend = self.latest_geometry_file() if self.notebook.select() == str(self.build_tab) else self.last_blend_path
        if not blend or not blend.is_file():
            messagebox.showwarning("Файл не найден", "После сборки файл .blend ещё не найден в папке результата.")
            self._set_explorer_target(None)
            return
        try:
            subprocess.Popen(["explorer.exe", "/select,", str(blend)])
        except OSError as exc:
            messagebox.showerror("Проводник", f"Не удалось открыть файл в Проводнике:\n{exc}")

    @staticmethod
    def classify_build_error(output):
        text = output.casefold()
        if "access is denied" in text or "permission" in text or "доступ" in text:
            return "доступ к файлу или папке"
        if "файл уже существует" in text or "already exists" in text:
            return "выходной checkpoint уже существует"
        if "папка сборки занята" in text or "lock" in text:
            return "папка сборки занята другим процессом"
        if "texture" in text or "текстур" in text or "missing_textures" in text:
            return "текстуры"
        if "gltf" in text or "skin" in text or "меш" in text or "triangle" in text:
            return "геометрия или skinning"
        if "blender" in text:
            return "Blender"
        return "общая ошибка pipeline"

    def stop_build(self):
        self.cancel_requested = True
        if self.process is not None:
            self._kill_process_tree(self.process)
            self.status_var.set("Остановка...")

    @staticmethod
    def _kill_process_tree(process):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        else:
            process.terminate()

    def refresh_blend_list(self):
        previous = self.selected_blend_path()
        output = Path(self.output_var.get().strip())
        self.blend_paths = sorted(output.glob("*.blend"), key=checkpoint_order, reverse=True) if output.is_dir() else []
        self.blend_list.delete(0, "end")
        for path in self.blend_paths:
            self.blend_list.insert("end", path.name)
        if self.blend_paths:
            self.blend_list.selection_set(self.blend_paths.index(previous) if previous in self.blend_paths else 0)
            self._set_explorer_target(self.blend_paths[0])
        self.status_var.set(f"Найдено checkpoint-файлов: {len(self.blend_paths)}")

    def selected_blend_path(self):
        selection = self.blend_list.curselection()
        if not selection or selection[0] >= len(self.blend_paths):
            return None
        return self.blend_paths[selection[0]]

    def open_selected_blend(self):
        blend = self.selected_blend_path()
        if blend is None:
            messagebox.showinfo("Вариант не выбран", "Выберите .blend в списке вариантов.")
            return
        blender = self.blender_var.get().strip()
        if not blender or not Path(blender).is_file():
            messagebox.showwarning("Blender не найден", "Укажите путь к blender.exe на вкладке настройки.")
            return
        self._set_explorer_target(blend)
        subprocess.Popen([blender, str(blend)])

    def show_selected_blend(self):
        blend = self.selected_blend_path()
        if blend is None:
            messagebox.showinfo("Вариант не выбран", "Выберите .blend в списке вариантов.")
            return
        self._set_explorer_target(blend)
        self.open_blend_in_explorer()

    def open_checkpoint(self):
        output = Path(self.output_var.get().strip())
        self.refresh_blend_list()
        blend = self.latest_geometry_file() if self.notebook.select() == str(self.build_tab) else self.selected_blend_path()
        if blend is None:
            messagebox.showwarning("Checkpoint не найден", "Сначала выполните geometry или textures.")
            return
        self._set_explorer_target(blend)
        blender = self.blender_var.get().strip()
        if not blender or not Path(blender).is_file():
            messagebox.showwarning("Blender не найден", "Укажите путь к blender.exe на вкладке настройки.")
            return
        subprocess.Popen([blender, str(blend)])
        self.refresh_blend_list()

    def audit_geometry_checkpoint(self):
        if self.busy or not self.project_open:
            return
        blend = self.geometry_checkpoint_for_audit()
        if blend is None:
            messagebox.showwarning("Checkpoint не найден", "Сначала соберите geometry, затем проверьте её checkpoint.")
            return
        blender = self.blender_var.get().strip()
        if not blender or not Path(blender).is_file():
            messagebox.showwarning("Blender не найден", "Укажите путь к blender.exe на вкладке настройки.")
            return
        project = self.project_path()
        if project is None:
            messagebox.showwarning("Проект не найден", "Сохраните проект перед запуском аудита.")
            return
        report_dir = project.parent / "reports" / "geometry_audits"
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.audit_report_path = None
            self.append_log(f"Не удалось создать папку отчётов аудита {report_dir}: {exc}")
            messagebox.showerror("Аудит checkpoint", "Не удалось создать папку отчётов проекта. Проверьте доступ к папке; подробности записаны во вкладку «Журнал».")
            return
        prefix = f"{blend.stem}_audit_"
        sequence = max((int(match.group(1)) for path in report_dir.glob(f"{prefix}*.json")
                        if (match := re.search(r"_(\d+)$", path.stem))), default=0) + 1
        report = report_dir / f"{prefix}{sequence:03d}.json"
        command = cli_command("audit", str(blend), "--output", str(report), "--blender", blender)
        self.audit_report_path = None
        if self.run_command(command, lambda code, output: self.on_geometry_audit_result(code, output, report)):
            self.status_var.set("Blender проверяет geometry checkpoint; рендер не запускается…")

    def geometry_checkpoint_for_audit(self):
        selected = self.selected_blend_path()
        if selected and selected.name.casefold().startswith("01_geometry"):
            return selected
        return self.latest_geometry_file()

    def latest_geometry_audit_report(self, blend):
        project = self.project_path()
        if project is None or blend is None:
            return None
        report_dir = project.parent / "reports" / "geometry_audits"
        prefix = f"{blend.stem}_audit_"
        numbered = []
        for path in report_dir.glob(f"{prefix}*.json") if report_dir.is_dir() else ():
            match = re.fullmatch(re.escape(prefix) + r"(\d+)\.json", path.name, re.IGNORECASE)
            if match and path.is_file():
                numbered.append((int(match.group(1)), path))
        return max(numbered, key=lambda item: item[0])[1] if numbered else None

    def on_geometry_audit_result(self, code, output, report):
        if code:
            self.audit_report_path = None
            self.status_var.set("Аудит geometry checkpoint завершился ошибкой")
            self.append_log("Ошибка аудита checkpoint: " + (output[-1800:] if output else "нет подробностей"))
            messagebox.showerror("Аудит checkpoint", "Не удалось проверить файл. Технические подробности записаны во вкладку «Журнал».")
            return
        try:
            data = json.loads(report.read_text(encoding="utf-8-sig"))
            summary = data["summary"]
            mesh_objects = int(summary["mesh_objects"])
            duplicate_groups = int(summary["same_world_geometry_groups"])
            disconnected = int(summary["far_disconnected_objects"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.audit_report_path = None
            self.append_log(f"Не удалось разобрать отчёт аудита: {exc}")
            self.status_var.set("Не удалось прочитать отчёт аудита checkpoint")
            messagebox.showerror("Аудит checkpoint", "Отчёт создан неверно. Подробности записаны во вкладку «Журнал».")
            return
        text = (f"Mesh-объектов: {mesh_objects}; совпадающих мировых геометрий: {duplicate_groups}; "
                f"объектов с разнесёнными компонентами: {disconnected}.")
        caveat = "Эти числа помогают найти места для просмотра и не означают автоматически, что геометрия неверна."
        self.audit_report_path = report
        self.status_var.set("Аудит geometry завершён; отчёт сохранён в проекте.")
        self.build_stage_var.set("Аудит checkpoint: завершён")
        self.build_detail_var.set(text)
        self.build_result_var.set(caveat)
        self.append_log(f"Аудит {report.stem}: {text} {caveat}")
        messagebox.showinfo("Аудит geometry checkpoint", text + "\n\n" + caveat + f"\n\nОтчёт: {report}")

    def open_geometry_audit_report(self):
        if not self.project_open or self.project_path() is None:
            messagebox.showinfo("Отчёт не найден", "Сначала откройте проект с geometry checkpoint.")
            return
        blend = self.geometry_checkpoint_for_audit()
        if blend is None:
            messagebox.showinfo("Checkpoint не найден", "В активном проекте нет geometry checkpoint для просмотра отчёта.")
            return
        report = self.latest_geometry_audit_report(blend)
        if report is None:
            messagebox.showinfo("Отчёт не найден", "Для выбранного geometry checkpoint ещё нет отчёта аудита.")
            return
        self.audit_report_path = report
        try:
            os.startfile(str(report))
        except OSError as exc:
            messagebox.showerror("Отчёт аудита", str(exc))

    def checkpoint_name(self, stage):
        base = {"geometry": "01_geometry", "textures": "02_textured", "final": "03_model", "all": "03_model"}.get(stage, "checkpoint")
        variant = self.build_variant_var.get().strip() or f"{self.skinning_var.get()}_{self.draw_var.get()}"
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in variant).strip("._-")
        return f"{base}_{safe}.blend" if safe else f"{base}.blend"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MSFS Model Builder")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--configure-msfs")
    parser.add_argument("--configure-blender")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.configure_msfs is not None or arguments.configure_blender is not None:
        settings = load_settings()
        for key, value in (("msfs_root", arguments.configure_msfs), ("blender", arguments.configure_blender)):
            if value:
                settings[key] = value
        save_settings(settings)
    if arguments.configure_only:
        return
    if arguments.self_test:
        app = BuilderApp()
        app.update_idletasks()
        app.destroy()
    else:
        BuilderApp().mainloop()


if __name__ == "__main__":
    main()

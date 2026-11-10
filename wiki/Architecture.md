# Architecture

## Три процесса

```
┌─────────────────────┐      JSON stdout/stderr      ┌──────────────────────┐
│ MSFSBuilder.exe     │ ───────────────────────────► │ MSFSBuilderCLI.exe   │
│ Tkinter GUI         │      subprocess + queue      │ оркестратор          │
│ (Python включён)    │ ◄─────────────────────────── │ (Python включён)     │
└─────────────────────┘                              └──────────┬───────────┘
                                                                │ spec JSON
                                                                ▼
                                                     ┌──────────────────────┐
                                                     │ blender.exe -b       │
                                                     │ worker + helpers     │
                                                     │ (bpy, NumPy Blender) │
                                                     └──────────────────────┘
```

GUI **не импортирует bpy** и не использует системный Python в поставке. Он запускает соседний `MSFSBuilderCLI.exe` (в режиме исходников — `python scripts/msfs_universal.py`) и читает вывод через очередь событий. Оркестратор запускает Blender с `--python-exit-code 1` и передаёт спецификацию файлом.

Оба executable используют общий каталог `_internal`. Blender исполняет поставляемые скрипты из `_internal/scripts` **своим** Python с `bpy` и NumPy.

## Модули

| Файл | Зависимости | Ответственность |
|---|---|---|
| `msfs_builder_gui.py` | Tkinter, стандартная библиотека | интерфейс, проекты, фон, дерево объектов, журнал |
| `rule_editor.py` | Tkinter, стандартная библиотека | графические редакторы шести типов правил; проверку выполняет CLI `validate`, а не свой код |
| `texture_table.py` | Tkinter, стандартная библиотека | таблица карт отчёта, замена через `texture_overrides`, поиск через CLI `find-textures` |
| `app_support.py` | стандартная библиотека | атомарный JSON, настройки, поиск Blender, имена файлов, восстановимое удаление, версия |
| `scripts/package_resolver.py` | стандартная библиотека, **без bpy** | поиск пакетов, разрешение моделей, диагностика с кодами причин, кандидаты для мастера выбора, имена суставов skin-узлов (`skin_joints`) |
| `scripts/package_index.py` | стандартная библиотека + resolver, **без bpy** | индекс установленных пакетов, граф наследования, перенос VFS-путей, кэш |
| `scripts/msfs_universal.py` | стандартная библиотека + resolver + index | CLI, валидация конфига, план, этапы, блокировки, отчёты |
| `scripts/msfs_universal_worker.py` | bpy, NumPy | исполнение этапа в Blender |
| `scripts/msfs_geometry.py` | bpy, NumPy | чтение glTF, draw ranges, упакованные атрибуты, импорт, нейтрализация материалов |
| `scripts/msfs_materials.py` | bpy | чтение материалов glTF, PBR-сеть, стекло/alpha, список пропущенных карт |
| `scripts/msfs_dds_normals.py` | NumPy, zlib | декодер BC4/BC5/DXT5N → PNG |
| `scripts/msfs_collections.py` | bpy | эвристическая классификация Outliner |
| `scripts/msfs_skin_split.py` | bpy, NumPy | разделение mesh по группам костей |
| `scripts/msfs_audit.py` | bpy | аудит готового `.blend`, режим `--objects-only` |
| `release/cli_entry.py` | стандартная библиотека | замороженная точка входа CLI, `runpy` поставляемого оркестратора |

`msfs_geometry.py`, `msfs_materials.py`, `msfs_collections.py`, `msfs_skin_split.py` имеют также собственные legacy-CLI. Универсальный конвейер их не использует: они вызываются как модули из worker.

## Поток данных

```
каталог MSFS ──► package_index ──► имена самолётов + пакеты + база (кэш)
                       │
                       ▼
                 package_resolver ──► код причины + кандидаты + origin
                                          │
                                          ▼
                          model_choices ──► роли + LOD + вершины/треугольники
                                          │
                                          ▼
                              мастер выбора (GUI) ──► models
                                          │
config.json ──► make_plan (валидация) ────┤
                                          ▼
                                   plan/spec JSON
                                          │
                                          ▼
              prepare_gltf (временный glTF + geometry.bin)
                                          │
                                          ▼
                    Blender import ──► skinning ──► collections
                                          │
                                          ▼
                    split / mirror / placements ──► exclusions
                                          │
                                          ▼
              geometry checkpoint (.blend + JSON report)
                                          │
                                          ▼
                    materials + DDS decode + pack images
                                          │
                                          ▼
              textured / final checkpoint (.blend + JSON report)
```

Индекс строится один раз на скан и передаётся resolver явно (`index=`). Resolver не импортирует `package_index`: зависимость односторонняя, поэтому диагностику можно запускать и без индекса — тогда относительные ссылки ливрей просто остаются неразрешёнными.

`model_choices` — надстройка над `resolve_aircraft(deep=True)` для мастера выбора. Она собирает кандидатов по ролям, дедуплицирует пути и считает вершины с треугольниками по JSON glTF, не открывая BIN. GUI вызывает её через CLI-команду `models` и не разбирает glTF самостоятельно: граница «GUI не читает геометрию» сохранена. Подтверждённый состав попадает в обычное поле `models` конфига, которое worker уже понимал до этапа C, — отдельного формата для мастера не вводилось. Подробности: [Model Selection](Model-Selection).

Редакторы правил устроены так же. `rule_editor.py` и `texture_table.py` лежат в корне рядом с `app_support.py`, импортируются обычным образом и поэтому попадают в сборку PyInstaller без отдельных настроек. Они не содержат определения «допустимого правила»: при сохранении записывают временный конфиг и вызывают CLI `validate`, то есть ту же `validate_config`, которую использует конвейер. Имена суставов для разделения по костям даёт `package_resolver.skin_joints` — чтение JSON glTF без bpy и без BIN, доступное через команду `bones`. Мировые границы объектов для подсказки разделения приходят из уже существовавшей команды `objects`, поэтому worker для этапа D не менялся. Подробности: [Rule Editors](Rule-Editors).

Исходный пакет MSFS **не изменяется**. Временные подготовленные glTF и декодированные нормали лежат только в каталоге результатов; временные каталоги `msfs-prepared-*` удаляются автоматически. Временный конфиг проверки правил создаётся в `msfs_rules_*` и удаляется сразу после ответа CLI.

## Границы ответственности

- **Индекс** знает, *где* лежат установленные самолёты и кто чья база. Он не читает glTF и не выбирает модель: при неоднозначности возвращает кандидатов.
- **Resolver** решает, *можно ли* собирать и *что* предложить. Он не читает геометрию и не знает про Blender.
- **Оркестратор** проверяет конфиг, выбирает номера, владеет блокировкой, запускает этапы и пишет отчёты. Он не трогает вершины.
- **Worker** исполняет один этап в Blender и возвращает машинный отчёт. Он не знает названий самолётов.
- **GUI** не содержит логики сборки: только представление, ввод параметров и запуск CLI. Проверку правил она делегирует команде `validate`, чтение костей — команде `bones`, поиск карт — команде `find-textures`.

Все решения, зависящие от конкретных имён объектов, задаются пользователем в [редакторах](Rule-Editors) и попадают в конфиг. Профилей C152, Wilga, ASK 21, B747 и других в универсальной версии нет; `profile` принимает только `generic`.

## Версионирование и поставка

`VERSION` в корне — единственный источник истины. `app_support.VERSION` читает его (в замороженном виде — из `_internal`). Сборочный скрипт передаёт версию Inno Setup через `/DAppVersion` и копирует файл в поставку. `release/version_info.txt` содержит версию ресурсов Windows и обновляется при выпуске.

## Настройки и данные пользователя

| Путь | Содержимое |
|---|---|
| `%LOCALAPPDATA%\MSFSModelBuilder\settings.json` | `msfs_root`, `blender` |
| `%LOCALAPPDATA%\MSFSModelBuilder\package_index.json` | кэш индекса пакетов, см. [Package Index](Package-Index) |
| `%LOCALAPPDATA%\MSFSModelBuilder\gui-errors.log` | необработанные исключения Tk |
| `%LOCALAPPDATA%\MSFSModelBuilder\DeletedProjects\` | восстановимый архив удалённых проектов |
| `<проект>\<имя>.json` | конфигурация проекта |
| `<проект>\.msfs-project.json` | маркер владельца каталога результатов |
| `<проект>\work\` | снимки конфигурации на запуск |
| `<проект>\blend\` | checkpoint, отчёты, планы, журналы, декодированные нормали |

Каталог `msfs_gui_build` внутри `SimObjects/Airplanes` исключён из скана, чтобы результаты не попадали в список самолётов симулятора. Дополнительно `output_dir` не может находиться внутри исходного пакета.

Дальше: [Rule Editors](Rule-Editors) · [Model Selection](Model-Selection) · [Package Index](Package-Index) · [MSFS glTF Format](MSFS-glTF-Format) · [Building and Release](Building-and-Release) · [CLI Reference](CLI-Reference)

---

## English version

The application has three processes:

1. `MSFSBuilder.exe` — Tkinter GUI and project state.
2. `MSFSBuilderCLI.exe` — the JSON-producing orchestrator used by the GUI.
3. `blender.exe -b` — the worker that reads glTF and writes the Blender checkpoint.

The resolver and validators run without `bpy`; package diagnosis, model selection and rule validation therefore work before Blender starts. The worker owns geometry, materials and scene metadata. The GUI only collects choices, starts a child process and displays its reports. Source packages are read-only and every stage writes into the project output folder.

See [GUI Workflow](GUI-Workflow), [CLI Reference](CLI-Reference) and [Build Modes](Build-Modes) for the public interfaces.

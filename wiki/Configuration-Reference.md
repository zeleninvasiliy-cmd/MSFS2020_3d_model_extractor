# Configuration Reference

## English version

The build configuration is JSON and is validated before Blender starts. Required fields are the source package and an output directory outside the source package. The GUI writes the normal project configuration; users should prefer the graphical editors for model selection, object exclusions, split/mirror/placement rules, collection overrides, pivots and texture replacements.

Relative paths are resolved from the configuration file. Unknown keys and invalid rule shapes are rejected. The `validate` CLI command runs the same validator used by the GUI, so a configuration accepted in the editor is the one the worker receives.

---

JSON-конфиг сборки читает `make_plan` (`scripts/msfs_universal.py`). Неизвестные ключи **отклоняются**. Относительные пути разрешаются от каталога файла конфигурации.

GUI формирует этот JSON автоматически; обычному пользователю редактировать его не нужно. Правила `split_*`, `mirror_objects`, `placements`, `collection_overrides`, `manual_keep_pivots` и `texture_overrides` задаются окнами [редакторов правил и таблицы карт](Rule-Editors). `normal_decode` и `converted_normal_dir` выбираются на вкладке «Текстуры», а `pose_position` и `repair_skin_roots` — в параметрах geometry. Без графического редактора остаётся только `profile`: GUI сохраняет его при круговой загрузке, но менять его можно только в файле.

Структура всех перечисленных правил проверяется функцией `validate_config` **до** запуска Blender. Та же функция вызывается командой CLI `validate <config.json>`, которую используют редакторы при каждом сохранении, — поэтому определение допустимого правила существует в одном месте.

Шаблон: `examples/config.template.json`. Шаблон разделения по костям: `examples/split_by_skin.template.json`.

## Обязательные

| Ключ | Тип | Описание |
|---|---|---|
| `source` | непустая строка-путь | пакет MSFS, папка самолёта или обёртка с одним пакетом |
| `output_dir` | непустая строка-путь | каталог результатов **вне** исходного пакета (включая любого родителя `SimObjects`) и вне папки самолёта |

## Выбор самолёта и моделей

| Ключ | Тип / значения | По умолчанию | Проверки |
|---|---|---|---|
| `aircraft` | строка | авто, если под `source` ровно одна папка самолёта | сравнение без учёта регистра; при неоднозначности ошибка со списком совпадений |
| `models` | список `{"path": str, "role": "exterior"\|"interior"}` | из `model_folder` или единственного варианта | путь — существующий `.gltf` или `.glb`; роль ограничена; дубликаты и пустой список отклоняются |
| `model_folder` | строка-путь | — | альтернатива `models`; разбирается через `model_from_cfg` |
| `livery` | строка | авто — только если ровно одна `texture.*` и нет общей папки `texture`; иначе задать явно. `base` — общая папка `texture`, при её отсутствии `texture.BASE` | отсутствующая папка → ошибка |
| `profile` | только `"generic"` (`"auto"` и `""` приводятся к нему) | `"generic"` | любое другое значение отклоняется: профилей конкретных самолётов в универсальной версии нет |
| `blender` | строка-путь к exe | `shutil.which("blender")` | файл должен существовать |

Если заданы одновременно `models` и `model_folder`, приоритет у `models`. Относительные пути в `models` отсчитываются от **папки самолёта**, а не от конфига; абсолютные принимаются как есть. Именно абсолютный путь записывает GUI, когда подтверждённая модель взята из пакета базового самолёта через [индекс пакетов](Package-Index) — иначе она указывала бы внутрь ливреи, где файла нет.

При `model_folder` или автовыборе единственного варианта объявления разбираются через индекс: относительная ссылка ливреи переносится в установленный базовый пакет. Если базовый самолёт не установлен или имя встречается в нескольких пакетах, ссылка остаётся неразрешённой, и `make_plan` сообщает диагностику вместо неясной ошибки пути.

В GUI ключ `models` править не нужно: его заполняет [мастер выбора моделей](Model-Selection) кнопкой «Выбрать модели...» на шаге 2. Мастер показывает все кандидаты по ролям с LOD, числом вершин и треугольников и источником роли, а подтверждение записывает абсолютные пути выбранных файлов. Для самолёта, требующего подтверждения состава, мастер открывается сам при выборе в каталоге; без подтверждённого состава сборка отклоняется. Список кандидатов в JSON печатает команда `models` — см. [CLI Reference](CLI-Reference).

## Режимы

| Ключ | Значения | По умолчанию |
|---|---|---|
| `skinning` | `bake` \| `strip` \| `hybrid` \| `manual` | `"strip"` |
| `draw_mode` | `auto` \| `msfs` \| `standard` | `"auto"` |
| `normal_decode` | `auto` \| `dxt5n` \| `off` | `"auto"` |
| `pose_position` | `REST` \| `POSE` | `"REST"` |
| `filter_runtime` | bool | `true` |
| `repair_skin_roots` | bool | `false` |
| `include_all_liveries` | bool | `false` |

`hybrid` требует непустой `hybrid_bake_objects`. `pose_position` применяется только в `bake`/`hybrid`. Семантика режимов: [Build Modes](Build-Modes).

## Имена и нумерация результатов

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `build_variant` | непустая строка | GUI задаёт `"<skinning>_<draw_mode>"`, для подтверждённого частичного состава — с суффиксом `_partial` | очищается в безопасное имя checkpoint; `"default"` и `"base"` отбрасываются |
| `build_sequence` | положительное целое (bool отклоняется) | автономер | нумерация отдельная для каждого варианта; минимум 3 цифры, без верхней границы |

Для `geometry` и `all` берётся максимальный существующий номер по всем этапам + 1. Для `textures` и `final` номер наследуется от входного checkpoint, если целевой файл не занят. Старые файлы без номера распознаются.

## Объекты и правки

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `exclude_objects` | список непустых строк (glob) | `[]` | удаление объектов и их дочерних узлов; сравнение без учёта регистра |
| `hybrid_bake_objects` | список непустых строк (glob) | `[]` | цели точечного bake в режиме `hybrid`; обязателен непустым |
| `manual_keep_pivots` | список имён узлов glTF | `[]` | pivots, которые не удаляются в `manual`; в редакторе выбираются из исходных узлов |
| `collection_overrides` | словарь glob → `"A/B/C"` | `{}` | переопределение эвристического пути коллекции; пустые сегменты отклоняются до запуска Blender |
| `placements` | словарь имя → `{"anchor": str, "offset_m": [x,y,z]}` | `{}` | перенос в точку anchor плюс offset; наследуется только положение, собственные поворот и масштаб сохраняются; offset — три конечных числа, bool отклоняется |
| `split_by_skin` | список правил | `[]` | разделение по группам костей |
| `split_spatial` | список правил | `[]` | разделение по мировым bounds или cuts по оси |
| `mirror_objects` | список правил | `[]` | восстановление одной стороны из проверенной пары |

Форматы правил:

```json
"split_by_skin": [
  {"object": "TAIL", "source_node": "TAIL", "parts": [
    {"name": "RUDDER", "bones": ["RUDDER"], "collection": "01_EXTERIOR/03_TAIL_AND_CONTROL_SURFACES", "pivot": null}
  ]}
]
```

```json
"split_spatial": [
  {"object": "WING", "axis": "X", "cuts": [-1.5, 1.5], "names": ["WING_L", "WING_C", "WING_R"]},
  {"object": "FUSELAGE", "default": "BODY", "regions": [
    {"name": "NOSE", "bounds": {"y": [null, -4.0], "x": null, "z": null}}
  ]}
]
```

```json
"mirror_objects": [{"source": "WING_RIGHT", "target": "WING_LEFT", "axis": "X"}]
```

Для `split_spatial` с `cuts`: числа по возрастанию, `names` на один длиннее. Для `regions`: `null` в bounds означает отсутствие ограничения. Ось mirror — `X`, `Y` или `Z`, по умолчанию `X`; это ось **мировой** плоскости симметрии, а не локальная ось объекта. Зеркальная копия получает перенесённое начало координат, пересчитанные UV (U → 1 − U) и пользовательские нормали.

Правки применяются **до** исключений, поэтому результат split или ссылку mirror можно безопасно исключить.

Все правила этого раздела редактируются графически: [Rule Editors](Rule-Editors). Имена объектов и узлов подставляются из фактического checkpoint, кости — из JSON glTF, границы разделения предлагаются по мировым bounds объекта.

## Текстуры

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `extra_texture_dirs` | список путей-каталогов | `[]` | дополнительные каталоги общих карт; должны существовать (кроме этапа `geometry`) |
| `converted_normal_dir` | путь-каталог или `null` | `null` | уже декодированные нормали, ожидаются файлы `<имя DDS>.png` |
| `texture_overrides` | словарь basename → путь к файлу | `{}` | точное переопределение карты; ключ — базовое имя карты **из glTF** без учёта регистра, значение — существующий файл; заполняется [таблицей карт](Rule-Editors) |
| `include_all_liveries` | bool | `false` | подключить все `texture.*` варианты к поиску |

Порядок поиска карты: `texture_overrides` → `converted_normal_dir` → первая папка из `texture_dirs`, содержащая basename. Цепочка `texture_dirs` строится по `fallback.N` из `texture.cfg` рекурсивно; ссылка, которой нет на диске внутри пакета ливреи, переносится в базовый пакет через [индекс пакетов](Package-Index).

## Минимальный пример

```json
{
  "source": "C:/MSFS/Packages/Community/my-aircraft",
  "aircraft": "My_Plane",
  "blender": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
  "output_dir": "D:/MSFS_Projects/my-plane/blend",
  "livery": "base",
  "skinning": "strip",
  "draw_mode": "auto"
}
```

## Пример подтверждённой частичной сборки

```json
{
  "source": "C:/MSFS/Packages/Official/Steam/asobo-aircraft-pitts-s1-reno",
  "aircraft": "Asobo_Pitts_S1_Reno",
  "output_dir": "D:/MSFS_Projects/pitts/blend",
  "models": [
    {"path": "model/S1_LOD01.gltf", "role": "exterior"},
    {"path": "model/S1_Interior_LOD01.gltf", "role": "interior"}
  ],
  "build_variant": "strip_auto_partial",
  "livery": "base"
}
```

## Что возвращает `make_plan`

Конфиг, обогащённый полями: `aircraft_path`, разрешённые абсолютные `models`, `texture_dirs` (в порядке fallback-цепочки), `missing_fallback_dirs`, нормализованные `texture_overrides`, абсолютные `blender` и `output_dir`.

`missing_fallback_dirs` — ожидаемый шум, а не обязательно ошибка: MSFS объединяет пакеты через VFS, поэтому `texture.cfg` часто ссылается на папки вне локального пакета.

Дальше: [Rule Editors](Rule-Editors) · [Model Selection](Model-Selection) · [Build Modes](Build-Modes) · [Textures and Materials](Textures-and-Materials) · [Object Organization](Object-Organization)

---

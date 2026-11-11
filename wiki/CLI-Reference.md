# CLI Reference

## English version

Run the source CLI with:

```powershell
python .\scripts\msfs_universal.py <command> [arguments]
```

The important commands are `roots`, `inventory`, `catalog`, `audit-plans`, `index`, `models`, `find-textures`, `build`, `audit`, `objects`, `validate` and `bones`. Machine-readable commands print JSON to stdout; diagnostics and failures use a non-zero exit code. `roots` shows detected and additional package roots. The repeatable `--root` option can combine multiple libraries. `inventory --deep` validates one package; `catalog --deep` applies the same validation to every discovered aircraft before project creation. `audit-plans` preflights geometry plans for every geometry-buildable catalog record and never starts Blender. `index` resolves livery inheritance. `build --stage geometry|textures|final|all` writes numbered checkpoints into the project output folder. The installed package accepts the same arguments through `MSFSBuilderCLI.exe`.

### `audit-plans`

Preflights the standard geometry build plan for every aircraft marked buildable by the catalog. It checks glTF/BIN sources, reuses one package index, and does not start Blender, create `.blend` files, or modify aircraft packages. A successful result confirms the source/configuration preflight only; it does not confirm Blender import or visual geometry quality.

```powershell
python .\scripts\msfs_universal.py audit-plans
python .\scripts\msfs_universal.py audit-plans --root "D:\MSFS\Community"
```

The JSON response reports buildable, validated and rejected plan counts, index errors and each rejected aircraft's path and problem code. Requested roots that do not exist appear in `missing_roots`; `scope_complete` becomes `false`, and the command exits with code 2 so a partial scan cannot look like full success. Inspect a rejected package with `inventory --deep` or the GUI.

---

Оркестратор: `scripts/msfs_universal.py`. В установленной версии те же аргументы принимает `MSFSBuilderCLI.exe`. Подкоманда обязательна.

```powershell
python .\scripts\msfs_universal.py <command> [args]
```

## Команды

### `roots`

Показывает корни Packages, которые программа находит автоматически, дополнительные пути и итоговый набор поиска. Команду использует GUI-окно **«Каталоги Packages...»**.

| Аргумент | Тип | По умолчанию | Описание |
|---|---|---|---|
| `--root` | путь, **повторяемый** | `[]` | дополнительный каталог Packages, Community, Official или модов |

```powershell
python .\scripts\msfs_universal.py roots
python .\scripts\msfs_universal.py roots --root "D:\MSFS\Community" --root "E:\CustomPackages"
```

Ответ содержит `automatic_roots`, `additional_roots`, `searched_roots` и `missing_additional_roots`. Дополнительные пути хранятся в `%LOCALAPPDATA%\MSFSModelBuilder\settings.json`; редактировать файл вручную не нужно.

### `inventory`

Диагностика ресурсов до сборки. Печатает JSON-список отчётов по каждому найденному самолёту.

| Аргумент | Тип | По умолчанию | Описание |
|---|---|---|---|
| `source` | путь, обязательный | — | пакет, папка самолёта или обёртка с одним пакетом |
| `--deep` | флаг | выключен | дополнительно разобрать glTF: BIN-буферы и неподдерживаемые возможности |
| `--root` | путь, **повторяемый** | `[]` | дополнительный корень Packages для поиска базовой модели |

Корни MSFS для поиска по имени (`roots`) обнаруживаются автоматически только когда задан `--deep` или `--root`. [Индекс пакетов](Package-Index.md) строится всегда: для самолёта внутри установленных Packages — по ним (с кэшем), для отдельного локального пакета — только по его контейнеру, без кэша.

```powershell
python .\scripts\msfs_universal.py inventory "C:\MSFS\Packages\Community\my-aircraft" --deep --root "C:\MSFS\Packages\Official"
```

Поля отчёта: [Package Diagnosis](Package-Diagnosis.md). Происхождение ресурсов (`origin`): [Package Index](Package-Index.md).

### `index`

Индекс установленных пакетов и наследования ливрей. Печатает JSON со сводкой и записями самолётов.

| Аргумент | Тип | По умолчанию | Описание |
|---|---|---|---|
| `--root` | путь, **повторяемый** | `[]` | дополнительный корень Packages или каталог модов |
| `--no-cache` | флаг | выключен | перестроить индекс, не используя кэш |
| `--aircraft` | строка | — | показать записи только этого самолёта: точное совпадение без учёта регистра |

```powershell
python .\scripts\msfs_universal.py index
python .\scripts\msfs_universal.py index --aircraft Asobo_208B_GRAND_CARAVAN_EX_Livery_01
python .\scripts\msfs_universal.py index --no-cache --root "D:\MSFS\Packages\Community"
```

Поля ответа: `searched_roots`, `packages`, `aircraft_names`, `cached`, `scanned`, `errors`, `cache_path`, `aircraft`. У записи самолёта — `name`, `path`, `package`, `base_container` (как объявлено в cfg) и `base_installed` (`true`/`false`, либо `null`, если база не объявлена). Подробности: [Package Index](Package-Index.md).

### `models`

Кандидаты состава моделей для [мастера выбора](Model-Selection.md). Печатает JSON с раздельными списками `exterior` и `interior`: все LOD, число вершин и треугольников, состояние BIN, происхождение пути и источник роли. Проверка всегда глубокая.

| Аргумент | Тип | По умолчанию | Описание |
|---|---|---|---|
| `source` | путь, обязательный | — | папка самолёта |
| `--root` | путь, **повторяемый** | `[]` | дополнительный корень Packages для поиска базовой модели |

```powershell
python .\scripts\msfs_universal.py models "C:\MSFS\Packages\Official\Steam\asobo-aircraft-pitts-s1-reno-livery-aviators\SimObjects\Airplanes\Asobo_Pitts_S1_Reno_LiveryAviators"
```

Базовый пакет сканируется только когда пакет частичный или одна из ролей не имеет пригодного кандидата. Числа вершин и треугольников читаются из JSON glTF без открытия BIN. Поля ответа и измеренный результат: [Model Selection](Model-Selection.md).

### `catalog`

The default catalog scan is shallow and fast. Add `--deep` when you need an exact pre-Blender compatibility report: each declared glTF/GLB is opened, buffers are checked and unsupported primitive features are reported. Deep mode may take longer on a full installation and never changes source packages.

Скан всех установленных пакетов. Возвращает `{"searched_roots": [...], "index": {...}, "aircraft": [...]}`, отсортировано по имени. Дедупликация по разрешённому пути. Ошибка сканирования одного пакета не прерывает обход: запись получает код `SCAN_FAILED` или `PACKAGE_NOT_FOUND` и текст ошибки в `detail`.

Блок `index` — сводка использованного индекса: `packages`, `aircraft_names`, `cached`, `scanned`, `errors`. GUI выводит её в журнал и в строку состояния.

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `--root` | путь, повторяемый | `[]` |
| `--match` | строка, повторяемая | `[]` |
| `--deep` | флаг | выключен |

`--match` — фильтр по подстроке в имени папки самолёта, без учёта регистра.
`--deep` — глубокая проверка glTF/GLB, BIN и поддерживаемых primitive до создания проекта; без флага каталог проверяет только структуру и наличие объявленных файлов.

```powershell
python .\scripts\msfs_universal.py catalog --match c152 --match bonanza
python .\scripts\msfs_universal.py catalog --deep --match c152
python .\scripts\msfs_universal.py catalog --root "D:\MSFS\Official" --root "E:\MSFS\Community"
```

### `audit-plans`

Проверяет, что стандартный план сборки геометрии может быть подготовлен для каждого самолёта, который каталог пометил как доступный. Команда использует глубокую проверку glTF/BIN, переиспользует один индекс пакетов и не запускает Blender, не создаёт `.blend` и не изменяет пакеты. Успех означает, что источники и параметры прошли preflight; фактический импорт в Blender и правильность геометрии этим не подтверждаются. Если один из явно запрошенных `--root` отсутствует, путь возвращается в `missing_roots`, `scope_complete` будет `false`, а код завершения станет 2 — частичная проверка не выглядит как полная.

| Аргумент | Тип | По умолчанию | Описание |
|---|---|---|---|
| `--root` | путь, повторяемый | `[]` | дополнительный корень Packages или модов |

```powershell
python .\scripts\msfs_universal.py audit-plans
python .\scripts\msfs_universal.py audit-plans --root "D:\MSFS\Community"
```

JSON содержит количества доступных записей, валидных и отклонённых планов, ошибки индекса и причину каждого отказа. При отказе проверьте конкретный пакет командой `inventory --deep` или через GUI.

### `find-textures`

Поиск недостающих карт из текстурного отчёта по всем корням пакетов.

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `report` | путь, обязательный | — |
| `--root` | путь, повторяемый | `[]` |

Читает `missing_textures[].filename`, сопоставляет по basename без учёта регистра (поддерживаются MSFS-относительные URI вида `..\TEXTURE4\FROST_ALBD.PNG.DDS`). Возвращает `matches`, `suggested_extra_texture_dirs`, `missing`.

```powershell
python .\scripts\msfs_universal.py find-textures .\work\02_textured.json
```

Каталоги из `suggested_extra_texture_dirs` добавляются в `extra_texture_dirs`, затем текстурирование повторяется. В GUI то и другое делает [таблица карт](Rule-Editors.md): кнопка «Найти в установленных пакетах» вызывает эту команду, «Использовать выбранный файл» записывает `texture_overrides`, а «Добавить найденные папки в поиск» дописывает каталоги в поле дополнительных папок.

### `build`

Запуск конвейера.

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `config` | путь, обязательный | — |
| `--stage` | `all` \| `geometry` \| `textures` \| `final` | `all` |
| `--input-blend` | путь | — |

`--input-blend` допустим только для `textures` и `final`.

| Этап | Результат | Что делает |
|---|---|---|
| `geometry` | `01_geometry_<variant>_<NNN>.blend` | подготовка и импорт glTF, skinning, коллекции, split/mirror/placements, исключения; нейтральные материалы |
| `textures` | `02_textured_<variant>_<NNN>.blend` | открывает geometry checkpoint, привязывает ALBD/COMP/NORM/EMISSIVE, декодирует DDS-нормали, упаковывает изображения |
| `final` | `03_model_<variant>_<NNN>.blend` | открывает textured checkpoint, перепроверяет статистику, переупаковывает изображения; геометрию не меняет |
| `all` | все три последовательно | зависимость `geometry → textures → final`; при отсутствии предыдущего этапа берётся последний подходящий файл |

```powershell
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage geometry
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage textures --input-blend ".\blend\01_geometry_strip_auto_001.blend"
```

Существующий checkpoint **никогда не перезаписывается**: номер выбирается автоматически, при совпадении пути сборка отклоняется.

### `audit`

Аудит готового `.blend` в фоновом Blender.

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `blend` | путь, обязательный | — |
| `--output` | путь, **обязательный** | — |
| `--blender` | путь | `blender` из PATH |

Отказывает, если файл `--output` уже существует. Печатает структурированный `summary`; основные коды описаны на странице [Package Diagnosis](Package-Diagnosis.md).

### `objects`

Фактический состав сохранённой сцены. Запускает аудит с `--objects-only` во временный каталог и печатает чистый JSON `{"blend": …, "objects": […]}` — баннер Blender не попадает в stdout. Эту команду использует GUI для дерева объектов и для кнопки «Прочитать объекты из checkpoint» в [редакторе правил](Rule-Editors.md).

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `blend` | путь, обязательный | — |
| `--blender` | путь | `blender` из PATH |

У каждого объекта: `name`, `source`, `parent`, `collections`, `vertices`, `faces`, `bounds` (мировые `[[min],[max]]` в метрах) и `materials`. Границы нужны редактору разделения по координатам для подсказки и кнопки «Предложить границы».

### `validate`

Проверка правил редактирования **без обращения к диску и без Blender**. Читает JSON-конфиг, вызывает ту же `validate_config`, что и конвейер, и печатает `{"ok": true, "rules": {<ключ>: <число правил>}}`. Эту команду вызывает окно [редакторов правил](Rule-Editors.md) при каждом сохранении и кнопка «Проверить все правила».

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `config` | путь, обязательный | — |

```powershell
python .\scripts\msfs_universal.py validate .\project\my-plane.json
```

При отказе код возврата `1`, а stderr содержит точное место ошибки, например `Ошибка: mirror_objects/1: ось должна быть X, Y или Z.` Проверяются `placements`, `mirror_objects`, `split_spatial`, `split_by_skin`, `collection_overrides`, `texture_overrides`, `manual_keep_pivots`, режимы и простые поля. Существование файлов и папок команда **не** проверяет — это делает `make_plan` при сборке.

### `bones`

Имена суставов skin-узлов glTF для редактора разделения по костям. Читает только JSON: BIN не открывается, Blender не запускается.

| Аргумент | Тип | По умолчанию |
|---|---|---|
| `gltf` | путь, обязательный | — |

```powershell
python .\scripts\msfs_universal.py bones "C:\MSFS\Packages\Community\my-aircraft\SimObjects\Airplanes\My_Plane\model\LOD00.gltf"
```

Ответ: `{"path": …, "available": true, "read_error": null, "skins": [{"node": "wheel_base_l", "joints": ["Hips", "LeftLeg"]]}]`. В список попадают только узлы, у которых есть **и** `skin`, **и** `mesh`. GLB-контейнер без Blender не читается, отсутствующий или повреждённый JSON даёт `read_error`; если skin-узлов нет, команда отказывает с объяснением — разделять по костям нечего.

## Коды возврата

| Код | Значение |
|---|---|
| `0` | успех |
| `1` | ошибка входа или исполнения (`ValueError`, `KeyError`, `TypeError`, `OSError`, ошибка разбора) |
| `2` | сборка завершена, файл создан, но есть замечания: недостающие карты, пропущенные материалы, ошибки упаковки |
| `130` | прервано пользователем |

Код `2` — **не авария**. GUI показывает «Готово с замечаниями», созданный файл доступен.

## Блокировка и останов

В каталоге результатов создаётся `.msfs_pipeline.lock` с JSON `{"pid": …, "child_pid": …}`. Устаревшая блокировка распознаётся по PID (Win32 `OpenProcess`/`GetExitCodeProcess`) и снимается; живая — уважается. Блокировка удаляется в `finally`.

GUI останавливает операцию деревом процессов (`taskkill /PID <pid> /T /F`), чтобы дочерний Blender не продолжал запись.

## Артефакты запуска

Для каждого этапа в каталоге результатов пишутся:

- `<stem>.json` — отчёт этапа;
- `<stage>-<run10>.plan.json` — точная спецификация, переданная worker;
- `<stage>-<run10>.log` — stdout/stderr Blender.

`run10` — первые 10 символов UUID запуска. Команда Blender:

```
blender -b --factory-startup --python-exit-code 1 --python msfs_universal_worker.py -- <spec>
```

Дальше: [Rule Editors](Rule-Editors.md) · [Package Index](Package-Index.md) · [Configuration Reference](Configuration-Reference.md) · [Build Modes](Build-Modes.md) · [Troubleshooting](Troubleshooting.md)

# MSFS Model Builder — консольное руководство

Для оконного релиза используйте `release/docs/USER_MANUAL_RU.html`. Следующие команды предназначены для запуска из исходников; установленный `MSFSBuilderCLI.exe` принимает те же аргументы вместо `python scripts/msfs_universal.py`.

## 1. Установка и зависимости

Нужны:

- Windows;
- Python 3.13 для запуска исходников (в установленной EXE-версии уже включён);
- Blender 5.x с glTF importer;
- распакованный MSFS-пакет с `.gltf` и соседним `.bin`;
- доступные DDS/PNG-текстуры.

Папка программы: каталог проекта с `msfs_builder_gui.py` и `scripts/`.

Команды выполняются из неё или с абсолютными путями:

```powershell
cd "C:\Path\To\msfs-model-builder"
```

## 2. Первое обследование пакета

Если путь указывает на распакованный пакет:

```powershell
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft" > inventory.json
```

Для поиска по установленным пакетам:

```powershell
python .\scripts\msfs_universal.py catalog --match aircraft-token
```

Подробная проверка одного самолёта (разбирает JSON glTF, ищет отсутствующие BIN и неподдерживаемые возможности):

```powershell
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft" --deep --root "D:\MSFS\Packages\Community"
```

`--root` можно повторять. Без `--deep` проверяется только наличие объявленных файлов — этот режим использует скан каталога, потому что полный разбор glTF по всем пакетам слишком медленный.

Индекс установленных пакетов строится автоматически и разрешает относительные ссылки ливрей на базовый самолёт. Посмотреть его состав:

```powershell
python .\scripts\msfs_universal.py index
python .\scripts\msfs_universal.py index --aircraft Asobo_208B_GRAND_CARAVAN_EX_Livery_01
python .\scripts\msfs_universal.py index --no-cache --root "D:\MSFS\Packages\Community"
```

`--aircraft` — точное имя без учёта регистра, `--no-cache` — перестроить индекс заново. У каждой записи есть `base_container` (как объявлено) и `base_installed` (найдена ли база среди установленных). Кэш лежит в `%LOCALAPPDATA%\MSFSModelBuilder\package_index.json` и инвалидируется по mtime каталога пакета и конфигов.

В inventory проверьте:

1. `can_build_geometry` и `can_build_textures`;
2. `reason_code` + `reason` + `action` — причина и рекомендуемое действие;
3. `needs_model_selection` — нужно ли подтвердить состав моделей;
4. `best_models` и `candidates` (у каждого кандидата есть `origin`: `model.cfg`, `xml`, `scan`, `base_container`, `aircraft_index` или `base_package` — последние два означают, что ресурс взят из другого установленного пакета);
5. `missing_resources` и `dependencies` (у зависимости есть `resolved`, `origin` и `detail`; `detail` различает «базовый самолёт не установлен» и «базовый самолёт установлен, но объявленный файл в нём отсутствует»);
6. точное имя aircraft-папки, model-папки и texture-варианты.

### Коды причин

| Код | Что означает | Что делать |
|---|---|---|
| `OK` | ресурсы найдены | собирать геометрию |
| `SUPPORTED_PARTIAL` | доступна только часть объявленных моделей | выбрать состав в мастере (`models` в CLI) или подключить пакет с недостающей моделью |
| `COMMON_RESOURCES_ONLY` | в пакете только общие ресурсы (XML, текстуры, звуки) | найти пакет с геометрией этого самолёта |
| `LIVERY_ONLY` | ливрея без собственной модели | выбрать базовый самолёт из `base_container` |
| `UNRESOLVED_ALIAS` | ссылка на базовую модель не разрешена | добавить корень Packages с базовым самолётом и повторить скан |
| `NO_MODEL_FOLDER` | нет папки `model` | указать папку самолёта или задать glTF вручную |
| `MISSING_MODEL_CFG` | нет `model.cfg` | выбрать glTF из `candidates` и сохранить в `models` |
| `INVALID_MODEL_CFG` | `model.cfg` не указывает пригодных моделей | проверить `[models]` или задать glTF вручную |
| `MISSING_GLTF` | ожидаемый glTF отсутствует | проверить целостность пакета или выбрать другой LOD |
| `MISSING_BUFFER` | glTF ссылается на отсутствующий `.bin` | восстановить пакет; смена skinning не поможет |
| `UNREADABLE_GLTF` | файл повреждён или недоступен | проверить права и целостность |
| `UNSUPPORTED_GLTF_FEATURE` | GLB, несколько buffers, data URI, sparse, Draco, не-треугольники | выбрать другой LOD; см. Приоритет 4 дорожной карты |
| `NO_TEXTURES` | геометрия есть, карт нет | указать ливрею или `extra_texture_dirs` |
| `PACKAGE_NOT_FOUND` | папка самолёта не найдена | пересканировать каталог |
| `ACCESS_DENIED` | нет доступа к файлам | проверить права, антивирус, облачную синхронизацию |
| `SCAN_FAILED` | структура пакета не разобрана | открыть подробную диагностику, указать папку или glTF вручную |

Если `needs_model_selection` истинно, GUI открывает мастер выбора моделей: раздельные списки экстерьера и интерьера со всеми LOD, числом вершин и треугольников, источником роли и происхождением файла. После подтверждения вы сохраняете явные `models`, а вариант сборки получает суффикс `_partial`. Кнопка `Выбрать модели...` на шаге «2. Настройка» открывает мастер повторно.

Те же кандидаты в JSON печатает CLI:

```powershell
python .\scripts\msfs_universal.py models "C:\Path\To\Aircraft" --root "D:\MSFS\Packages\Community"
```

В ответе `roles.exterior` и `roles.interior` — списки с полями `path`, `name`, `lod`, `vertices`, `triangles`, `role_source`, `origin`, `declared`, `default`, `available` и `status`. `role_source` различает `model.cfg` (роль объявлена) и `имя файла` (роль угадана по токенам имени). `origin=base_package` означает, что файл найден обходом базового пакета: так бывает, когда ливрея объявляет interior XML, которого в базе нет, а сам glTF интерьера там лежит под другим именем LOD. `base_aircraft.scanned` показывает, выполнялся ли этот обход. Недоступные файлы остаются в списке со `status` = `MISSING_BUFFER`, `UNSUPPORTED_GLTF_FEATURE`, `UNREADABLE_GLTF` или `MISSING_GLTF` — программа не прячет то, что лежит на диске.

В CLI задайте `models` сами:

```json
"models": [
  {"path": "model/S1_LOD01.gltf", "role": "exterior"},
  {"path": "model/S1_Interior_LOD01.gltf", "role": "interior"}
]
```

Пути в `models` относительны папке самолёта; абсолютные принимаются как есть — именно их записывает GUI, когда файл взят из пакета базового самолёта. Ошибка выбора моделей в `build` дополняется блоком «Диагностика пакета» с тем же кодом, списком доступных моделей и подсказкой выполнить `models <путь>` для просмотра всех кандидатов.

## 3. Создание конфигурации

Скопируйте `examples/config.template.json`. Для первой сборки задайте:

- `source` — пакет или папка конкретного самолёта;
- `aircraft` — точное имя из inventory, если source содержит несколько самолётов;
- `blender` — путь к `blender.exe`;
- `output_dir` — новая папка вне исходного пакета;
- `models` — явные exterior/interior glTF;
- `livery` — `base` или имя texture-варианта.

`output_dir` нельзя помещать внутрь исходного MSFS-пакета. Программа автоматически выбирает следующий номер checkpoint; существующие файлы не перезаписываются. В GUI output_dir — подпапка `blend` проекта.

В оконной версии правила редактирования (`split_by_skin`, `split_spatial`, `mirror_objects`, `placements`, `collection_overrides`, `manual_keep_pivots`) и замены карт (`texture_overrides`) задаются графически: кнопки «Правила редактирования...» на вкладке «Геометрия» и «Таблица карт...» на вкладке «Текстуры». JSON ниже описывает те же поля для консольного запуска.

### Проверка конфигурации до сборки

```powershell
python .\scripts\msfs_universal.py validate .\project\my-plane.json
```

Команда не обращается к пакету и не запускает Blender: она вызывает тот же разбор конфигурации, что и конвейер, и печатает `{"ok": true, "rules": {...}}` либо причину отказа. Эту проверку выполняет редактор правил при каждом сохранении.

### Чтение костей и объектов

```powershell
python .\scripts\msfs_universal.py bones "C:\Path\To\model\LOD00.gltf"
python .\scripts\msfs_universal.py objects .\work\...\01_geometry.blend --blender "C:\Path\blender.exe"
```

`bones` читает только документ glTF/GLB (геометрические BIN для имён суставов не нужны) и возвращает узлы со skin вместе со списками суставов. `objects` возвращает фактические mesh-объекты созданного `.blend` с числом вершин, треугольников и мировыми границами. Обе команды заполняют выпадающие списки редактора правил, поэтому имена не приходится угадывать.

## 4. Полный цикл

### Шаг 1 — geometry

Начните с самого безопасного режима:

```powershell
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage geometry
```

Откройте созданный `01_geometry_<режим>_<номер>.blend` и проверьте:

- вид сверху: симметрия крыльев;
- вид спереди: двигатели/колёса не перевёрнуты;
- вид сбоку: нос, хвост, двери и стойки;
- рулевые поверхности, закрылки, спойлеры;
- остекление и интерьер;
- Outliner и отдельность объектов.

Проверка пользователя обязательна: числовой отчёт не определяет, что объект является нужным рулём.

### Шаг 2 — textures

После подтверждения геометрии:

```powershell
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage textures
```

Откройте созданный `02_textured_<режим>_<номер>.blend` в Material Preview. Проверьте ливрею, нормали, COMP, стекло, эмиссивные карты и приборы. Для точного выбора исходника CLI поддерживает `--input-blend "C:/project/blend/01_geometry_strip_auto_001.blend"`; GUI передаёт выбранный файл автоматически.

Если есть `missing_textures`, выполните:

```powershell
python .\scripts\msfs_universal.py find-textures .\work\...\02_textured.json
```

Каталоги из `suggested_extra_texture_dirs` добавьте в `extra_texture_dirs`, затем повторите textures. При необходимости выберите исходный checkpoint явно.

### Шаг 3 — final

```powershell
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage final
```

`03_model_<режим>_<номер>.blend` — финальный checkpoint после текстурного этапа. Он не добавляет анимации.

### Все этапы одной командой

```powershell
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage all
```

Используйте `all` только после того, как уже понимаете геометрию пакета. Для пошаговой приёмки предпочтительнее отдельные этапы.

## 5. Выбор skinning-режима

Порядок диагностики:

1. `strip` — первый прогон;
2. если wing/engine/control surface смещены из-за pivot — `manual`;
3. если только несколько объектов требуют настоящей оценки костей — `hybrid` и `hybrid_bake_objects`;
4. если вся модель неправильно зависит от armature — `bake`.

`manual` сохраняет статические вершины MSFS и отключает animation pivots. Он не рассчитывает деформацию костями: её рассчитывают `bake` и выбранные объекты в `hybrid`.

Пример manual:

```json
{"skinning": "manual", "manual_keep_pivots": ["SPECIAL_PIVOT_OBJECT"]}
```

После изменения конфигурации повторите сборку: следующий номер будет назначен автоматически отдельно для каждого режима.

## 6. Типовые исправления

В GUI каждое правило из этого раздела добавляется кнопкой «Правила редактирования...» с выбором объектов из списка; JSON-примеры показывают, какое поле при этом записывается.

### Одна сторона развернута или смещена

Сначала попробуйте `manual`. Если одна сторона явно повреждена в исходном пакете, добавьте:

```json
"mirror_objects": [
  {"source": "WING_RIGHT", "target": "WING_LEFT", "axis": "X"}
]
```

Перед mirror проверьте, что source-объект действительно правильный. Программа копирует его mesh, материалы и UV и отражает относительно **мировой** плоскости симметрии по указанной оси: вершины пересчитываются, начало координат копии переносится на зеркальную сторону, порядок вершин полигонов разворачивается, U-координата заменяется на `1 − U`, а пользовательские нормали пересчитываются вместе с геометрией. Повёрнутый source-объект при этом оказывается на правильной стороне, а не на той же самой.

### Несколько частей слиты в один mesh

Используйте `split_spatial`, если граница определяется координатами. Используйте `split_by_skin`, если части имеют разные кости. После split проверьте, что число треугольников не изменилось.

В редакторе границ оси предлагаются по фактическим bounds объекта, а кости читаются из glTF кнопкой «Загрузить кости из glTF»; уже назначенные другой части суставы недоступны для повторного выбора.

### В сцене лишние collision/occluder/служебные объекты

Сначала оставьте `filter_runtime: true`. Для конкретных объектов добавьте glob-маски:

```json
"exclude_objects": ["*CHOCK*", "*COLLISION*", "AUX_*"]
```

### Текстура не найдена

1. Сверьте basename в `missing_textures`.
2. Запустите `find-textures` по отчёту.
3. Добавьте найденную папку в `extra_texture_dirs`.
4. Для одной конфликтующей карты используйте `texture_overrides`.
5. Для BC5/DXT5N проверьте `normal_decode` и `converted_normal_dir`.

В GUI шаги 1–4 выполняет «Таблица карт...»: она показывает состояние каждой карты отчёта, позволяет заменить файл, выбрать из кандидатов и найти карту в установленных пакетах. Ключом замены служит имя карты из glTF, а не имя нового файла — таблица записывает его сама.

### Ошибка draw range или артефакты треугольников

- `auto` — стандартный выбор;
- `msfs` — если glTF точно имеет ASOBO draw ranges;
- `standard` — только для обычного glTF.

Сравните `source_triangles` и `triangle_delta_before_cleanup` в JSON-отчёте.

### Blender не импортирует JOINTS/WEIGHTS

Переключитесь на `skinning: strip` или `manual`. В manual scalar weights автоматически переводятся в VEC4. Если ошибка сохраняется, проверьте соседний `.bin`, LOD и корректность accessors.

## 7. Аудит и журналы

После сборки:

```powershell
python .\scripts\msfs_universal.py audit .\work\...\03_model.blend --output .\work\...\audit.json --blender "C:\Path\blender.exe"
```

В JSON смотрите:

- `mesh_objects`, `triangles`, `vertices`;
- `missing_uv`;
- `bounds_m`;
- `collections`;
- `exact_world_duplicates`;
- `far_disconnected`;
- `missing_textures`, `unreadable_images`, `packing_failures`.

Каждый этап также сохраняет `*.log` с последними строками Blender при ошибке.

## 8. Что остаётся пользователю

Программа автоматизирует чтение glTF, подготовку индексов, skinning-режимы, generic-разделение, поиск карт, PBR-сеть, упаковку и отчёты. Пользователь всё равно должен:

- выбрать правильные LOD и exterior/interior;
- проверить геометрию в Blender;
- выбрать кости/объекты для `split_by_skin` из прочитанного списка;
- подтвердить границы `split_spatial`, предложенные по bounds объекта;
- подтвердить источник для `mirror_objects`;
- принять решение по ливрее и общим fallback-картам;
- сообщить имена и вид проблемных объектов для следующего итерационного правила.

Программа читает имена, кости и границы сама и проверяет правило до запуска Blender, но не назначает роль и не объявляет форму правильной: выбор и визуальная приёмка остаются за пользователем.

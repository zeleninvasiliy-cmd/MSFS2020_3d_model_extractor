# Reports and Audit

Каждый этап пишет машинный JSON-отчёт рядом с checkpoint. Отчёт — основной источник диагностики: он не заменяет визуальную проверку, но объясняет, что именно произошло.

## Общие поля (все этапы)

| Поле | Смысл |
|---|---|
| `blend` | путь созданного файла |
| `stage` | `geometry` / `textures` / `final` |
| `profile` | всегда `generic` |
| `build_variant`, `build_sequence` | имя варианта и номер — по ним выбирается точный исходный checkpoint |
| `models` | фактический состав моделей с ролями |
| `mesh_objects`, `triangles`, `vertices` | статистика сцены |
| `bounds_m` | `{min, max}` в метрах |
| `missing_uv` | объекты без UV |
| `empty_transforms` | пустые узлы |
| `collections` | распределение по коллекциям |
| `objects` | фактический состав сохранённой сцены |
| `review` | список сообщений «нужна проверка» |
| `incomplete` | истина при замечаниях → код возврата `2` |

## Отчёт геометрии

| Поле | Смысл |
|---|---|
| `sources` | по каждой модели: `path`, `skin`, `skinned_meshes`, `mesh_triangles`, `excluded_nodes`, `triangles`, `scalar_weight_repairs`, `manual_skin_repairs` |
| `sources[].skin` | `skins_removed`, `skinning_attributes_removed`, `repaired_roots`, `hybrid_reference`, `hybrid_applied`, `manual_detached_nodes` |
| `source_triangles` | ожидаемое число треугольников из draw ranges |
| `triangle_delta_before_cleanup` | расхождение с фактом **до** исключений — главный признак неверного `draw_mode` |
| `pose` | статистика bake: `armatures_removed`, `empties_hidden`, `survivor_names`, `modifiers_applied`, `modifier_failures`; пусто вне `bake` |
| `removed_objects` | что удалили исключения и фильтр runtime |
| `geometry_fixes` | результаты split, spatial split, mirror, placements |
| `object_catalog` | снимок **до** исключений: `{name, type, collections, group_path, source, source_node, parent, included}` |

`object_catalog` позволяет вернуть исключённые объекты при следующей сборке: список не теряет удалённые имена.

## Отчёт текстур

| Поле | Смысл |
|---|---|
| `missing_textures` | `[{material, map, filename}]` — вход для `find-textures` |
| `unreadable_images` | `{путь: ошибка}`, включая загрузки нулевого размера |
| `applied_materials`, `skipped_materials` | применённые и пропущенные (без glTF-происхождения) |
| `compressed_normals_to_review` | `{путь: codec}` — DXT5, не декодированные в `auto` |
| `decoded_normals` | `{путь: {codec, png}}` |
| `duplicate_content` | списки путей с одинаковым SHA-256 |
| `ambiguous_textures` | `{basename: [кандидаты]}` при более чем одном совпадении |
| `resolved_textures` | `{"kind:basename": путь}` |
| `texture_search_order`, `missing_fallback_dirs` | порядок поиска и недоступные fallback-каталоги |
| `used_images`, `packed_images`, `packing_failures` | упаковка в `.blend` |

`incomplete` вычисляется как `bool(gaps is None or gaps or packing_failures)`, где `gaps = len(missing_textures) + len(skipped_materials)`. Значение хранится и в свойстве сцены `msfs_pipeline_texture_gaps`.

Подробнее: [Textures and Materials](Textures-and-Materials).

## Свойства сцены и объектов

| Свойство | На чём | Зачем |
|---|---|---|
| `msfs_pipeline_models` | сцена | состав моделей для последующих этапов |
| `msfs_pipeline_texture_gaps` | сцена | число замечаний по картам |
| `msfs_source_role`, `msfs_pipeline_source` | mesh | происхождение: exterior/interior и путь glTF |
| `msfs_source_path` | материал | сопоставление с определением из glTF |
| `msfs_preview_hidden` | mesh | decal, скрытый на геометрическом этапе и возвращённый после текстурирования |

## Аудит готового `.blend`

```powershell
python .\scripts\msfs_universal.py audit .\blend\03_model_strip_auto_001.blend --output .\audit.json --blender "C:\Path\blender.exe"
```

`--output` обязателен; существующий файл не перезаписывается.

| Поле | Смысл |
|---|---|
| `summary` | `mesh_objects`, `same_base_name_groups`, `same_local_geometry_groups`, `same_world_geometry_groups`, `gear_candidates`, `far_disconnected_objects` |
| `same_base_names` | объекты с общим базовым именем (Blender-суффиксы `.001`) — признак дублей |
| `same_local_geometry` | совпадение по хешу локальной геометрии |
| `same_world_geometry` | совпадение по хешу мировой геометрии — настоящие дубли в пространстве |
| `gear_candidates` | похожие на стойки/колёса объекты |
| `far_disconnected_objects` | `component_count`, `spread_m`, `components[:20]` — разлёт островов > 0.5 м |
| `objects` | имя, источник, родитель, коллекции, вершины, грани, bounds, материалы |

`far_disconnected` и `same_world_geometry` — числовые подсказки о смещённых или продублированных деталях. Они указывают, **что** посмотреть, но не доказывают, что положение неверно.

Команда `objects` использует тот же аудит с `--objects-only` и возвращает чистый JSON для дерева GUI.

## Журналы и планы

| Файл | Содержимое |
|---|---|
| `<stage>-<run10>.log` | stdout/stderr Blender; при ошибке показываются последние строки |
| `<stage>-<run10>.plan.json` | точная спецификация, переданная worker — воспроизводимый снимок запуска |
| `<проект>/work/run-<uuid>.json` | снимок конфигурации GUI на запуск |
| `%LOCALAPPDATA%\MSFSModelBuilder\gui-errors.log` | необработанные исключения интерфейса |
| `%LOCALAPPDATA%\MSFSModelBuilder\package_index.json` | кэш индекса пакетов, не отчёт запуска; см. [Package Index](Package-Index) |

## Сводка индекса в выводе `catalog`

Кроме списка самолётов `catalog` возвращает блок `index` — он объясняет, откуда взялись разрешённые ссылки ливрей:

| Поле | Смысл |
|---|---|
| `packages` | сколько пакетов попало в индекс |
| `aircraft_names` | сколько различных имён самолётов |
| `cached`, `scanned` | сколько пакетов взято из кэша и просканировано заново |
| `errors` | недоступные каталоги: `{path, detail}`; скан остальных продолжается |

GUI печатает эту сводку в «Журнал» после каждого сканирования. Полный список пакетов, имён и состояния базовых самолётов открывает меню «Индекс пакетов…», а в CLI — команда `index`.

Поля `origin` у моделей и зависимостей в `inventory` показывают, откуда взят ресурс: `model.cfg`, `xml`, `scan`, `base_container`, `aircraft_index`, `base_package` или `ambiguous` при нескольких равных кандидатах. Подробный разбор — [Package Diagnosis](Package-Diagnosis).

## Что приложить к сообщению об ошибке

Версию программы и Blender, название и версию пакета, режимы сборки, текст ошибки из «Журнала», точные имена объектов и шаги воспроизведения. Файлы журналов и отчётов лежат рядом с результатами проекта. Весь пакет самолёта присылать не нужно — для первичной диагностики достаточно отчёта и кода причины.

Не добавляйте в issue игровые ресурсы, свои проекты, токены и абсолютные пути профиля.

Дальше: [CLI Reference](CLI-Reference) · [Troubleshooting](Troubleshooting) · [Testing](Testing)
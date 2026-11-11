# Textures and Materials

## English version

The texture stage reads material assignments from the selected glTF and resolves PBR maps through the package resolver. The table reports missing, substituted, duplicated and unreadable images. Texture replacements are keyed by the original map basename.

The worker handles common DDS/PNG maps, alpha modes, glass materials and normal-map conversion. When a normal map cannot be decoded safely, the report asks for manual review instead of silently producing a blank image. The original package remains untouched.

The GUI's installed-package search groups report URIs by map basename, deduplicates repeated file paths, labels each basename as a unique or ambiguous match and summarizes both counts. Adding suggested folders while any basename is ambiguous requires confirmation because automatic lookup can select a different livery; use an explicit per-map replacement when the exact file matters.

---

Текстурирование — отдельный этап, который открывается **после** подтверждённой пользователем геометрии. Он не меняет вершины.

## Карты MSFS

| Суффикс | Назначение |
|---|---|
| `ALBD` | albedo / base color |
| `COMP` | упакованные occlusion / roughness / metallic |
| `NORM` | normal map |
| `EMISSIVE` | эмиссия (приборы, подсветка) |

Материалы читаются из исходных glTF через расширение `MSFT_texture_dds` (`read_materials`). Файлы карт ищутся по basename в индексированных каталогах.

Каналы **COMP**: `R = occlusion`, `G = roughness`, `B = metallic`. К Principled BSDF подключаются `G` → Roughness и `B` → Metallic (с умножением на фактор материала); канал `R` разделяется, но в шейдере v1 не используется.

**NORM**: зелёный канал инвертируется в шейдере — MSFS хранит нормали в DirectX-соглашении, Blender ожидает OpenGL.

## Порядок поиска карты

1. `texture_overrides` — точное переопределение по basename (ключи без учёта регистра);
2. `converted_normal_dir` — уже декодированные PNG вида `<имя DDS>.png`;
3. первая папка из `texture_dirs`, содержащая basename.

`texture_dirs` строится по цепочке `fallback.N` из `texture.cfg` рекурсивно, затем добавляются `extra_texture_dirs`. Ссылка, которой нет на диске внутри пакета ливреи, переносится в базовый пакет через [индекс пакетов](Package-Index.md) (`origin=base_package`). Флажок «Подключать все texture.*» расширяет поиск на другие ливреи.

При одинаковых именах изображений разные ливреи конфликтуют. Для предсказуемого результата сначала используйте выбранную ливрею и её штатные fallback-каталоги. Все неоднозначности попадают в `ambiguous_textures`.

## DDS и нормали

Blender не читает BC5-нормали как изображение нормалей. Декодер `msfs_dds_normals.py`:

- определяет формат по заголовку (DX10 DXGI 83/84, fourcc `BC5S`/`BC5U`/`ATI2`, DXT5);
- декодирует BC4-блоки, восстанавливает `Z = sqrt(1 − x² − y²)`;
- пишет PNG потоково через zlib, ограничение 8192×8192;
- сохраняет в `decoded_normals/<sha256[:10]>-<имя>.png`; в рамках одного запуска карта декодируется один раз, при повторной сборке — заново с перезаписью файла.

| `normal_decode` | Поведение |
|---|---|
| `auto` | декодирует BC5S/BC5U; DXT5 оставляет и записывает в `compressed_normals_to_review` |
| `dxt5n` | дополнительно декодирует DXT5 по зелёному каналу |
| `off` | не декодирует; BC5 может загрузиться с размером (0,0) → `unreadable_images` |

## Стекло и прозрачность

Стеклянные материалы определяются по расширениям Asobo (`kitty_glass`, `glass`, `windshield_v2`) и эвристике: transmission 0.85, alpha 0.38. Alpha mode glTF (`OPAQUE`, `MASK`, `BLEND`) переводится в настройки Blender (`DITHERED`; в старых версиях — `CLIP`/`BLEND`). Отдельно применяется исправление непрозрачности fiberglass.

На геометрическом этапе материалы **нейтрализуются**: серый Principled, прозрачный для превью стекла и decal. Объекты, целиком состоящие из decal, скрываются с флагом `msfs_preview_hidden` и возвращаются после текстурирования. Это нужно, чтобы служебные проекции не мешали проверке формы.

## Упаковка

Изображения упаковываются в `.blend`, поэтому финальный файл переносится на другой ПК без исходных карт. Отчёт содержит `used_images`, `packed_images`, `packing_failures`. Ошибки упаковки дают код возврата `2` («Готово с замечаниями»), а не потерю файла.

Дубликаты по содержимому выявляются через SHA-256 и попадают в `duplicate_content` — это подсказка, что одна карта используется под разными именами.

## Недостающие карты

Отчёт содержит:

| Поле | Смысл |
|---|---|
| `missing_textures` | `[{material, map: albd\|comp\|norm\|emissive, filename}]` |
| `unreadable_images` | `{путь: ошибка}`, включая загрузки нулевого размера |
| `skipped_materials` | материалы без сопоставления с glTF-происхождением |
| `compressed_normals_to_review` | DXT5, не декодированные в режиме `auto` |
| `decoded_normals` | `{путь: {codec, png}}` |
| `ambiguous_textures` | `{basename: [кандидаты]}` при более чем одном совпадении |
| `resolved_textures` | `{"kind:basename": путь}` |
| `texture_search_order`, `missing_fallback_dirs` | порядок поиска и недоступные fallback-каталоги |

`missing_fallback_dirs` — часто ожидаемый шум: MSFS объединяет пакеты через VFS, поэтому `texture.cfg` ссылается на папки вне локального пакета.

### Поиск по всем пакетам

```powershell
python .\scripts\msfs_universal.py find-textures .\blend\02_textured_strip_auto_001.json
```

Команда обходит все корни пакетов и сопоставляет basename без учёта регистра, поддерживая MSFS-относительные URI (`..\TEXTURE4\FROST_ALBD.PNG.DDS`). Результат: `matches`, `suggested_extra_texture_dirs`, `missing`.

Каталоги из `suggested_extra_texture_dirs` добавляются в `extra_texture_dirs`, затем этап повторяется. Для одной конфликтующей карты используйте `texture_overrides`.

### Таблица карт в GUI

Всё перечисленное делается кнопками: «4. Текстуры» → **«Таблица карт...»** ([Rule Editors](Rule-Editors.md)). Окно показывает одну строку на базовое имя карты с её состоянием, путём и материалами, а поля отчёта с ключом-путём (сжатые и распакованные нормали, нечитаемые изображения, дубликаты) приводятся к тому же имени, чтобы карта не распадалась на две строки из-за регистра.

| Задача | Кнопка |
|---|---|
| посмотреть, что не нашлось и почему | таблица и панель подробностей |
| подставить свой файл | «Заменить...» — пишет `texture_overrides` под именем карты **из glTF** |
| выбрать один из найденных программой путей | «Выбрать из кандидатов...» |
| найти карту в других установленных пакетах | «Найти в установленных пакетах» — CLI `find-textures` |
| вернуть автоматический поиск | «Сбросить замену» |

Поиск в установленных пакетах группирует URI по basename карты, убирает повторяющиеся пути, помечает каждую карту как однозначную или неоднозначную и показывает обе сводные цифры. Если есть неоднозначные совпадения, перед добавлением предложенных папок программа запрашивает подтверждение: автоматический поиск может выбрать другую ливрею. Для точной карты используйте явную замену отдельного файла.

Отчёт берётся из `02_textured*.json` последней сборки: итоговый `03_model*.json` содержит только геометрию и карты не скрывает. Замена применяется при следующем запуске «Добавить textures» или «Весь цикл».

### Динамические изображения

Приборы и дисплеи, которые симулятор рисует во время работы, могут не иметь готовой текстуры в пакете. Их отсутствие в отчёте — не ошибка сборки. Такие поверхности остаются без карты или с базовым материалом.

## Происхождение материалов

Worker пишет на меш `msfs_source_role` и `msfs_pipeline_source`, на новые материалы — `msfs_source_path`. По этому признаку материал сопоставляется с определением из нужного glTF. Для старых checkpoint без признака используется сопоставление по имени файла, что неоднозначно при одинаковых basename двух моделей.

Дальше: [Rule Editors](Rule-Editors.md) · [Build Modes](Build-Modes.md) · [Troubleshooting](Troubleshooting.md)

---

# Build Modes

Три независимых переключателя влияют на результат. Ни один из них не «правильный вообще»: выбор зависит от того, как пакет хранит геометрию. Визуальную правильность подтверждает пользователь в Blender.

## `skinning`

MSFS хранит части самолёта привязанными к костям анимации. Задача — получить статическое положение без импорта анимаций.

| Режим | Что делает | Когда пробовать | Риск |
|---|---|---|---|
| `strip` (по умолчанию) | удаляет `node.skin`, `skins`, `JOINTS_0/1`, `WEIGHTS_0/1` из подготовленного glTF; вершины остаются там, где их положил источник | первый прогон всегда | части, зависящие от костей, могут остаться в bind-pose, получить pivot-смещение или разойтись по сторонам |
| `manual` | сохраняет **статические вершины MSFS в координатах самолёта**, не вычисляя деформацию костями; удаляет `matrix/translation/rotation/scale` узла («animation pivot»), затем отвязывает mesh от родителя и ставит единичную мировую матрицу | детали смещены или развёрнуты из-за pivots, нестандартных весов, zero-scale драйверов | **не вычисляет деформацию костями**; если деталь действительно должна быть деформирована, положение останется исходным |
| `bake` | импортирует armature, применяет ARMATURE-модификаторы в `REST`/`POSE`, удаляет арматуру, восстанавливает мировые матрицы | вся модель неправильно зависит от armature | нестандартные skeleton roots, scalar weights и несовместимые bind matrices могут дать ошибку импорта или неверное положение; отказ модификатора — жёсткая ошибка |
| `hybrid` | основа через `strip`; сначала импортируется одноразовая **baked-копия**, запоминаются мировые координаты вершин целей, затем вершины выбранных объектов переносятся в эти координаты | несколько проблемных деталей при в целом правильной основе | требует **identical vertex и polygon counts** между bake и strip; пустой список целей отклоняется ещё в конфиге |

`manual_keep_pivots` — список имён узлов glTF, чьи pivots сохраняются в режиме `manual`. Полезно, когда конкретной детали нужен её узел.

`repair_skin_roots` — попытка восстановить skeleton roots по именам skin/node; применяется в `bake` и в bake-эталоне режима `hybrid`.

`pose_position` (`REST` по умолчанию, либо `POSE`) действует только в `bake`/`hybrid`.

### Порядок диагностики

1. `strip` — первый прогон;
2. если wing/engine/control surface смещены из-за pivot — `manual`;
3. если только несколько объектов требуют настоящей оценки костей — `hybrid` + цели;
4. если вся модель неправильно зависит от armature — `bake`.

Каждый режим сохраняется отдельным пронумерованным checkpoint, поэтому сравнение ничего не перезаписывает.

### Как выбрать цели hybrid в GUI

На вкладке «3. Геометрия» выделите объект или группу в дереве и нажмите **«Hybrid: выбранная деталь»**. Кнопка переключает имя в `hybrid_bake_objects`; счётчик показывает число выбранных деталей. Имена экранируются как точные шаблоны, а не glob. Программа не проверяет, что объект действительно skinned — это остаётся на пользователе.

## `draw_mode`

MSFS упаковывает индексы в draw ranges внутри `extras.ASOBO_primitive`. Режим определяет, как читать индексы.

| Режим | Поведение |
|---|---|
| `auto` (по умолчанию) | **по каждому primitive**: MSFS-декодирование, если есть `extras.ASOBO_primitive`, иначе обычные индексы glTF |
| `msfs` | принудительно MSFS-декодирование для каждого primitive; если у primitive нет `extras.ASOBO_primitive`, сборка отклоняется с сообщением, где указаны путь glTF, имя mesh, индекс primitive и совет использовать `auto` |
| `standard` | никогда не распаковывать; обычные треугольники glTF |

Распаковка: `StartIndex` (по умолчанию 0), `PrimitiveCount` — число **треугольников** (индексов в 3 раза больше), `BaseVertexIndex` прибавляется к каждому индексу. Winding разворачивается (`triangles[:, ::-1]`), потому что packaged MSFS хранит обратный порядок вершин относительно стандартного glTF.

Преобразование упакованных **атрибутов** вершин выполняется всегда, когда primitive распознан как MSFS, независимо от `draw_mode`.

Начинать следует с `auto`. `msfs` нужен для диагностики packaged MSFS glTF, `standard` — для обычного glTF без MSFS-расширений. Сравнивайте `source_triangles` и `triangle_delta_before_cleanup` в отчёте.

## `normal_decode`

Нормальные карты MSFS часто лежат в DDS с BC5S/BC5U или DXT5, которые Blender не читает как нормали.

| Режим | Поведение |
|---|---|
| `auto` (по умолчанию) | декодирует BC5S/BC5U в PNG; DXT5 оставляет как есть и записывает в `compressed_normals_to_review` |
| `dxt5n` | дополнительно декодирует DXT5 по зелёному каналу (BC4-стиль) |
| `off` | не декодирует; BC5 может загрузиться в Blender с размером (0,0) и попасть в `unreadable_images` |

Декодер восстанавливает Z как `sqrt(1 − x² − y²)`, ограничение 8192×8192. Результат пишется в `decoded_normals/<sha256[:10]>-<имя>.png` внутри каталога результатов. В рамках одного запуска каждая карта декодируется один раз; при повторной сборке декодирование выполняется заново и файл перезаписывается.

Шейдер всегда инвертирует зелёный канал NORM (DirectX → OpenGL).

Альтернатива декодированию на лету — `converted_normal_dir` с уже готовыми PNG: приоритет выше, чем у исходных DDS.

## Что режимы НЕ делают

- Не восстанавливают отсутствующий interior или недостающий LOD.
- Не исправляют неверное назначение ролей моделям.
- Не доказывают правильную форму: название режима не является результатом визуальной проверки.
- Не влияют на доступность пакета — причины недоступности описаны в [Package Diagnosis](Package-Diagnosis), и смена skinning там не поможет.

Дальше: [MSFS glTF Format](MSFS-glTF-Format) · [Object Organization](Object-Organization) · [Troubleshooting](Troubleshooting)

---

## English version

Build modes are deliberately independent so a user can compare results:

- `geometry` imports the selected exterior/interior glTF files and writes a numbered Blender file.
- `textures` reads a geometry checkpoint and attaches the selected PBR maps.
- `final` creates the final report and saves the completed variant.
- `all` runs the stages in order.

`draw_mode` selects automatic MSFS primitive handling or an explicit mode. `split_by_skin` separates skinned parts, `split_spatial` cuts by object bounds, `mirror_objects` creates a reflected copy, and `placements` uses only the anchor translation while preserving the part rotation and scale. DDS normal decoding is reported when it is ambiguous. Re-running a mode creates the next sequence number instead of overwriting a checkpoint.

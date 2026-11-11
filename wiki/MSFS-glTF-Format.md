# MSFS glTF Format

## English version

The adapter reads the glTF JSON and its available buffers, maps MSFS attributes and creates Blender meshes and materials. It validates primitive modes, indices, accessors, winding and node transforms before creating the scene.

Supported resources depend on the installed package and the current adapter. Missing buffers, unsupported extensions and malformed containers are reported before Blender. The program does not silently replace a failed primitive with an approximate mesh. See [Known Issues](Known-Issues.md) for the current limits.

Geometry compressed with `KHR_draco_mesh_compression` or `EXT_meshopt_compression` is not decoded. Deep diagnosis detects the extension at its declaration/use site, and the Blender worker repeats the guard so a build cannot silently import compressed bytes as ordinary geometry. Decompress the source in its exporter or choose another LOD. Neither extension appeared in the 285 glTF models selected by the current local deep catalog scan.

---

Microsoft Flight Simulator 2020 хранит модели в glTF 2.0 с расширениями Asobo. Стандартный импортёр Blender такие файлы читает неверно: индексы упакованы в draw ranges, атрибуты сжаты, winding обратный. Эта страница описывает особенности, которые обрабатывает `scripts/msfs_geometry.py`.

## Draw ranges: `ASOBO_primitive`

В `primitive.extras.ASOBO_primitive`:

| Поле | Смысл | По умолчанию |
|---|---|---|
| `StartIndex` | смещение в accessor индексов | `0` |
| `PrimitiveCount` | число **треугольников** (индексов втрое больше) | обязательное |
| `BaseVertexIndex` | прибавляется к каждому индексу | `0` |

Декодирование (`unpack_indices`):

1. проверить `mode == 4` и `0 <= start < start + 3*count <= accessor.count`;
2. прочитать индексы (`5123` → `<u2`, `5125` → `<u4`);
3. взять срез `[start : start + 3*count]`, reshape в треугольники;
4. **развернуть winding**: `triangles[:, ::-1]` — packaged MSFS хранит обратный порядок вершин относительно стандартного glTF;
5. прибавить `BaseVertexIndex`;
6. проверить, что максимальный индекс не выходит за accessor POSITION;
7. записать новый accessor `5125/SCALAR/34963`.

Возвращается число треугольников — оно попадает в отчёт как ожидаемое и сравнивается с фактическим (`triangle_delta_before_cleanup`).

## Упакованные атрибуты вершин

`unpack_vertex_attributes` приводит сжатые данные к float:

| Атрибут | componentType | Преобразование |
|---|---|---|
| `TEXCOORD_*` | `5122` | half-float `<f2` |
| `NORMAL`, `TANGENT` | `5120` | signed byte / 127, clamp ≥ −1; ширина 3 или 4 |
| `COLOR_*` | `5120` | unsigned / 255 |
| `COLOR_*` | `5123` | half-float |
| `JOINTS_*`, `WEIGHTS_*` | — | не трогаются на этом шаге |
| прочее | — | ошибка с пояснением |

Преобразование выполняется, когда primitive распознан как MSFS, **независимо** от `draw_mode`.

## Scalar weights

MSFS часто хранит привязку к одной кости как SCALAR FLOAT вместо VEC4. `normalize_scalar_skin_weights` разворачивает такое значение в `[w, 0, 0, 0]` и отмечает число исправлений в отчёте (`scalar_weight_repairs`). Без этого Blender не импортирует JOINTS/WEIGHTS.

## Узлы и трансформации

- `rotation` в glTF — порядок **XYZW**; Blender ожидает WXYZ. Чтение: `x, y, z, w = node.get("rotation", (0,0,0,1))`.
- `matrix` — column-major, при чтении транспонируется.
- Иерархия проверяется на циклы и много-parenting до вычисления мировых матриц.
- Ось MSFS Y-up приводится к Blender Z-up; в split-by-skin порядок вершин сверяется после свапа `[:, [0,2,1]] * [1,-1,1]`.

## Буферы и контейнеры

Общий загрузчик `scripts/msfs_gltf.py` нормализует JSON glTF и GLB к документу
плюс списку байтовых буферов:

- один или несколько локальных BIN с относительными URI;
- embedded `data:` URI;
- GLB version 2 с JSON и BIN chunks;
- buffer без `uri` внутри GLB;
- объединение нескольких buffers с перебазированием `bufferView` offsets.

Перед импортом Blender подготовленный glTF получает единый `geometry.bin`,
поэтому MSFS draw-range декодер и статический skinning работают одинаково для
JSON glTF и GLB. Sparse accessors и стандартные `TRIANGLE_STRIP`/`TRIANGLE_FAN`
материализуются перед импортом; точки, линии, Draco и Meshopt пока не декодируются.
Сжатие `KHR_draco_mesh_compression` и `EXT_meshopt_compression` обнаруживается по
extensions и местам его применения как resolver-ом, так и перед обработкой в
Blender worker. У сжатого источника можно выбрать другой LOD или распаковать
геометрию в экспортёре. В 285 glTF-моделях текущего локального каталога эти два
расширения не встретились.

## Runtime и невидимые узлы

Фильтр `filter_runtime` (по умолчанию включён) удаляет узлы по токенам имени:

```
blur, frost, colision, collision, occluder, _slow, tuto_
```

(`colision` — опечатка, реально встречающаяся в пакетах MSFS, поэтому оставлена.)

Невидимые расширения: `ASOBO_material_invisible`, `ASOBO_material_environment_occluder`. Runtime-материалы: `PROPELERSIDE`, `TutoMeshes`.

Стеклянные расширения: `ASOBO_material_kitty_glass`, `ASOBO_material_glass`, `ASOBO_material_windshield_v2` — по ним геометрия остекления помечается для превью и последующей настройки прозрачности.

## Что выбрасывается при подготовке

Из подготовленного glTF удаляются `animations`, `images`, `textures`, `samplers`, `extensionsUsed`, `extensionsRequired`. Геометрический этап не должен тянуть за собой текстуры и анимации: материалы нейтрализуются, карты подключаются отдельным этапом.

## Manual static skin path

`manual_skin_vertices` сохраняет POSITION в координатах самолёта, **не вычисляя** матрицы костей, добавляет новые VEC3 accessors и удаляет `matrix/translation/rotation/scale` skinned-узла, если его имя не входит в `manual_keep_pivots`. Это устраняет повторное применение animation pivot импортёром Blender, из-за которого детали разворачивались и смещались. Число исправлений попадает в `manual_skin_repairs`.

Режим не заменяет `bake`: деформацию костями он не считает.

## Материалы

`read_materials` извлекает ALBD/COMP/NORM/EMISSIVE через расширение `MSFT_texture_dds`. Каналы COMP: **R = occlusion, G = roughness, B = metallic**. NORM требует инверсии зелёного канала (DirectX → OpenGL). Подробности: [Textures and Materials](Textures-and-Materials.md).

## Диагностика против декодирования

Resolver (`inspect_gltf`) проверяет документ **до** сборки и сообщает о
неподдерживаемых конструкциях. Общий загрузчик используется также командой
`bones` и `split_by_skin`, поэтому GLB не теряет имена суставов. Декодер
(`msfs_geometry`) на оставшихся ограничениях падает с пояснением. Это
намеренное разделение: понятное ограничение не должно превращаться в аварию
worker.

Дальше: [Build Modes](Build-Modes.md) · [Package Diagnosis](Package-Diagnosis.md) · [Textures and Materials](Textures-and-Materials.md)

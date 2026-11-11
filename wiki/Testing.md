# Testing

## English version

The repository test suite is synthetic and does not require an MSFS installation. Run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python msfs_builder_gui.py --self-test
python -c "import compileall; raise SystemExit(0 if compileall.compile_dir('.', quiet=1) else 1)"
```

The Windows GitHub Actions job repeats compilation, GUI startup and the regression suite. Tests cover package resolution, inheritance, model selection, GUI state, editing rules, texture tables, glTF metadata and pipeline locks. Real aircraft and Blender acceptance remain user checks.

An additional local, no-render smoke sample uses the normal GUI-generated project config and `build --stage geometry` CLI, then the normal checkpoint audit, with temporary outputs. M18 covered five representative packages; M20 added eight more across float/wheel DHC-2, G-21, JN-4, DC-3, Spirit of St. Louis, A320neo and a four-engine generic model. All 8 built one checkpoint and passed the audit. Path-free measurements are in [headless_import_sample_m20.json](../compatibility/headless_import_sample_m20.json). Audit duplicate/disconnected counts are review hints and do not certify visual correctness.

M21 exercises the explicit model-selection path on six real partial or incomplete packages. Candidates come from `models`; the role-separated chooser state is confirmed through the GUI callback; `make_config` creates the project config; then normal geometry build and audit run. All 6 built one checkpoint and passed the structural audit, including a Pitts livery whose interior came from the indexed base package. The other cases include exterior-only partial liveries, invalid model.cfg files and an A310 without model.cfg. Path-free evidence is in [headless_model_choice_sample_m21.json](../compatibility/headless_model_choice_sample_m21.json). Filename-based roles are suggestions the user must verify visually; a successful import is not visual acceptance.

M23 broadens the sample to rotorcraft. Seven installed rotorcraft from different packages (Cabri G2 variants, Cowan R22/R66, Mi-2 and Bell 407) each produced one checkpoint and passed Blender audit; build time was 7.7–30.6 seconds. The installed RSP R44 remains blocked before Blender by `UNRESOLVED_ALIAS` because its declared base aircraft is absent. The path-free report is [headless_rotorcraft_sample_m23.json](../compatibility/headless_rotorcraft_sample_m23.json). All sampled sources use JSON glTF with one local buffer and `MSFT_texture_dds`; this measures worker/package coverage but does not exercise GLB or other geometry encodings.

M25 checks nine float/ski configurations plus the large Hughes H-4 flying boat. All 9 built one checkpoint and passed audit, in 7.1–17 seconds. The catalog selected the `model.floats` folder for XCub floats and ordinary `model` folders for the other variants. Path-free results are in [headless_float_ski_large_aircraft_m25.json](../compatibility/headless_float_ski_large_aircraft_m25.json). This verifies import and variant resolution, not the visual placement of floats or skis.

M27 reran `audit-plans` over the live installation: 226/226 geometry-buildable entries validated, zero rejected, zero index errors, complete scope. Adding the user's An-2 package root raised the catalog to 237 entries and 230/230 valid plans; all four An-2 configurations were available. The remaining seven records are classified by explicit non-buildable reasons. Path-free counts are in [live_plan_audit_m27.json](../compatibility/live_plan_audit_m27.json). Plan validation does not guarantee Blender import or visual correctness.

M28 exercises the 15-variant A320neo package with no `model.cfg`. The GUI chooser explicitly confirmed the available exterior and interior LOD01 candidates from separate model folders; the normal builder created one 129 MB checkpoint and Blender 5.2 audit passed with 2,259 mesh objects. The audit also reported 3 same-world-geometry groups and 484 far-disconnected objects; these are inspection hints, not proof of defects. No render or visual acceptance was performed. See [headless_a320neo_model_choice_m28.json](../compatibility/headless_a320neo_model_choice_m28.json).

M29 adds a 17-aircraft geometry import sample from previously unimported installed packages: Caravan 208B, Baron G58 livery, CAP 10C, CJ4, DA40 NG, DG1001E, DV20 livery, F/A-18E, generic private jet, King Air 350, Longitude livery, LS8, Pipistrel livery, TBM 930, Wright Flyer, 103 Solo livery and SR22 livery. All 17 produced one checkpoint and passed Blender 5.2 audit through GUI-generated configuration and the normal CLI; six partial packages used the explicit model chooser. This remains structural smoke coverage, not visual approval. See [headless_broad_import_sample_m29.json](../compatibility/headless_broad_import_sample_m29.json).

M31 tested the complete geometry→textures path on 11 varied aircraft, including the large multi-variant A320neo. All 11 produced geometry and textured checkpoints and passed final Blender 5.2 audit. Eight texture reports were complete; three partial liveries reported missing maps and returned code 2 while still producing an auditable checkpoint. Inventory confirmed their base aircraft packages are absent, and `find-textures` found 27/28 Baron, 21/22 Pipistrel and 203/206 SR22 unique maps unavailable in installed roots. This is missing source data, not a failed resolver. See [headless_texture_stage_sample_m31.json](../compatibility/headless_texture_stage_sample_m31.json).

The compatibility audit is reproducible without committing aircraft files: run `python scripts/msfs_universal.py catalog --deep > catalog.json`, then `python scripts/compatibility_report.py catalog.json --output compatibility/compatibility_snapshot.json`. The report keeps counts, affected-aircraft totals and unique missing targets by blocker, stable dependency `problem_code`s and a path-free format matrix (unique models, source formats, extensions, primitive modes and sparse accessors); machine-specific paths are discarded. The detailed GUI diagnosis groups dependency states and gives a next step for missing or ambiguous links; optional texture fallback targets are distinguished when their aircraft folder is not installed. Human-readable `detail` strings are not used as the primary machine classification.

The shared configuration validator rejects unknown fields in both the graphical rule preflight and the build command. The catalog suppresses only a non-buildable `fs-base-history` placeholder shadowed by a same-name geometry-buildable package, and records the suppressed path for diagnostics. Package-index fixtures also cover resource-only packages, manifest dependency resolution and ambiguity-safe VFS rebasing. Format regressions cover compression declarations on glTF primitives and buffer views; the resolver and worker both reject Draco/Meshopt geometry before importing it as ordinary triangles.

---

Три уровня проверки. Игровые ресурсы не используются нигде: все входы синтетические, поэтому набор проходит на GitHub Actions без MSFS и Blender.

Аудит совместимости воспроизводится отдельно: `catalog --deep` проверяет установленные glTF/GLB и BIN до создания проекта, а `scripts/compatibility_report.py` сохраняет только безопасную сводку: число затронутых самолётов и число уникальных целей по типу блокера, стабильные `problem_code` неразрешённых связей, уникальные модели, форматы, расширения, primitive modes и sparse accessors — без личных путей. Пропущенные fallback можно отдельно увидеть как цель на самолёт, которого нет в выбранных каталогах, через `optional_texture_target_aircraft_missing`. Человекочитаемое поле `detail` отделено от классификации, поэтому перевод интерфейса не меняет статистику. Снимок для текущей рабочей версии создаётся той же командой после обновления каталога.

Дополнительно локально проверяются реальные сборки без рендера: GUI формирует конфигурацию проекта, CLI выполняет `build --stage geometry`, затем запускается аудит checkpoint; временные результаты удаляются. В M18 проверено 5 пакетов, в M20 добавлено ещё 8: DHC-2 на поплавках и колёсах, G-21, JN-4, DC-3, Spirit of St. Louis, A320neo и четырёхмоторная общая модель. Все восемь создали по одному checkpoint и прошли аудит. Сводка без личных путей: [headless_import_sample_m20.json](../compatibility/headless_import_sample_m20.json). Число совпадений и разнесённых компонент — только подсказки для просмотра; оно не доказывает визуальную правильность модели.

M21 проверяет явный выбор моделей на шести реальных частичных или неполных пакетах: кандидаты получены командой `models`, роли подтверждены через обработчик мастера GUI, конфигурация сформирована `make_config`, затем выполнены обычная геометрическая сборка и аудит. Все 6 создали по одному checkpoint и прошли структурную проверку; в том числе интерьер ливреи Pitts найден через индекс в базовом пакете. Также проверены частичные ливреи только с экстерьером, некорректные `model.cfg` и A310 без `model.cfg`. Отчёт без личных путей: [headless_model_choice_sample_m21.json](../compatibility/headless_model_choice_sample_m21.json). Роль по имени файла остаётся подсказкой, которую надо проверять визуально; успешный импорт не заменяет визуальную приёмку.

M23 расширил выборку винтокрылыми моделями. Семь установленных вертолётов из разных пакетов (Cabri G2, Cowan R22/R66, Ми-2 и Bell 407) создали по одному checkpoint и прошли аудит Blender; сборка заняла 7,7–30,6 секунды. Установленный RSP R44 остановлен до Blender с `UNRESOLVED_ALIAS`: заявленная базовая модель отсутствует. Отчёт без личных путей: [headless_rotorcraft_sample_m23.json](../compatibility/headless_rotorcraft_sample_m23.json). Все проверенные источники используют JSON glTF с одним локальным буфером и `MSFT_texture_dds`; это проверяет обработку пакетов и worker, но не охватывает GLB и другие кодировки геометрии.

M25 проверяет девять вариантов с поплавками/лыжами и большую летающую лодку Hughes H-4. Все 9 создали по одному checkpoint и прошли аудит за 7,1–17 секунд. Каталог выбрал `model.floats` для поплавкового XCub и обычный каталог `model` для остальных вариантов. Сводка без личных путей: [headless_float_ski_large_aircraft_m25.json](../compatibility/headless_float_ski_large_aircraft_m25.json). Эта проверка подтверждает импорт и выбор model-folder, но не визуальное положение поплавков или лыж.

M27 повторил `audit-plans` для установленного каталога: 226/226 доступных геометрических планов прошли проверку, отказов и ошибок индекса — 0, охват полный. С дополнительным корнем An-2 каталог содержит 237 записей и 230/230 валидных планов; доступны все четыре варианта Ан-2. Остальные семь записей имеют явные причины недоступности. Сводка без личных путей: [live_plan_audit_m27.json](../compatibility/live_plan_audit_m27.json). Валидный план не гарантирует импорт в Blender или визуальную корректность.

M28 проверяет пакет A320neo с 15 вариантами и без `model.cfg`. В мастере GUI явно подтверждены доступные LOD01 экстерьера и интерьера из разных model-папок; штатная сборка создала один checkpoint размером 129 МБ, аудит Blender 5.2 прошёл на 2 259 mesh-объектах. Аудит также сообщил о 3 группах совпадающей мировой геометрии и 484 разъединённых объектах; это подсказки для осмотра, а не доказанные дефекты. Рендер и визуальная приёмка не выполнялись. Отчёт: [headless_a320neo_model_choice_m28.json](../compatibility/headless_a320neo_model_choice_m28.json).

M29 добавляет выборку импорта геометрии из 17 ранее не проверенных установленных пакетов: Caravan 208B, ливрея Baron G58, CAP 10C, CJ4, DA40 NG, DG1001E, ливрея DV20, F/A-18E, типовой частный реактивный самолёт, King Air 350, ливрея Longitude, LS8, ливрея Pipistrel, TBM 930, Wright Flyer, ливрея 103 Solo и ливрея SR22. Все 17 создали по одному checkpoint и прошли аудит Blender 5.2 через конфигурацию GUI и обычный CLI; для шести частичных пакетов использован явный мастер выбора модели. Это структурная проверка импорта, а не визуальная приёмка. Отчёт: [headless_broad_import_sample_m29.json](../compatibility/headless_broad_import_sample_m29.json).

M31 проверил полный путь «геометрия → текстуры» на 11 разных самолётах, включая крупный A320neo с несколькими вариантами моделей. Все 11 создали геометрический и текстурированный checkpoint и прошли итоговый аудит Blender 5.2. Восемь текстурных отчётов были полными; три частичные ливреи сообщили об отсутствующих картах и вернули код 2, хотя checkpoint был создан и прошёл аудит. Inventory подтвердил отсутствие базовых самолётов, а `find-textures` не нашёл в установленных корнях 27/28 карт Baron, 21/22 Pipistrel и 203/206 карт SR22. Это нехватка исходных ресурсов, а не ошибка resolver. Отчёт: [headless_texture_stage_sample_m31.json](../compatibility/headless_texture_stage_sample_m31.json).

## 1. Регрессия без Blender и без MSFS

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python msfs_builder_gui.py --self-test
```

Тесты не сканируют установленный MSFS и не пишут в пользовательский кэш. Реальные самолёты и визуальная приёмка Blender остаются ручной проверкой пользователя.

### `tests/test_resolver.py` — 33 сценария

Диагностика пакетов до сборки. Каждый сценарий создаёт минимальное дерево во временном каталоге.

| Группа | Что проверяется |
|---|---|
| независимость | модуль не импортирует `bpy` и не содержит `import bpy` |
| полный пакет | `OK`, геометрия и текстуры доступны, не partial, не требует выбора |
| общие ресурсы | `COMMON_RESOURCES_ONLY` для XML без glTF/BIN |
| алиасы | `UNRESOLVED_ALIAS`; разрешение по имени в другом корне |
| неполный состав | отсутствующий interior → `SUPPORTED_PARTIAL`; interior из соседнего пакета |
| model.cfg | cfg без `[models]` → `INVALID_MODEL_CFG`; отсутствующий cfg → `MISSING_MODEL_CFG` |
| model XML | LOD-список без cfg; незаэкранированный `<` в `Behaviors` не ломает разбор |
| BIN | shallow против deep; отсутствующий BIN единственной модели блокирует сборку |
| build-plan | общий glTF, объявленный за экстерьер и интерьер, импортируется один раз; `audit-plans` валидирует синтетический установленный пакет без запуска Blender; отсутствующий корень помечает охват неполным |
| glTF | GLB, несколько buffers, data URI, sparse, triangle strip/fan; Draco и Meshopt отклоняются до worker; не-треугольный mode; нечитаемый JSON; LOD01 спасает ситуацию |
| обнаружение | объявленный XML отсутствует, но LOD glTF есть; уже отвергнутый путь не предлагается повторно; найденный GLB с отсутствующим BIN или неподдерживаемым расширением отклоняется в deep |
| структура | exterior/interior в разных `model.*`; одна модель на роль при нескольких кандидатах; `msfs_gui_build` исключён; ливрея без model доходит до inventory; корень пакета с общей `texture` не мешает спуску; лист под `Airplanes` с общими ресурсами и заглушка |
| карты | геометрия без изображений → `NO_TEXTURES` |
| отказ | отсутствующая папка → `PACKAGE_NOT_FOUND` |

`PlanDiagnosisTests`: частичный пакет требует явных `models` (ошибка содержит «Диагностика пакета» и `SUPPORTED_PARTIAL`, затем сборка проходит с заданным составом); common-only отклоняется с причиной.

`tests/test_gltf.py` проверяет JSON/GLB контейнеры, несколько буферов, data URI и общий детектор сжатия Draco/Meshopt на primitive и bufferView.

### `tests/test_index.py` — 39 сценариев

[Индекс пакетов](Package-Index) и его влияние на диагностику. Тоже синтетическое дерево во временном каталоге, без bpy и без MSFS.

| Группа | Что проверяется |
|---|---|
| независимость | `package_index.py` не содержит `import bpy` |
| индекс | самолёт и пакет проиндексированы, ресурсные пакеты без самолёта найдены в Official/Community, `content_type` прочитан, поиск по имени регистронезависим |
| перенос | якорь по имени самолёта; хвост внутри корня пакета → базовый пакет; существующий путь возвращается без подмены и нормализуется |
| честность | отсутствующая база не выдумывается; владелец не считается собственной базой; цикл в объявлениях не зацикливает |
| неоднозначность | несколько пакетов с одним именем → `ambiguous` и список кандидатов, а не угадывание |
| кэш | повторное использование по сигнатуре; инвалидация при добавлении самолёта (`os.utime`); другой список корней игнорируется; повреждённый JSON игнорируется |
| ошибки | недоступный корень попадает в `errors`, остальные сканируются |
| cfg | комментарий `;` и кавычки в `base_container` снимаются |
| описание | `describe` помечает установленную и отсутствующую базу, фильтр по точному имени без учёта регистра |
| наследование | ливрея получает интерьер из базового пакета и становится `OK`; без индекса та же ливрея `SUPPORTED_PARTIAL`; отсутствующая база оставляет partial; неоднозначная настоящая база сообщается; shadowed `fs-base-history` не создаёт ложный конфликт |
| причины | «базовый самолёт не установлен» против «базовый самолёт установлен, но объявленный файл в нём отсутствует» |
| сборка | `model_from_cfg` возвращает перенесённый путь с `origin=aircraft_index`; manifest-зависимости и общие VFS-пути ищутся по пакетам ресурсов; неоднозначность не угадывается и не вызывает сбой диагностики |

### `tests/test_pipeline.py` — 15 проверок

Оркестратор; Blender подменён только на границе процесса.

- нумерация изолирована по режимам и не ограничена тремя цифрами (999 → 1000 → 1001);
- отсутствующая зависимость этапа отклоняется **до** запуска Blender;
- legacy-checkpoint без номера распознаётся;
- устаревшая блокировка снимается, живая уважается;
- невалидный конфиг отклоняется, включая `build_sequence: true`;
- неизвестный ключ проекта отклоняется общей проверкой `validate`, до запуска Blender;
- сканирование одного локального пакета **не вытесняет** кэш индекса установленного симулятора;
- сканирование внутри установленных Packages кэш использует и повторно берёт записи из него;
- stdout команды `objects` — чистый JSON, баннер Blender не загрязняет вывод;
- неверные правила всех шести типов (`split_by_skin`, `split_spatial`, `mirror_objects`, `placements`, `collection_overrides`, `texture_overrides`) отклоняются `validate_config` до запуска Blender — отдельный подсценарий на каждый вид ошибки;
- корректный набор правил всех шести типов плюс замена карты принимается.
- пустая запись `fs-base-history` скрывается только при наличии собираемого одноимённого пакета; уникальная заглушка остаётся видимой.

### `tests/test_model_choices.py` — 14 проверок

[Мастер выбора моделей](Model-Selection). Синтетическое дерево, без bpy и без MSFS.

| Группа | Что проверяется |
|---|---|
| числа | вершины и треугольники читаются из JSON без BIN; общий accessor `POSITION` считается один раз; не-треугольный primitive не даёт треугольников; отсутствующий файл не даёт чисел |
| состав | полный пакет перечисляет все LOD с номерами и числами; LOD00 отмечен по умолчанию; номер LOD берётся из имени файла, а не из позиции в цепочке XML (`ext_LOD06` третьим в цепочке остаётся 06); файл без номера в имени не получает LOD |
| честность | отсутствующий BIN виден в статусе и не отмечается; роль по имени файла помечена как подсказка; один путь предлагается один раз |
| база | ливрея с отсутствующим объявленным XML получает интерьер из базового пакета с `origin=base_package` и `role_source=имя файла`, но без отметки по умолчанию; полный пакет базовый каталог не сканирует |
| отказ | нечитаемый glTF показывается с причиной, а не исчезает из списка |
| CLI | команда `models` возвращает обе роли и имя самолёта |

### `tests/test_desktop.py` — 58 проверок

Настоящее Tk-приложение, свёрнутое в `withdraw()`.

- сохранение сохраняет вкладку и расширенные правила (`placements`), output принудительно `<проект>/blend`;
- исключённый по glob объект возвращается, обновление списка не теряет изменения;
- выбор самолёта при создании проекта transient: вкладка каталога появляется и исчезает;
- удаление legacy-проекта не трогает общую папку `blend`;
- guard занятости предотвращает второй запуск;
- каталог объектов переживает исключения;
- суффикс `_partial` сохраняется при смене режима и повторной синхронизации, снимается при удалении `models`;
- диагностика читаема без JSON: `format_diagnosis` и `format_detail` показывают BIN, неподдерживаемые возможности, ошибки чтения, кандидатов и неразрешённые ссылки; подробный отчёт группирует зависимости и предлагает следующий шаг;
- происхождение из индекса видно словами («источник: пакет базового самолёта»), а не кодом `aircraft_index`; в деталях показан каталог-источник;
- неоднозначная база перечисляет пакеты-кандидаты;
- отсутствующая база называется по имени, а не длинным путём;
- подробности ошибки чтения остаются в подробном виде и не замусоривают краткую сводку;
- окно индекса показывает сводку, кэш, ошибки доступа и пометку «НЕ установлена»; пустой результат объясняется;
- строка состояния разделяет полные пакеты, требующие выбора и недоступные;
- сводка индекса и недоступный корень попадают в журнал;
- «последний» geometry-checkpoint выбирается по номеру, даже если старый файл тронут позже (`os.utime`);
- список вариантов упорядочен по номеру, legacy-файл без номера уходит в конец, цель Проводника — первый элемент;
- при равных номерах решает время изменения;
- мастер выбора показывает LOD, вершины и треугольники и заранее отмечает только объявленные роли;
- строку без BIN отметить нельзя, кнопка подтверждения при пустом составе выключена;
- сохранённый состав проекта важнее предложения программы;
- подтверждение записывает `models`, сохраняет суффикс `_partial`, очищает дерево объектов и закрывает окно;
- мастер запрашивает команду `models` с путём выбранного самолёта.
- аудит выбранного/latest geometry checkpoint формирует пронумерованный отчёт внутри проекта, показывает review hints, не объявляет их ошибками и открывает сохранённый JSON.
- отчёт аудита восстанавливается после повторного открытия проекта; поиск ограничен выбранным checkpoint и сортирует по номеру, игнорируя старый in-memory путь от другого проекта.
- кнопка управления Packages показывается для `UNRESOLVED_ALIAS` и отсутствующей `base_container`, открывает менеджер корней, скрыта для успешной сборки и необязательного отсутствующего texture fallback.
- восстановление Packages добавляет корень через диалог и запускает сканирование; отмена ничего не меняет, дубликат повторно не сохраняется, в проекте повторно проверяется source inventory.

### `tests/test_editors.py` — 34 проверки

[Редакторы правил и таблица карт](Rule-Editors). Настоящие виджеты Tk и настоящий CLI отдельным процессом; синтетический glTF с skin-узлами и синтетический отчёт текстур.

| Группа | Что проверяется |
|---|---|
| кости (5) | суставы читаются из JSON без Blender и без BIN; узлы без `skin` не предлагаются; отсутствующий, GLB и повреждённый файл дают `read_error`, а не догадку; команда `bones` печатает JSON и отказывает файлу без skin-узлов; команда `validate` считает правила и отклоняет немонотонные границы |
| хранение (2) | строки редактора превращаются в значение конфига и обратно для всех шести типов без потерь; `referenced_names` собирает все имена объектов, якорей и pivot |
| редактор правил (14) | список сохранённых правил и переключение типа; зеркало сохраняется через настоящую проверку CLI; одинаковые источник и цель отклоняются до вызова CLI; неверная ось отклоняется конвейером, форма остаётся открытой; неизвестное имя даёт предупреждение с возможностью отказаться; смещение принимает запятую (`1,5`); пустой уровень коллекции отклоняется; удаление и порядок строк; «Проверить все правила» не помечает проект изменённым; имена частей следуют за числом границ; предложенные границы лежат внутри мировых bounds; пустой предел области сохраняется как `null`; части выбираются из настоящего списка костей; кость, занятая другой частью, не назначается повторно |
| таблица карт (12) | базовое имя совпадает с `basename` worker (`%20`, регистр, обратные слэши); состояния, виды и материалы строк; поля с ключом-путём объединяются в ту же строку; итоговый отчёт без полей текстур не скрывает карты; порядок по номеру сборки, а не по времени изменения; отсутствие отчёта объясняется; замена пишется под именем карты, а не нового файла; обновление сохраняет выбор; сброс удаляет ключ; выбор из кандидатов записывает путь; поиск вызывает `find-textures`, применяет совпадение и добавляет папки без повторов; сохранённый проект хранит замену |

## 2. Фоновая проверка настоящим Blender

```powershell
& 'C:\path\to\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_worker_checks.py
```

Скрипт (не unittest) печатает `BLENDER_WORKER_CHECKS_PASSED`. Проверяет:

- отклонение циклов в вычислении мировых матриц узлов;
- недопустимый индекс текстуры;
- границы усечённого accessor;
- сквозной `build_geometry` на синтетическом glTF с `exclude_objects` и `mirror_objects` — порядок «mirror до исключений»;
- `draw_mode=msfs` на обычном glTF отклоняется с сообщением, содержащим имя файла, индекс primitive и совет использовать `auto`; удаление runtime-материала не сдвигает индекс в сообщении;
- зеркалирование повёрнутого, масштабированного и смещённого источника: мировые координаты совпадают с отражением, начало координат перенесено, определитель матрицы положителен, U перевёрнут по вершинам, мировая нормаль отражена (допуск 1e-3 на квантование custom normals);
- `placements` переносит объект в точку повёрнутого и масштабированного якоря плюс `offset_m`, сохраняя собственные поворот и масштаб;
- decal скрыт на геометрическом этапе и возвращён после `build_textures`;
- zero-scale skin driver в `manual_skin_vertices` не приводит к отказу.

Этот уровень **не входит в CI**: на раннере нет Blender. Он выполняется локально перед выпуском.

## 3. Приёмка пользователем

Обязательная часть, которую нельзя автоматизировать:

1. минимальный синтетический вход для новой возможности и для её ошибки;
2. CLI-тест resolver без Blender;
3. фоновая проверка Blender: число частей, UV, материалы, transforms;
4. проверка GUI и переносимости проекта;
5. **проверка реального самолёта пользователем в Blender**, без добавления его ресурсов в репозиторий.

Названия объектов и числовые отчёты сами по себе не доказывают правильную геометрию. Рендеры автоматически не создаются; визуальная приёмка выполняется пользователем.

## CI

`.github/workflows/tests.yml`, `windows-latest`, Python 3.13:

1. `python -m compileall -q msfs_builder_gui.py app_support.py rule_editor.py texture_table.py scripts tests`;
2. `python msfs_builder_gui.py --self-test`;
3. `python -m unittest discover -s tests -p "test_*.py" -v`.

Запускается на push, pull request и вручную.

## Правила для новых тестов

Для любого нового способа чтения модели добавьте маленький синтетический glTF-тест, опишите ограничения и проверьте прежние режимы. Не добавляйте исходные самолёты, текстуры, свои проекты, токены и абсолютные пути профиля.

Новый графический инструмент проверяйте через его настоящие виджеты и настоящий CLI, а не через вызов внутренних функций в обход кнопок: именно так были найдены неверный ключ замены карты, потеря выбора при обновлении таблицы и выбор отчёта без полей текстур.

Дальше: [Rule Editors](Rule-Editors) · [Model Selection](Model-Selection) · [Package Index](Package-Index) · [Building and Release](Building-and-Release) · [Known Issues](Known-Issues)

# Package Diagnosis / Диагностика пакета

## English version

Diagnosis runs before Blender and explains why an aircraft can or cannot be built. The GUI and CLI use the same resolver, so reason codes are consistent.

If `fs-base-history` contains a non-buildable placeholder with the same aircraft name as an installed geometry-buildable package, the placeholder is omitted from the selectable aircraft list and returned separately as `suppressed_history_stubs`. A history entry without a buildable peer remains visible as unavailable. Other same-name packages remain visible and are marked as duplicates.

### Codes

| Code | Meaning | Action |
|---|---|---|
| `OK` | complete composition found | build it |
| `SUPPORTED_PARTIAL` | only some roles or LODs are available | confirm the composition in the wizard |
| `COMMON_RESOURCES_ONLY` | only shared resources exist | locate the model package |
| `LIVERY_ONLY` | only a livery exists | add the base aircraft |
| `MISSING_MODEL_CFG` | `model.cfg` is absent | choose glTF files manually |
| `INVALID_MODEL_CFG` | configuration is invalid | check the `[models]` section |
| `MISSING_BUFFER` | the BIN buffer is absent | restore the source package |
| `UNRESOLVED_ALIAS` | `base_container` was not found | add the base package root |
| `UNSUPPORTED_GLTF_FEATURE` | the format is unsupported | choose another LOD or defer the package |

### Fast and deep modes

Without `--deep`, `inventory` checks structure, configuration and declared file presence. `inventory --deep` reads JSON glTF/GLB, validates buffers and primitives, and reports unsupported extensions. Deep mode is slower but provides the exact pre-Blender reason.

### Partial builds

For `SUPPORTED_PARTIAL`, the `models` command and GUI wizard display exterior and interior roles, every discovered LOD, vertex and triangle counts, role source and resource origin. Only roles declared by configuration are selected by default. A filename-based candidate is included only after explicit confirmation.

### Package index

The `index` command builds a cached index of installed packages and resolves livery VFS links to base aircraft. The GUI shows `base_container`, whether the base is installed and any ambiguous candidates. An inaccessible package does not stop the rest of the scan.

The detailed GUI report groups dependencies by type and shows resolved counts, a few unresolved examples and a next step. For a missing manifest package, verify the package installation and scan roots. For a missing `base_container`, install the base aircraft or add its Packages root. For an ambiguous model file, compare the listed candidates and assign the intended file with **Choose models**. Texture fallbacks are optional; use the texturing report to check whether a material map is actually missing.

---

## Русская версия

Диагностика запускается до Blender и объясняет, почему самолёт можно или нельзя собрать. GUI и CLI используют один resolver, поэтому коды причин совпадают.

Если в `fs-base-history` есть не собираемая заглушка с тем же именем, что у установленного пакета со собираемой геометрией, заглушка скрывается из списка выбора самолёта и возвращается отдельно в `suppressed_history_stubs`. Если собираемого дубля нет, history-запись остаётся в списке как недоступная. Прочие пакеты с одинаковыми именами остаются видимыми и помечаются как дубликаты.

### Коды

| Код | Значение | Действие |
|---|---|---|
| `OK` | полный состав найден | можно собирать |
| `SUPPORTED_PARTIAL` | доступна часть ролей или LOD | подтвердить состав в мастере |
| `COMMON_RESOURCES_ONLY` | только общие ресурсы | найти пакет модели |
| `LIVERY_ONLY` | только ливрея | добавить базовый самолёт |
| `MISSING_MODEL_CFG` | нет `model.cfg` | выбрать glTF вручную |
| `INVALID_MODEL_CFG` | конфигурация повреждена | проверить секцию `[models]` |
| `MISSING_BUFFER` | отсутствует BIN | восстановить исходный пакет |
| `UNRESOLVED_ALIAS` | не найден `base_container` | добавить корень базы |
| `UNSUPPORTED_GLTF_FEATURE` | формат не поддержан | выбрать другой LOD или отложить пакет |

### Быстрый и глубокий режим

`inventory` без `--deep` проверяет структуру, конфигурации и наличие объявленных файлов. `inventory --deep` читает JSON glTF/GLB, проверяет buffers и primitive и сообщает о неподдерживаемых расширениях. Глубокий режим медленнее, но показывает точную причину отказа до запуска Blender.

### Частичная сборка

Для `SUPPORTED_PARTIAL` команда `models` и GUI-мастер показывают две роли — exterior и interior — все найденные LOD, число вершин и треугольников, источник роли и происхождение ресурса. По умолчанию выбираются только роли, объявленные конфигурацией. Кандидат, предложенный по имени файла, включается после подтверждения пользователя.

### Индекс пакетов

Команда `index` строит кэш индекса установленных пакетов и разрешает VFS-ссылки ливрей на базовые самолёты. В GUI видны `base_container`, статус базы и неоднозначные кандидаты. Ошибка одного каталога не останавливает сканирование остальных.

Подробный отчёт GUI группирует зависимости по типу, показывает число найденных ссылок, несколько примеров проблем и следующий шаг. Если не найден пакет из manifest, проверьте его установку и выбранные каталоги сканирования. Для отсутствующего `base_container` установите базовый самолёт или добавьте его корень Packages. При неоднозначной ссылке на модель сравните кандидатов и назначьте нужный файл кнопкой **«Выбрать модели…»**. Texture fallback необязателен: наличие реально пропущенной карты проверяйте в отчёте текстурирования.

# Package Diagnosis / Диагностика пакета

## Русская версия

Диагностика запускается до Blender и отвечает на вопрос «почему самолёт нельзя собрать». GUI и CLI используют один resolver, поэтому код причины одинаков в обоих интерфейсах.

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

`inventory` без `--deep` проверяет структуру, конфигурации и наличие объявленных файлов. `inventory --deep` читает JSON glTF/GLB, проверяет buffers, primitive и поддерживаемые расширения. Глубокий режим медленнее, но показывает точную причину отказа до запуска Blender.

### Частичная сборка

Для `SUPPORTED_PARTIAL` команда `models` и GUI-мастер показывают две роли — exterior и interior — все найденные LOD, вершины, треугольники, источник роли и происхождение ресурса. По умолчанию выбираются только роли, объявленные конфигурацией. Кандидат, предложенный по имени файла, включается только после подтверждения пользователя.

### Пакетный индекс

Команда `index` строит кэш индекса установленных пакетов и разрешает VFS-ссылки ливрей на базовые самолёты. В GUI видны `base_container`, найденная база и неоднозначные кандидаты. Ошибка одного каталога не останавливает сканирование остальных.

## English version

Diagnosis runs before Blender and answers “why can this aircraft not be built”. The GUI and CLI use the same resolver, so reason codes are identical in both interfaces.

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

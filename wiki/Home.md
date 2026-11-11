# MSFS Model Builder — wiki


---

## Русская версия

Эта wiki описывает текущую версию **1.2.0** — Windows-конвейер для извлечения доступной статической геометрии MSFS 2020 в Blender. Программа импортирует геометрию и PBR-текстуры, распределяет объекты по коллекциям и сохраняет варианты `.blend`. Анимации не импортируются.

### Быстрый путь

| Страница | Назначение |
|---|---|
| [Getting Started](Getting-Started) | требования, установка и первый проект |
| [GUI Workflow](GUI-Workflow) | вкладки, кнопки и порядок работы |
| [Package Diagnosis](Package-Diagnosis) | причины недоступности и частичные пакеты |
| [Package Index](Package-Index) | наследование ливрей и происхождение ресурсов |
| [Model Selection](Model-Selection) | выбор exterior/interior и LOD |
| [Rule Editors](Rule-Editors) | split, mirror, placement, коллекции и карты |
| [Troubleshooting](Troubleshooting) | типовые ошибки и безопасные действия |

### Справочники

| Страница | Назначение |
|---|---|
| [CLI Reference](CLI-Reference) | команды и аргументы CLI |
| [Configuration Reference](Configuration-Reference) | JSON-конфигурация и проверки |
| [Build Modes](Build-Modes) | режимы геометрии и текстур |
| [Textures and Materials](Textures-and-Materials) | карты, DDS и материалы |
| [Object Organization](Object-Organization) | коллекции, исключения и разделение |
| [Architecture](Architecture) | процессы и границы модулей |
| [MSFS glTF Format](MSFS-glTF-Format) | поддерживаемые данные glTF |
| [Building and Release](Building-and-Release) | пересборка Windows-пакета |
| [Testing](Testing) | локальные и CI-проверки |
| [Known Issues](Known-Issues) | ограничения и известные дефекты |

Исходники MSFS открываются только для чтения. Нужны реальные локальные glTF/GLB, BIN, XML и карты. Закрытые или отсутствующие файлы программа не восстанавливает; визуальную приёмку выполняет пользователь в Blender.

Документы верхнего уровня: [README](../README.md), [руководство пользователя](../USER_GUIDE.md), [английское руководство](../USER_GUIDE_EN.md), [лицензия](../LICENSE), [пояснение к лицензии](../LICENSE_NOTICE.md).

## English version

This wiki documents the current **1.2.0** release: a Windows pipeline that imports available static MSFS 2020 geometry into Blender. It imports geometry and PBR textures, organizes objects into collections and saves separate `.blend` variants. Animations are not imported.

### Start here

| Page | Purpose |
|---|---|
| [Getting Started](Getting-Started) | requirements, installation and the first project |
| [GUI Workflow](GUI-Workflow) | tabs, buttons and the workflow |
| [Package Diagnosis](Package-Diagnosis) | availability reasons and partial packages |
| [Package Index](Package-Index) | livery inheritance and resource origin |
| [Model Selection](Model-Selection) | exterior/interior and LOD selection |
| [Rule Editors](Rule-Editors) | split, mirror, placement, collections and maps |
| [Troubleshooting](Troubleshooting) | common errors and safe actions |

### References

| Page | Purpose |
|---|---|
| [CLI Reference](CLI-Reference) | CLI commands and arguments |
| [Configuration Reference](Configuration-Reference) | JSON configuration and validation |
| [Build Modes](Build-Modes) | geometry and texture modes |
| [Textures and Materials](Textures-and-Materials) | maps, DDS and materials |
| [Object Organization](Object-Organization) | collections, exclusions and splitting |
| [Architecture](Architecture) | processes and module boundaries |
| [MSFS glTF Format](MSFS-glTF-Format) | supported glTF data |
| [Building and Release](Building-and-Release) | rebuilding the Windows package |
| [Testing](Testing) | local and CI checks |
| [Known Issues](Known-Issues) | current limitations and known defects |

MSFS sources are read-only. Real local glTF/GLB, BIN, XML and texture files are required. Protected or missing files are not reconstructed; the user performs visual acceptance in Blender.

Top-level documents: [README](../README.md), [Russian user guide](../USER_GUIDE.md), [English user guide](../USER_GUIDE_EN.md), [license](../LICENSE), and [license notice](../LICENSE_NOTICE.md).

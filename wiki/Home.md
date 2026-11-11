# MSFS Model Builder — wiki

## English version

This wiki documents the current **1.3.0** release: a Windows pipeline that imports available static MSFS 2020 geometry into Blender. It imports geometry and PBR textures, organizes objects into collections and saves separate `.blend` variants. Animations are not imported.

### Start here

| Page | Purpose |
|---|---|
| [Getting Started](Getting-Started.md) | requirements, installation and the first project |
| [GUI Workflow](GUI-Workflow.md) | tabs, buttons and the workflow |
| [Package Diagnosis](Package-Diagnosis.md) | availability reasons and partial packages |
| [Package Index](Package-Index.md) | livery inheritance and resource origin |
| [Model Selection](Model-Selection.md) | exterior/interior and LOD selection |
| [Rule Editors](Rule-Editors.md) | split, mirror, placement, collections and maps |
| [Troubleshooting](Troubleshooting.md) | common errors and safe actions |

### References

| Page | Purpose |
|---|---|
| [CLI Reference](CLI-Reference.md) | CLI commands and arguments |
| [Configuration Reference](Configuration-Reference.md) | JSON configuration and validation |
| [Build Modes](Build-Modes.md) | geometry and texture modes |
| [Textures and Materials](Textures-and-Materials.md) | maps, DDS and materials |
| [Object Organization](Object-Organization.md) | collections, exclusions and splitting |
| [Architecture](Architecture.md) | processes and module boundaries |
| [MSFS glTF Format](MSFS-glTF-Format.md) | supported glTF data |
| [Building and Release](Building-and-Release.md) | rebuilding the Windows package |
| [Known Issues](Known-Issues.md) | current limitations and known defects |

MSFS sources are read-only. Real local glTF/GLB, BIN, XML and texture files are required. Protected or missing files are not reconstructed; the user performs visual acceptance in Blender.

Top-level documents: [README](../README.md), [Russian user guide](../USER_GUIDE.md), [English user guide](../USER_GUIDE_EN.md), [license](../LICENSE), and [license notice](../LICENSE_NOTICE.md).

---

## Русская версия

Эта wiki описывает текущую версию **1.3.0** — Windows-конвейер для импорта доступной статической геометрии MSFS 2020 в Blender. Программа импортирует геометрию и PBR-текстуры, распределяет объекты по коллекциям и сохраняет отдельные варианты `.blend`. Анимации не импортируются.

### Быстрый путь

| Страница | Назначение |
|---|---|
| [Getting Started](Getting-Started.md) | требования, установка и первый проект |
| [GUI Workflow](GUI-Workflow.md) | вкладки, кнопки и порядок работы |
| [Package Diagnosis](Package-Diagnosis.md) | причины недоступности и частичные пакеты |
| [Package Index](Package-Index.md) | наследование ливрей и происхождение ресурсов |
| [Model Selection](Model-Selection.md) | выбор exterior/interior и LOD |
| [Rule Editors](Rule-Editors.md) | split, mirror, placement, коллекции и карты |
| [Troubleshooting](Troubleshooting.md) | типовые ошибки и безопасные действия |

### Справочники

| Страница | Назначение |
|---|---|
| [CLI Reference](CLI-Reference.md) | команды и аргументы CLI |
| [Configuration Reference](Configuration-Reference.md) | JSON-конфигурация и проверки |
| [Build Modes](Build-Modes.md) | режимы геометрии и текстур |
| [Textures and Materials](Textures-and-Materials.md) | карты, DDS и материалы |
| [Object Organization](Object-Organization.md) | коллекции, исключения и разделение |
| [Architecture](Architecture.md) | процессы и границы модулей |
| [MSFS glTF Format](MSFS-glTF-Format.md) | поддерживаемые данные glTF |
| [Building and Release](Building-and-Release.md) | пересборка Windows-пакета |
| [Known Issues](Known-Issues.md) | ограничения и известные дефекты |

Исходники MSFS открываются только для чтения. Нужны реальные локальные glTF/GLB, BIN, XML и карты. Закрытые или отсутствующие файлы программа не восстанавливает; визуальную приёмку выполняет пользователь в Blender.

Документы верхнего уровня: [README](../README.md), [руководство пользователя](../USER_GUIDE.md), [английское руководство](../USER_GUIDE_EN.md), [лицензия](../LICENSE), [пояснение к лицензии](../LICENSE_NOTICE.md).

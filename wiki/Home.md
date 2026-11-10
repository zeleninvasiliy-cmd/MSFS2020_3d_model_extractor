# MSFS Model Builder — wiki

Windows-программа, которая собирает **статическую** 3D-модель самолёта из доступных ресурсов Microsoft Flight Simulator 2020 в Blender: геометрия, PBR-текстуры, объекты разделены по коллекциям. **Анимации не импортируются и не создаются.** Внешний вид, комплектность и правильность расположения деталей проверяет пользователь в Blender.

Версия: **1.2.0**. Python 3.13 x64 включён в поставку; Blender устанавливается отдельно (проверено с 5.2.3 LTS).

## С чего начать

| Страница | О чём |
|---|---|
| [Getting Started](Getting-Started) | требования, установка, первый проект за 10 минут |
| [GUI Workflow](GUI-Workflow) | все вкладки, порядок шагов, жизненный цикл проекта |
| [Package Diagnosis](Package-Diagnosis) | почему самолёт «недоступен», коды причин, частичная сборка |
| [Package Index](Package-Index) | индекс установленных пакетов, наследование ливрей, происхождение ресурсов |
| [Model Selection](Model-Selection) | мастер выбора состава: exterior/interior, LOD, число вершин и треугольников |
| [Rule Editors](Rule-Editors) | графические редакторы split/mirror/placements и таблица карт с заменой текстур |
| [Troubleshooting](Troubleshooting) | типовые симптомы и действия |

## Справочники

| Страница | О чём |
|---|---|
| [CLI Reference](CLI-Reference) | все команды, флаги, коды возврата |
| [Configuration Reference](Configuration-Reference) | каждый ключ JSON-конфига, значения по умолчанию, проверки |
| [Build Modes](Build-Modes) | `skinning`, `draw_mode`, `normal_decode`: что делают и когда применять |
| [Textures and Materials](Textures-and-Materials) | DDS, каналы COMP, fallback-цепочки, поиск недостающих карт |
| [Object Organization](Object-Organization) | коллекции, исключения, split, mirror, placements |
| [Reports and Audit](Reports-and-Audit) | поля JSON-отчётов и что они означают |

## Как это устроено

| Страница | О чём |
|---|---|
| [Architecture](Architecture) | модули, процессы, поток данных, границы ответственности |
| [MSFS glTF Format](MSFS-glTF-Format) | `ASOBO_primitive`, упакованные атрибуты, winding, кватернионы |
| [Building and Release](Building-and-Release) | PyInstaller, Inno Setup, portable, контрольные суммы |
| [Testing](Testing) | наборы тестов, CI, фоновая проверка Blender |

## Развитие

| Страница | О чём |
|---|---|
| [Roadmap Assessment](Roadmap-Assessment) | оценка плана, приоритеты, рекомендация |
| [Known Issues](Known-Issues) | выявленные проблемы, ранее не замеченные |
| [Compatibility Roadmap](../docs/COMPATIBILITY_ROADMAP.md) | исходный план расширения совместимости |
| [Contributing](Contributing) | правила разработки и приёмки |

## Границы программы

- Нужны **доступные локальные** glTF + BIN. Программа не скачивает, не расшифровывает и не восстанавливает отсутствующие исходники.
- Поддерживается один локальный BIN рядом с glTF и треугольные primitives. GLB, несколько buffers, data URI, sparse accessors и Draco **диагностируются**, но не декодируются.
- Группировка объектов и определение роли модели по имени — эвристики. Они не доказывают правильность геометрии.
- Встроенного 3D-просмотра нет. Визуальная приёмка выполняется в Blender пользователем.
- Исходный пакет MSFS открывается только для чтения. Результаты всегда пишутся вне пакета.

## Документы в репозитории

[README](../README.md) · [TECHNICAL_GUIDE](../TECHNICAL_GUIDE.md) · [USER_GUIDE](../USER_GUIDE.md) · [GUI_GUIDE](../GUI_GUIDE.md) · [RELEASE_AUDIT](../RELEASE_AUDIT.md) · [WORKER_AUDIT](../WORKER_AUDIT.md) · [Руководство пользователя (HTML)](../release/docs/USER_MANUAL_RU.html)

# Package Index

## English version

The package index is a no-`bpy` cache built from selected MSFS roots. It maps aircraft names to folders, packages to roots and livery `base_container` declarations to their installed bases. Configuration mtimes and the index version invalidate stale records.

When a relative VFS path does not exist in the livery, the resolver tries the indexed aircraft or base package. The origin is preserved in diagnostics. If two packages can own the same resource, the index reports ambiguity and the user must choose; an inaccessible package does not abort the scan.

Texture fallback diagnostics keep the original unresolved path when no package matches. If multiple base packages contain the fallback directory, the dependency stays unresolved and lists all candidates instead of returning an empty path.

---

Индекс установленных пакетов решает одну задачу: **ресурсы лежат в соседнем пакете, а конфиг ливреи указывает внутрь себя**. Реализован в `scripts/package_index.py` — модуле без `bpy`, который используют и CLI, и GUI.

## Почему ливрея указывает «не туда»

MSFS монтирует пакеты в общее дерево VFS. Ливрея пишет относительные пути для уже смонтированного дерева:

```ini
[VARIATION]
base_container = "..\Asobo_208B_GRAND_CARAVAN_EX"

[models]
interior = ..\..\Asobo_208B_GRAND_CARAVAN_EX\model\208B_GRAND_CARAVAN_EX_INTERIOR.xml
```

В игре этот путь существует. На диске он разрешается внутри пакета ливреи:

```
…\Official\Steam\asobo-aircraft-208b-grand-caravan-ex-livery-01\SimObjects\Airplanes\Asobo_208B_GRAND_CARAVAN_EX\model\…
```

Такой папки нет — интерьер лежит в **базовом** пакете `asobo-aircraft-208b-grand-caravan-ex`. Без индекса resolver честно сообщает «ресурс отсутствует», и ливрея попадает в частичные, хотя полный состав фактически установлен.

## Что индексируется

`PackageIndex.build(roots, cache_path=…)` обходит корни `Packages` (Official/Steam и Community) и дополнительные моды:

| Источник | Что берётся |
|---|---|
| `SimObjects/Airplanes/*` | имена самолётов и их каталоги |
| `manifest.json` пакета | `package_version`, `content_type`, `title` |
| `aircraft.cfg`, `[VARIATION]` | объявленная база (`base_container`) |

Содержимое `model.cfg`, model XML и glTF на этом шаге **не читается** — индекс должен строиться быстро. Их разбирает resolver, уже зная, где искать.

Значение `base_container` очищается от комментариев `;` и кавычек. Граф наследования плоский: `base_aircraft(folder)` возвращает только непосредственную базу, без рекурсии, поэтому цикл в объявлениях не приводит к зацикливанию.

## Два правила переноса пути

`PackageIndex.rebase(target, owner)` возвращает `(path, origin, candidates)`.

Существующий на диске путь возвращается как есть, с `origin=None` — индекс ничего не подменяет.

| Правило | Когда срабатывает | `origin` |
|---|---|---|
| якорь по имени самолёта | сегмент пути совпадает с именем установленного самолёта; префикс заменяется на его каталог, хвост сохраняется | `aircraft_index` |
| якорь по корню пакета | путь лежит внутри корня собственного пакета; хвост переносится в корень базового пакета | `base_package` |

Второе правило нужно для `texture.cfg`: `fallback.1=..\..\..\..\texture\Gauges` указывает не на именованный самолёт, а на каталог внутри пакета.

Если подходящих пакетов **несколько**, возвращается `path=None`, `origin="ambiguous"` и список кандидатов. Resolver не угадывает: он показывает список, а выбор остаётся за пользователем. Диагностика `texture.cfg` сохраняет исходный путь fallback, помечает зависимость неразрешённой и перечисляет все найденные варианты. Если база объявлена, но не установлена, путь не выдумывается.

## Что разрешается через индекс

| Ссылка | Функция resolver |
|---|---|
| `aircraft.cfg [VARIATION] base_container` | `collect_dependencies` |
| `model.cfg [models]` (XML и glTF) | `inspect_variant`, `model_from_cfg` |
| LOD из model XML | `read_model_xml` — пути считаются от папки XML, поэтому перенос XML автоматически переносит и его glTF |
| `texture.cfg fallback.*` | `collect_dependencies`, `texture_folders` |
| папки карт для этапа текстур | `texture_folders` |

У каждого ресурса сохраняется `origin`, и он виден в GUI и в JSON-отчёте. Значения: `model.cfg`, `xml`, `scan`, `base_container`, `aircraft_index`, `base_package`, `name_lookup`.

## Кэш

| Свойство | Значение |
|---|---|
| Путь | `%LOCALAPPDATA%\MSFSModelBuilder\package_index.json` |
| Запись | атомарная: `.tmp` + `os.replace` |
| Сигнатура пакета | mtime и размер каталога пакета, `manifest.json`, `layout.json`, `SimObjects/Airplanes` и каждого прямого `aircraft.cfg` |
| Инвалидация | изменилась сигнатура, версия индекса или список корней; повреждённый JSON игнорируется |
| Ошибка доступа | корень попадает в `errors`, остальные продолжают сканироваться |

Сигнатура не читает содержимое файлов, поэтому прогретый индекс строится примерно за 0.4 с. Добавили самолёт в пакет — изменился mtime `SimObjects/Airplanes`, пакет пересканируется. Изменили `base_container` внутри существующего `aircraft.cfg` — изменился mtime самого файла, поэтому пакет также пересканируется. При изменении схемы сигнатуры версия индекса увеличивается, и старый кэш игнорируется.

Сканирование **одного локального пакета** (корень вне установленных `Packages`) кэш не использует. Иначе каждый открытый проект и каждый тест вытеснял бы индекс установленного симулятора: список корней не совпал бы, и следующая реальная проверка пересканировала бы все 223 пакета.

## Команда CLI

```powershell
python .\scripts\msfs_universal.py index
python .\scripts\msfs_universal.py index --aircraft Asobo_208B_GRAND_CARAVAN_EX_Livery_01
python .\scripts\msfs_universal.py index --no-cache --root "D:\MSFS\Packages\Community"
```

| Флаг | Действие |
|---|---|
| `--root` | дополнительный корень, можно повторять |
| `--no-cache` | перестроить индекс, не используя кэш |
| `--aircraft` | показать записи только этого самолёта, без учёта регистра, точное совпадение |

Ответ содержит `searched_roots`, `packages`, `aircraft_names`, `cached`, `scanned`, `errors`, `cache_path` и `aircraft`. У каждой записи самолёта есть `base_container` (как объявлено) и `base_installed` — установлена ли база среди проиндексированных пакетов.

`catalog` возвращает сводку индекса в блоке `index`; `inventory`, `make_plan` и диагностика при отказе выбора моделей используют индекс автоматически.

## Окно GUI

Меню **«Индекс пакетов…»**:

- сводка: число пакетов и имён, сколько взято из кэша и сколько просканировано заново, путь к файлу кэша, каталоги поиска и ошибки доступа;
- по каждому самолёту — путь и объявленная база с пометкой «установлена» / «НЕ установлена»;
- фильтр по точному имени самолёта (Enter или кнопка «Показать»);
- кнопка **«Перестроить индекс»** — то же, что `--no-cache`.

В диагностике выбранного самолёта индекс даёт:

- строку **«Базовый самолёт: … — источник: пакет базового самолёта»** либо точную причину отказа;
- происхождение каждой предлагаемой модели, а в подробном виде — каталог-источник;
- для неразрешённой ссылки на модель — «базовый самолёт не установлен» или «базовый самолёт установлен, но объявленный файл в нём отсутствует». Это разные действия пользователя: установить пакет или выбрать модель вручную.

Строка состояния под списком разделяет полные пакеты, требующие выбора моделей и недоступные.

## Производительность

Сравнение путей идёт через `os.path.normcase(os.path.abspath(...))`, а не через `Path.resolve()`. На Windows `resolve()` вызывает `nt._getfinalpathname`; профилирование каталога показало 58 826 таких вызовов и 1.77 с только на них. Хвост пути при этом сохраняет исходный регистр: `relative_to` на Windows регистронезависим, поэтому возвращаемый путь совпадает с реальным именем каталога.

## Границы

- Индекс не скачивает и не восстанавливает отсутствующие пакеты.
- Он не определяет роль модели по имени файла и не подставляет интерьер вместо объявленного XML.
- Неоднозначность всегда передаётся пользователю.
- Исходные пакеты открываются только для чтения; кэш пишется в профиль пользователя.

Дальше: [Package Diagnosis](Package-Diagnosis) · [CLI Reference](CLI-Reference) · [Architecture](Architecture) · [Textures and Materials](Textures-and-Materials)

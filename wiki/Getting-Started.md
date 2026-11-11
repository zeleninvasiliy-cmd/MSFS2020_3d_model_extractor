# Getting Started

## English version

Requirements are Windows 10/11 x64, Blender 5.x installed separately, and locally available MSFS package files. Python is only required for a source checkout; the packaged EXE already includes its runtime.

Create a project from **Files → New project**, choose a workspace and an aircraft source, then select Blender and the output folder. Run the deep package check for an unfamiliar mod. Build geometry first, inspect it in Blender, and only then add textures. Results are stored under the project's `blend` directory and never inside the MSFS package.

---

## Требования

| Компонент | Нужно | Примечание |
|---|---|---|
| Windows | 10/11 x64 | установщик ставится для текущего пользователя, без прав администратора |
| Python | **не нужен** для EXE-версии | включён в поставку; для запуска из исходников — Python 3.13 x64 |
| Blender | 5.x, отдельно | проверено с 5.2.3 LTS; нужен встроенный glTF importer и NumPy |
| MSFS 2020 | распакованные пакеты | доступны локальные `.gltf` с BIN или `.glb`, а также DDS/PNG-карты |
| Inno Setup | только для сборки | на компьютере пользователя не требуется |

Зашифрованные пакеты, модели без доступного glTF и ливреи без базового самолёта собрать нельзя. Программа объясняет причину по каждому пакету — см. [Package Diagnosis](Package-Diagnosis).

## Установка

1. Запустите `MSFSModelBuilder-1.3.0-Setup.exe`.
2. При желании укажите папку `Packages` MSFS и `blender.exe`. Поля необязательны: пути задаются и в программе.
3. Откройте MSFS Model Builder из меню «Пуск».

Установка выполняется в `%LOCALAPPDATA%\Programs\MSFS Model Builder`. Настройки пользователя — `%LOCALAPPDATA%\MSFSModelBuilder\settings.json`. Деинсталлятор удаляет только файлы приложения; проекты и настройки остаются.

**Portable:** распакуйте ZIP целиком. Нельзя переносить один `.exe` отдельно от `MSFSBuilderCLI.exe` и каталога `_internal` — они используют общую среду выполнения.

Установщик не подписан цифровым сертификатом издателя.

## Как программа находит MSFS

Читается `UserCfg.opt` текущего пользователя и значение `InstalledPackagesPath`:

- `%APPDATA%\Microsoft Flight Simulator\UserCfg.opt` — Steam/retail;
- `%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_*\LocalCache\UserCfg.opt` — Microsoft Store.

Если конфиг не найден, используются стандартные места установки. Затем выполняется обход вглубь до 4 уровней в поисках `model*` или `SimObjects/Airplanes`, поэтому находятся и `Official`, и `Community`. Папка игры и папка `Packages` могут лежать на разных дисках.

Если автоматический поиск ничего не нашёл: «Выбрать каталог» → укажите `Packages`, `Official`, `Community`, папку распакованного мода или конкретного самолёта. Выбранный корень сохраняется в настройках и передаётся CLI как `--root`.

## Как программа находит Blender

1. `blender` в `PATH`;
2. иначе `Blender Foundation/Blender*/blender.exe` под `%PROGRAMFILES%` и `%LOCALAPPDATA%\Programs` — выбирается лексикографически старшая версия.

Путь всегда можно задать вручную: меню «Пути и настройки» или поле Blender на вкладке «2. Настройка».

## Первый проект

1. **Файлы → Новый проект.** Открывается шаг «1. Самолёт».
2. «Сканировать MSFS» либо «Выбрать каталог» → «Сканировать».
3. Изучите пометки в списке. Если самолёт помечен `⚠` или `◐`, прочитайте причину под списком и нажмите **«Проверить пакет подробно»**. Для ливреи помогает меню **«Индекс пакетов…»**: там видно, установлен ли базовый самолёт, геометрию которого она использует ([Package Index](Package-Index)).
4. Выберите самолёт → «Далее». Для частичного состава откроется [мастер выбора моделей](Model-Selection): отметьте файлы экстерьера и интерьера, посмотрите LOD и число вершин, подтвердите. Строка с источником роли «имя файла» по умолчанию не отмечена — это подсказка, а не назначение.
5. Укажите **отдельную** папку проекта и имя. По умолчанию предлагается `Documents\MSFS_Projects`. Папка не должна существовать и не должна находиться внутри пакета MSFS.
6. На вкладке «2. Настройка» выберите model-вариант и ливрею, проверьте Blender → «Далее».
7. Вкладка «3. Геометрия»: начните с `strip` + `auto` → **«Собрать geometry»**.
8. Откройте результат в Blender и проверьте: симметрию крыльев, двигатели и колёса (не перевёрнуты), нос/хвост/двери/стойки, рули и закрылки, остекление и интерьер, Outliner.
9. После подтверждения геометрии — вкладка «4. Текстуры»: выберите нужный `01_geometry*.blend` → **«Добавить textures»** → проверьте в Material Preview.
10. При необходимости «Собрать final».

Результаты лежат в подпапке `blend` проекта. Каждый режим получает собственную нумерацию, старые файлы не перезаписываются:

```
01_geometry_strip_auto_001.blend
01_geometry_strip_auto_002.blend
01_geometry_manual_auto_001.blend
01_geometry_strip_auto_partial_001.blend
02_textured_strip_auto_001.blend
03_model_strip_auto_001.blend
```

## Запуск из исходников

```powershell
git clone https://github.com/YOUR_ACCOUNT/msfs-model-builder.git
cd msfs-model-builder
python msfs_builder_gui.py
```

CLI:

```powershell
python .\scripts\msfs_universal.py catalog --match c152
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft" --deep
python .\scripts\msfs_universal.py build .\examples\config.myplane.json --stage geometry
```

Установленный `MSFSBuilderCLI.exe` принимает те же аргументы вместо `python scripts/msfs_universal.py`.

## Что остаётся пользователю

Программа автоматизирует чтение glTF, подготовку индексов, skinning-режимы, разделение, поиск карт, PBR-сеть, упаковку и отчёты. Пользователь:

- выбирает правильные LOD и роли exterior/interior;
- **проверяет геометрию и текстуры в Blender** — числовой отчёт не определяет, что объект является нужным рулём;
- подтверждает частичный состав и источник для mirror;
- задаёт границы пространственного разделения и имена костей, если автоматика не справилась;
- принимает решение по ливрее и общим fallback-картам.

Дальше: [GUI Workflow](GUI-Workflow) · [Build Modes](Build-Modes) · [Troubleshooting](Troubleshooting)

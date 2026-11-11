# MSFS Model Builder 1.2.0

## English

MSFS Model Builder is a Windows pipeline for preparing static aircraft models from locally available Microsoft Flight Simulator 2020 resources and saving them as Blender `.blend` files. It imports geometry, materials and PBR textures, organizes objects into collections and keeps separate build variants. Animations are intentionally not imported.

Exact extraction requires the original files to be available locally: glTF/GLB, BIN, XML, configuration files and texture maps. The program does not decrypt protected packages or invent missing source geometry.

### Quick start

1. Install `MSFSModelBuilder-1.2.0-Setup.exe` from the [GitHub Release](https://github.com/zeleninvasiliy-cmd/MSFS2020_3d_model_extractor/releases/tag/v1.2.0), or run the source tree with Python 3.13.
2. Install Blender 5.x separately and select `blender.exe` in “Paths and settings”.
3. Create a project, select an MSFS package or mod folder, then choose an aircraft.
4. Build geometry, inspect the `.blend` in Blender, and run texturing afterwards.

See the [Russian user guide](USER_GUIDE.md) or the [English user guide](USER_GUIDE_EN.md). The [wiki](wiki/Home.md) contains the implementation and command reference in both languages.

### Source checkout

```powershell
python .\msfs_builder_gui.py
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft"
python .\scripts\msfs_universal.py catalog --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py build .\examples\config.template.json --stage geometry
```

The GUI and CLI share the same resolver, validator and Blender worker. For an incomplete package, the model wizard lists exterior/interior roles, LODs, vertex and triangle counts, and resource origin. Rule editors and the texture table are graphical; normal users do not need to edit JSON for the standard workflow.

### License

The code is distributed under [PolyForm Noncommercial 1.0.0](LICENSE), with project guidance in [LICENSE_NOTICE.md](LICENSE_NOTICE.md). Personal, educational, research and other noncommercial use is allowed. Commercial use requires separate permission. MSFS aircraft, textures and user projects are not included in this repository.

---

## Русский

MSFS Model Builder — Windows-конвейер для подготовки статической модели самолёта из доступных ресурсов Microsoft Flight Simulator 2020 в Blender. Программа собирает геометрию, материалы и PBR-текстуры, распределяет объекты по коллекциям и сохраняет варианты `.blend`. Анимации намеренно не импортируются.

Точный импорт возможен только для ресурсов, которые реально доступны на диске: glTF/GLB, BIN, XML, конфигурации и карты. Программа не расшифровывает закрытые пакеты и не создаёт отсутствующую исходную геометрию.

### Быстрый старт

1. Установите `MSFSModelBuilder-1.2.0-Setup.exe` из [GitHub Release](https://github.com/zeleninvasiliy-cmd/MSFS2020_3d_model_extractor/releases/tag/v1.2.0) или запустите исходники с Python 3.13.
2. Установите Blender 5.x отдельно и укажите `blender.exe` в меню «Пути и настройки».
3. Создайте проект, выберите каталог MSFS или папку мода, затем самолёт.
4. Выполните сборку геометрии, проверьте `.blend` в Blender, после этого запустите текстурирование.

Подробные инструкции: [руководство пользователя](USER_GUIDE.md). Английская версия: [USER_GUIDE_EN.md](USER_GUIDE_EN.md). Справочник реализации и команд находится в [wiki](wiki/Home.md); страницы wiki содержат русскую и английскую версии.

### Запуск из исходников

```powershell
python .\msfs_builder_gui.py
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft"
python .\scripts\msfs_universal.py catalog --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py build .\examples\config.template.json --stage geometry
```

GUI и CLI используют один и тот же resolver, валидатор и Blender worker. Для неполного пакета мастер моделей показывает exterior/interior, LOD, число вершин и треугольников, а также происхождение ресурса. Редакторы правил и таблица текстур работают через кнопки и списки; ручная правка JSON для обычного цикла не нужна.

### Лицензия

Код распространяется по [PolyForm Noncommercial 1.0.0](LICENSE) с пояснением в [LICENSE_NOTICE.md](LICENSE_NOTICE.md). Некоммерческое, учебное, исследовательское и личное использование разрешено. Коммерческое использование требует отдельного разрешения. Самолёты, текстуры MSFS и пользовательские проекты в репозиторий не входят.

## English

MSFS Model Builder is a Windows pipeline for preparing static aircraft models from locally available Microsoft Flight Simulator 2020 resources and saving them as Blender `.blend` files. It imports geometry, materials and PBR textures, organizes objects into collections and keeps separate build variants. Animations are intentionally not imported.

Exact extraction requires the original files to be available locally: glTF/GLB, BIN, XML, configuration files and texture maps. The program does not decrypt protected packages or invent missing source geometry.

### Quick start

1. Install `MSFSModelBuilder-1.2.0-Setup.exe` from the [GitHub Release](https://github.com/zeleninvasiliy-cmd/MSFS2020_3d_model_extractor/releases/tag/v1.2.0), or run the source tree with Python 3.13.
2. Install Blender 5.x separately and select `blender.exe` in “Paths and settings”.
3. Create a project, select an MSFS package or mod folder, then choose an aircraft.
4. Build geometry, inspect the `.blend` in Blender, and run texturing afterwards.

See the [Russian user guide](USER_GUIDE.md) or the [English user guide](USER_GUIDE_EN.md). The [wiki](wiki/Home.md) contains the implementation and command reference in both languages.

### Source checkout

```powershell
python .\msfs_builder_gui.py
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft"
python .\scripts\msfs_universal.py catalog --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py build .\examples\config.template.json --stage geometry
```

The GUI and CLI share the same resolver, validator and Blender worker. For an incomplete package, the model wizard lists exterior/interior roles, LODs, vertex and triangle counts, and resource origin. Rule editors and the texture table are graphical; normal users do not need to edit JSON for the standard workflow.

### License

The code is distributed under [PolyForm Noncommercial 1.0.0](LICENSE), with project guidance in [LICENSE_NOTICE.md](LICENSE_NOTICE.md). Personal, educational, research and other noncommercial use is allowed. Commercial use requires separate permission. MSFS aircraft, textures and user projects are not included in this repository.

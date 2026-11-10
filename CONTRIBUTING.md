# Разработка

Python 3.13 x64, Windows. GUI и CLI используют стандартную библиотеку; `bpy` и NumPy для обработчиков предоставляет отдельно установленный Blender.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe msfs_builder_gui.py --self-test
```

Проверка обработчиков настоящим Blender:

```powershell
& 'C:\path\to\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_worker_checks.py
```

Для любого нового способа чтения модели добавьте маленький синтетический glTF-тест, опишите ограничения и проверьте прежние режимы. Новый графический инструмент проверяйте через его настоящие виджеты и настоящий CLI, а не в обход кнопок. Не добавляйте исходные самолёты, текстуры, свои проекты, токены и абсолютные пути своего профиля. Названия объектов сами по себе не доказывают правильную геометрию; визуальную проверку выполняет пользователь.

Сборка установщика: [release/BUILDING.md](release/BUILDING.md). Архитектура: [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md). Приоритеты расширения: [docs/COMPATIBILITY_ROADMAP.md](docs/COMPATIBILITY_ROADMAP.md) и [docs/FUTURE_ROADMAP.md](docs/FUTURE_ROADMAP.md). История изменений: [CHANGELOG.md](CHANGELOG.md).

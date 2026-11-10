# Building and Release

Сборочный компьютер: Windows x64, Python 3.13 x64, Inno Setup 7. На компьютере пользователя Python и Inno Setup не требуются. Blender устанавливается отдельно.

## Подготовка среды

Из корня репозитория:

```powershell
python -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r release/build_requirements.txt
```

Зависимости закреплены: `pyinstaller==6.16.0`, `pyinstaller-hooks-contrib`, `altgraph`, `packaging`, `pefile`, `pywin32-ctypes`, `setuptools`.

## Сборка

```powershell
powershell -ExecutionPolicy Bypass -File .\release\build_release.ps1 -Python C:\path\to\venv\Scripts\python.exe
```

`-ExecutionPolicy Bypass` действует только на один процесс и не меняет настройки Windows. Он нужен, когда политика выполнения скриптов не задана (все уровни `Undefined` → `Restricted`). Если политика уже `RemoteSigned`, флаг не требуется.

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `-Python` | `.venv-release\Scripts\python.exe` | интерпретатор сборочной среды |
| `-ISCC` | `C:\Program Files\Inno Setup 7\ISCC.exe` | компилятор Inno Setup |
| `-SkipFreeze` | выключен | пропустить PyInstaller, пересобрать только поставку и установщик |

## Что делает скрипт

1. Читает версию из `VERSION`.
2. PyInstaller `--onedir`: оконный `MSFSBuilder` из `msfs_builder_gui.py` и консольный `MSFSBuilderCLI` из `release/cli_entry.py`.
3. Объединяет поставки: оба executable используют общий `_internal`.
4. Копирует `VERSION`, два пользовательских руководства (`USER_GUIDE.md`, `USER_GUIDE_EN.md`) и лицензионные файлы Python/Tk/PyInstaller.
5. Смоук-тесты: `MSFSBuilderCLI.exe --help` и `MSFSBuilder.exe --self-test`.
6. Компилирует установщик Inno Setup с `/DAppVersion` из `VERSION`.
7. Создаёт portable ZIP и `SHA256SUMS.txt`.

Результаты:

```
release/dist/MSFSBuilder/                          автономная переносимая папка
release/output/MSFSModelBuilder-1.2.0-Setup.exe    установщик
release/output/MSFSModelBuilder-1.2.0-Portable.zip переносимая версия
release/output/SHA256SUMS.txt                      контрольные суммы
```

`release/build/`, `release/dist/` и `release/output/` исключены из git.

## Точка входа CLI

`release/cli_entry.py` исполняет поставляемый оркестратор через `runpy` с реальным путём скрипта. Явные импорты стандартной библиотеки в начале файла нужны, чтобы PyInstaller собрал модули, которые динамически исполняемый CLI использует (включая `urllib.parse` для resolver). Blender-only модули остаются в поставляемых скриптах и исполняются Python самого Blender.

## Установка

Inno Setup, per-user, без прав администратора:

- каталог `%LOCALAPPDATA%\Programs\MSFS Model Builder`;
- x64, Windows 10+, языки RU/EN, необязательный ярлык на рабочем столе;
- две дополнительные страницы мастера: каталог пакетов MSFS и `blender.exe`, с проверкой существования;
- после установки скрыто запускается `MSFSBuilder.exe --configure-only --configure-msfs "<dir>" --configure-blender "<exe>"`, что записывает `settings.json`;
- ярлыки в меню «Пуск» для приложения, HTML-руководства и деинсталлятора.

Деинсталлятор удаляет только установленные файлы. Проекты и настройки пользователя остаются.

## Переносимость

- Python включён в поставку; системный Python не используется.
- GUI запускает соседний `MSFSBuilderCLI.exe`, чтобы получать вывод и код возврата фоновых операций.
- Blender запускает поставляемые скрипты из `_internal/scripts` своим Python с `bpy` и NumPy.
- **Нельзя** переносить один `.exe` отдельно от `MSFSBuilderCLI.exe` и каталога `_internal`.
- Пути MSFS и Blender хранятся в профиле пользователя, а не в каталоге программы; кириллица в путях поддерживается.
- Результаты всегда вне пакета MSFS, чтобы созданные `.blend` не попадали в список самолётов симулятора.

## Проверка после сборки

```powershell
powershell -File .\release\verify_installer.ps1
```

Проверяются: тихая установка в отдельный каталог, запуск установленных GUI и CLI, сохранение путей через `--configure-only`, удаление тестовой установки с сохранением пользовательских настроек. Состав поставки на игровые ресурсы скрипт не проверяет — это контролируется правилами репозитория и сборочным скриптом.

## Публикация

Установщик и portable ZIP загружаются как файлы **GitHub Release**, а не в историю исходников. К тегу версии прикладываются `Setup.exe`, `Portable.zip` и `SHA256SUMS.txt`. Исходные документы и wiki остаются в основном репозитории.

Установщик не подписан цифровым сертификатом. Для публичного распространения следует подписать `.exe` и установщик доверенным сертификатом и проверить чистую Windows VM с выбранной версией Blender. Лицензия распространения исходников пока не выбрана: [LICENSE_NOTICE](../LICENSE_NOTICE.md).

Дальше: [Architecture](Architecture) · [Testing](Testing) · [Getting Started](Getting-Started)

---

## English version

A release build is made on Windows with Python 3.13 x64 and Inno Setup 7:

1. Create a virtual environment and install `release/build_requirements.txt`.
2. Run `release/build_release.ps1` with the build Python and optional `-ISCC`.
3. The script freezes the GUI and CLI, copies the two user guides and license notices, runs CLI/GUI smoke tests, builds Setup and Portable packages, and writes `SHA256SUMS.txt`.
4. Upload only the Setup, Portable ZIP and checksum file to the GitHub Release.

Blender and MSFS packages are never bundled. A portable build must keep both executables and the shared `_internal` directory together. The installer is per-user and does not delete projects or settings.

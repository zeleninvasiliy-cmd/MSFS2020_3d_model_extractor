# Сборка Windows-релиза

Сборочный компьютер: Windows x64, Python 3.13 x64, Inno Setup 7. На компьютере пользователя Python и Inno Setup не требуются. Blender устанавливается отдельно.

1. Создайте изолированную Python-среду и установите `build_requirements.txt`.
   Из корня репозитория:

   ```powershell
   python -m venv .venv-release
   .\.venv-release\Scripts\python.exe -m pip install -r release/build_requirements.txt
   ```
2. Выполните из каталога проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\release\build_release.ps1 -Python C:\path\to\venv\Scripts\python.exe
```

Параметр `-ISCC` позволяет указать другой путь к компилятору Inno Setup. По умолчанию используется `C:\Program Files\Inno Setup 7\ISCC.exe`.

`release/dist/MSFSBuilder` — автономная переносимая папка. `release/output/MSFSModelBuilder-1.2.0-Setup.exe` — установщик. Скрипт печатает SHA-256 готового установщика и проверяет запуск обеих программ. Исходники самолётов, проекты пользователя и `.blend` в установщик не входят.

GUI запускает отдельный `MSFSBuilderCLI.exe`, чтобы получать вывод и код возврата фоновых операций. Оба executable используют общий `_internal`. Blender запускает поставляемые исходные скрипты из `_internal/scripts` своим Python с `bpy` и NumPy. Не удаляйте и не переносите один `.exe` отдельно от остальной переносимой папки.

Установка выполняется для текущего пользователя в `%LOCALAPPDATA%\Programs\MSFS Model Builder`, без прав администратора. Выбранные во время установки пути передаются приложению через `--configure-only`, `--configure-msfs` и `--configure-blender`; пользовательские настройки находятся в `%LOCALAPPDATA%\MSFSModelBuilder\settings.json`.

Деинсталлятор удаляет только установленные файлы приложения. Проекты и настройки пользователя остаются. Установщик не подписан цифровым сертификатом. Для публичного распространения следует подписать `.exe` и установщик доверенным сертификатом и проверить чистую Windows VM с выбранной версией Blender.

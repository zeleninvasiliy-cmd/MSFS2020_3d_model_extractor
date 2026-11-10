# Загрузка на GitHub

В папке репозитория уже находятся только исходники, тесты, шаблоны и документация. Сборки EXE/ZIP, игровые ресурсы, рабочие проекты и локальные результаты проверок исключены. Ветка — `main`. Исходный код распространяется по PolyForm Noncommercial License 1.0.0 (см. `LICENSE` и `LICENSE_NOTICE.md`).

Перед первым публичным push выполните финальную проверку ниже. Она намеренно не включена в автоматический скрипт: commit и push требуют явного решения владельца.

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern '\.(blend|blend1|gltf|glb|bin|dds|pck|fsarchive|exe|zip)$'
python -m compileall -q msfs_builder_gui.py app_support.py rule_editor.py texture_table.py scripts tests
python msfs_builder_gui.py --self-test
python -m unittest discover -s tests -p "test_*.py" -q
```

Команда `git ls-files` должна не вывести игровые/сборочные расширения. Если в `git status` видны только ожидаемые исходники и документация, можно переходить к индексации.

## Через терминал

Создайте пустой репозиторий в своём аккаунте GitHub без автогенерации README и .gitignore. Затем выполните в этой папке:

```powershell
git status
git add .
git commit -m "Release source 1.2.0"
git remote add origin https://github.com/YOUR_ACCOUNT/msfs-model-builder.git
git push -u origin main
```

Вместо `YOUR_ACCOUNT` укажите свой аккаунт. Авторизацию выполните стандартным способом GitHub; токены не сохраняйте в исходниках. Если имя/email автора Git ещё не настроены, задайте свои значения локально для этого репозитория через `git config user.name` и `git config user.email`.

Альтернатива: GitHub Desktop → File → Add local repository → выбрать эту папку → создать начальный commit → Publish repository.

## Релизные файлы

Установщик и Portable ZIP загружайте как файлы GitHub Release, а не в историю исходников. При выпуске тега `v1.2.0` приложите Setup.exe, Portable.zip и SHA256SUMS.txt из отдельного готового релиза. Репозиторий содержит инструкции пересборки `release/BUILDING.md`.

## Wiki

Каталог `wiki/` содержит готовые страницы. GitHub wiki — отдельный репозиторий, поэтому копирование выполняется после первой публикации основного репозитория:

```powershell
git clone https://github.com/YOUR_ACCOUNT/msfs-model-builder.wiki.git ..\msfs-model-builder-wiki
Copy-Item .\wiki\*.md ..\msfs-model-builder-wiki\ -Force
git -C ..\msfs-model-builder-wiki add .
git -C ..\msfs-model-builder-wiki commit -m "Wiki 1.2.0"
git -C ..\msfs-model-builder-wiki push
```

Если GitHub ещё не создал wiki-репозиторий, откройте вкладку Wiki на сайте и создайте первую страницу вручную — после этого клонирование сработает. Внутренние ссылки в страницах записаны без расширения `.md`, как этого требует GitHub wiki. Каталог `wiki/` остаётся в основном репозитории как источник правок.

CI проверяет GUI/CLI на Windows без симулятора. Реальные самолёты и визуальная приёмка остаются локальными. Для issues используйте обезличенные журналы и минимальные синтетические примеры вместо пакетов игры.

## После публикации

1. Включите branch protection для `main` и обязательную проверку Windows Actions.
2. Создайте GitHub Release `v1.2.0` и приложите Setup.exe, Portable.zip и SHA256SUMS.txt из локального `release/output`.
3. Скопируйте `wiki/*.md` в GitHub Wiki, если Wiki нужна пользователям.
4. Проверьте, что в описании релиза есть отдельное предупреждение: Blender устанавливается отдельно, а визуальная проверка геометрии выполняется пользователем.
5. После первой обратной связи обновляйте `CHANGELOG.md` и `docs/FUTURE_ROADMAP.md`; не переписывайте исторический `RELEASE_AUDIT.md` задним числом.

Удалённый репозиторий, commit и push автоматически не создавались.

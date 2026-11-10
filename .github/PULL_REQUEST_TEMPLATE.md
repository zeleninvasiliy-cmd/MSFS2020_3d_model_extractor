## Что изменено

Коротко опишите пользовательский результат и затронутые этапы (`inventory`, `index`, `models`, geometry, textures, GUI, release).

## Проверки

- [ ] `python -m compileall -q msfs_builder_gui.py app_support.py rule_editor.py texture_table.py scripts tests`
- [ ] `python msfs_builder_gui.py --self-test`
- [ ] `python -m unittest discover -s tests -p "test_*.py" -q`
- [ ] Проверен `git diff --check`
- [ ] Для изменений геометрии выполнена отдельная проверка в Blender или указано, почему она невозможна

## Совместимость и данные

- [ ] В репозиторий не добавлены MSFS-пакеты, текстуры, `.blend`, BIN/GLTF/GLB, личные пути или секреты
- [ ] Новые ограничения и коды ошибок описаны в документации
- [ ] Добавлены синтетические тесты без игровых ресурсов

## Риски

Опишите известные ограничения, fallback и обратную совместимость с существующими проектами.

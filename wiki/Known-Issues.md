# Known Issues / Известные ограничения

## English version

This list describes the current development state based on release **1.3.0**; changes on feature branches are not release artifacts.

### Source-data limits

- Exact geometry requires an available glTF/GLB and every referenced BIN buffer.
- Shared packages containing only XML, sounds or textures are reported as `COMMON_RESOURCES_ONLY`.
- A livery without an installed `base_container` remains partial.
- Packages with multiple candidates require an explicit role and LOD selection.
- Draco- and Meshopt-compressed geometry (`KHR_draco_mesh_compression`, `EXT_meshopt_compression`) is detected but not decoded; use another LOD or decompress it in the source exporter. Other features reported as unsupported by deep diagnosis are not guessed.
- Protected or encrypted resources are not decrypted.

### Build limits

- Animations are intentionally not imported.
- The result may require a Blender check of symmetry, landing gear, control surfaces and glazing.
- Filename-based role detection is only a hint; the user confirms the final choice.
- Non-standard DDS normal maps may need manual review.
- There is no embedded 3D preview.

### Safe response

1. Run the deep package diagnosis.
2. Check the origin of every selected glTF and the presence of BIN files.
3. Confirm the model composition in the wizard for a partial package.
4. Use the graphical placement or mirror rule for an offset part, then compare a new Blender variant.
5. Do not edit MSFS source files or remove an active checkpoint.

---

## Русская версия

Список относится к версии **1.3.0** и описывает действующие ограничения программы.

### Ограничения исходных данных

- Для точной геометрии нужны доступные glTF/GLB и все указанные в них BIN-буферы.
- Общие пакеты только с XML, звуками или текстурами получают статус `COMMON_RESOURCES_ONLY`.
- Ливрея без установленного `base_container` остаётся частичной.
- Для пакетов с несколькими кандидатами пользователь явно выбирает роль и LOD.
- Геометрия, сжатая Draco или Meshopt (`KHR_draco_mesh_compression`, `EXT_meshopt_compression`), распознаётся, но не декодируется; выберите другой LOD или распакуйте её в исходном экспортёре. Другие отмеченные диагностикой возможности программа не подменяет догадкой.
- Защищённые или зашифрованные ресурсы не расшифровываются.

### Ограничения сборки

- Анимации намеренно не импортируются.
- Результат может потребовать проверки симметрии, шасси, управляющих поверхностей и остекления в Blender.
- Определение роли по имени файла является только подсказкой; окончательное решение подтверждает пользователь.
- DDS-нормали нестандартного формата могут потребовать ручной проверки.
- Встроенного 3D-просмотра нет.

### Безопасные действия

1. Запустите подробную диагностику пакета.
2. Проверьте происхождение выбранных glTF и наличие BIN.
3. Для частичного пакета подтвердите состав в мастере моделей.
4. Для смещения детали используйте графический placement или mirror и сравните новый вариант в Blender.
5. Не редактируйте исходные файлы MSFS и не удаляйте активный checkpoint.

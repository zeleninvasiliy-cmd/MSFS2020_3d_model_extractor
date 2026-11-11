# Known Issues / Известные ограничения

## English version

This list applies to **1.2.0**. These are current operating limits, not a historical audit of earlier milestones.

### Source-data limits

- Exact geometry is impossible without an available glTF/GLB and its BIN buffer.
- Shared packages containing only XML, sounds or textures are reported as `COMMON_RESOURCES_ONLY`.
- A livery without an installed `base_container` remains partial.
- Packages with multiple candidates require an explicit role and LOD selection.
- Draco, KTX2 and other unsupported glTF extensions are diagnosed before Blender; the program never silently invents geometry.
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

Список относится к версии **1.2.0**. Это рабочие ограничения, а не исторический аудит старых этапов.

### Ограничения исходных данных

- Без доступного glTF/GLB и соседнего BIN точная геометрия невозможна.
- Общие пакеты с XML, звуками или текстурами без модели получают статус `COMMON_RESOURCES_ONLY`.
- Ливрея без установленного `base_container` остаётся частичной.
- Пакеты с несколькими кандидатами требуют ручного выбора роли и LOD.
- Draco, KTX2 и другие неподдержанные расширения glTF диагностируются до Blender; программа не подменяет геометрию догадкой.
- Закрытые или зашифрованные ресурсы не расшифровываются.

### Ограничения сборки

- Анимации намеренно не импортируются.
- Результат может потребовать проверки симметрии, шасси, управляющих поверхностей и стекла в Blender.
- Определение роли по имени файла является только подсказкой; окончательное решение принимает пользователь.
- DDS-нормали нестандартного формата могут потребовать ручной проверки.
- Встроенного 3D-просмотра нет.

### Безопасные действия

1. Запустите подробную диагностику пакета.
2. Проверьте происхождение выбранных glTF и наличие BIN.
3. Для частичного пакета подтвердите состав в мастере моделей.
4. Для смещения детали используйте графический placement или mirror, затем сравните новый вариант в Blender.
5. Не редактируйте исходные файлы MSFS и не удаляйте активный checkpoint.

## English version

This list applies to **1.2.0**. These are current operating limits, not a historical audit of earlier milestones.

### Source-data limits

- Exact geometry is impossible without an available glTF/GLB and its BIN buffer.
- Shared packages containing only XML, sounds or textures are reported as `COMMON_RESOURCES_ONLY`.
- A livery without an installed `base_container` remains partial.
- Packages with multiple candidates require an explicit role and LOD selection.
- Draco, KTX2 and other unsupported glTF extensions are diagnosed before Blender; the program never silently invents geometry.
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

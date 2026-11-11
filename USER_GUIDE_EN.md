# MSFS Model Builder — User Guide (English)

This guide matches **1.2.1**. Blender is installed separately; animations are outside the current workflow.

## 1. Installation

Download the Setup or Portable package from the [GitHub Release](https://github.com/zeleninvasiliy-cmd/MSFS2020_3d_model_extractor/releases/tag/v1.2.1). End users do not need Python or Inno Setup. Install Blender 5.x with the glTF importer and NumPy.

To run from source, use Windows, Python 3.13 x64 and a separate Blender installation:

```powershell
cd "C:\Path\To\msfs-model-builder"
python .\msfs_builder_gui.py
```

## 2. Create a project

1. Open **Files → New project**.
2. Select a project workspace. The path dialog can create a new folder.
3. Select an MSFS package, `Community`, `Official`, an unpacked mod, or a specific aircraft folder.
4. If several entries share a name, select the required package and livery.
5. In the general settings choose Blender and the output directory. Work outside an open project is disabled.

MSFS roots are detected from `UserCfg.opt` and common install locations. If an aircraft or its base is in another library, click **Package folders...** and add the required folders. The window separates automatically detected roots from manual entries and shows how many folders take part in search and how many saved paths are missing. Missing paths have a ⚠ marker; remove them and add the correct folder again. If the list cannot be refreshed, technical details are written to the **Log** tab. **Choose catalog** also adds the selected path and starts a scan.

Projects store settings, selected models, rules, map replacements and the `.blend` variant history. The original aircraft folder is never modified.

## 3. Diagnose the package

When an aircraft is missing or marked partial, click **Deep package check**. The result includes a reason code and an action:

| Code | Meaning | Action |
|---|---|---|
| `SUPPORTED_PARTIAL` | only part of the model set is available | open the model wizard and confirm the composition |
| `COMMON_RESOURCES_ONLY` | only shared XML/textures/sounds were found | select the aircraft package |
| `LIVERY_ONLY` | a livery exists without a model | add the base aircraft package |
| `MISSING_MODEL_CFG` / `INVALID_MODEL_CFG` | `model.cfg` is missing or invalid | choose glTF files in the wizard |
| `MISSING_BUFFER` | the BIN next to a glTF is missing | restore the source package |
| `UNRESOLVED_ALIAS` | `base_container` was not found | add the root containing the base aircraft |
| `UNSUPPORTED_GLTF_FEATURE` | the format or primitive is unsupported | choose another LOD or keep the package for a separate adapter |

The package index resolves livery references to a base aircraft. Ambiguous matches are shown to the user instead of guessed.

## 4. Model wizard

For an incomplete package, the wizard displays separate **Exterior** and **Interior** lists. Each row shows LOD, vertices, triangles, role source, origin and BIN availability. Only roles declared by the package are selected by default. A role suggested only from a filename must be confirmed manually.

The selection is saved in the project. Partial builds receive the `_partial` variant suffix.

## 5. Build geometry

On the **Geometry** tab choose `draw_mode`, `split_by_skin`, `split_spatial`, mirroring and placement only when needed. Click **Build geometry**. The screen remains on the geometry tab and shows the status, progress, error type and output path.

Every build mode has its own sequence. Repeating a mode creates the next numbered file in the project `blend` folder instead of overwriting an earlier result. After a successful build, use **Open in Blender** or **Show in Explorer**.

Inspect the result in Blender: left/right symmetry, landing gear, control surfaces, cockpit and unexpected objects. Use **Editing rules** for corrections instead of changing MSFS source files.

## 6. Editing rules

The graphical editor supports:

- splitting by skin joints or spatial bounds;
- mirrored copies with reflected transforms and UVs;
- placement by the anchor translation while preserving the part rotation and scale;
- moving objects into collections;
- keeping pivots and excluding individual objects.

**Validate all rules** calls the same validation used by the CLI before Blender starts.

## 7. Textures

On the **Textures** tab select a geometry checkpoint and click **Add textures**. The table shows each map, material, state, source file and candidates found in installed MSFS packages. Choose replacements with the graphical controls; the key remains the glTF map name, not the replacement filename.

If a map is missing, search installed packages first. DDS normal maps may require manual review; the program reports when a format cannot be decoded safely.

## 8. CLI and diagnostics

```powershell
python .\scripts\msfs_universal.py inventory "C:\Path\To\Aircraft" --deep
python .\scripts\msfs_universal.py catalog --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py catalog --root "D:\Official" --root "E:\Community"
python .\scripts\msfs_universal.py roots --root "D:\Mods"
python .\scripts\msfs_universal.py catalog --deep --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py index --no-cache --root "D:\MSFS\Packages"
python .\scripts\msfs_universal.py models "C:\Path\To\Aircraft"
python .\scripts\msfs_universal.py validate .\project.json
python .\scripts\msfs_universal.py build .\project.json --stage geometry
```

`inventory` checks one package; `catalog` lists aircraft; add `--deep` to validate every glTF/GLB and BIN before project creation. `index` resolves package inheritance, `models` prints role candidates, `validate` checks configuration without Blender, and `build` runs a stage. The GUI exposes the same option as **Deep glTF/BIN check**. See [wiki/CLI-Reference.md](wiki/CLI-Reference.md) for the complete reference.

`roots` lists automatically detected roots, added roots and the effective search set. Repeat `--root` to pass multiple directories.

## 9. When the result is wrong

First verify the selected glTF files and resource origin, then compare another build mode. Use placement by anchor translation for an offset part, `mirror_objects` for a mirrored part, and the object tree to exclude unwanted objects. If the original glTF/BIN is missing, exact geometry cannot be reconstructed.

Stage logs are available on the **Journal** tab and in the project folder. Do not delete a checkpoint during an active build; the program only removes stale locks automatically.

## 10. Current limitations

- Blender is required separately.
- Animations are not imported.
- Protected or missing source files are not reconstructed.
- The user must inspect the result in Blender.
- Commercial use of the code requires separate permission under the project license.

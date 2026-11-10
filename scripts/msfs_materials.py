"""Generic MSFS ALBD/COMP/NORM/EMISSIVE material builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--model", type=Path, action="append", required=True)
    parser.add_argument("--texture-dir", type=Path, required=True)
    parser.add_argument("--converted-normal-dir", type=Path)
    parser.add_argument("--extra-texture-dir", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def texture_filename(gltf, textures, images, index):
    if index is None:
        return None
    if not isinstance(index, int) or not 0 <= index < len(textures):
        raise ValueError(f"Invalid glTF texture index: {index}")
    tex = textures[index]
    ext = tex.get("extensions", {})
    dds = ext.get("MSFT_texture_dds", {})
    source = dds.get("source", tex.get("source"))
    if source is None:
        return None
    if not isinstance(source, int) or not 0 <= source < len(images):
        raise ValueError(f"Invalid glTF image index: {source}")
    return images[source].get("uri")


def read_materials(model_path):
    data = json.loads(model_path.read_text(encoding="utf-8-sig"))
    textures = data.get("textures", [])
    images = data.get("images", [])
    result = {}
    for index, material in enumerate(data.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        base = pbr.get("baseColorTexture", {})
        comp = pbr.get("metallicRoughnessTexture", {})
        normal = material.get("normalTexture", {})
        emissive = material.get("emissiveTexture", {})
        result[index] = {
            "name": material.get("name", f"material_{index}"),
            "index": index,
            "model": model_path.name,
            "albd": texture_filename(data, textures, images, base.get("index")),
            "comp": texture_filename(data, textures, images, comp.get("index")),
            "norm": texture_filename(data, textures, images, normal.get("index")),
            "emissive": texture_filename(data, textures, images, emissive.get("index")),
            "base_color_factor": pbr.get("baseColorFactor", [1, 1, 1, 1]),
            "metallic_factor": pbr.get("metallicFactor", 1.0),
            "roughness_factor": pbr.get("roughnessFactor", 1.0),
            "emissive_factor": material.get("emissiveFactor", [0, 0, 0]),
            "alpha_mode": material.get("alphaMode", "OPAQUE"),
            "alpha_cutoff": material.get("alphaCutoff", 0.5),
            "double_sided": bool(material.get("doubleSided", False)),
        }
    return result


def resolve_texture(texture_dir, filename, converted_normal_dir=None, extra_texture_dirs=None):
    if not filename:
        return None
    # Packaged MSFS glTF files may contain relative or absolute developer
    # paths.  The package texture folders are authoritative, so resolve by
    # the case-insensitive basename instead of the embedded path.
    basename = Path(str(filename).replace("\\", "/")).name
    if converted_normal_dir is not None and "_NORM." in filename.upper():
        converted = converted_normal_dir / (basename + ".png")
        if converted.is_file():
            return converted.resolve()
    direct = texture_dir / basename
    if direct.is_file():
        return direct.resolve()
    wanted = basename.casefold()
    search_dirs = [texture_dir] + list(extra_texture_dirs or [])
    for search_dir in search_dirs:
        for candidate in search_dir.rglob("*"):
            if candidate.is_file() and candidate.name.casefold() == wanted:
                return candidate.resolve()
    return None


def load_image(path, colorspace):
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.colorspace_settings.name = colorspace
    except Exception:
        pass
    return image


def new_image_node(nodes, image, name, x, y):
    node = nodes.new("ShaderNodeTexImage")
    node.name = name
    node.label = name
    node.image = image
    node.location = (x, y)
    return node


def set_alpha_mode(material, alpha_mode):
    if alpha_mode == "OPAQUE":
        return
    try:
        material.surface_render_method = "DITHERED"
    except Exception:
        # Blender 4.0 and older use blend_method; newer releases removed it.
        if hasattr(material, "blend_method"):
            material.blend_method = "CLIP" if alpha_mode == "MASK" else "BLEND"


def build_material(material, source, texture_dir, missing, extra_texture_dirs=None, *, resolver=None):
    material.use_nodes = True
    material.node_tree.nodes.clear()
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (650, 40)
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (380, 40)
    shader.name = "MSFS Universal Principled"
    shader.label = "MSFS Universal PBR"
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    factor = source["base_color_factor"]
    shader.inputs["Base Color"].default_value = tuple(factor[:3]) + (factor[3] if len(factor) > 3 else 1.0,)
    shader.inputs["Metallic"].default_value = source["metallic_factor"]
    shader.inputs["Roughness"].default_value = source["roughness_factor"]
    emissive_factor = source.get("emissive_factor", [0, 0, 0])
    shader.inputs["Emission Color"].default_value = tuple(emissive_factor) + (1.0,)
    shader.inputs["Emission Strength"].default_value = 1.0

    if resolver is None:
        def resolver(key, filename):
            normal_dir = getattr(build_material, "converted_normal_dir", None) if key == "norm" else None
            return resolve_texture(texture_dir, filename, normal_dir, extra_texture_dirs)
    albd_path, comp_path, norm_path, emissive_path = (
        resolver(key, source[key]) for key in ("albd", "comp", "norm", "emissive")
    )
    for key, original, resolved in (("albd", source["albd"], albd_path), ("comp", source["comp"], comp_path),
                                    ("norm", source["norm"], norm_path), ("emissive", source["emissive"], emissive_path)):
        if original and resolved is None:
            missing.append({"material": material.name, "map": key, "filename": original})

    if albd_path:
        albd = new_image_node(nodes, load_image(albd_path, "sRGB"), "MSFS ALBD", -800, 180)
        color = nodes.new("ShaderNodeMixRGB")
        color.blend_type = "MULTIPLY"
        color.inputs[0].default_value = 1.0
        color.inputs[2].default_value = tuple(factor[:3]) + (1.0,)
        links.new(albd.outputs["Color"], color.inputs[1])
        links.new(color.outputs[0], shader.inputs["Base Color"])
        if source["alpha_mode"] != "OPAQUE" and "Alpha" in albd.outputs:
            alpha = nodes.new("ShaderNodeMath")
            alpha.operation = "MULTIPLY"
            alpha.inputs[1].default_value = factor[3] if len(factor) > 3 else 1.0
            links.new(albd.outputs["Alpha"], alpha.inputs[0])
            links.new(alpha.outputs[0], shader.inputs["Alpha"])

    if comp_path:
        comp = new_image_node(nodes, load_image(comp_path, "Non-Color"), "MSFS COMP", -800, -80)
        sep = nodes.new("ShaderNodeSeparateColor")
        sep.mode = "RGB"
        sep.location = (-520, -80)
        links.new(comp.outputs["Color"], sep.inputs["Color"])
        # MSFS COMP convention: R=occlusion, G=roughness, B=metallic.
        for channel, socket, factor_key in (("Green", "Roughness", "roughness_factor"), ("Blue", "Metallic", "metallic_factor")):
            multiply = nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            multiply.inputs[1].default_value = source[factor_key]
            links.new(sep.outputs[channel], multiply.inputs[0])
            links.new(multiply.outputs[0], shader.inputs[socket])

    if norm_path:
        norm = new_image_node(nodes, load_image(norm_path, "Non-Color"), "MSFS NORM", -800, -340)
        sep = nodes.new("ShaderNodeSeparateColor")
        sep.mode = "RGB"
        sep.location = (-520, -340)
        invert_g = nodes.new("ShaderNodeMath")
        invert_g.operation = "SUBTRACT"
        invert_g.location = (-300, -300)
        invert_g.inputs[0].default_value = 1.0
        combine = nodes.new("ShaderNodeCombineColor")
        combine.mode = "RGB"
        combine.location = (-80, -340)
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (170, -220)
        links.new(norm.outputs["Color"], sep.inputs["Color"])
        links.new(sep.outputs["Red"], combine.inputs["Red"])
        links.new(sep.outputs["Green"], invert_g.inputs[1])
        links.new(invert_g.outputs[0], combine.inputs["Green"])
        links.new(sep.outputs["Blue"], combine.inputs["Blue"])
        links.new(combine.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])

    if emissive_path:
        emissive = new_image_node(nodes, load_image(emissive_path, "sRGB"), "MSFS EMISSIVE", -800, 440)
        emission = nodes.new("ShaderNodeMixRGB")
        emission.blend_type = "MULTIPLY"
        emission.inputs[0].default_value = 1.0
        emission.inputs[2].default_value = tuple(emissive_factor) + (1.0,)
        links.new(emissive.outputs["Color"], emission.inputs[1])
        links.new(emission.outputs[0], shader.inputs["Emission Color"])
        if "Emission Strength" in shader.inputs:
            shader.inputs["Emission Strength"].default_value = 1.0

    glass_name = material.name.casefold()
    if any(token in glass_name for token in ("glass", "windshield")) and not any(
            token in glass_name for token in ("glass_fiber", "fiberglass", "fibreglass")):
        if "Transmission Weight" in shader.inputs:
            shader.inputs["Transmission Weight"].default_value = 0.85
        shader.inputs["Roughness"].default_value = min(shader.inputs["Roughness"].default_value, 0.12)
        shader.inputs["Alpha"].default_value = 0.38
    set_alpha_mode(material, source["alpha_mode"])
    material.diffuse_color = tuple(factor[:3]) + (factor[3] if len(factor) > 3 else 1.0,)
    material["msfs_texture_stage"] = "v1"
    material["msfs_albd"] = source["albd"] or ""
    material["msfs_comp"] = source["comp"] or ""
    material["msfs_norm"] = source["norm"] or ""
    material["msfs_alpha_mode"] = source["alpha_mode"]
    return {"albd": bool(albd_path), "comp": bool(comp_path), "norm": bool(norm_path), "emissive": bool(emissive_path)}


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()), load_ui=False, use_scripts=False)
    texture_dir = args.texture_dir.resolve()
    build_material.converted_normal_dir = args.converted_normal_dir.resolve() if args.converted_normal_dir else None
    extra_texture_dirs = [path.resolve() for path in args.extra_texture_dir]
    sources = {}
    for path in args.model:
        path = path.resolve()
        sources[path.name] = read_materials(path)

    missing = []
    applied = []
    skipped = []
    for material in bpy.data.materials:
        model = material.get("msfs_model")
        index = material.get("msfs_material_index")
        if model not in sources or index is None or int(index) not in sources[model]:
            skipped.append(material.name)
            continue
        source = sources[model][int(index)]
        maps = build_material(material, source, texture_dir, missing, extra_texture_dirs)
        applied.append({"material": material.name, "source": source["name"], "model": model, "index": int(index), "maps": maps})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    report = {
        "blend": str(args.output.resolve()),
        "texture_dir": str(texture_dir),
        "material_count": len(bpy.data.materials),
        "applied_count": len(applied),
        "skipped_materials": skipped,
        "missing_textures": missing,
        "applied": applied,
        "image_count": len(bpy.data.images),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"applied": len(applied), "images": len(bpy.data.images), "missing": len(missing)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

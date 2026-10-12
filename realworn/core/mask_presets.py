"""Mask presets (ING-6): a layer's whole mask setup (ingredients, Edge Lock, Levels, Height Blend,
but never the painted image) saved as JSON in the user's config folder and applied to any layer,
like Substance smart masks. References are stored by the referenced layer's name and resolved
among the target's layers below on load (dropped if there is no such layer)."""

import json
import os
import re

import bpy

FOLDER = None  # tests point this at a temp folder
_ING = ("kind", "amount", "scale", "rotation", "contrast", "invert", "seed", "angle", "width")
_LAYER = ("lock_source", "lock_strength", "lock_width", "threshold", "softness", "use_height_blend", "height_blend")
VERSION = 1


def folder():
    path = FOLDER or bpy.utils.user_resource("CONFIG", path=os.path.join("realworn", "mask_presets"), create=True)
    os.makedirs(path, exist_ok=True)
    return path


def _file(name):
    safe = re.sub(r"[^A-Za-z0-9 _.-]", "_", name).strip() or "preset"
    return os.path.join(folder(), safe + ".json")


def list_presets():
    return sorted(os.path.splitext(f)[0] for f in os.listdir(folder()) if f.endswith(".json"))


def capture(mat, layer):
    from . import compiler
    data = {"version": VERSION, "layer": {k: getattr(layer, k) for k in _LAYER}, "ingredients": []}
    for ing in layer.ingredients:
        d = {k: getattr(ing, k) for k in _ING}
        if ing.kind == "GRUNGE" and ing.image is not None:
            d["image"] = ing.image.name
            d["image_path"] = bpy.path.abspath(ing.image.filepath) if ing.image.filepath else ""
        if ing.kind == "REFERENCE":
            ref = compiler.layer_by_id(mat, ing.ref_layer_id)
            d["ref_name"] = ref.name if ref is not None else ""
        data["ingredients"].append(d)
    return data


def save(mat, layer, name):
    path = _file(name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(capture(mat, layer), fh, indent=1, sort_keys=True)
    return path


def _image(d):
    img = bpy.data.images.get(d.get("image", ""))
    if img is not None:
        return img
    p = d.get("image_path", "")
    if p and os.path.exists(p):
        img = bpy.data.images.load(p, check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        return img
    from . import grunge
    try:
        return grunge.load(os.path.splitext(d.get("image", ""))[0])
    except KeyError:
        return None


def apply(mat, layer, data):
    """Replace the layer's mask setup with `data` (from capture() or a preset file)."""
    from . import compiler, layers
    below = {ly.name: ly.id for ly in layers.layers_below(mat, layer)}
    with compiler.batch(mat):
        layer.ingredients.clear()
        for k, v in data.get("layer", {}).items():
            if k in _LAYER:
                setattr(layer, k, v)
        for d in data.get("ingredients", []):
            if d.get("kind") == "REFERENCE" and d.get("ref_name") not in below:
                continue  # ING-5: only layers below can be referenced
            ing = layer.ingredients.add()
            for k in _ING:
                if k in d:
                    setattr(ing, k, d[k])
            if ing.kind == "GRUNGE":
                ing.image = _image(d)
            elif ing.kind == "REFERENCE":
                ing.ref_layer_id = below[d["ref_name"]]
    compiler.compile(mat)
    return layer


def load(mat, layer, name):
    with open(_file(name), encoding="utf-8") as fh:
        return apply(mat, layer, json.load(fh))

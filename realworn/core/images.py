"""Mask and content images: create, size, resize, export, and never lose paint on save.

PNT-1  one RGBA mask per painted layer, RW_<object>_<layer>_mask, non-colour, alpha 0 = not
       painted (Channel Packed so colour and alpha never premultiply).
PNT-2  resolution from texel density: px per metre of the object's largest dimension, rounded to
       a power of two, clamped 512..4096; Resize keeps the paint (resampled).
SAV-1  created packed by default; preference PNG writes //textures/realworn/<object>/<image>.png.
SAV-2  save_pre handler: every dirty RealWorn image is packed or written before the file saves
       (pattern from Ucupaint image_ops.save_pack_all and Paint System image.save_image, see
       docs/reference_notes.md; no code copied).
"""

import math
import os

import bpy
import numpy as np

from . import naming

MIN_RES, MAX_RES = 512, 4096
FORCE_STORAGE = None  # tests set "PACKED" / "PNG" (preferences are unavailable unregistered)


def _prefs():
    try:
        from ..props import prefs
        return prefs()
    except Exception:
        return None


def texel_resolution(obj, density=None):
    """PNT-2: power of two of (density px/m * largest world dimension), clamped 512..4096."""
    if density is None:
        p = _prefs()
        density = p.texel_density if p is not None else 1024
    dim = max(obj.dimensions) if obj is not None else 1.0
    px = max(density * max(dim, 1e-3), 1.0)
    res = 2 ** int(round(math.log2(px)))
    return int(min(max(res, MIN_RES), MAX_RES))


def _fill(img, rgba):
    w, h = img.size
    img.pixels.foreach_set(np.tile(np.asarray(rgba, np.float32), w * h))


def is_rw_image(img):
    return img is not None and (naming.IMG_MASK in img or naming.IMG_CONTENT in img)


def create_mask(obj, layer, res=None, kind="mask"):
    """New RGBA image for a layer's mask (or content), transparent, tagged, packed or saved."""
    res = res or (layer.mask_res if layer.mask_res else texel_resolution(obj))
    name = (naming.mask_image_name if kind == "mask" else naming.content_image_name)(obj.name, layer.name)
    img = bpy.data.images.new(name, res, res, alpha=True, float_buffer=False)
    img.alpha_mode = "CHANNEL_PACKED"
    if kind == "mask":
        img.colorspace_settings.name = "Non-Color"
        _fill(img, (0.0, 0.0, 0.0, 0.0))
        img[naming.IMG_MASK] = "{}/{}".format(obj.name, layer.id)
    else:
        _fill(img, (1.0, 1.0, 1.0, 0.0))
        img[naming.IMG_CONTENT] = "{}/{}".format(obj.name, layer.id)
    store(img, obj)
    return img


def ensure_mask(obj, mat, layer):
    if layer.mask_image is None:
        layer.mask_image = create_mask(obj, layer)  # structural: compiles
    return layer.mask_image


def ensure_content(obj, mat, layer):
    if layer.content_image is None:
        layer.content_image = create_mask(obj, layer, kind="content")
    return layer.content_image


def storage_mode():
    if FORCE_STORAGE:
        return FORCE_STORAGE
    p = _prefs()
    return p.mask_storage if p is not None else "PACKED"


def store(img, obj=None, blend_path=None):
    """SAV-1: pack (default) or write a PNG under //textures/realworn/<object>/ next to the .blend
    (`blend_path` is the file being saved, so the very first save already writes PNGs).
    Returns 'packed' or 'saved'."""
    blend_path = blend_path or bpy.data.filepath
    if storage_mode() == "PNG" and blend_path:
        owner = (img.get(naming.IMG_MASK) or img.get(naming.IMG_CONTENT) or "realworn/").split("/")[0]
        owner = owner or (obj.name if obj else "realworn")
        folder = os.path.join(os.path.dirname(blend_path), "textures", "realworn", bpy.path.clean_name(owner))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, bpy.path.clean_name(img.name) + ".png")
        try:
            if img.packed_file is not None:
                img.unpack(method="REMOVE")
            img.filepath_raw = path
            img.file_format = "PNG"
            img.save()
            img.source = "FILE"
            img.filepath = "//" + os.path.relpath(path, os.path.dirname(blend_path)).replace("\\", "/")
            return "saved"
        except (RuntimeError, ValueError):
            pass  # fall back to packing (Paint System does the same)
    if img.packed_file is not None and not img.is_dirty:
        return "packed"
    img.pack()
    return "packed"


def save_all(blend_path=None, force=False):
    """SAV-2: called from save_pre with the path being saved. Packs or writes every RealWorn
    image that has unsaved pixels or no storage yet."""
    done = 0
    for img in bpy.data.images:
        if not is_rw_image(img):
            continue
        unstored = img.packed_file is None and not (img.filepath and os.path.exists(bpy.path.abspath(img.filepath)))
        if img.is_dirty or force or unstored:
            store(img, blend_path=blend_path)
            done += 1
    return done


def resize(img, res):
    """Resize keeps existing paint (resampled by Blender's scale())."""
    if tuple(img.size) == (res, res):
        return img
    img.scale(res, res)
    store(img)
    return img


def fill(img, value):
    """PNT-7 Fill (1: layer everywhere, painted) / Clear (0: back to not painted, alpha 0)."""
    if value > 0:
        _fill(img, (1.0, 1.0, 1.0, 1.0))
    else:
        _fill(img, (0.0, 0.0, 0.0, 0.0))
    img.update()
    store(img)


def pixels(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def export_masks(obj, folder):
    """REM-2 Export Masks: one PNG per painted layer image. Returns the written paths."""
    from . import setup
    os.makedirs(folder, exist_ok=True)
    out = []
    for mat in setup.layered_materials(obj):
        for ly in mat.realworn.layers:
            for kind, img in (("mask", ly.mask_image), ("content", ly.content_image)):
                if img is None:
                    continue
                path = os.path.join(folder, "{}_{}_{}.png".format(bpy.path.clean_name(mat.name),
                                                                bpy.path.clean_name(ly.name), kind))
                copy = img.copy()
                try:
                    copy.filepath_raw = path
                    copy.file_format = "PNG"
                    copy.save()
                    out.append(path)
                finally:
                    bpy.data.images.remove(copy)
    return out

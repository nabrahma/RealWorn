"""Painted images: create, size, resize, export, and never lose paint on save.

MSK-3  one image per painted layer, RW_<object>_<layer>_mask on RW_Paint: 2048 px per metre of
       the object's largest dimension, a power of two clamped 1024..4096, 8-bit. Reveal masks are
       float so Depth has no stepping (Blender keeps float images at 32 bits in memory; they are
       stored as half-float EXR in PNG mode). Masks start black: nothing painted.
DEC-1  a Decals layer's image is RGBA, created fully transparent (alpha 0, the key
       setting); DEC-2 4096 px by default (2048 and 8192 options).
       Resize and Upgrade Mask keep the paint (bicubic).
SAV-1  created packed by default; preference PNG writes //textures/realworn/<object>/<image>.png.
SAV-2  save_pre handler: every dirty RealWorn image is packed or written before the file saves
       (pattern from Ucupaint image_ops.save_pack_all and Paint System image.save_image, see
       THIRD_PARTY.md; no code copied).
"""

import math
import os

import bpy
import numpy as np

from . import naming

MIN_RES, MAX_RES = 1024, 4096
DENSITY = 2048                         # px per metre of the largest dimension
DECAL_MIN_DENSITY = 400                # DEC-2: warn below this many decal px per metre
FORCE_STORAGE = None  # tests set "PACKED" / "PNG" (preferences are unavailable unregistered)
EMPTY = (0.0, 0.0, 0.0, 1.0)           # a mask with nothing painted
EMPTY_DECAL = (0.0, 0.0, 0.0, 0.0)     # DEC-1: alpha 0
NEUTRAL_PUDDLE = (0.5, 0.5, 0.5, 1.0)  # Puddle: grey leaves the ground alone (white lowers, black raises)


def _prefs():
    try:
        from ..props import prefs
        return prefs()
    except Exception:
        return None


def texel_resolution(obj, density=None):
    """MSK-3: power of two of (density px/m x largest world dimension), clamped 1024..4096."""
    if density is None:
        p = _prefs()
        density = p.texel_density if p is not None else DENSITY
    dim = max(obj.dimensions) if obj is not None else 1.0
    px = max(density * max(dim, 1e-3), 1.0)
    res = 2 ** int(round(math.log2(px)))
    return int(min(max(res, MIN_RES), MAX_RES))


def needs_precision(layer):
    """Reveal and Puddle masks move heights: float pixels, no terraces."""
    return layer.kind in ("REVEAL", "PUDDLE")


def layer_resolution(obj, layer):
    if layer.kind == "DECALS":
        return int(layer.decal_res)
    return layer.mask_res or texel_resolution(obj)


def decal_density(obj, layer, res=None):
    """DEC-2: decal pixels per metre of the object's largest dimension."""
    res = res or (layer.mask_image.size[0] if layer.mask_image is not None else int(layer.decal_res))
    return res / max(max(obj.dimensions), 1e-3)


def mask_bytes(res, precise):
    """RAM of one RGBA image: 8-bit, or float (32-bit in memory)."""
    return res * res * 4 * (4 if precise else 1)


def memory_estimate(obj, layers):
    """Bytes the painted images of these layers take at their current (or default) size."""
    total = 0
    for ly in layers:
        if ly.mask_image is not None:
            res = ly.mask_image.size[0]
        elif ly.kind in ("PAINT", "REVEAL", "DECALS") or (ly.kind == "PUDDLE" and ly.puddle_source == "PAINT"):
            res = layer_resolution(obj, ly)
        else:
            continue
        total += mask_bytes(res, needs_precision(ly))
    return total


def _fill(img, rgba):
    w, h = img.size
    img.pixels.foreach_set(np.tile(np.asarray(rgba, np.float32), w * h))


def is_rw_image(img):
    return img is not None and (naming.IMG_MASK in img or naming.IMG_BAKED_SOURCE in img)


def create_mask(obj, layer, res=None):
    """A new painted image for the layer: a black mask, or for Decals a transparent RGBA image."""
    res = res or layer_resolution(obj, layer)
    decal = layer.kind == "DECALS"
    name = naming.mask_image_name(obj.name, layer.name, "decal" if decal else "mask")
    img = bpy.data.images.new(name, res, res, alpha=True, float_buffer=needs_precision(layer))
    img.alpha_mode = "CHANNEL_PACKED"
    img.colorspace_settings.name = "sRGB" if decal else "Non-Color"
    _fill(img, empty_value(layer.kind))
    img[naming.IMG_MASK] = "{}/{}".format(obj.name, layer.id)
    store(img, obj)
    return img


def empty_value(kind):
    """What a fresh (or cleared) image of this kind holds: nothing painted."""
    return EMPTY_DECAL if kind == "DECALS" else (NEUTRAL_PUDDLE if kind == "PUDDLE" else EMPTY)


def ensure_mask(obj, mat, layer):
    if layer.mask_image is None:
        layer.mask_image = create_mask(obj, layer)  # structural: compiles
    return layer.mask_image


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
        owner = (img.get(naming.IMG_MASK) or img.get(naming.IMG_BAKED_SOURCE) or "realworn/").split("/")[0]
        owner = owner or (obj.name if obj else "realworn")
        folder = os.path.join(os.path.dirname(blend_path), "textures", "realworn", bpy.path.clean_name(owner))
        os.makedirs(folder, exist_ok=True)
        precise = img.is_float
        path = os.path.join(folder, bpy.path.clean_name(img.name) + (".exr" if precise else ".png"))
        try:
            if img.packed_file is not None:
                img.unpack(method="REMOVE")
            img.filepath_raw = path
            img.file_format = "OPEN_EXR" if precise else "PNG"
            if precise:
                img.use_half_precision = True  # 16-bit half float on disk
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


def _cubic_weights(t):
    """Keys cubic convolution (a = -0.5) weights for the 4 taps around fractional offset t."""
    a = -0.5
    x = np.stack([1 + t, t, 1 - t, 2 - t])
    ax = np.abs(x)
    return np.where(ax <= 1, (a + 2) * ax ** 3 - (a + 3) * ax ** 2 + 1,
                    np.where(ax < 2, a * ax ** 3 - 5 * a * ax ** 2 + 8 * a * ax - 4 * a, 0.0))


def _resample_axis(arr, n, axis):
    old = arr.shape[axis]
    pos = (np.arange(n) + 0.5) * old / n - 0.5
    i0 = np.floor(pos).astype(np.int64)
    w = _cubic_weights(pos - i0).astype(np.float32)  # (4, n)
    out = 0.0
    for k in range(4):
        idx = np.clip(i0 - 1 + k, 0, old - 1)
        taken = np.take(arr, idx, axis=axis)
        shape = [1] * arr.ndim
        shape[axis] = n
        out = out + taken * w[k].reshape(shape)
    return out


def resample_bicubic(px, res):
    """Bicubic resample of an (h, w, c) array to (res, res, c), clamped to 0..1. Channels that are
    identical (masks painted white: R = G = B) are resampled once."""
    px = px.astype(np.float32, copy=False)
    out = np.empty((res, res, px.shape[2]), np.float32)
    done = {}
    for c in range(px.shape[2]):
        twin = next((k for k in done if np.array_equal(px[..., k], px[..., c])), None)
        if twin is not None:
            out[..., c] = out[..., twin]
            continue
        out[..., c] = _resample_axis(_resample_axis(px[..., c], res, 0), res, 1)
        done[c] = True
    return np.clip(out, 0.0, 1.0, out=out)


def upgrade(obj, layer, res=None):
    """Upgrade Mask (UI-4): resample a layer's image to the current density (bicubic, paint kept)
    and to float for Reveal. Returns the (possibly new) image."""
    img = layer.mask_image
    if img is None:
        return None
    res = res or layer_resolution(obj, layer)
    precise = needs_precision(layer)
    if tuple(img.size) == (res, res) and img.is_float == precise:
        return img
    px = resample_bicubic(pixels(img), res) if tuple(img.size) != (res, res) else pixels(img)
    new = bpy.data.images.new(img.name + ".up", res, res, alpha=True, float_buffer=precise)
    new.alpha_mode = img.alpha_mode
    new.colorspace_settings.name = img.colorspace_settings.name
    for k in img.keys():
        new[k] = img[k]
    new.pixels.foreach_set(px.astype(np.float32).ravel())
    new.update()
    name = img.name
    img.user_remap(new)  # the layer and the stack's image node follow
    bpy.data.images.remove(img)
    new.name = name
    # left dirty and unpacked: the save handler packs or writes it (SAV-2), as after a stroke
    return new


def fill(img, value, decal=False, kind=None):
    """Fill (1: the layer everywhere) / Clear (0: nothing painted; decals back to alpha 0,
    puddles back to neutral grey)."""
    kind = kind or ("DECALS" if decal else "PAINT")
    if value > 0:
        _fill(img, (1.0, 1.0, 1.0, 1.0))
    else:
        _fill(img, empty_value(kind))
    img.update()
    store(img)


def pixels(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def export_masks(obj, folder):
    """Export Masks (Remove dialog): one PNG per painted layer image. Returns the written paths."""
    from . import setup
    os.makedirs(folder, exist_ok=True)
    out = []
    for mat in setup.layered_materials(obj):
        for ly in mat.realworn.layers:
            for kind, img in (("mask", ly.mask_image), ("baked", ly.baked_image)):
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

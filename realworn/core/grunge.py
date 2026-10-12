"""Grunge library (GRN-1): bundled generated grunges plus the user's folder. Brush modes arrive
at P3."""

import os

import bpy

from . import assets

GRUNGE_DIR = os.path.join(assets.ASSET_DIR, "grunges")
_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")


def _user_folder():
    try:
        from ..props import prefs
        p = prefs()
        return bpy.path.abspath(p.grunge_folder) if p and p.grunge_folder else ""
    except Exception:
        return ""


def library():
    """[(file name, absolute path)] of grunge images (bundled first, then the user folder)."""
    out = []
    for folder in (GRUNGE_DIR, _user_folder()):
        if folder and os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(_EXT):
                    out.append((f, os.path.join(folder, f)))
    return out


_previews = None
_enum_items = []


def library_enum_items():
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    for i, (name, path) in enumerate(library()):
        icon = 0
        if _previews is not None:
            if name not in _previews:
                _previews.load(name, path, "IMAGE")
            icon = _previews[name].icon_id
        _enum_items.append((name, os.path.splitext(name)[0].replace("_", " ").title(), path, icon, i))
    if not _enum_items:
        _enum_items.append(("NONE", "No grunges found", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None


# ------------------------------------------------------------------ brushes
# GRN-6 / DMG-5: RealWorn's own brush assets, created on first use; user brushes are never edited.
BRUSHES = {
    "RW Soft": {"spacing": 10, "strength": 1.0, "falloff": "SMOOTH"},
    "RW Grunge": {"spacing": 35, "strength": 1.0, "falloff": "SMOOTH", "map": "RANDOM"},
    "RW Chips": {"spacing": 45, "strength": 1.0, "falloff": "CONSTANT", "map": "RANDOM"},
    "RW Scratch": {"spacing": 8, "strength": 1.0, "falloff": "SHARP", "map": "VIEW_PLANE"},
    "RW Dents": {"spacing": 30, "strength": 0.8, "falloff": "SPHERE"},
    "RW Cracks": {"spacing": 6, "strength": 1.0, "falloff": "SHARP", "map": "STENCIL"},
}
_FALLOFF_PRESETS = ("SMOOTH", "SPHERE", "ROOT", "SHARP", "LIN", "POW4", "INVSQUARE", "CONSTANT")


def ensure_brush(name="RW Soft", mode="TEXTURE_PAINT", image=None, map_mode=None):
    """The named RealWorn brush (created and marked as an asset on first use). With `image` the
    grunge becomes the brush's Texture Mask in `map_mode` (RANDOM / VIEW_PLANE / STENCIL)."""
    spec = BRUSHES.get(name, BRUSHES["RW Soft"])
    key = name if mode == "TEXTURE_PAINT" else "{} ({})".format(name, mode.split("_")[0].title())
    b = bpy.data.brushes.get(key)
    if b is None:
        b = bpy.data.brushes.new(key, mode=mode)
        b.spacing = spec["spacing"]
        b.strength = spec["strength"]
        b.blend = "MIX"
        if spec["falloff"] in _FALLOFF_PRESETS:
            try:
                b.curve_distance_falloff_preset = spec["falloff"]
            except (TypeError, AttributeError):
                pass
        b.color = (1.0, 1.0, 1.0)
        b.secondary_color = (0.0, 0.0, 0.0)
        b["rw_brush"] = True
    if b.asset_data is None:
        b.asset_mark()
    if image is not None:
        tex = b.mask_texture
        if tex is None or tex.type != "IMAGE":
            tex = bpy.data.textures.new(key + " Mask", type="IMAGE")
            tex["rw_brush"] = True
            b.mask_texture = tex
        tex.image = image
        slot = b.mask_texture_slot
        slot.mask_map_mode = map_mode or spec.get("map", "RANDOM")
        slot.use_random = slot.mask_map_mode == "RANDOM"
        slot.random_angle = 6.2831853
    elif map_mode == "NONE" and b.mask_texture is not None:
        b.mask_texture = None
    return b


def activate_brush(brush):
    """Brushes are assets in 5.x: tool settings' brush is read-only, asset_activate sets it
    (spike v2 c). Returns True on success."""
    from . import ctx
    try:
        with bpy.context.temp_override(**ctx.override()):
            r = bpy.ops.brush.asset_activate(asset_library_type="LOCAL", asset_library_identifier="",
                                             relative_asset_identifier="Brush" + os.sep + brush.name)
        return "FINISHED" in r
    except (RuntimeError, TypeError):
        return False

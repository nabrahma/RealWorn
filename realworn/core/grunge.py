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
    "RW Hard": {"spacing": 8, "strength": 1.0, "falloff": "CONSTANT"},  # v2.1 RES-5
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


def _in_paint_mode():
    vl = bpy.context.view_layer
    ob = vl.objects.active if vl is not None else None
    return ob is not None and ob.mode in ("TEXTURE_PAINT", "VERTEX_PAINT")


HARD_TYPES = ("WEAR", "SCRATCHES", "DAMAGE")  # RES-5: hard by default; Edge Detail softens nothing


def default_brush(kind):
    """RES-5: RW Hard for Wear, Scratches and Damage; RW Soft for the rest (Edge Detail now
    supplies the crisp edge for Dirt, Dust and Water)."""
    return "RW Hard" if kind in HARD_TYPES else "RW Soft"


def chosen_brush(scene=None, kind=None):
    """The brush the user picked last (remembered on the scene), else the layer type's default."""
    scene = scene or bpy.context.scene
    return scene.get("rw_brush") or default_brush(kind)


def activate_brush(brush, remember=True):
    """Brushes are assets in 5.x: tool settings' brush is read-only, asset_activate sets it
    (spike v2 c). Only valid while an object is in a paint mode: outside one, Blender 5.2.1
    dereferences null in WM_toolsystem_activate_brush_and_tool (crash found in P3). The choice is
    remembered on the scene and Paint Enter activates it. Returns True when activated now."""
    from . import ctx
    if remember:
        bpy.context.scene["rw_brush"] = brush.name
    if not _in_paint_mode():
        return False
    try:
        with bpy.context.temp_override(**ctx.override()):
            r = bpy.ops.brush.asset_activate(asset_library_type="LOCAL", asset_library_identifier="",
                                             relative_asset_identifier="Brush" + os.sep + brush.name)
        return "FINISHED" in r
    except (RuntimeError, TypeError):
        return False


# ------------------------------------------------------------- grunge use
MAP_FOR_MODE = {"STAMP": "RANDOM", "PROJECTED": "VIEW_PLANE", "STENCIL": "STENCIL"}
BRUSH_FOR_MODE = {"STAMP": "RW Grunge", "PROJECTED": "RW Grunge", "STENCIL": "RW Cracks"}


def _path(name):
    for n, p in library():
        if n == name or os.path.splitext(n)[0] == name:
            return p
    if os.path.isabs(name) and os.path.exists(name):
        return name
    raise KeyError("grunge '{}' not in the library".format(name))


def suggested_scale(image_or_name, default=None):
    """SRC-7: suggested tile size in metres for a grunge, from grunges.json next to it (bundled
    library or the user's folder; {"name.png": {"size_m": 0.3}}) or a "<name>.json" sidecar."""
    import json
    if hasattr(image_or_name, "filepath"):
        path = bpy.path.abspath(image_or_name.filepath) if image_or_name.filepath else ""
        name = os.path.basename(path) or image_or_name.name
    else:
        name = image_or_name if image_or_name.lower().endswith(".png") else image_or_name + ".png"
        try:
            path = _path(name)
        except KeyError:
            return default
    folder = os.path.dirname(path)
    for meta, key in ((os.path.join(folder, "grunges.json"), name),
                      (os.path.join(folder, os.path.splitext(name)[0] + ".json"), None)):
        if folder and os.path.exists(meta):
            try:
                with open(meta, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            entry = data.get(key) if key else data
            if isinstance(entry, dict) and "size_m" in entry:
                return float(entry["size_m"])
    return default


def load(name):
    """The grunge image (Non-Color, reused if already loaded)."""
    path = _path(name)
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(path):
            return img
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color"
    img["rw_grunge"] = True
    return img


def set_texture_look(brush, contrast=1.0, invert=False):
    """GRN-7 grunge contrast and invert, applied to RealWorn's own brush texture only."""
    tex = brush.mask_texture if brush is not None else None
    if tex is None or not brush.name.startswith("RW "):
        return False
    tex.contrast = contrast
    tex.use_color_ramp = bool(invert)
    if invert:
        els = tex.color_ramp.elements
        els[0].position, els[0].color = 0.0, (1.0, 1.0, 1.0, 1.0)
        els[-1].position, els[-1].color = 1.0, (0.0, 0.0, 0.0, 1.0)
    return True


def use(mode, name, obj=None, mat=None, layer=None, contrast=1.0, invert=False, amount=1.0, scale=None):
    """Apply grunge `name` in `mode`:
    STAMP     brush Texture Mask with Random mapping and random angle (GRN-2)
    PROJECTED brush Texture Mask with View Plane mapping (GRN-3)
    STENCIL   brush Texture Mask with Stencil mapping, centred in the 3D View (GRN-4)
    FILL      the layer's Grunge Fill ingredient (GRN-5)
    Returns the brush (stamp / projected / stencil) or the ingredient (fill)."""
    img = load(name)
    if mode == "FILL":
        from . import compiler
        with compiler.batch(mat):
            ing = next((i for i in layer.ingredients if i.kind == "GRUNGE"), None) or layer.ingredients.add()
            ing.kind = "GRUNGE"
            ing.image = img
            ing.amount = amount
            ing.scale = scale if scale is not None else suggested_scale(img, 1.0)  # SRC-7
            ing.contrast = max(-1.0, min(1.0, contrast - 1.0))
            ing.invert = invert
        compiler.compile(mat)
        return ing
    brush = ensure_brush(BRUSH_FOR_MODE[mode], image=img, map_mode=MAP_FOR_MODE[mode])
    set_texture_look(brush, contrast, invert)
    if mode == "STENCIL":
        from . import ctx
        win, screen, area, region = ctx.window_area()
        if region is not None:
            brush.mask_stencil_pos = (region.width / 2.0, region.height / 2.0)
            side = min(region.width, region.height) * 0.35
            brush.mask_stencil_dimension = (side, side)
    activate_brush(brush)
    return brush

"""Libraries (grunges, damage alphas, decals) and RealWorn's three brushes (PNT-3, PNT-5, PNT-6).

Libraries: the bundled generated images in assets/<kind>/ plus the user's folder from the
preferences; subfolders become categories (decals: Drips, Dirt, Graffiti, Stickers, Mold, Cracks).

Brushes, with fixed settings. RealWorn creates its own brush assets and never edits
the user's:
  RW Soft     default round brush, smooth falloff (Paint, Dirt touch-ups)
  RW Damage   Texture Mask from the selected damage alpha, Mask Mapping View Plane, Rake on,
              Falloff Constant (Reveal, Edge Wear touch-ups)
  RW Stencil  Texture from the selected decal, Mapping Stencil, Image Aspect applied, Texture
              Opacity Override Overlay on (Decals)
"""

import os

import bpy

from . import assets

FOLDERS = {"grunges": os.path.join(assets.ASSET_DIR, "grunges"),
           "alphas": os.path.join(assets.ASSET_DIR, "alphas"),
           "decals": os.path.join(assets.ASSET_DIR, "decals")}
PREF = {"grunges": "grunge_folder", "alphas": "alpha_folder", "decals": "decal_folder"}
_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp")
USER_PREFIX = "user:"


def _user_folder(kind):
    try:
        from ..props import prefs
        p = prefs()
        path = getattr(p, PREF[kind], "") if p else ""
        return bpy.path.abspath(path) if path else ""
    except Exception:
        return ""


def library(kind):
    """[(key, absolute path, category)] of a library: bundled first, then the user's folder.
    Keys are paths relative to the library folder ("chips_large.png", "Drips/drip_01.png");
    user images are prefixed "user:"."""
    out = []
    for root, prefix in ((FOLDERS[kind], ""), (_user_folder(kind), USER_PREFIX)):
        if not root or not os.path.isdir(root):
            continue
        for folder, dirs, files in os.walk(root):
            dirs.sort()
            rel = os.path.relpath(folder, root)
            category = "" if rel == "." else rel.split(os.sep)[0]
            for f in sorted(files):
                if f.lower().endswith(_EXT) and not f.lower().endswith("_nrm.png"):
                    key = f if rel == "." else "{}/{}".format(rel.replace(os.sep, "/"), f)
                    out.append((prefix + key, os.path.join(folder, f), category))
    return out


def path_of(kind, key):
    for k, p, _ in library(kind):
        if k == key or os.path.splitext(k)[0] == key:
            return p
    if os.path.isabs(key) and os.path.exists(key):
        return key
    raise KeyError("'{}' not in the {} library".format(key, kind))


def load(kind, key):
    """The library image (grunges and alphas Non-Color, decals sRGB), reused if already loaded."""
    path = path_of(kind, key)
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(path):
            return img
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "sRGB" if kind == "decals" else "Non-Color"
    img["rw_library"] = kind
    return img


def suggested_scale(image_or_name, default=None):
    """Suggested tile size in metres for a grunge, from grunges.json next to it ({"name.png":
    {"size_m": 0.3}}) or a "<name>.json" sidecar."""
    import json
    if hasattr(image_or_name, "filepath"):
        path = bpy.path.abspath(image_or_name.filepath) if image_or_name.filepath else ""
        name = os.path.basename(path) or image_or_name.name
    else:
        name = image_or_name if image_or_name.lower().endswith(".png") else image_or_name + ".png"
        try:
            path = path_of("grunges", name)
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


_previews = {}
_enum_items = {}


def library_enum_items(kind):
    """Enum items with thumbnails for a library (the item list must outlive the call)."""
    items = _enum_items.setdefault(kind, [])
    items.clear()
    pcoll = _previews.get(kind)
    try:
        import bpy.utils.previews
        if pcoll is None:
            pcoll = _previews[kind] = bpy.utils.previews.new()
    except Exception:
        pcoll = None
    for i, (key, path, category) in enumerate(library(kind)):
        icon = 0
        if pcoll is not None:
            if key not in pcoll:
                pcoll.load(key, path, "IMAGE")
            icon = pcoll[key].icon_id
        stem = os.path.splitext(os.path.basename(key))[0].replace("_", " ").title()
        label = "{}: {}".format(category, stem) if category else stem
        items.append((key, label, path, icon, i))
    if not items:
        items.append(("NONE", "Nothing in the {} library".format(kind), "", 0, 0))
    return items


def free_previews():
    import bpy.utils.previews
    for pcoll in _previews.values():
        bpy.utils.previews.remove(pcoll)
    _previews.clear()


# ------------------------------------------------------------------ brushes
BRUSHES = {
    "RW Soft": {"spacing": 10, "strength": 1.0, "falloff": "SMOOTH"},
    "RW Damage": {"spacing": 10, "strength": 1.0, "falloff": "CONSTANT"},
    "RW Stencil": {"spacing": 10, "strength": 1.0, "falloff": "CONSTANT"},
    "RW Puddle": {"spacing": 10, "strength": 1.0, "falloff": "SMOOTH"},
}
DEFAULT_ALPHA = "chips.png"
DEFAULT_DECAL = "Drips/drips_01.png"


def ensure_brush(name="RW Soft"):
    """The named RealWorn brush, created and marked as an asset on first use, with its settings."""
    spec = BRUSHES[name]
    b = bpy.data.brushes.get(name)
    if b is None:
        b = bpy.data.brushes.new(name, mode="TEXTURE_PAINT")
        b.spacing = spec["spacing"]
        b.strength = spec["strength"]
        b.blend = "MIX"
        b.curve_distance_falloff_preset = spec["falloff"]
        b.color = (1.0, 1.0, 1.0)
        b.secondary_color = (0.0, 0.0, 0.0)
        b["rw_brush"] = True
    if b.asset_data is None:
        b.asset_mark()
    return b


def _image_texture(brush, slot_attr, image):
    tex = getattr(brush, slot_attr)
    if tex is None or tex.type != "IMAGE":
        tex = bpy.data.textures.new(brush.name + (" Mask" if slot_attr == "mask_texture" else " Texture"), type="IMAGE")
        tex["rw_brush"] = True
        setattr(brush, slot_attr, tex)
    tex.image = image
    return tex


def set_damage_alpha(key=None, scene=None):
    """REV-3: the damage alpha becomes RW Damage's Texture Mask: View Plane, Rake, Constant."""
    scene = scene or bpy.context.scene
    key = key if key and key != "NONE" else scene.get("rw_damage_alpha") or DEFAULT_ALPHA
    b = ensure_brush("RW Damage")
    try:
        img = load("alphas", key)
    except KeyError:
        return b
    _image_texture(b, "mask_texture", img)
    slot = b.mask_texture_slot
    slot.mask_map_mode = "VIEW_PLANE"
    slot.use_rake = True
    slot.use_random = False
    b.curve_distance_falloff_preset = "CONSTANT"
    scene["rw_damage_alpha"] = key
    return b


def puddle_outline_items():
    """Puddle Outline choices: a plain round brush, then the grunge library."""
    items = _enum_items.setdefault("puddle_outline", [])
    items.clear()
    items.append(("NONE", "Round", "A plain soft round brush", 0, 0))
    for i, it in enumerate(library_enum_items("grunges")):
        if it[0] != "NONE":
            items.append((it[0], it[1], it[2], it[3], i + 1))
    return items


def set_puddle_outline(key=None, scene=None):
    """The Puddle brush: soft and round, or with a grunge as its mask for ragged outlines."""
    scene = scene or bpy.context.scene
    key = key if key is not None else scene.get("rw_puddle_outline", "NONE")
    b = ensure_brush("RW Puddle")
    img = None
    if key and key != "NONE":
        try:
            img = load("grunges", key)
        except KeyError:
            img = None
    if img is None:
        b.mask_texture = None
        key = "NONE"
    else:
        _image_texture(b, "mask_texture", img)
        slot = b.mask_texture_slot
        slot.mask_map_mode = "VIEW_PLANE"
        slot.use_rake = False
        slot.use_random = True
    scene["rw_puddle_outline"] = key
    return b


def stencil_fit(brush, image, side=None):
    """Image Aspect: the stencil keeps the decal's proportions (what Blender's Stencil Fit Image
    Aspect does), `side` pixels tall (default: keep the current height)."""
    w, h = image.size if image is not None and image.size[0] else (1, 1)
    half_h = side / 2.0 if side else brush.stencil_dimension[1]
    brush.stencil_dimension = (half_h * w / h, half_h)
    return brush.stencil_dimension


def set_stencil_decal(key=None, scene=None, region=None):
    """DEC-3: the decal becomes RW Stencil's Texture: Stencil mapping, Image Aspect, Override
    Overlay (the overlay hides while a stroke is painted, so the view stays readable)."""
    scene = scene or bpy.context.scene
    key = key if key and key != "NONE" else scene.get("rw_decal") or DEFAULT_DECAL
    b = ensure_brush("RW Stencil")
    try:
        img = load("decals", key)
    except KeyError:
        return b
    _image_texture(b, "texture", img)
    b.texture_slot.map_mode = "STENCIL"
    b.use_primary_overlay = True
    b.use_primary_overlay_override = True
    b.texture_overlay_alpha = 60
    if region is not None:
        b.stencil_pos = (region.width / 2.0, region.height / 2.0)
        stencil_fit(b, img, min(region.width, region.height) * 0.5)
    else:
        stencil_fit(b, img)
    scene["rw_decal"] = key
    return b


def brush_for(kind):
    """PNT-3: the brush a layer kind paints with."""
    from . import kinds
    return kinds.INFO[kind]["paint"] or "RW Soft"


def prepare_brush(kind, scene=None, region=None):
    """The kind's brush, with the current damage alpha or decal applied."""
    name = brush_for(kind)
    if name == "RW Damage":
        return set_damage_alpha(scene=scene)
    if name == "RW Stencil":
        return set_stencil_decal(scene=scene, region=region)
    if name == "RW Puddle":
        return set_puddle_outline(scene=scene)
    return ensure_brush(name)


def _in_paint_mode():
    vl = bpy.context.view_layer
    ob = vl.objects.active if vl is not None else None
    return ob is not None and ob.mode == "TEXTURE_PAINT"


def activate_brush(brush):
    """Brushes are assets in 5.x: tool settings' brush is read-only, asset_activate sets it
    (spike v2 c). Only valid while an object is in a paint mode: outside one, Blender 5.2.1
    dereferences null in WM_toolsystem_activate_brush_and_tool (crash found in v2 P3).
    Returns True when activated now."""
    from . import ctx
    if not _in_paint_mode():
        return False
    try:
        with bpy.context.temp_override(**ctx.override()):
            r = bpy.ops.brush.asset_activate(asset_library_type="LOCAL", asset_library_identifier="",
                                             relative_asset_identifier="Brush" + os.sep + brush.name)
        return "FINISHED" in r
    except (RuntimeError, TypeError):
        return False

"""Load Texture (LT-1..LT-5): pick a folder (or files); maps are detected by name, the way Node
Wrangler's Principled setup does (idea only, no code copied):

  color, albedo, diffuse, basecolor; rough (or gloss, inverted); metal; normal (OpenGL or
  DirectX, detected); height, disp, displacement; ao; packed ARM / ORM maps (R ambient occlusion,
  G roughness, B metallic), split in the shader.

Poly Haven (`x_nor_dx_1k`, `x_arm_1k`) and ambientCG (`X_1K-PNG_NormalDX`) names work. A size in
the folder or file name (`2K_1m`, `rust_50cm`) sets Scale, else 1 m (LT-2). The library (LT-4) is a
folder of such sets, shown as thumbnails, plus Recent.
"""

import json
import os
import re

import bpy

_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga", ".webp")
KEYS = {
    "color": ("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col"),
    "roughness": ("roughness", "rough", "rgh"),
    "gloss": ("glossiness", "gloss", "smoothness"),
    "metallic": ("metallic", "metalness", "metal", "mtl"),
    "normal_dx": ("normaldx", "nor_dx", "normal_dx"),
    "normal": ("normal_gl", "nor_gl", "normal", "nrm", "nor", "normalgl"),
    "height": ("height", "displacement", "disp", "bump"),
    "ao": ("ambientocclusion", "ambient_occlusion", "occlusion", "ao"),
    "packed": ("arm", "orm"),
}
_SIZE = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(m|cm)(?![a-z])")
_SPLIT = re.compile(r"[^a-z0-9]+")
RECENT_MAX = 8
_recent_fallback = []  # unregistered (tests): Recent lives here instead of the preferences


def _lookup(word):
    for ch, words in KEYS.items():
        if word in words:
            return ch
    return None


def classify(filename):
    """Channel a file name belongs to, or None. Map words are searched from the END of the name
    (asset names often contain channel words: metal_plate_diff_1k is colour, not metallic);
    two-token words (nor_gl, base_color) are tried before single tokens."""
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    tokens = [t for t in _SPLIT.split(stem) if t]
    for i in range(len(tokens) - 1, -1, -1):
        if i > 0:
            ch = _lookup(tokens[i - 1] + "_" + tokens[i])
            if ch:
                return ch
        ch = _lookup(tokens[i])
        if ch:
            if ch == "normal" and i + 1 < len(tokens) and tokens[i + 1] in ("dx", "directx"):
                return "normal_dx"
            return ch
        if i > 0 and tokens[i] in ("dx", "directx") and _lookup(tokens[i - 1]) == "normal":
            return "normal_dx"
    return None


def detect(paths):
    """{channel: path} from a folder path or a list of files; first match per channel wins, an
    OpenGL normal is preferred over a DirectX one ('normal_is_dx' marks a DirectX one), a roughness
    map over a glossiness one, separate maps over a packed one."""
    if isinstance(paths, str):
        folder = bpy.path.abspath(paths)
        paths = [os.path.join(folder, f) for f in sorted(os.listdir(folder))] if os.path.isdir(folder) else [folder]
    out = {}
    for p in paths:
        if not p.lower().endswith(_EXT):
            continue
        ch = classify(p)
        if ch == "normal_dx":
            out.setdefault("normal_dx", p)
        elif ch and ch not in out:
            out[ch] = p
    if "normal" not in out and "normal_dx" in out:
        out["normal"] = out["normal_dx"]
        out["normal_is_dx"] = True
    out.pop("normal_dx", None)
    if "roughness" in out:
        out.pop("gloss", None)
    return out


def scale_from_name(paths):
    """LT-2: a real-world size in the folder or file names (`2K_1m`, `rust_50cm`), in metres."""
    if isinstance(paths, str):
        paths = [paths]
    for p in paths:
        parts = [os.path.basename(os.path.dirname(p)), os.path.splitext(os.path.basename(p))[0]]
        for part in parts:
            m = _SIZE.search(part.lower())
            if m:
                v = float(m.group(1))
                return v / 100.0 if m.group(2) == "cm" else v
    return None


def set_name(paths):
    """A display name for a set: its folder (or the parent of a 'textures' folder)."""
    p = paths if isinstance(paths, str) else os.path.dirname(paths[0])
    p = bpy.path.abspath(p).rstrip("/\\")
    name = os.path.basename(p)
    if name.lower() in ("textures", "maps", "tex") and os.path.dirname(p):
        name = os.path.basename(os.path.dirname(p))
    return name.replace("_", " ")


def load(path, non_color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def assign(ts, paths, scale=None):
    """Fill a texture set (RWTextureSet) from detected maps. `scale` None: from the name, else 1 m.
    Images are replaced; Scale, Roughness offset and Bump strength are kept unless a scale is given
    or found in the name (LT-5). Returns the channels found."""
    maps = detect(paths)
    if not maps:
        return []
    if scale is None:
        scale = scale_from_name(list(maps.values()))
    done = []
    gloss = "gloss" in maps and "roughness" not in maps
    ts.color = load(maps["color"], False) if "color" in maps else None
    ts.roughness = load(maps.get("roughness") or maps.get("gloss"), True) if ("roughness" in maps or gloss) else None
    ts.gloss = gloss
    ts.metallic = load(maps["metallic"], True) if "metallic" in maps else None
    ts.height = load(maps["height"], True) if "height" in maps else None
    ts.normal = load(maps["normal"], True) if "normal" in maps else None
    ts.normal_dx = bool(maps.get("normal_is_dx"))
    ts.ao = load(maps["ao"], True) if "ao" in maps else None
    ts.packed = load(maps["packed"], True) if "packed" in maps else None
    if scale is not None:
        ts.scale = scale
    folder = paths if isinstance(paths, str) else os.path.dirname(paths[0])
    ts.folder = folder
    ts.name = set_name(paths)
    for ch in ("color", "roughness", "metallic", "height", "normal", "ao", "packed"):
        if getattr(ts, ch) is not None:
            done.append(ch + (" (from gloss)" if ch == "roughness" and gloss else "")
                        + (" (DirectX)" if ch == "normal" and ts.normal_dx else ""))
    add_recent(folder)
    return done


def measure_height(ts, step=4):
    """The height map's 2nd and 98th percentiles (0..1) on every `step`-th pixel, stored on the set.
    Puddle layers normalise the ground by them, so a map that uses only part of 0..1 still spans
    the full Height Scale. Measured once per image (the first time a Puddle needs it)."""
    import numpy as np
    from . import images, puddle
    img = ts.height
    if img is None:
        return 0.0, 1.0
    px = images.pixels(img)[::step, ::step, 0]
    lo, hi = puddle.height_range(px) if px.size else (0.0, 1.0)
    if not np.isfinite(lo) or not np.isfinite(hi):
        lo, hi = 0.0, 1.0
    ts.height_lo, ts.height_hi = lo, hi
    ts.height_measured = img.name
    return lo, hi


def clear(ts):
    for ch in ("color", "roughness", "metallic", "height", "normal", "ao", "packed"):
        setattr(ts, ch, None)
    ts.name, ts.folder, ts.gloss = "", "", False


# ------------------------------------------------------------------ library
def library(folder):
    """LT-4: every texture set under `folder` (a directory with a colour or height map).
    Returns [{"name", "path", "category", "thumb"}], sorted by name."""
    folder = bpy.path.abspath(folder) if folder else ""
    out = []
    if not folder or not os.path.isdir(folder):
        return out
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        maps = detect([os.path.join(root, f) for f in sorted(files)])
        if "color" in maps or "height" in maps:
            rel = os.path.relpath(root, folder)
            out.append({"name": set_name(root), "path": root,
                        "category": rel.split(os.sep)[0] if os.sep in rel else "",
                        "thumb": maps.get("color") or maps.get("height")})
    return sorted(out, key=lambda e: e["name"].lower())


def _prefs():
    try:
        from ..props import prefs
        return prefs()
    except Exception:
        return None


def recent():
    p = _prefs()
    if p is None:
        return list(_recent_fallback)
    try:
        return [r for r in json.loads(p.recent_textures or "[]") if isinstance(r, str)]
    except ValueError:
        return []


def add_recent(folder):
    folder = bpy.path.abspath(folder)
    items = [folder] + [r for r in recent() if os.path.normcase(r) != os.path.normcase(folder)]
    items = items[:RECENT_MAX]
    p = _prefs()
    if p is None:
        _recent_fallback[:] = items
    else:
        p.recent_textures = json.dumps(items)
    return items


def realindex_sets():
    """Texture sets from the RealIndex add-on when it is enabled (its read-only api module); else []."""
    import importlib
    for name in bpy.context.preferences.addons.keys():
        if name != "realindex" and not name.endswith(".realindex"):
            continue
        try:
            api = importlib.import_module(name + ".api")
            sets = api.texture_sets()
        except Exception:
            return []
        out = []
        for t in sets:
            folder = t.get("folder")
            if folder and os.path.isdir(folder):
                out.append({"name": "RealIndex: " + t["name"], "path": folder, "category": "RealIndex",
                            "thumb": t.get("preview") or t.get("maps", {}).get("color")})
        return sorted(out, key=lambda e: e["name"].lower())
    return []


_previews = None
_enum_items = []


def library_enum_items(folder):
    """Enum items with thumbnails: Recent first, then the library folder's sets, then RealIndex's."""
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    entries, seen = [], set()
    for r in recent():
        if os.path.isdir(r):
            maps = detect(r)
            entries.append({"name": "Recent: " + set_name(r), "path": r,
                            "thumb": maps.get("color") or maps.get("height")})
            seen.add(os.path.normcase(r))
    entries += [e for e in library(folder) if os.path.normcase(e["path"]) not in seen]
    seen |= {os.path.normcase(e["path"]) for e in entries}
    entries += [e for e in realindex_sets() if os.path.normcase(e["path"]) not in seen]
    for i, e in enumerate(entries):
        icon = 0
        if _previews is not None and e["thumb"]:
            key = e["path"]
            if key not in _previews:
                _previews.load(key, e["thumb"], "IMAGE")
            icon = _previews[key].icon_id
        _enum_items.append((e["path"], e["name"], e["path"], icon, i))
    if not _enum_items:
        _enum_items.append(("NONE", "No texture sets (set a Texture Library folder in Preferences)", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None

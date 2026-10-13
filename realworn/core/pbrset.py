"""PBR Set content (LAY-2, v2.1 CNT-5..CNT-7): pick a folder (or files); maps are detected by
name, the way Node Wrangler's Principled setup does (idea only, no code copied): color / albedo /
diffuse / basecolor, rough (or gloss, inverted), metal, normal (OpenGL or DirectX, detected),
height / disp, ao. Poly Haven (`x_nor_dx_1k`) and ambientCG (`X_1K-PNG_NormalDX`) names work.
A size in the folder or file name (`2K_1m`, `rust_50cm`) sets the projection scale.

The content library (CNT-6) is a folder of such sets, shown as thumbnails per layer type."""

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
}
_SIZE = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(m|cm)(?![a-z])")
# CNT-6: which layer types a library set suits, from its category folder or name
CATEGORY_WORDS = (("RUST", ("rust", "corrosion", "oxid")), ("DIRT", ("dirt", "mud", "soil", "grime")),
                  ("DUST", ("dust", "sand", "powder")), ("WATER", ("water", "puddle", "wet")),
                  ("SCRATCHES", ("scratch",)), ("WEAR", ("metal", "steel", "iron", "aluminium", "aluminum")),
                  ("DAMAGE", ("concrete", "brick", "plaster", "stone", "wood", "rock")), ("PAINT", ("paint",)))
_SPLIT = re.compile(r"[^a-z0-9]+")


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
    """{channel: path} from a folder path or a list of files; first match per channel wins,
    an OpenGL normal is preferred over a DirectX one (then 'normal_is_dx' is set), a roughness
    map over a glossiness one."""
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
    """CNT-5: a real-world size in the folder or file names (`2K_1m`, `rust_50cm`), in metres."""
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


def category(name, parent=""):
    """The layer type a library set suits (from its category folder, else its name), or 'ALL'."""
    for text in (parent.lower(), name.lower()):
        for kind, words in CATEGORY_WORDS:
            if any(w in text for w in words):
                return kind
    return "ALL"


def library(folder):
    """CNT-6: every PBR set under `folder` (a directory with at least a colour or height map).
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
            parent = rel.split(os.sep)[0] if os.sep in rel else ""
            name = os.path.basename(root)
            out.append({"name": name, "path": root, "category": category(name, parent),
                        "thumb": maps.get("color") or maps.get("height")})
    return sorted(out, key=lambda e: e["name"].lower())


def load(path, non_color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


_previews = None
_enum_items = []


def library_enum_items(folder, kind="ALL"):
    """Enum items (with thumbnails) of the content library sets that suit layer type `kind`."""
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    i = 0
    for e in library(folder):
        if kind not in ("ALL", None) and e["category"] not in (kind, "ALL"):
            continue
        icon = 0
        if _previews is not None and e["thumb"]:
            key = e["path"]
            if key not in _previews:
                _previews.load(key, e["thumb"], "IMAGE")
            icon = _previews[key].icon_id
        _enum_items.append((e["path"], e["name"].replace("_", " "), e["path"], icon, i))
        i += 1
    if not _enum_items:
        _enum_items.append(("NONE", "No PBR sets for this layer type", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None


def assign(mat, layer, paths, scale=None):
    """Use a detected PBR set as the layer's content. `scale` None: from the folder name, else
    1 m. Returns the channels assigned."""
    from . import compiler
    maps = detect(paths)
    if scale is None:
        scale = scale_from_name(list(maps.values()) if maps else paths) or 1.0
    if "gloss" in maps and "roughness" not in maps:
        maps["roughness"] = maps.pop("gloss")
        gloss = True
    else:
        gloss = False
    done = []
    with compiler.batch(mat):
        for ch in ("color", "roughness", "metallic", "height"):
            if ch not in maps:
                continue
            c = getattr(layer, ch)
            c.image = load(maps[ch], non_color=ch != "color")
            c.source = "PBRSET"
            c.enabled = True
            c.scale = scale
            c.invert = gloss and ch == "roughness"
            if ch == "height" and c.value == 0.0:
                c.value = 1.0  # 1 mm of relief per unit of height map
            done.append(ch + (" (from gloss)" if c.invert else ""))
        if "normal" in maps:
            layer.normal_image = load(maps["normal"], non_color=True)
            layer.normal_dx = bool(maps.get("normal_is_dx"))
            done.append("normal" + (" (DirectX)" if layer.normal_dx else ""))
        if "ao" in maps:
            layer.ao_image = load(maps["ao"], non_color=True)
            done.append("ao")
        if "height" in maps and layer.type in ("WEAR", "RUST") and layer.detail.strength > 0:
            layer.detail.source = "CONTENT_HEIGHT"  # CNT-7: edges follow the paint texture
            done.append("edge detail: content height")
    compiler.compile(mat)
    return done

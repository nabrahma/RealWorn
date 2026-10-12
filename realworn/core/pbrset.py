"""PBR Set content (LAY-2): pick a folder (or files); maps are detected by name, the way Node
Wrangler's Principled setup does (idea only, no code copied): color / albedo / diffuse /
basecolor, rough, metal, normal / nor, height / disp / displacement."""

import os
import re

import bpy

_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga", ".webp")
KEYS = {
    "color": ("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col"),
    "roughness": ("roughness", "rough", "rgh"),
    "metallic": ("metallic", "metalness", "metal", "mtl"),
    "normal": ("normal_gl", "nor_gl", "normal", "nrm", "nor", "normalgl"),
    "height": ("height", "displacement", "disp", "bump"),
}
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
    an OpenGL normal is preferred over a DirectX one."""
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
    out.pop("normal_dx", None)
    return out


def load(path, non_color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def assign(mat, layer, paths, scale=1.0):
    """Use a detected PBR set as the layer's content. Returns the channels assigned."""
    from . import compiler
    maps = detect(paths)
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
            if ch == "height" and c.value == 0.0:
                c.value = 1.0  # 1 mm of relief per unit of height map
            done.append(ch)
        if "normal" in maps:
            layer.normal_image = load(maps["normal"], non_color=True)
            done.append("normal")
    compiler.compile(mat)
    return done

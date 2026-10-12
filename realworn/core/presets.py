"""Presets: load assets/presets/*.json, validate them, map them to RW_Stack inputs.

Pure Python (no bpy) so the schema and mapping are unit-tested outside Blender.
"""

import json
import os

PRESET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "presets")

UNDERLAYERS = {
    # name: (color, roughness, metallic)
    "bare_steel": ((0.55, 0.55, 0.56), 0.32, 1.0),
    "aggregate": ((0.70, 0.68, 0.64), 0.95, 0.0),
    "raw_wood": ((0.62, 0.45, 0.28), 0.80, 0.0),
    "whitened": ((0.78, 0.78, 0.76), 0.75, 0.0),
}
USER_PRESETS = ("painted_metal", "bare_metal", "concrete", "wood", "plastic")
LAYERS = ("edge_wear", "rust", "cavity_dirt", "contact_grime", "dust", "streaks")
METAL_HINTS = ("metal", "steel", "iron", "pipe", "rail", "barrel", "can", "tank", "railing", "girder")
WOOD_HINTS = ("wood", "crate", "plank", "timber", "pallet", "log", "board")
PLASTIC_HINTS = ("plastic", "bin", "cone", "crate_plastic", "bucket", "pvc")


class PresetError(ValueError):
    pass


def _is_color(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, (int, float)) and 0 <= c <= 1 for c in v)


def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def validate(p):
    """Return a list of human-readable schema errors (empty when valid)."""
    errs = []
    if not isinstance(p, dict):
        return ["preset must be an object"]
    for k in ("id", "label"):
        if not isinstance(p.get(k), str) or not p.get(k):
            errs.append("missing string '{}'".format(k))
    if not _num(p.get("porosity"), 0, 1):
        errs.append("porosity must be a number in 0..1")
    if "breakup_scale" in p and not _num(p["breakup_scale"], 0.05, 20):
        errs.append("breakup_scale must be in 0.05..20")
    layers = p.get("layers")
    if not isinstance(layers, dict):
        return errs + ["missing 'layers' object"]
    for name in layers:
        if name not in LAYERS:
            errs.append("unknown layer '{}'".format(name))
    for name in LAYERS:
        lay = layers.get(name)
        if lay is None:
            errs.append("missing layer '{}'".format(name))
            continue
        if not isinstance(lay.get("enabled"), bool):
            errs.append("{}.enabled must be true/false".format(name))
        if not _num(lay.get("strength", 0), 0, 3):
            errs.append("{}.strength must be in 0..3".format(name))
        if "color" in lay and not _is_color(lay["color"]):
            errs.append("{}.color must be [r, g, b] in 0..1".format(name))
    ew = layers.get("edge_wear") or {}
    if "underlayer" in ew:
        u = ew["underlayer"]
        if not (u in UNDERLAYERS or _is_color(u)):
            errs.append("edge_wear.underlayer must be one of {} or a color".format(sorted(UNDERLAYERS)))
    for k, lo, hi in (("primer_width", 0, 1), ("chip_sharpness", 0, 1), ("chip_bump", 0, 0.05), ("polish", 0, 1)):
        if k in ew and not _num(ew[k], lo, hi):
            errs.append("edge_wear.{} must be in {}..{}".format(k, lo, hi))
    if "primer_color" in ew and not _is_color(ew["primer_color"]):
        errs.append("edge_wear.primer_color must be a color")
    return errs


def load_all(directory=PRESET_DIR):
    out = {}
    for f in sorted(os.listdir(directory)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(directory, f), encoding="utf-8") as fh:
            p = json.load(fh)
        errs = validate(p)
        if errs:
            raise PresetError("{}: {}".format(f, "; ".join(errs)))
        out[p["id"]] = p
    return out


_cache = {}


def get(preset_id):
    if not _cache:
        _cache.update(load_all())
    if preset_id not in _cache:
        raise PresetError("unknown preset '{}'".format(preset_id))
    return _cache[preset_id]


def _strength(layers, name):
    lay = layers.get(name, {})
    return float(lay.get("strength", 0.0)) if lay.get("enabled") else 0.0


def stack_inputs(p):
    """Map a preset dict to {RW_Stack input name: value}."""
    L = p["layers"]
    ew = L["edge_wear"]
    u = ew.get("underlayer", "bare_steel")
    ucol, urough, umetal = UNDERLAYERS[u] if isinstance(u, str) else (tuple(u), 0.5, 0.0)
    vals = {
        "Edge Wear": _strength(L, "edge_wear"),
        "Underlayer Color": tuple(ucol),
        "Underlayer Roughness": urough,
        "Underlayer Metallic": umetal,
        "Primer Color": tuple(ew.get("primer_color", (0.5, 0.5, 0.5))),
        "Primer Width": float(ew.get("primer_width", 0.0)),
        "Chip Sharpness": float(ew.get("chip_sharpness", 0.6)),
        "Chip Bump": float(ew.get("chip_bump", 0.0)),
        "Polish": float(ew.get("polish", 0.0)),
        "Rust": _strength(L, "rust"),
        "Cavity Dirt": _strength(L, "cavity_dirt"),
        "Grime": _strength(L, "contact_grime"),
        "Dust": _strength(L, "dust"),
        "Streaks": _strength(L, "streaks"),
        "Porosity": float(p["porosity"]),
        "Breakup Scale": float(p.get("breakup_scale", 1.0)),
    }
    for layer, key in (("rust", "Rust Color"), ("cavity_dirt", "Dirt Color"), ("contact_grime", "Grime Color"),
                       ("dust", "Dust Color")):
        if "color" in L[layer]:
            vals[key] = tuple(L[layer]["color"])
    return vals


def choose_auto(metallic, roughness, name=""):
    """Auto rule: metallic > 0.5 -> Bare Metal; metal-ish name -> Painted Metal;
    wood/plastic names -> Wood/Plastic (extension of the PRD rule); else Concrete."""
    n = (name or "").lower()
    if metallic > 0.5:
        return "bare_metal"
    if any(h in n for h in METAL_HINTS):
        return "painted_metal"
    if any(h in n for h in PLASTIC_HINTS):
        return "plastic"
    if any(h in n for h in WOOD_HINTS):
        return "wood"
    return "concrete"

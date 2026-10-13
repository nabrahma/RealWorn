"""Layer types and their defaults (PRD v2 "Layer types and their defaults"). Pure Python.

Types only decide how a new layer starts; any layer can be turned into any look by editing its
channels. Colours are linear RGB, heights are millimetres.
"""

COLOR_BLENDS = ("MIX", "MULTIPLY", "OVERLAY", "ADD", "DARKEN")
SCALAR_BLENDS = ("MIX", "MIN", "MAX")
HEIGHT_BLENDS = ("ADD", "SUBTRACT", "MAX", "REPLACE")
SOURCES = ("FLAT", "IMAGE", "PBRSET", "TINTED_GRUNGE")
CHANNEL_NAMES = ("color", "roughness", "metallic", "height")
GENERATOR_KINDS = ("EDGE", "CAVITY", "CONTACT")  # need the RW_Masks modifier (ING-1)
LOCK_SOURCES = ("NONE", "EDGE", "CAVITY", "CONTACT", "UP")


def _ch(enabled=True, value=0.0, blend="MIX", source="FLAT"):
    return {"enabled": enabled, "value": value, "blend": blend, "source": source}


TYPES = {
    "DIRT": {
        "label": "Dirt", "icon": "BRUSH_DATA",
        "color": _ch(True, (0.10, 0.075, 0.05), "MULTIPLY"),
        "roughness": _ch(True, 0.9), "metallic": _ch(True, 0.0), "height": _ch(False, 0.0, "ADD"),
        "use_height_blend": True, "height_blend": 0.5,
    },
    "DUST": {
        "label": "Dust", "icon": "PARTICLES",
        "color": _ch(True, (0.62, 0.60, 0.56)), "roughness": _ch(True, 1.0), "metallic": _ch(True, 0.0),
        "height": _ch(False, 0.0, "ADD"), "suggest": "UP",
    },
    "RUST": {
        "label": "Rust", "icon": "COLORSET_02_VEC",
        "color": _ch(True, (0.16, 0.055, 0.018), "MIX", "TINTED_GRUNGE"), "roughness": _ch(True, 0.85),
        "metallic": _ch(True, 0.0), "height": _ch(True, 0.5, "ADD"), "suggest": "GRUNGE:rust_spots",
    },
    "WEAR": {
        "label": "Wear", "icon": "MOD_EDGESPLIT",
        "color": _ch(True, (0.56, 0.57, 0.58)), "roughness": _ch(True, 0.3), "metallic": _ch(True, 1.0),
        "height": _ch(True, 0.2, "SUBTRACT"), "lock_source": "EDGE", "lock_strength": 0.6,
        "threshold": 0.5, "softness": 0.25,
    },
    "SCRATCHES": {
        "label": "Scratches", "icon": "GREASEPENCIL",
        "color": _ch(True, (0.08, 0.08, 0.08), "ADD"), "roughness": _ch(True, 0.25),
        "metallic": _ch(False, 0.0), "height": _ch(True, 0.05, "SUBTRACT"), "suggest": "BRUSH:RW Scratch",
    },
    "WATER": {
        "label": "Water", "icon": "MOD_FLUIDSIM",
        # metallic keeps the base (deviation from the PRD table's "0", see P4 notes): water over
        # steel is still steel under a film; the coat models the water itself
        "color": _ch(False, (0.0, 0.0, 0.0)), "roughness": _ch(True, 0.03), "metallic": _ch(False, 0.0),
        "height": _ch(False, 0.0, "ADD"), "water": True,
    },
    "PAINT": {
        "label": "Paint", "icon": "TPAINT_HLT",
        "color": _ch(True, (1.0, 1.0, 1.0)), "roughness": _ch(True, 0.5), "metallic": _ch(True, 0.0),
        "height": _ch(False, 0.0, "ADD"), "content": True,
    },
    "DAMAGE": {
        "label": "Damage", "icon": "MOD_BOOLEAN",
        "color": _ch(True, (0.55, 0.53, 0.50)), "roughness": _ch(True, 0.8), "metallic": _ch(True, 0.0),
        "height": _ch(False, 0.0, "ADD"), "damage": True, "threshold": 0.5, "softness": 0.1,
    },
    "DECAL": {
        "label": "Decal", "icon": "IMAGE_DATA",
        "color": _ch(True, (1.0, 1.0, 1.0)), "roughness": _ch(True, 0.45), "metallic": _ch(True, 0.0),
        "height": _ch(False, 0.0, "ADD"), "decal": True,
    },
    "CUSTOM": {
        "label": "Custom", "icon": "MODIFIER",
        "color": _ch(True, (0.5, 0.5, 0.5)), "roughness": _ch(True, 0.5), "metallic": _ch(True, 0.0),
        "height": _ch(True, 0.0, "ADD"),
    },
}
ORDER = ("DIRT", "DUST", "RUST", "WEAR", "SCRATCHES", "WATER", "PAINT", "DAMAGE", "DECAL", "CUSTOM")

LAYER_DEFAULTS = {"use_height_blend": False, "height_blend": 0.0, "lock_source": "NONE", "lock_strength": 0.0,
                  "threshold": 0.5, "softness": 1.0}


# ------------------------------------------------------------------ v2.1 Edge Detail
DETAIL_MODES = ("ERODE", "BURN", "HEIGHT")
DETAIL_SOURCES = ("LAYER_GRUNGE", "BASE_HEIGHT", "BASE_AO", "CONTENT_HEIGHT", "GRUNGE2")
DETAIL_OFF = {"mode": "ERODE", "source": "LAYER_GRUNGE", "strength": 0.0, "width": 0.05, "threshold": 0.5,
              "protect": True, "grunge": None, "scale": 0.25, "grunge2": None, "mix2": 0.0}


def _det(mode, source, strength, width, protect, grunge, scale, grunge2=None, mix2=0.0):
    return {"mode": mode, "source": source, "strength": strength, "width": width, "threshold": 0.5,
            "protect": protect, "grunge": grunge, "scale": scale, "grunge2": grunge2, "mix2": mix2}


# PRD v2.1 "Defaults per layer type". `grunge` is the Layer Grunge (and the Base Height fallback
# when the base has no height map); `scale` is its tile size in metres (SRC-7 suggested sizes).
DETAIL = {
    # Dirt and Water also mix a fine breakup in, so their edge is irregular where the base is flat
    "DIRT": _det("HEIGHT", "BASE_HEIGHT", 0.7, 0.05, False, "grime_clouds", 0.3, "breakup_fine", 0.3),
    "DUST": _det("ERODE", "LAYER_GRUNGE", 0.5, 0.10, False, "speckle_fine", 0.25),
    "RUST": _det("ERODE", "LAYER_GRUNGE", 0.8, 0.04, False, "breakup_rust", 0.25),
    "WEAR": _det("ERODE", "LAYER_GRUNGE", 0.8, 0.02, True, "chips_small", 0.2),
    "SCRATCHES": _det("ERODE", "LAYER_GRUNGE", 0.9, 0.02, True, "scratches_fine", 0.3),
    "WATER": _det("HEIGHT", "BASE_HEIGHT", 0.8, 0.03, False, "smudge", 0.5, "breakup_fine", 0.2),
    "DAMAGE": _det("ERODE", "BASE_HEIGHT", 0.7, 0.03, True, "chips_small", 0.2),
}


def detail_defaults(kind):
    """Edge Detail defaults for a layer type (Paint, Decal, Custom: off)."""
    return dict(DETAIL.get(kind, DETAIL_OFF))


def _smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0) if b != a else float(x >= a)
    return t * t * (3 - 2 * t)


def edge_detail(mode, m, d, s, w, t=0.5, protect=False):
    """Reference (pure Python) of the Edge Detail groups (builders/sh_edge_detail.py)."""
    hw = max(w, 1e-3) / 2.0
    if mode == "ERODE":
        b = 1.0 + (min(max((1 - m) * 4, 0.0), 1.0) - 1.0) * (1.0 if protect else 0.0)
        return _smoothstep(t - hw, t + hw, m - (1 - d) * s * b)
    if mode == "BURN":
        burn = min(max(1 - (1 - m) / max(d, 0.02), 0.0), 1.0)
        return _smoothstep(t - hw, t + hw, m + (burn - m) * s)
    if mode == "HEIGHT":
        return _smoothstep(-hw, hw, m * s - d - (t - 0.5)) * min(max(m * 20, 0.0), 1.0)
    raise KeyError(mode)


def blends_for(channel):
    if channel == "color":
        return COLOR_BLENDS
    if channel == "height":
        return HEIGHT_BLENDS
    return SCALAR_BLENDS


def defaults(kind):
    """Full default dict for a new layer of `kind` (channels plus layer-level controls)."""
    if kind not in TYPES:
        raise KeyError("unknown layer type {!r}".format(kind))
    t = TYPES[kind]
    out = dict(LAYER_DEFAULTS)
    out.update({k: v for k, v in t.items() if k not in ("label", "icon")})
    for ch in CHANNEL_NAMES:
        out[ch] = dict(t[ch])
    return out


def validate(kind):
    """List of problems in one type's defaults (empty == valid). Used by tests."""
    errs = []
    d = defaults(kind)
    for ch in CHANNEL_NAMES:
        c = d[ch]
        if c["blend"] not in blends_for(ch):
            errs.append("{}.{}: blend {} not allowed".format(kind, ch, c["blend"]))
        if c["source"] not in SOURCES:
            errs.append("{}.{}: source {}".format(kind, ch, c["source"]))
        if ch == "color":
            if len(c["value"]) != 3 or not all(0.0 <= x <= 1.0 for x in c["value"]):
                errs.append("{}.color value".format(kind))
        elif ch in ("roughness", "metallic") and not 0.0 <= c["value"] <= 1.0:
            errs.append("{}.{} value out of 0..1".format(kind, ch))
    if d["lock_source"] not in LOCK_SOURCES:
        errs.append("{}: lock source {}".format(kind, d["lock_source"]))
    if not 0.0 <= d["threshold"] <= 1.0 or not 0.0 <= d["softness"] <= 1.0:
        errs.append("{}: levels out of range".format(kind))
    return errs


def mask_formula(P, paint_rgb, paint_a, lock, k, threshold, softness, opacity):
    """Reference (pure Python) of the per-pixel mask the compiler builds (PRD "How a mask is
    computed"): M = levels(lerp(P, paint, alpha) * lerp(1, lock, k)) * opacity."""
    m = P + (paint_rgb - P) * paint_a
    m *= 1.0 + (lock - 1.0) * k
    s = max(softness, 1e-3)
    lo, hi = threshold - s / 2.0, threshold + s / 2.0
    m = min(max((m - lo) / (hi - lo), 0.0), 1.0)
    return m * opacity

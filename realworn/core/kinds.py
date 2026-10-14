"""The six layer kinds, their defaults and presets, and the mask recipe's
reference math. Pure Python: no bpy, so tests/pure checks it outside Blender.

Every layer is a material plus a mask. Kinds differ only in where the mask comes from:

  VARIATION  grunge only, no painting
  PAINT      your painting, plus Breakup
  REVEAL     your painting with the Damage brush, plus Breakup; the content sits under, with Depth
  DECALS     the painted decal image's own alpha
  EDGE_WEAR  Bevel edge detection (the grunge varies the bevel radius), plus optional painting
  DIRT       ambient occlusion, plus Breakup, plus optional painting

The mask recipe (MSK-1), the same for every kind:

  M = ramp_{t,w}( S - a * ramp_g(G) ) * opacity

S is the kind's source, G the Breakup grunge, a the Breakup Amount, ramp_g the grunge's own Color
Ramp (Breakup Contrast c: stops at c/2 and 1 - c/2), and the outer ramp has stops at t - w/2
(black) and t + w/2 (white), w = 0.5 at Sharpness 0 down to 0.01 at Sharpness 1.
"""

KINDS = ("VARIATION", "PAINT", "REVEAL", "DECALS", "EDGE_WEAR", "DIRT")
# Default stack position, bottom to top (the classic order: variation over the base, paint over
# that, worn edges, damage breaking through, decals over the damage, dirt settling on top).
ORDER = ("VARIATION", "PAINT", "EDGE_WEAR", "REVEAL", "DECALS", "DIRT")
CONTENTS = ("TEXTURE", "TINT_BELOW", "COLOR")  # Tint Below: a recoloured copy of the Base (the classic trick)

INFO = {
    "VARIATION": {"label": "Variation", "icon": "MOD_NOISE", "paint": None},
    "PAINT": {"label": "Paint", "icon": "BRUSH_DATA", "paint": "RW Soft"},
    "REVEAL": {"label": "Reveal", "icon": "MOD_BOOLEAN", "paint": "RW Damage"},
    "DECALS": {"label": "Decals", "icon": "IMAGE_DATA", "paint": "RW Stencil"},
    "EDGE_WEAR": {"label": "Edge Wear", "icon": "MOD_BEVEL", "paint": "RW Damage", "optional_paint": True},
    "DIRT": {"label": "Dirt", "icon": "SHADING_RENDERED", "paint": "RW Soft", "optional_paint": True},
}

# Internal recipes for the generated sources (the classic fixed nodes).
EDGE_GAIN = 10.0             # Edge Wear: S = (1 - Bevel . Normal) x 10 (the classic Multiply)
AO_RAMP = (0.5, 0.95)        # Dirt: S = 1 where AO <= 0.5, 0 where AO >= 0.95 (Color Ramp)
BEVEL_SAMPLES = 8            # ENG-4
AO_SAMPLES = 16
PLASTER_GREY = (0.52, 0.51, 0.49)
DIRT_BROWN = (0.1, 0.075, 0.05)

# Variation grunges cycle so three Variations never line up (VAR-3).
VARIATION_GRUNGES = ("smudge.png", "breakup_fine.png", "breakup_rust.png", "dust.png", "grime_clouds.png")

# Per-kind defaults. Keys are RWLayer properties; "breakup" names the grunge (amount 0 means off).
DEFAULTS = {
    "VARIATION": dict(content="TINT_BELOW", saturation=-0.3, breakup="smudge.png", breakup_amount=1.0,
                      threshold=0.75, sharpness=0.6),
    "PAINT": dict(content="TINT_BELOW", hue=0.5, breakup="chips_large.png", breakup_amount=0.0,
                  threshold=0.5, sharpness=0.5),
    "REVEAL": dict(content="COLOR", color=PLASTER_GREY, roughness=0.85, breakup="chips_small.png",
                   breakup_amount=0.0, threshold=0.5, sharpness=0.7, depth_mm=2.0, edge_dark=0.3),
    "DECALS": dict(content="TEXTURE", roughness=0.6, breakup="grime_clouds.png", breakup_amount=0.0,
                   threshold=0.5, sharpness=0.0, decal_blend="NORMAL"),
    "EDGE_WEAR": dict(content="TINT_BELOW", saturation=-0.4, value=0.25, breakup="breakup_fine.png",
                      breakup_amount=0.6, threshold=0.5, sharpness=0.5, width_mm=5.0),
    "DIRT": dict(content="COLOR", color=DIRT_BROWN, roughness=0.9, breakup="dust.png", breakup_amount=0.3,
                 threshold=0.45, sharpness=1.0, distance_cm=20.0),
}

# Presets offered on the + menu (VAR-2, REV-4, DEC-4). Values override the kind's defaults.
PRESETS = {
    "VARIATION": (
        ("WASHED_OUT", "Washed Out", dict(content="TINT_BELOW", saturation=-0.3)),
        ("DARK_PATCHES", "Dark Patches", dict(content="TINT_BELOW", saturation=0.0, value=-0.25)),
        ("DIRT_PATCHES", "Dirt Patches", dict(content="COLOR", color=(0.12, 0.09, 0.06), roughness=0.9,
                                              saturation=0.0)),
        ("SECOND_MATERIAL", "Second Material", dict(content="TEXTURE", saturation=0.0)),
    ),
    "REVEAL": (
        ("DAMAGE", "Damage", {}),
        ("SCRATCHES", "Scratches", dict(depth_mm=0.3, alpha="scratches.png")),
    ),
    "DECALS": (
        ("GRAFFITI", "Graffiti", dict(decal_blend="NORMAL")),
        ("GRIME", "Grime", dict(decal_blend="DARKEN", roughness=0.7)),
    ),
}

TIPS = {
    "VARIATION": "Keep each Variation subtle and stack several",
    "DECALS": "Drips start at ledges and sills, dirt collects at the bottom, graffiti sits where "
              "a person could reach",
}


def label(kind):
    return INFO[kind]["label"]


def paintable(kind):
    return INFO[kind]["paint"] is not None


def paint_optional(kind):
    return bool(INFO[kind].get("optional_paint"))


def defaults(kind, preset=None):
    """The kind's default values, updated by a preset's."""
    d = dict(DEFAULTS[kind])
    for key, _, values in PRESETS.get(kind, ()):
        if key == preset:
            d.update(values)
    return d


def preset_items(kind):
    return [(key, name) for key, name, _ in PRESETS.get(kind, ())]


def insert_index(kinds_bottom_to_top, kind):
    """UI-1: where a new layer of `kind` goes: above the last layer whose kind sits at or below it
    in ORDER (layers the user dragged elsewhere are respected as they are)."""
    rank = ORDER.index(kind)
    idx = 0
    for i, k in enumerate(kinds_bottom_to_top):
        if ORDER.index(k) <= rank:
            idx = i + 1
    return idx


# ------------------------------------------------------------------ recipe math
def width(sharpness):
    """Outer ramp width: 0.5 at Sharpness 0, 0.01 at Sharpness 1."""
    s = min(max(sharpness, 0.0), 1.0)
    return 0.5 + (0.01 - 0.5) * s


def ramp_stops(threshold, sharpness):
    """(black, white) stop positions of the outer Color Ramp."""
    w = width(sharpness)
    return threshold - w / 2.0, threshold + w / 2.0


def breakup_stops(contrast):
    """(black, white) stops of the grunge's own Color Ramp (Breakup Contrast 0: identity)."""
    c = min(max(contrast, 0.0), 0.98)
    return c / 2.0, 1.0 - c / 2.0


def _ramp(x, lo, hi):
    """A two-stop linear Color Ramp: 0 at lo, 1 at hi (a Color Ramp clamps its input to 0..1)."""
    x = min(max(x, 0.0), 1.0) if isinstance(x, (int, float)) else x.clip(0.0, 1.0)
    t = (x - lo) / max(hi - lo, 1e-6)
    return min(max(t, 0.0), 1.0) if isinstance(t, (int, float)) else t.clip(0.0, 1.0)


def recipe(source, grunge, amount, contrast, threshold, sharpness, opacity=1.0):
    """Reference value of the mask recipe (floats or NumPy arrays)."""
    g = _ramp(grunge, *breakup_stops(contrast)) if amount > 0 else 0.0
    return _ramp(source - amount * g, *ramp_stops(threshold, sharpness)) * opacity


def edge_source(dot):
    """Edge Wear source from Bevel normal . geometry normal (1 on flats)."""
    return (1.0 - dot) * EDGE_GAIN


def ao_source(ao):
    """Dirt source from the AO value (1 in the open)."""
    lo, hi = AO_RAMP
    return 1.0 - _ramp(ao, lo, hi)


def edge_radius(width_m, breakup, grunge):
    """EDW-1: the grunge through a Map Range into the Bevel radius: width x (1 - b + b G)."""
    return width_m * (1.0 - breakup + breakup * grunge)


def hsv_inputs(hue, saturation, value):
    """Hue / Saturation / Value node inputs from the layer's shifts (0, 0, 0 is no change)."""
    return 0.5 + hue, 1.0 + saturation, 1.0 + value

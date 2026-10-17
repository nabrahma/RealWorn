"""The Puddle layer's model: water stands where a water level is above the ground.

Pure Python (floats or NumPy arrays, no bpy), so tests/pure checks the math outside Blender and
the compiler builds the same formulas as nodes. All heights and depths are in millimetres.

Ground and depth

  H  = Height Scale x base_norm + stack_extra     (Height Source: Stack)
     = Height Scale x base_norm                   (Base Only)
     = 0                                          (None)
  H' = H - dips x Dip Depth - P x Paint Depth     (+ a lift outside the paint in Paint-only mode)
  d  = Water Level - H'                           (> 0: under water, by that much)

base_norm is the base material's height map normalised by its 2nd and 98th percentiles (-0.5 to
0.5 across the measured range); stack_extra is what the layers below add to the shared height
(Reveal holes, textured Variations), in millimetres. P is the painted mask as a signed value:
the image starts at 0.5 grey (no change), white lowers the ground, black raises it. Painting
therefore never paints water directly; it moves the ground, so painted puddles still fill grout
and cracks before stone faces.

Zones (smooth steps on d, all widths in mm)

  water  smoothstep(-WATERLINE, WATERLINE, d)   the crispest transition, as a real waterline
  deep   smoothstep(0, Deep Threshold, d)
  edge   smoothstep(-Edge Width, 0, d)           the wet, glossy band just outside the water
  halo   smoothstep(-(Edge Width + Halo Width x Halo), -Edge Width, d)

Water only stands on near-horizontal faces: where the world normal's Z is below the flat
threshold, d is pushed far below zero (a smooth gate), so kerbs and walls stay dry.

Wet film (Wet Film above 0): a skin of water over every flat stone, glossy but thin enough to
follow the stone's relief, so reflections break into streaks

  F = Wet Film x gate x (1 - Dry Patches x ramp(B1)) x opacity     how wet (film weight)
  R = Relief Through Film x lerp(0.2, 1, B2) x (1 - deep)            relief showing through it

B1 and B2 are two samples of the Film Breakup texture (Noise, or a grunge from the library) at
its own scale, the second one offset, so some patches mirror and others scatter. The Noise
breakup is normalised with smoothstep(0.3, 0.7) of its value; a grunge is used as it is. ramp is
smoothstep(0.4, 0.6). F acts as extra wetness out of the water: porosity darkening with max(wet,
F), base roughness x (1 - 0.7 F), Coat Weight max(coat, F), Coat Roughness lerp(0.12, Film
Gloss, F) on flat faces, Coat IOR 1.33, and the coat normal a Bump of the shared height at
strength R. Standing water keeps the puddle look exactly.
"""

import math

WATERLINE = 0.1          # mm: half-width of the water / wet-edge transition
DRY_DEPTH = -50.0        # mm: d on walls and kerb sides (far outside every zone)
FLAT_SOFT = (0.06, 0.02)  # gate from threshold - 0.06 (dry) to threshold + 0.02 (full)
PAINT_LIFT = 100.0       # mm: Paint-only mode raises unpainted ground out of the water
HALO_WETNESS = 0.4       # how wet the damp halo is, relative to the wet edge
DARKEST = 0.2            # fully wet, fully porous ground keeps 20 % of its colour
WATER_ROUGHNESS = 0.3    # base roughness of ground under water (the coat reflects on top)
COAT_IOR = 1.33
COAT_ROUGHNESS = (0.08, 0.02, 0.005)  # wet edge (thin film), shallow, deep (mirror)
EDGE_ROUGHNESS = 0.5     # base roughness factor at the wet edge
HALO_ROUGHNESS = 0.85    # base roughness factor in the damp halo
DEBRIS = 0.4             # Debris Settle 1 darkens the deepest water by 40 %
TIDE = 0.35              # Tide Mark 1 darkens the halo's outer ring by 35 %
RIPPLE_SCALE = 40.0      # wind ripple noise, per metre
OILY_FILM_NM = 450.0     # thin film thickness of the oily sheen patches
OILY_SCALE = 1.2         # oily patch noise, per metre

TINTS = {
    "CLEAR": (0.012, 0.016, 0.02),
    "MUDDY": (0.09, 0.065, 0.04),
    "OILY": (0.012, 0.016, 0.02),
}
MUDDY_ABSORPTION = 0.5   # muddy water hides the ground twice as fast

FILM_NOISE_RANGE = (0.3, 0.7)   # Noise breakup: its value normalised to 0..1
FILM_RAMP = (0.4, 0.6)          # ramp(B1): where Dry Patches dry the film
FILM_OFFSET = (0.37, 0.71, 0.13)  # B2: the breakup sampled again this far away (in tiles)
FILM_RELIEF_MIN = 0.2           # the calmest patches keep 20 % of the relief
FILM_ROUGHNESS = 0.7            # full film multiplies base roughness by 1 - 0.7
FILM_COAT_ROUGHNESS = 0.12      # coat roughness at the faintest film (Film Gloss at full film)
FILM_DEFAULTS = dict(film_relief=0.6, film_scale_m=1.5, dry_patches=0.0, film_gloss=0.02)

# Level presets (the Add menu and the layer's Preset): level, halo, depth look, and the wet film.
_DAMP = dict(water_level_mm=-4.0, halo=1.3, depth_look_mm=8.0)
_WET = dict(water_level_mm=-2.0, halo=1.0, depth_look_mm=8.0)
PRESETS = (
    ("DAMP", "Damp", dict(_DAMP, wet_film=0.0)),
    ("WET", "Wet", dict(_WET, wet_film=0.0)),
    ("PUDDLES", "Puddles", dict(water_level_mm=0.5, halo=1.0, depth_look_mm=8.0, wet_film=0.0)),
    ("SOAKED", "Soaked", dict(water_level_mm=4.0, halo=0.8, depth_look_mm=10.0, wet_film=0.0)),
    ("RAIN_SOAKED", "Rain-soaked", dict(_DAMP, wet_film=1.0, film_relief=0.6, dry_patches=0.0)),
    ("JUST_RAINED", "Just Rained", dict(_WET, wet_film=0.8, film_relief=0.5, dry_patches=0.2)),
    ("DRYING", "Drying", dict(_DAMP, wet_film=0.5, film_relief=0.4, dry_patches=0.6)),
)
FILM_PRESETS = ("RAIN_SOAKED", "JUST_RAINED", "DRYING")
DEFAULT_PRESET = "WET"

# Surface presets: how much height the base map spans, and broad dips for flat-ish surfaces.
SURFACES = (
    ("ASPHALT", "Asphalt", dict(height_scale_mm=3.0, broad_dips=True, dip_depth_mm=12.0, dip_scale_m=3.0)),
    ("COBBLESTONE", "Cobblestone", dict(height_scale_mm=25.0, broad_dips=False)),
    ("TILES", "Tiles", dict(height_scale_mm=6.0, broad_dips=True, dip_depth_mm=4.0, dip_scale_m=2.0)),
    ("CONCRETE", "Concrete", dict(height_scale_mm=5.0, broad_dips=True, dip_depth_mm=10.0, dip_scale_m=2.5)),
    ("DIRT_ROAD", "Dirt Road", dict(height_scale_mm=20.0, broad_dips=True, dip_depth_mm=30.0, dip_scale_m=2.0)),
)


def preset_values(key, table=PRESETS):
    for k, _, values in table:
        if k == key:
            return dict(values)
    raise KeyError(key)


# ------------------------------------------------------------------ helpers
def _np():
    import numpy
    return numpy


def _is_scalar(x):
    return isinstance(x, (int, float))


def clamp(x, lo=0.0, hi=1.0):
    if _is_scalar(x):
        return min(max(x, lo), hi)
    return _np().clip(x, lo, hi)


def smoothstep(e0, e1, x):
    """Blender's Map Range SMOOTHSTEP from (e0, e1) to (0, 1), clamped."""
    span = e1 - e0
    if _is_scalar(span) and abs(span) < 1e-9:
        span = 1e-9
    t = clamp((x - e0) / span)
    return t * t * (3.0 - 2.0 * t)


def exp(x):
    return math.exp(x) if _is_scalar(x) else _np().exp(x)


def maximum(a, b):
    if _is_scalar(a) and _is_scalar(b):
        return max(a, b)
    return _np().maximum(a, b)


def lerp(a, b, t):
    return a + (b - a) * t


# ------------------------------------------------------------------ height
def height_range(values, lo_pct=2.0, hi_pct=98.0):
    """(lo, hi) percentiles of a height map's 0..1 values (a NumPy array)."""
    np = _np()
    v = np.asarray(values, dtype=np.float32).ravel()
    lo, hi = np.percentile(v, [lo_pct, hi_pct])
    return float(lo), float(hi)


def base_norm(v, lo, hi):
    """A height map value normalised to -0.5..0.5 across its measured range."""
    span = max(hi - lo, 0.02)
    return (v - (lo + hi) / 2.0) / span


def ground(base_n, stack_extra_mm, height_scale_mm, source="STACK"):
    if source == "NONE":
        return 0.0 * base_n if not _is_scalar(base_n) else 0.0
    h = height_scale_mm * base_n
    return h + stack_extra_mm if source == "STACK" else h


def paint_signed(mask_value):
    """The painted image (0.5 neutral) as -1 (raise) .. 1 (lower)."""
    return clamp(mask_value * 2.0 - 1.0, -1.0, 1.0)


def lowered(H, paint=0.0, paint_depth_mm=20.0, mode="AUTO_AND_PAINT", dips=0.0, dip_depth_mm=0.0):
    """H': the ground the water sees. `paint` is the signed painted value (-1..1)."""
    h = H - dips * dip_depth_mm
    if mode == "AUTO":
        return h
    h = h - paint * paint_depth_mm
    if mode == "PAINT":
        h = h + (1.0 - clamp(paint)) * (PAINT_LIFT + paint_depth_mm)
    return h


def flat_gate(normal_z, threshold):
    lo, hi = FLAT_SOFT
    return smoothstep(threshold - lo, threshold + hi, normal_z)


def depth(level_mm, H_lowered, gate=1.0):
    """d = L - H', pushed to DRY_DEPTH where the face is not flat."""
    d = level_mm - H_lowered
    return lerp(DRY_DEPTH, d, gate)


# ------------------------------------------------------------------ zones
def zones(d, edge_mm=1.5, halo_mm=6.0, halo=1.0, deep_mm=6.0):
    """{'water', 'deep', 'edge', 'halo', 'wet'} weights (0..1) from depth d."""
    w = smoothstep(-WATERLINE, WATERLINE, d)
    deep = smoothstep(0.0, deep_mm, d)
    edge = smoothstep(-edge_mm, 0.0, d)
    hal = smoothstep(-(edge_mm + halo_mm * halo), -edge_mm, d)
    wet = maximum(HALO_WETNESS * hal, edge)
    return {"water": w, "deep": deep, "edge": edge, "halo": hal, "wet": wet}


# ------------------------------------------------------------------ look
def porosity(roughness):
    """Rough (porous) ground darkens when wet, smooth ground barely does."""
    return clamp((roughness - 0.5) / 0.4)


def absorption(d, depth_look_mm, tint="CLEAR"):
    """exp(-d/k) under water (1 above it): how much of the ground still shows."""
    k = depth_look_mm * (MUDDY_ABSORPTION if tint == "MUDDY" else 1.0)
    return exp(-maximum(d, 0.0) / max(k, 1e-3))


def look(color, roughness, metallic, d, z, opacity=1.0, darkening=1.0, depth_look_mm=8.0, tint_rgb=TINTS["CLEAR"],
         tint="CLEAR", debris=0.0, tide=0.0, film=0.0):
    """Base colour (per channel, same shape as `color`'s channels) and base roughness under the
    puddle. `color` is a sequence of three channels (floats or arrays); `z` is zones(d); `film` is
    the wet film weight F (opacity included)."""
    wet = maximum(z["wet"] * opacity, film)
    k = (1.0 - metallic) * porosity(roughness) * wet * darkening
    keep = 1.0 - (1.0 - DARKEST) * k
    a = absorption(d, depth_look_mm, tint)
    water, deep, hal = z["water"] * opacity, z["deep"] * opacity, z["halo"] * opacity
    out = []
    for c, t in zip(color, tint_rgb):
        c_wet = c * keep
        c_under = lerp(t, c_wet, a)
        c1 = lerp(c_wet, c_under, water)
        c1 = c1 * (1.0 - DEBRIS * debris * deep)
        c1 = c1 * (1.0 - TIDE * tide * 4.0 * hal * (1.0 - hal))
        out.append(c1)
    r = roughness * (1.0 - (1.0 - HALO_ROUGHNESS) * hal) * (1.0 - (1.0 - EDGE_ROUGHNESS / HALO_ROUGHNESS) * z["edge"] * opacity)
    r = r * (1.0 - FILM_ROUGHNESS * film)
    r = lerp(r, WATER_ROUGHNESS, water)
    return out, r


def coat(z, opacity=1.0, weight_in=0.0, roughness_in=0.03, ior_in=1.5, film=None, gloss=0.02, gate=1.0):
    """(Coat Weight, Coat Roughness, Coat IOR). With a wet film (`film` = F, opacity included),
    flat faces (`gate`) take the film's coat roughness and IOR outside the water."""
    e = z["edge"] * opacity
    w_zone = maximum(weight_in, e)
    cr_zone = lerp(lerp(COAT_ROUGHNESS[0], COAT_ROUGHNESS[1], z["water"]), COAT_ROUGHNESS[2], z["deep"])
    if film is None:
        return w_zone, lerp(roughness_in, cr_zone, e), lerp(ior_in, COAT_IOR, e)
    present = gate * opacity
    film_r = lerp(roughness_in, lerp(FILM_COAT_ROUGHNESS, gloss, film), present)
    return (maximum(w_zone, film), lerp(film_r, cr_zone, e), lerp(ior_in, COAT_IOR, maximum(e, present)))


def relief(d, z, depth_look_mm=8.0, opacity=1.0, tint="CLEAR"):
    """Bump strength: ground relief fades with depth and is flat in deep water."""
    fade = absorption(d, depth_look_mm, tint) * (1.0 - z["deep"])
    return 1.0 - opacity * (1.0 - fade)


def film_breakup_noise(fac):
    """The Noise breakup's value normalised to 0..1."""
    return smoothstep(FILM_NOISE_RANGE[0], FILM_NOISE_RANGE[1], fac)


def film_weight(wet_film, b1, dry_patches=0.0, gate=1.0, opacity=1.0):
    """F: how wet the film is (0..1)."""
    return wet_film * gate * (1.0 - dry_patches * smoothstep(FILM_RAMP[0], FILM_RAMP[1], b1)) * opacity


def film_relief(relief, b2, deep=0.0):
    """R: the Bump strength of the ground relief in the film's coat normal."""
    return relief * lerp(FILM_RELIEF_MIN, 1.0, b2) * (1.0 - deep)


def true_height(H_lowered, level_mm):
    """True Depth: the water surface is flat at the water level (mm)."""
    return maximum(H_lowered, level_mm)


# ------------------------------------------------------------------ Mask View
VIEW_COLORS = {
    "dry": (0.18, 0.18, 0.18),
    "halo": (0.55, 0.45, 0.25),
    "edge": (0.2, 0.75, 0.75),
    "shallow": (0.1, 0.35, 0.95),
    "deep": (0.02, 0.05, 0.35),
}


def view_color(z):
    """The Mask View colour ramp: dry grey, halo, wet edge, shallow, deep."""
    out = []
    for i in range(3):
        c = VIEW_COLORS["dry"][i]
        c = lerp(c, VIEW_COLORS["halo"][i], z["halo"])
        c = lerp(c, VIEW_COLORS["edge"][i], z["edge"])
        c = lerp(c, VIEW_COLORS["shallow"][i], z["water"])
        c = lerp(c, VIEW_COLORS["deep"][i], z["deep"])
        out.append(c)
    return out

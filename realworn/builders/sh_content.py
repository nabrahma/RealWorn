"""Content looks (PRD v2.1 CNT-1..CNT-4): RW_Content_<Type> turns a layer's flat colour and
roughness into a textured effect. Two or three object-space noises plus the layer's grunge vary
colour, roughness and a micro height (mm) that joins the stack's ONE shared bump (rule 15).

Inputs   Color, Roughness           the layer's channel values (their sliders stay live)
         Color Variation, Roughness Variation, Micro (micro height strength), Scale (metres)
         Mask, Edge Mask            the layer mask after and before Edge Detail (CNT-4: Rust's
                                    orange rim, Dirt's drier edge live in the band between them)
         Base Height, Grunge        normalised base height and the Edge Detail value (0.5 if none)
Outputs  Color, Roughness, Height (mm, to be multiplied by the mask by the compiler)

Constants are frozen here by eye on the reference crate (PRD CNT-1).
"""

from ..core import naming
from ._dsl import Tree

LOOK_TYPES = ("DIRT", "DUST", "RUST", "WEAR", "SCRATCHES", "WATER", "DAMAGE")
RUST_RIM = (0.28, 0.075, 0.018)


def _common(t):
    t.inp("Color", "COLOR", (0.5, 0.5, 0.5))
    t.inp("Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Color Variation", "FLOAT", 0.4, 0.0, 1.0)
    t.inp("Roughness Variation", "FLOAT", 0.4, 0.0, 1.0)
    t.inp("Micro", "FLOAT", 0.5, 0.0, 4.0)
    t.inp("Scale", "FLOAT", 0.3, 0.001, 100.0)
    t.inp("Mask", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Edge Mask", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Base Height", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Grunge", "FLOAT", 0.5, 0.0, 1.0)
    t.out("Color", "COLOR")
    t.out("Roughness", "FLOAT")
    t.out("Height", "FLOAT")
    tc = t.outp(t.node("ShaderNodeTexCoord"), "Object")
    s = t.I("Scale")
    p = t.vmath("DIVIDE", tc, t.comb(s, s, s))
    # single-octave noises: each octave is a full Perlin evaluation per shading point (and three
    # when the look's relief feeds the shared bump); measured in docs/milestones/Q4/notes.md
    n1 = t.maprange(t.noise(p, 1.0, detail=1.0), 0.3, 0.7, -1.0, 1.0)  # broad patches
    n2 = t.maprange(t.noise(t.vmath("ADD", p, (5.3, 1.7, 8.1)), 7.0, detail=1.0), 0.3, 0.7, -1.0, 1.0)
    fine = t.noise(p, 60.0, detail=0.0)  # grit, 0..1
    return p, n1, n2, fine


def _vary(t, color, n1, n2, sat=1.0):
    cv = t.I("Color Variation")
    hsv = t.node("ShaderNodeHueSaturation", Hue=t.add(0.5, t.mul_all(n1, cv, 0.04)), Saturation=sat,
                 Value=t.add(1.0, t.mul(t.add(t.mul(n1, 0.5), t.mul(n2, 0.25)), cv)), Fac=1.0, Color=color)
    return t.outp(hsv)


def _rough(t, n1, n2, extra=None):
    r = t.add(t.I("Roughness"), t.mul_all(t.add(t.mul(n1, 0.6), t.mul(n2, 0.4)), t.I("Roughness Variation"), 0.5))
    return t.clamp(t.add(r, extra) if extra is not None else r)


def build_type(kind):
    t = Tree.new_group(naming.content_group(kind), "SHADER")
    p, n1, n2, fine = _common(t)
    col, micro, thick = t.I("Color"), t.I("Micro"), t.I("Edge Mask")
    height = 0.0
    rough_extra = None
    sat = 1.0
    if kind == "DIRT":
        # two browns: darker where the base is low (wetter, thicker); a drier, lighter edge band
        dark = t.mix(1.0, col, (0.5, 0.5, 0.5), blend="MULTIPLY")
        col = t.mix(t.mul(t.sub(1.0, t.I("Base Height")), 0.7), col, dark)
        dry = t.mul(t.clamp(t.sub(1.0, thick)), t.I("Mask"))
        col = t.mix(t.mul(dry, 0.5), col, t.mix(1.0, col, (1.6, 1.5, 1.4), blend="MULTIPLY"))
        rough_extra = t.mul(thick, -0.12)  # smoother where thick
        height = t.mul_all(t.sub(fine, 0.5), micro, 0.08)
    elif kind == "DUST":
        sat = 0.35
    elif kind == "RUST":
        # dark brown core, orange rim along the stroke boundary (between Edge Mask and Mask)
        # mottled core (darker where the grunge is dark), orange only in the outer part of the stroke
        rim = t.sub(1.0, t.maprange(thick, 0.3, 0.8, interp="SMOOTHSTEP"))
        col = t.mix(t.mul(rim, 0.65), col, (*RUST_RIM, 1.0))
        # mottle from noises independent of the grunge: Erode keeps rust where the grunge is light,
        # so the grunge itself is nearly constant across visible rust
        mid = t.noise(t.vmath("ADD", p, (2.1, 9.4, 4.4)), 18.0, detail=1.0)
        g = t.maprange(t.add(t.mul(fine, 0.5), t.mul(mid, 0.5)), 0.3, 0.7, 0.45, 1.35)
        col = t.mix(1.0, col, t.comb(g, g, g), blend="MULTIPLY")
        height = t.add(t.mul_all(t.sub(t.I("Grunge"), 1.0), micro, 0.15), t.mul_all(t.sub(fine, 0.5), micro, 0.05))
    elif kind == "WEAR":
        brush = t.noise(t.vmath("MULTIPLY", p, (2.0, 60.0, 60.0)), 1.0, detail=1.0)  # streaks along X
        n1 = t.maprange(brush, 0.3, 0.7, -1.0, 1.0)
        n2 = t.mul(n2, 0.3)
        height = t.mul_all(t.sub(brush, 0.5), micro, 0.02)
    elif kind == "SCRATCHES":
        n1 = t.mul(n1, 0.3)
        height = t.mul_all(t.I("Grunge"), micro, -0.03)
    elif kind == "WATER":
        ripple = t.noise(p, 20.0, detail=1.0)
        n1 = t.mul(t.add(n2, 1.0), 0.05)  # roughness only upward, 0.01 .. 0.06
        n2 = t.mul(n2, 0.0)
        height = t.mul_all(t.sub(ripple, 0.5), micro, 0.02)
    elif kind == "DAMAGE":
        col = t.mix(1.0, col, t.comb(t.add(0.85, t.mul(fine, 0.3)), t.add(0.85, t.mul(fine, 0.3)),
                                     t.add(0.85, t.mul(fine, 0.3))), blend="MULTIPLY")
        height = t.mul_all(t.sub(fine, 0.5), micro, 0.1)
    t.O("Color", _vary(t, col, n1, n2, sat))
    t.O("Roughness", _rough(t, n1, n2, rough_extra))
    t.O("Height", height)
    t.layout()
    return t.t


def build():
    return [build_type(k) for k in LOOK_TYPES]

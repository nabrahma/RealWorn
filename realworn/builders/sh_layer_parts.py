"""Shared building blocks the compiler instances inside every RW_Stack::<material> (CMP-5).

RW_P_PaintOver   lerp(procedural, painted value, painted alpha): alpha records "painted here"
RW_P_EdgeLock    mask * lerp(1, lock, strength)  (ING-2)
RW_P_HeightBlend mask * (1 + amount * (1 - 2 * height)): low spots reach the threshold first (ING-4)
RW_P_Levels      threshold with softness (ING-3); softness 1 and threshold 0.5 is the identity
RW_P_Up          1 on faces whose world normal is within Angle of straight up
RW_P_Contrast    invert, then contrast around 0.5 (grunge and generator ingredients)
RW_P_Variation   hue / value / roughness jitter from a large object-space noise (LAY-4)
"""

from ..core import naming
from ._dsl import Tree


def build_paint_over():
    t = Tree.new_group(naming.SH_PAINT_OVER, "SHADER")
    t.inp("Procedural", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Paint", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Alpha", "FLOAT", 0.0, 0.0, 1.0)
    t.out("Mask", "FLOAT")
    t.O("Mask", t.mixf(t.I("Alpha"), t.I("Procedural"), t.I("Paint")))
    t.layout()
    return t.t


def build_edge_lock():
    t = Tree.new_group(naming.SH_EDGE_LOCK, "SHADER")
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Lock", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Strength", "FLOAT", 0.0, 0.0, 1.0)
    t.out("Mask", "FLOAT")
    t.O("Mask", t.mul(t.I("Mask"), t.mixf(t.I("Strength"), 1.0, t.I("Lock"))))
    t.layout()
    return t.t


def build_height_blend():
    t = Tree.new_group(naming.SH_HEIGHT_BLEND, "SHADER")
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Height", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.5, 0.0, 2.0)
    t.out("Mask", "FLOAT")
    t.O("Mask", t.clamp(t.mul(t.I("Mask"), t.add(1.0, t.mul(t.I("Amount"), t.sub(1.0, t.mul(t.I("Height"), 2.0)))))))
    t.layout()
    return t.t


def build_levels():
    t = Tree.new_group(naming.SH_LEVELS, "SHADER")
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Threshold", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Softness", "FLOAT", 1.0, 0.0, 1.0)
    t.out("Mask", "FLOAT")
    half = t.mul(t.max(t.I("Softness"), 0.001), 0.5)
    t.O("Mask", t.maprange(t.I("Mask"), t.sub(t.I("Threshold"), half), t.add(t.I("Threshold"), half)))
    t.layout()
    return t.t


def build_up():
    t = Tree.new_group(naming.SH_UP, "SHADER")
    t.inp("Angle", "FLOAT", 0.7853982, 0.0, 1.5707964, subtype="ANGLE")
    t.out("Up", "FLOAT")
    geo = t.node("ShaderNodeNewGeometry")
    _, _, nz = t.sep(t.outp(geo, "Normal"))
    c = t.math("COSINE", t.I("Angle"))
    t.O("Up", t.maprange(nz, t.sub(c, 0.05), t.add(c, 0.05), interp="SMOOTHSTEP"))
    t.layout()
    return t.t


def build_contrast():
    t = Tree.new_group(naming.SH_CONTRAST, "SHADER")
    t.inp("Value", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Contrast", "FLOAT", 0.0, -1.0, 1.0)
    t.inp("Invert", "FLOAT", 0.0, 0.0, 1.0)
    t.out("Value", "FLOAT")
    x = t.math("ABSOLUTE", t.sub(t.I("Invert"), t.I("Value")))
    k = t.div(t.add(1.0, t.I("Contrast")), t.max(t.sub(1.0, t.I("Contrast")), 0.05))
    t.O("Value", t.clamp(t.add(0.5, t.mul(t.sub(x, 0.5), k))))
    t.layout()
    return t.t


def build_variation():
    t = Tree.new_group(naming.SH_VARIATION, "SHADER")
    t.inp("Color", "COLOR", (0.5, 0.5, 0.5))
    t.inp("Amount", "FLOAT", 0.2, 0.0, 1.0)
    t.inp("Scale", "FLOAT", 0.5, 0.01, 100.0)
    t.out("Color", "COLOR")
    t.out("Roughness Offset", "FLOAT")
    tc = t.outp(t.node("ShaderNodeTexCoord"), "Object")
    v = t.vmath("DIVIDE", tc, t.comb(t.I("Scale"), t.I("Scale"), t.I("Scale")))
    # Perlin fBm sits mostly in 0.3..0.7: stretch it to -1..1 before scaling
    n1 = t.maprange(t.noise(v, 1.0, detail=2.0), 0.3, 0.7, -1.0, 1.0)
    n2 = t.maprange(t.noise(t.vmath("ADD", v, (17.3, 5.1, 9.7)), 1.0, detail=2.0), 0.3, 0.7, -1.0, 1.0)
    amt = t.I("Amount")
    hsv = t.node("ShaderNodeHueSaturation", Hue=t.add(0.5, t.mul_all(n1, amt, 0.05)),
                 Saturation=1.0, Value=t.add(1.0, t.mul_all(n2, amt, 0.5)), Fac=1.0,
                 Color=t.I("Color"))
    t.O("Color", t.outp(hsv))
    t.O("Roughness Offset", t.mul_all(n1, amt, 0.25))
    t.layout()
    return t.t


def build():
    return [build_paint_over(), build_edge_lock(), build_height_blend(), build_levels(), build_up(),
            build_contrast(), build_variation()]

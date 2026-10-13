"""Edge Detail (PRD v2.1 EDG-1..EDG-8): turn a soft painted mask into a crisp edge decided by a
full-resolution detail value d (grunge, base height...). One group per mode; the compiler adds the
mode's group only while Strength > 0 (lean compile, EDG-2).

m: the layer's combined mask (after paint-over and ingredients), d: detail 0..1 (after Detail
Contrast / Invert), s: Strength, w: Edge Width, t: Threshold, b: interior protection.

RW_P_EdgeErode   e = m - (1 - d) * s * b,                     M = smoothstep(t - w/2, t + w/2, e)
                 b = lerp(1, clamp((1 - m) * 4), Protect): with Protect on, the solid middle of a
                 stroke (m = 1) is not eroded, only its boundary breaks up
RW_P_EdgeBurn    e = 1 - (1 - m) / max(d, eps) (Color Burn), blended with m by s,
                 M = smoothstep(t - w/2, t + w/2, clamp(e))
RW_P_EdgeHeight  M = smoothstep(-w/2, w/2, m * s - d - (t - 0.5)) * clamp(m * 20)
                 the stroke is a water level against the detail as terrain; the last factor keeps
                 unpainted texels empty (without it m = 0 over the lowest point d = 0 gives 0.5)
"""

from ..core import naming
from ._dsl import Tree


def _io(t, protect=False):
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Detail", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Strength", "FLOAT", 0.7, 0.0, 1.0)
    t.inp("Width", "FLOAT", 0.05, 0.001, 1.0)
    t.inp("Threshold", "FLOAT", 0.5, 0.0, 1.0)
    if protect:
        t.inp("Protect", "FLOAT", 0.0, 0.0, 1.0)
    t.out("Mask", "FLOAT")
    return t.mul(t.max(t.I("Width"), 0.001), 0.5)


def build_erode():
    t = Tree.new_group(naming.SH_EDGE_ERODE, "SHADER")
    hw = _io(t, protect=True)
    m = t.I("Mask")
    b = t.mixf(t.I("Protect"), 1.0, t.clamp(t.mul(t.sub(1.0, m), 4.0)))
    e = t.sub(m, t.mul_all(t.sub(1.0, t.I("Detail")), t.I("Strength"), b))
    th = t.I("Threshold")
    t.O("Mask", t.maprange(e, t.sub(th, hw), t.add(th, hw), interp="SMOOTHSTEP"))
    t.layout()
    return t.t


def build_burn():
    t = Tree.new_group(naming.SH_EDGE_BURN, "SHADER")
    hw = _io(t)
    m = t.I("Mask")
    burn = t.clamp(t.sub(1.0, t.div(t.sub(1.0, m), t.max(t.I("Detail"), 0.02))))
    e = t.mixf(t.I("Strength"), m, burn)
    th = t.I("Threshold")
    t.O("Mask", t.maprange(e, t.sub(th, hw), t.add(th, hw), interp="SMOOTHSTEP"))
    t.layout()
    return t.t


def build_height():
    t = Tree.new_group(naming.SH_EDGE_HEIGHT, "SHADER")
    hw = _io(t)
    m = t.I("Mask")
    level = t.sub(t.sub(t.mul(m, t.I("Strength")), t.I("Detail")), t.sub(t.I("Threshold"), 0.5))
    fill = t.maprange(level, t.mul(hw, -1.0), hw, interp="SMOOTHSTEP")
    t.O("Mask", t.mul(fill, t.clamp(t.mul(m, 20.0))))
    t.layout()
    return t.t


def build():
    return [build_erode(), build_burn(), build_height()]

"""RW_P_Damage: painted dents with a light-catching rim (DMG-1, DMG-2).

Mask is the Damage layer's final mask. Inside = the crisp interior (Edge Sharpness narrows the
transition); the dent is Depth mm deep inside; the rim is a band just outside the break, raised by
Rim Height mm and brightened by Rim Brightness. Shader and Displacement modes share these
values, so switching depth keeps the look.

v2.1 DMG-10 / DMG-11 Follow Base: the carve is scaled by 2 x the normalised base height, so a
painted patch on bricks loses brick faces (high) before mortar (low) and the break follows the
bricks. Follow 0 is v2.0's flat carve.
"""

from ..core import naming
from ._dsl import Tree


def build():
    t = Tree.new_group(naming.SH_DAMAGE, "SHADER")
    t.t.description = "RealWorn painted damage: dent + rim"
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Raw", "FLOAT", 0.0, 0.0, 1.0, description="The mask before Levels: the brush falloff shapes the bowl")
    t.inp("Depth", "FLOAT", 3.0, 0.0, 100.0, description="Dent depth in mm")
    t.inp("Rim Height", "FLOAT", 0.6, 0.0, 20.0, description="Rim height in mm")
    t.inp("Rim Width", "FLOAT", 0.25, 0.01, 1.0)
    t.inp("Rim Brightness", "FLOAT", 0.35, 0.0, 1.0)
    t.inp("Sharpness", "FLOAT", 0.8, 0.0, 1.0)
    t.inp("Reveal", "FLOAT", 0.6, 0.0, 1.0, description="How much of a dent breaks through to the inner material")
    t.inp("Base Height", "FLOAT", 0.5, 0.0, 1.0, description="Normalised base height (v2.1 Follow Base)")
    t.inp("Follow", "FLOAT", 0.0, 0.0, 1.0, description="0: flat carve (v2.0); 1: carve follows the base")
    t.out("Height", "FLOAT")
    t.out("Reveal Mask", "FLOAT")
    t.out("Inside", "FLOAT")
    t.out("Rim", "FLOAT")
    t.out("Brighten", "FLOAT")
    m = t.I("Mask")
    soft = t.mul(t.inv(t.I("Sharpness")), 0.25)
    inside = t.maprange(m, t.sub(0.5, soft), t.add(0.5, t.add(soft, 0.001)), interp="SMOOTHSTEP")
    raw = t.I("Raw")
    rw = t.I("Rim Width")
    # rim: a band on the outside of the dent, where the brush falloff is still low
    rim = t.mul(t.maprange(raw, t.mul(rw, 0.2), t.mul(rw, 0.8), interp="SMOOTHSTEP"),
                t.inv(t.maprange(raw, t.mul(rw, 0.8), t.add(t.mul(rw, 0.8), 0.25), interp="SMOOTHSTEP")))
    # bowl: depth follows the soft mask, so the dent floor curves (a crisp floor would only shade
    # at its wall)
    bowl = t.maprange(raw, t.mul(rw, 0.6), 1.0, interp="SMOOTHSTEP")
    t.O("Inside", inside)
    t.O("Rim", rim)
    follow = t.mixf(t.I("Follow"), 1.0, t.mul(t.I("Base Height"), 2.0))
    t.O("Height", t.sub(t.mul(rim, t.I("Rim Height")), t.mul_all(bowl, t.I("Depth"), follow)))
    t.O("Brighten", t.mul(rim, t.I("Rim Brightness")))
    # the inner material shows where the dent is strongest (a hard stroke breaks fully; a soft dent
    # dab only breaks at its centre)
    lo = t.inv(t.I("Reveal"))
    t.O("Reveal Mask", t.mul(inside, t.maprange(raw, lo, t.add(lo, 0.12), interp="SMOOTHSTEP")))
    t.layout()
    return t.t

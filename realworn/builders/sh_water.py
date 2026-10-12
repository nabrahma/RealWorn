"""RW_P_Water: hand-painted water over everything below (WAT-1..WAT-4). No rain, no puddle logic:
the painted mask decides where it is wet.

WAT-1 darken: colour * lerp(1, Darken, mask * porosity); porosity from the BASE material
      (roughness * (1 - metallic)), so metal barely darkens and concrete darkens a lot.
WAT-2 coat: weight max(coat, mask), IOR -> 1.33, coat roughness -> the layer's roughness.
WAT-3 depth: Flatten = mask * depth (the compiler fades the bump and layer height under it).
WAT-4 edge darkening: a thin ring 4 m (1 - m) along the mask boundary.
"""

from ..core import naming
from ._dsl import Tree


def build():
    t = Tree.new_group(naming.SH_WATER, "SHADER")
    t.t.description = "RealWorn hand-painted water"
    t.inp("Color", "COLOR", (0.5, 0.5, 0.5))
    t.inp("Coat Weight", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Coat Roughness", "FLOAT", 0.03, 0.0, 1.0)
    t.inp("Coat IOR", "FLOAT", 1.5, 1.0, 4.0)
    t.inp("Mask", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Base Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Base Metallic", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Water Roughness", "FLOAT", 0.03, 0.0, 1.0)
    t.inp("Darken", "FLOAT", 0.65, 0.0, 1.0)
    t.inp("Depth", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Edge", "FLOAT", 0.15, 0.0, 1.0)
    t.out("Color", "COLOR")
    t.out("Coat Weight", "FLOAT")
    t.out("Coat Roughness", "FLOAT")
    t.out("Coat IOR", "FLOAT")
    t.out("Flatten", "FLOAT")
    m = t.I("Mask")
    porosity = t.clamp(t.mul_all(t.I("Base Roughness"), t.inv(t.I("Base Metallic")), 1.4))
    k = t.mixf(t.mul(m, porosity), 1.0, t.I("Darken"))
    ring = t.mul_all(m, t.inv(m), 4.0, t.I("Edge"))
    k = t.mul(k, t.inv(t.mul(ring, 0.6)))
    t.O("Color", t.mix(1.0, t.I("Color"), t.comb(k, k, k), blend="MULTIPLY"))
    t.O("Coat Weight", t.max(t.I("Coat Weight"), m))
    t.O("Coat Roughness", t.mixf(m, t.I("Coat Roughness"), t.I("Water Roughness")))
    t.O("Coat IOR", t.mixf(m, t.I("Coat IOR"), 1.33))
    t.O("Flatten", t.mul(m, t.I("Depth")))
    t.layout()
    return t.t

"""Builds the projector-decal group (DEC-1).

RW_DecalProject: Texture Coordinate > Object of the decal Empty -> UV and a unit-box mask.
v2: a decal is an ordinary layer; the compiler instances this group in the layer's block.
"""

from ..core import naming
from ._dsl import Tree


def build_project():
    t = Tree.new_group(naming.SH_DECAL_PROJECT, "SHADER")
    t.inp("Vector", "VECTOR", hide_value=True, description="Texture Coordinate > Object of the decal Empty")
    t.out("UV", "VECTOR")
    t.out("Box", "FLOAT")
    x, y, z = t.sep(t.I("Vector"))
    t.O("UV", t.comb(t.add(t.mul(x, 0.5), 0.5), t.add(t.mul(y, 0.5), 0.5), 0.0))
    box = None
    for c in (x, y, z):
        inside = t.maprange(t.math("ABSOLUTE", c), 1.0, 0.98)  # 1 inside, soft 2% edge
        box = inside if box is None else t.mul(box, inside)
    t.O("Box", box)
    t.layout()
    return t.t


def build():
    return [build_project()]

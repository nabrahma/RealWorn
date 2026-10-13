"""RW_P_AntiTile (PRD v2.1 SRC-6): break up the repeats of a box-projected grunge.

Input Vector is the grunge's mapped coordinate (1 unit = 1 tile). Voronoi cells of `Cell` tiles
(default 3) each get a random 3D rotation and offset; the compiler samples the image at A (this
pixel's cell) and B (the next nearest cell) and mixes by Blend, which is 0.5 on a cell border and
0 deep inside a cell, so cell borders show no seam. Two lookups instead of one: opt-in per layer.
"""

import math

from ..core import naming
from ._dsl import Tree


def build():
    t = Tree.new_group(naming.SH_ANTI_TILE, "SHADER")
    t.inp("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True)
    t.inp("Cell", "FLOAT", 3.0, 0.1, 100.0)
    t.inp("Seed", "FLOAT", 0.0)
    t.out("A", "VECTOR")
    t.out("B", "VECTOR")
    t.out("Blend", "FLOAT")
    p = t.vmath("ADD", t.I("Vector"), t.comb(t.I("Seed"), t.mul(t.I("Seed"), 0.37), t.mul(t.I("Seed"), 0.71)))
    scale = t.div(1.0, t.max(t.I("Cell"), 0.1))
    outs = []
    for feature in ("F1", "F2"):
        v = t.node("ShaderNodeTexVoronoi", props={"feature": feature, "voronoi_dimensions": "3D"},
                   Vector=p, Scale=scale, Randomness=1.0)
        col = t.outp(v, "Color")
        rot = t.node("ShaderNodeVectorRotate", props={"rotation_type": "EULER_XYZ"}, Vector=t.I("Vector"),
                     Rotation=t.vmath("SCALE", col, scale=2 * math.pi))
        outs.append((t.vmath("ADD", t.outp(rot), t.vmath("SCALE", col, scale=37.0)), t.outp(v, "Distance")))
    (a, d1), (b, d2) = outs
    t.O("A", a)
    t.O("B", b)
    t.O("Blend", t.mul(t.sub(1.0, t.maprange(t.sub(d2, d1), 0.0, 0.15, interp="SMOOTHSTEP")), 0.5))
    t.layout()
    return t.t

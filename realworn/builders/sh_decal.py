"""Builds the projector-decal groups (DEC-1..DEC-4).

RW_DecalProject: Texture Coordinate > Object of the decal Empty -> UV and a unit-box mask.
RW_L_Decal: composites one decal over the accumulated decal channels that feed RW_Stack.
Each material chains one RW_L_Decal per decal; the chain's result enters the stack after
edge wear and before dirt (DEC-2), so dirt, dust, wetness and puddles all apply on top.
"""

from ..core import naming
from ._dsl import Tree

ACC = (  # accumulated decal channels: (name, type, default)
    ("Color", "COLOR", (0.0, 0.0, 0.0)),
    ("Alpha", "FLOAT", 0.0),
    ("Roughness", "FLOAT", 0.5),
    ("Rough Alpha", "FLOAT", 0.0),
    ("Darken", "FLOAT", 0.0),
    ("Damage", "FLOAT", 0.0),
    ("Height", "FLOAT", 0.0),
    ("Normal", "VECTOR", None),
    ("Normal Alpha", "FLOAT", 0.0),
)


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


def build_layer():
    t = Tree.new_group(naming.SH_DECAL, "SHADER")
    for name, st, default in ACC:
        if st == "VECTOR":
            t.inp(name, st, hide_value=True)
        else:
            t.inp(name, st, default)
    t.inp("Image Color", "COLOR", (1.0, 1.0, 1.0))
    t.inp("Image Alpha", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Box", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Projection Normal", "VECTOR", (0.0, 0.0, 1.0), description="World direction the decal faces (Empty +Z)")
    t.inp("Mode", "FLOAT", 0.0, 0.0, 2.0, description="0 Full, 1 Grime (channel-only), 2 Damage")
    t.inp("Opacity", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Decal Roughness", "FLOAT", 0.45, 0.0, 1.0)
    t.inp("Normal Map", "COLOR", (0.5, 0.5, 1.0), description="Optional name_nrm.png")
    t.inp("Has Normal", "FLOAT", 0.0, 0.0, 1.0)
    for name, st, _ in ACC:
        t.out(name, "COLOR" if st == "COLOR" else st)

    geo = t.node("ShaderNodeNewGeometry")
    facing = t.vmath("DOT_PRODUCT", t.outp(geo, "Normal"), t.vmath("NORMALIZE", t.I("Projection Normal")))
    fade = t.smooth(facing, 0.45, 0.6)  # DEC-3: about 60 degrees cut-off, no stretched pixels
    a = t.clamp(t.mul_all(t.I("Image Alpha"), t.I("Box"), fade, t.I("Opacity")))
    mode = t.I("Mode")
    full = t.math("COMPARE", mode, 0.0, 0.5)
    grime = t.math("COMPARE", mode, 1.0, 0.5)
    damage = t.math("COMPARE", mode, 2.0, 0.5)

    af = t.mul(a, full)
    t.O("Color", t.mix(af, t.I("Color"), t.I("Image Color")))
    t.O("Alpha", t.add(af, t.mul(t.I("Alpha"), t.inv(af))))
    ar = t.mul(a, t.add(full, grime))
    grime_rough = t.mixf(t.lum(t.I("Image Color")), 0.95, t.I("Decal Roughness"))
    t.O("Roughness", t.mixf(ar, t.I("Roughness"), t.mixf(grime, t.I("Decal Roughness"), grime_rough)))
    t.O("Rough Alpha", t.max(t.I("Rough Alpha"), ar))
    t.O("Darken", t.max(t.I("Darken"), t.mul(a, grime)))
    t.O("Damage", t.max(t.I("Damage"), t.mul(a, damage)))
    t.O("Height", t.sub(t.I("Height"), t.mul_all(a, damage, 0.002)))
    nm = t.node("ShaderNodeNormalMap", 1.0, t.I("Normal Map"))
    an = t.mul_all(a, t.I("Has Normal"), t.inv(grime))
    t.O("Normal", t.mixv(an, t.I("Normal"), t.outp(nm)))
    t.O("Normal Alpha", t.max(t.I("Normal Alpha"), an))
    t.layout()
    return t.t


def build():
    return [build_project(), build_layer()]

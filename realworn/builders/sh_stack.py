"""Builds RW_Stack: the channel-mode layer stack inserted in front of each Principled BSDF.

The user's Base Color, Metallic, Roughness, Normal and Coat channels flow in, get weathered
by the layers below in physical order, and flow back out into the same Principled BSDF:

1 Base  2 Edge wear  3 Rust  (decals, DEC-2)  4 Cavity dirt  5 Contact/splash grime
6 Dust  7 Paint override (rw_paint R adds wear, B removes 2-6)
(v2 P0: wetness, rain, puddles and shelter removed; coat channels pass through.)

Scene sliders come from Attribute (View Layer) nodes, per-object values from Attribute
(Object) nodes, masks from Attribute (Geometry) nodes. Preset values are the inputs of
each material's RW_Stack instance, so one shared group serves every material.
"""

import bpy

from ..core import naming
from ._dsl import Tree

# (name, socket type, default, min, max, description) for preset-driven inputs.
PRESET_INPUTS = (
    ("Edge Wear", "FLOAT", 0.8, 0.0, 3.0, "Edge wear strength"),
    ("Underlayer Color", "COLOR", (0.55, 0.55, 0.56), None, None, "Revealed by deep chips"),
    ("Underlayer Roughness", "FLOAT", 0.35, 0.0, 1.0, ""),
    ("Underlayer Metallic", "FLOAT", 1.0, 0.0, 1.0, ""),
    ("Primer Color", "COLOR", (0.32, 0.18, 0.12), None, None, "Revealed at the rim of chips"),
    ("Primer Width", "FLOAT", 0.12, 0.0, 1.0, "0 disables the primer ring"),
    ("Chip Sharpness", "FLOAT", 0.85, 0.0, 1.0, "Crisp (1) or soft (0) wear boundary"),
    ("Chip Bump", "FLOAT", 0.002, 0.0, 0.05, "Paint thickness step at the chip boundary (m)"),
    ("Polish", "FLOAT", 0.0, 0.0, 1.0, "1: edges polish instead of chipping (bare metal)"),
    ("Rust", "FLOAT", 0.4, 0.0, 3.0, "Rust strength; 0 for non-metal presets"),
    ("Rust Color", "COLOR", (0.30, 0.11, 0.035), None, None, ""),
    ("Cavity Dirt", "FLOAT", 0.7, 0.0, 3.0, ""),
    ("Dirt Color", "COLOR", (0.05, 0.045, 0.04), None, None, ""),
    ("Grime", "FLOAT", 0.5, 0.0, 3.0, "Contact and splash grime"),
    ("Grime Color", "COLOR", (0.12, 0.10, 0.075), None, None, ""),
    ("Dust", "FLOAT", 0.3, 0.0, 3.0, ""),
    ("Dust Color", "COLOR", (0.55, 0.52, 0.48), None, None, ""),
    ("Streaks", "FLOAT", 0.3, 0.0, 3.0, "Dirty streaks running down vertical faces"),
    ("Breakup Scale", "FLOAT", 1.0, 0.05, 20.0, "Scale of the breakup noise"),
)

CHANNEL_INPUTS = (
    ("Base Color", "COLOR", (0.8, 0.8, 0.8)),
    ("Metallic", "FLOAT", 0.0),
    ("Roughness", "FLOAT", 0.5),
    ("Normal", "VECTOR", None),
    ("Coat Weight", "FLOAT", 0.0),
    ("Coat Roughness", "FLOAT", 0.03),
    ("Coat IOR", "FLOAT", 1.5),
    ("Coat Normal", "VECTOR", None),
)


def _grp(t, name, node_name=None, **inputs):
    return t.node("ShaderNodeGroup", props={"node_tree": bpy.data.node_groups[name]}, label=name, name=node_name,
                  **inputs)


def build():
    t = Tree.new_group(naming.SH_STACK, "SHADER")
    t.t.description = "RealWorn layer stack (channel mode)"
    for name, st, default in CHANNEL_INPUTS:
        if st == "VECTOR":
            t.inp(name, st, hide_value=True)
        else:
            t.inp(name, st, default, 0.0 if st == "FLOAT" else None, 1.0 if name != "Coat IOR" and st == "FLOAT" else None)
    t.inp("Surface Height", "FLOAT", 0.5, description="Material height/displacement texture")
    t.inp("Has Surface Height", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Attr Edge Weight", "FLOAT", 1.0, 0.0, 1.0, description="0 when the edge source is Bevel only")
    t.inp("Extra Edge", "FLOAT", 0.0, 0.0, 1.0, description="Bevel node edge source (Cycles)")
    t.inp("Attr Cavity Weight", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Extra Cavity", "FLOAT", 0.0, 0.0, 1.0, description="Raycast cavity source")
    t.inp("Decal Color", "COLOR", (0.0, 0.0, 0.0))
    t.inp("Decal Alpha", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Decal Rough Alpha", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Darken", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Damage", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Height", "FLOAT", 0.0)
    t.inp("Decal Normal", "VECTOR", hide_value=True)
    t.inp("Decal Normal Alpha", "FLOAT", 0.0, 0.0, 1.0)
    for name, st, default, lo, hi, desc in PRESET_INPUTS:
        t.inp(name, st, default, lo, hi, description=desc)
    for name, st, _ in CHANNEL_INPUTS:
        t.out(name, "COLOR" if st == "COLOR" else st)
    t.out("Height", "FLOAT")
    t.out("Preview", "FLOAT")
    t.out("Coverage", "FLOAT")

    # ---- inputs from the scene, the object and the mesh (no drivers)
    scene = {k: t.attr(k, "VIEW_LAYER") for k in naming.SCENE_PROPS}
    ob = {k: t.attr(k, "OBJECT") for k in naming.OBJECT_PROPS}
    geo = {k: t.attr(k, "GEOMETRY") for k in naming.MASK_ATTRS + (naming.ATTR_DAMAGE,)}
    paint = t.node("ShaderNodeSeparateColor", t.attr(naming.ATTR_PAINT, "GEOMETRY", out="Color"))
    p_add, p_rem = t.outp(paint, "Red"), t.outp(paint, "Blue")
    keep = t.inv(p_rem)

    edge = t.max_all(t.mul(geo[naming.ATTR_EDGE], t.I("Attr Edge Weight")), t.I("Extra Edge"),
                     t.I("Decal Damage"), t.mul(geo[naming.ATTR_DAMAGE], 0.6))
    cavity = t.max(t.mul(geo[naming.ATTR_CAVITY], t.I("Attr Cavity Weight")), t.I("Extra Cavity"))

    brk = _grp(t, naming.SH_BREAKUP, Seed=ob[naming.OB_SEED], Scale=t.I("Breakup Scale"))
    sm = _grp(t, naming.SH_SHADING_MASKS, Ground_Z=scene[naming.SC_GROUND_Z],
              Splash_Height=scene[naming.SC_SPLASH], Seed=ob[naming.OB_SEED])
    large, fine, comb = t.outp(brk, "Large"), t.outp(brk, "Fine"), t.outp(brk, "Combined")
    age, dirt = scene[naming.SC_AGE], scene[naming.SC_DIRT]
    dirt_amt = t.mul(dirt, ob[naming.OB_DIRT])

    # ---- 2 edge wear
    wear_amount = t.mul_all(t.I("Edge Wear"), ob[naming.OB_WEAR], t.add(0.35, t.mul(age, 0.65)))
    l2 = _grp(t, naming.SH_L_EDGE, Color=t.I("Base Color"), Roughness=t.I("Roughness"), Metallic=t.I("Metallic"),
              Height=0.0, Edge=edge, Breakup=comb, Micro=t.outp(brk, "Micro"), Large=large, Amount=wear_amount, Paint_Add=p_add, Paint_Remove=p_rem,
              Underlayer_Color=t.I("Underlayer Color"), Underlayer_Roughness=t.I("Underlayer Roughness"),
              Underlayer_Metallic=t.I("Underlayer Metallic"), Primer_Color=t.I("Primer Color"),
              Primer_Width=t.I("Primer Width"), Sharpness=t.I("Chip Sharpness"), Chip_Bump=t.I("Chip Bump"),
              Polish=t.I("Polish"))
    # ---- 3 rust
    rust_amount = t.mul_all(t.I("Rust"), t.pow(age, 1.5), 1.6, keep)
    l3 = _grp(t, naming.SH_L_RUST, Color=t.outp(l2, "Color"), Roughness=t.outp(l2, "Roughness"),
              Metallic=t.outp(l2, "Metallic"), Height=t.outp(l2, "Height"), Chip=t.outp(l2, "Chip"),
              Cavity=cavity, Breakup=fine, Amount=rust_amount, Rust_Color=t.I("Rust Color"))
    # ---- decals (DEC-2: after base and edge wear, before dirt)
    ld = _grp(t, naming.SH_L_DECALS, Color=t.outp(l3, "Color"), Roughness=t.outp(l3, "Roughness"),
              Metallic=t.outp(l3, "Metallic"), Height=t.outp(l3, "Height"), Decal_Color=t.I("Decal Color"),
              Decal_Alpha=t.I("Decal Alpha"), Decal_Roughness=t.I("Decal Roughness"),
              Decal_Rough_Alpha=t.I("Decal Rough Alpha"), Decal_Darken=t.I("Decal Darken"),
              Decal_Height=t.I("Decal Height"))
    # ---- 4 cavity dirt
    l4 = _grp(t, naming.SH_L_CAVITY, Color=t.outp(ld, "Color"), Roughness=t.outp(ld, "Roughness"),
              Metallic=t.outp(ld, "Metallic"), Height=t.outp(ld, "Height"), Cavity=cavity, Breakup=comb,
              Amount=t.mul_all(t.I("Cavity Dirt"), dirt_amt, 2.0, keep), Dirt_Color=t.I("Dirt Color"))
    # ---- 5 contact and splash grime, streaks
    l5 = _grp(t, naming.SH_L_GRIME, Color=t.outp(l4, "Color"), Roughness=t.outp(l4, "Roughness"),
              Metallic=t.outp(l4, "Metallic"), Height=t.outp(l4, "Height"), Contact=geo[naming.ATTR_CONTACT],
              Splash=t.outp(sm, "Height"), Streak=t.outp(sm, "Streak"), Up=t.outp(sm, "Up"),
              Is_Ground=ob[naming.OB_GROUND], Breakup=comb,
              Amount=t.mul_all(t.I("Grime"), dirt_amt, 1.6, keep),
              Streak_Amount=t.mul_all(t.I("Streaks"), t.add(age, dirt), keep), Grime_Color=t.I("Grime Color"))
    # ---- 6 dust
    l6 = _grp(t, naming.SH_L_DUST, Color=t.outp(l5, "Color"), Roughness=t.outp(l5, "Roughness"),
              Metallic=t.outp(l5, "Metallic"), Height=t.outp(l5, "Height"), Up=t.outp(sm, "Up"), Breakup=large,
              Shelter=0.0, Wet=0.0, Amount=t.mul_all(t.I("Dust"), scene[naming.SC_DUST], 1.6, keep),
              Dust_Color=t.I("Dust Color"))

    # ---- height -> bump on top of the user's own normal (normal maps survive).
    # Only chips and decals add relief: Cycles evaluates a Bump's height subtree three
    # times, so keeping it small matters (rust/dirt relief was too small to see anyway).
    height = t.add(t.outp(l2, "Height"), t.I("Decal Height"))
    base_normal = t.mixv(t.I("Decal Normal Alpha"), t.I("Normal"), t.I("Decal Normal"))
    bump = t.node("ShaderNodeBump", 1.0, 1.0, Height=height, Normal=base_normal)

    t.O("Base Color", t.outp(l6, "Color"))
    t.O("Roughness", t.outp(l6, "Roughness"))
    t.O("Metallic", t.outp(l6, "Metallic"))
    t.O("Normal", t.outp(bump))
    for name in ("Coat Weight", "Coat Roughness", "Coat IOR", "Coat Normal"):
        t.O(name, t.I(name))
    t.O("Height", height)

    # ---- Mask Preview (scene rw_preview selects; no recompile when switching)
    sel = scene[naming.SC_PREVIEW]
    prev = None
    for code, val in ((1, edge), (2, cavity), (3, geo[naming.ATTR_CONTACT]), (7, t.outp(l6, "Mask")),
                      (8, t.outp(l5, "Grime")), (9, t.outp(t.node("ShaderNodeMath", t.outp(sm, "Streak"), 0.0,
                                                                   props={"operation": "ADD"})))):
        term = t.mul(t.math("COMPARE", sel, float(code), 0.5), val)
        prev = term if prev is None else t.add(prev, term)
    t.O("Preview", prev)
    t.O("Coverage", t.max_all(t.outp(l2, "Mask"), t.outp(l3, "Mask"), t.outp(ld, "Mask"), t.outp(l4, "Mask"),
                              t.outp(l5, "Mask"), t.outp(l6, "Mask")))
    t.layout(dx=260, dy=150)
    return [t.t]

"""Shader layer groups used inside RW_Stack.

Every layer shares one interface: channels in (Color, Roughness, Metallic, Height),
a mask and parameters in, channels out (plus the layer's final mask). Adding a layer
means writing one builder here and inserting it in sh_stack.py.
"""

from ..core import naming
from ._dsl import Tree


def _channels_in(t):
    t.inp("Color", "COLOR", (0.5, 0.5, 0.5))
    t.inp("Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Metallic", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Height", "FLOAT", 0.0)


def _channels_out(t, mask=True):
    t.out("Color", "COLOR")
    t.out("Roughness", "FLOAT")
    t.out("Metallic", "FLOAT")
    t.out("Height", "FLOAT")
    if mask:
        t.out("Mask", "FLOAT")


# ----------------------------------------------------------------- utilities
def build_breakup():
    """Two noises (large patches, fine grunge) offset by the per-object seed."""
    t = Tree.new_group(naming.SH_BREAKUP, "SHADER")
    t.inp("Seed", "FLOAT", 0.0)
    t.inp("Scale", "FLOAT", 1.0, 0.01, 100.0)
    t.out("Large", "FLOAT")
    t.out("Fine", "FLOAT")
    t.out("Combined", "FLOAT")
    t.out("Micro", "FLOAT")
    tc = t.node("ShaderNodeTexCoord")
    seed = t.I("Seed")
    offset = t.comb(t.mul(seed, 1.37), t.mul(seed, 2.11), t.mul(seed, 0.73))
    co = t.vmath("ADD", t.outp(tc, "Object"), offset)
    large = t.maprange(t.noise(co, t.mul(t.I("Scale"), 1.2), detail=1.0, roughness=0.5), 0.32, 0.68)
    fine = t.maprange(t.noise(co, t.mul(t.I("Scale"), 9.0), detail=3.0, roughness=0.65), 0.25, 0.75)
    t.O("Large", large)
    t.O("Fine", fine)
    t.O("Combined", t.clamp(t.add(t.mul(large, 0.65), t.mul(fine, 0.55))))
    micro = t.maprange(t.noise(co, t.mul(t.I("Scale"), 38.0), detail=2.0, roughness=0.7), 0.3, 0.7)
    t.O("Micro", micro)
    t.layout()
    return t.t


def build_shading_masks():
    """Masks that depend only on the shading point: Up, Flat, Height above ground, Streak."""
    t = Tree.new_group(naming.SH_SHADING_MASKS, "SHADER")
    t.inp("Ground Z", "FLOAT", 0.0)
    t.inp("Splash Height", "FLOAT", 0.4)
    t.inp("Seed", "FLOAT", 0.0)
    t.out("Up", "FLOAT")
    t.out("Flat", "FLOAT")
    t.out("Height", "FLOAT")
    t.out("Vertical", "FLOAT")
    t.out("Streak", "FLOAT")
    t.out("Normal Z", "FLOAT")
    geo = t.node("ShaderNodeNewGeometry")
    _, _, nz = t.sep(t.outp(geo, "Normal"))
    _, _, pz = t.sep(t.outp(geo, "Position"))
    t.O("Normal Z", nz)
    t.O("Up", t.smooth(nz, 0.5, 0.95))
    t.O("Flat", t.smooth(nz, 0.9, 0.94))
    above = t.sub(pz, t.I("Ground Z"))
    t.O("Height", t.inv(t.div(above, t.max(t.I("Splash Height"), 1e-4))))
    vertical = t.inv(t.smooth(t.math("ABSOLUTE", nz), 0.2, 0.35))
    t.O("Vertical", vertical)
    # rain streaks / rust runs: noise stretched along world Z on vertical faces
    tc = t.node("ShaderNodeTexCoord")
    ox, oy, oz = t.sep(t.outp(tc, "Object"))
    s = t.I("Seed")
    stretched = t.comb(t.add(t.mul(ox, 2.5), s), t.add(t.mul(oy, 2.5), s), t.mul(oz, 0.22))
    streak = t.smooth(t.noise(stretched, 2.5, detail=2.0, roughness=0.6, distortion=0.15), 0.55, 0.75)
    t.O("Streak", t.mul(streak, vertical))
    t.layout()
    return t.t


def build_bevel_edge():
    """Cycles-only edge source: Bevel node normal vs true normal (MASK-7)."""
    t = Tree.new_group(naming.SH_BEVEL_EDGE, "SHADER")
    t.inp("Radius", "FLOAT", 0.01, 0.0, 1.0, subtype="DISTANCE")
    t.out("Edge", "FLOAT")
    geo = t.node("ShaderNodeNewGeometry")
    bev = t.node("ShaderNodeBevel", t.I("Radius"))
    d = t.vmath("DOT_PRODUCT", t.outp(bev), t.outp(geo, "Normal"))
    t.O("Edge", t.clamp(t.mul(t.sub(1.0, d), 12.0)))
    t.layout()
    return t.t


def build_ray_cavity():
    """Live cavity from four shader Raycast rays (M0 spike c: works in Cycles and EEVEE)."""
    t = Tree.new_group(naming.SH_RAY_CAVITY, "SHADER")
    t.inp("Distance", "FLOAT", 0.08, 0.0, 10.0, subtype="DISTANCE")
    t.out("Cavity", "FLOAT")
    geo = t.node("ShaderNodeNewGeometry")
    n = t.outp(geo, "Normal")
    start = t.vmath("ADD", t.outp(geo, "Position"), t.vmath("SCALE", n, scale=0.001))
    acc = None
    for d in ((0.6, 0.6, 0.6), (0.6, -0.6, -0.6), (-0.6, 0.6, -0.6), (-0.6, -0.6, 0.6)):
        direction = t.vmath("NORMALIZE", t.vmath("ADD", n, d))
        ray = t.node("ShaderNodeRaycast", Position=start, Direction=direction, Length=t.I("Distance"))
        hit = t.outp(ray, "Is Hit")
        acc = hit if acc is None else t.add(acc, hit)
    t.O("Cavity", t.clamp(t.mul(acc, 0.35)))
    t.layout()
    return t.t


# -------------------------------------------------------------------- layers
def build_edge_wear():
    """Layer 2: chipped paint revealing primer then the underlayer, or polish (bare metal)."""
    t = Tree.new_group(naming.SH_L_EDGE, "SHADER")
    _channels_in(t)
    t.inp("Edge", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Breakup", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Micro", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Large", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.5, 0.0, 3.0)
    t.inp("Paint Add", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Paint Remove", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Underlayer Color", "COLOR", (0.55, 0.55, 0.56))
    t.inp("Underlayer Roughness", "FLOAT", 0.35, 0.0, 1.0)
    t.inp("Underlayer Metallic", "FLOAT", 1.0, 0.0, 1.0)
    t.inp("Primer Color", "COLOR", (0.32, 0.18, 0.12))
    t.inp("Primer Width", "FLOAT", 0.12, 0.0, 1.0)
    t.inp("Sharpness", "FLOAT", 0.85, 0.0, 1.0)
    t.inp("Chip Bump", "FLOAT", 0.002, 0.0, 0.05, subtype="DISTANCE")
    t.inp("Polish", "FLOAT", 0.0, 0.0, 1.0)
    _channels_out(t)
    t.out("Chip", "FLOAT")

    col, rough, metal, height = t.I("Color"), t.I("Roughness"), t.I("Metallic"), t.I("Height")
    # wear spreads further from the edge as Amount grows, then is broken up by two noises
    spread = t.pow(t.clamp(t.I("Edge")), t.div(1.0, t.add(1.0, t.mul(t.I("Amount"), 1.5))))
    v = t.mul(spread, t.add(0.3, t.add(t.mul(t.I("Breakup"), 0.6), t.mul(t.I("Micro"), 0.6))))  # height-blended
    v = t.mul(v, t.add(0.55, t.mul(t.I("Large"), 0.9)))  # some edges barely chip, others heavily
    thr = t.max(t.sub(1.15, t.mul(t.I("Amount"), 0.85)), 0.05)
    soft = t.add(t.mul(t.inv(t.I("Sharpness")), 0.2), 0.01)
    keep = t.inv(t.I("Paint Remove"))
    chip = t.mul(t.clamp(t.add(t.maprange(v, t.sub(thr, soft), t.add(thr, soft)), t.I("Paint Add"))), keep)
    pthr = t.sub(thr, t.I("Primer Width"))
    outer = t.mul(t.clamp(t.add(t.maprange(v, t.sub(pthr, soft), t.add(pthr, soft)), t.I("Paint Add"))), keep)

    # chipped: paint -> primer (outer ring) -> underlayer (inner)
    c_chip = t.mix(chip, t.mix(outer, col, t.I("Primer Color")), t.I("Underlayer Color"))
    r_chip = t.mixf(chip, t.mixf(outer, rough, 0.6), t.I("Underlayer Roughness"))
    m_chip = t.mixf(chip, t.mixf(outer, metal, 0.0), t.I("Underlayer Metallic"))
    h_chip = t.sub(height, t.mul(t.I("Chip Bump"), t.add(outer, t.mul(chip, 0.5))))

    # polished: broad band, brighter and smoother, no height step
    pol = t.mul(t.clamp(t.add(t.maprange(v, t.sub(thr, 0.3), t.add(thr, 0.1)), t.I("Paint Add"))), keep)
    c_pol = t.mix(pol, col, t.mix(0.25, col, (1.0, 1.0, 1.0)))
    r_pol = t.mixf(pol, rough, t.mul(rough, 0.35))

    p = t.I("Polish")
    t.O("Color", t.mix(p, c_chip, c_pol))
    t.O("Roughness", t.mixf(p, r_chip, r_pol))
    t.O("Metallic", t.mixf(p, m_chip, metal))
    t.O("Height", t.mixf(p, h_chip, height))
    t.O("Mask", t.mixf(p, outer, pol))
    t.O("Chip", t.mixf(p, chip, pol))
    t.layout()
    return t.t


def build_rust():
    """Layer 3: rust grows from revealed metal and cavities, scaled by age (metal presets)."""
    t = Tree.new_group(naming.SH_L_RUST, "SHADER")
    _channels_in(t)
    t.inp("Chip", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Cavity", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Breakup", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.0, 0.0, 3.0)
    t.inp("Rust Color", "COLOR", (0.30, 0.11, 0.035))
    _channels_out(t)
    src = t.add(t.mul(t.I("Chip"), 0.8), t.mul(t.I("Cavity"), 0.5))
    raw = t.mul_all(src, t.add(0.3, t.mul(t.I("Breakup"), 1.2)), t.I("Amount"))
    m = t.smooth(raw, 0.25, 0.65)
    rust = t.mix(t.I("Breakup"), t.I("Rust Color"), t.mix(0.5, t.I("Rust Color"), (0.0, 0.0, 0.0)))
    t.O("Color", t.mix(m, t.I("Color"), rust))
    t.O("Roughness", t.mixf(m, t.I("Roughness"), 0.88))
    t.O("Metallic", t.mixf(m, t.I("Metallic"), 0.0))
    t.O("Height", t.add(t.I("Height"), t.mul(m, 0.0008)))
    t.O("Mask", m)
    t.layout()
    return t.t


def build_decal_apply():
    """Decal composite (built by the RW_L_Decal chain) applied after edge wear (DEC-2)."""
    t = Tree.new_group(naming.SH_L_DECALS, "SHADER")
    _channels_in(t)
    t.inp("Decal Color", "COLOR", (0.0, 0.0, 0.0))
    t.inp("Decal Alpha", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Decal Rough Alpha", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Darken", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Decal Height", "FLOAT", 0.0)
    _channels_out(t)
    a = t.I("Decal Alpha")
    c = t.mix(a, t.I("Color"), t.I("Decal Color"))
    dk = t.I("Decal Darken")
    c = t.mix(t.mul(dk, 0.75), c, (0.0, 0.0, 0.0))
    r = t.mixf(t.I("Decal Rough Alpha"), t.I("Roughness"), t.I("Decal Roughness"))
    r = t.mixf(t.mul(dk, 0.35), r, 0.92)
    t.O("Color", c)
    t.O("Roughness", r)
    t.O("Metallic", t.mixf(a, t.I("Metallic"), 0.0))
    t.O("Height", t.add(t.I("Height"), t.I("Decal Height")))
    t.O("Mask", t.max(a, dk))
    t.layout()
    return t.t


def build_cavity_dirt():
    """Layer 4: dark, rough, non-metallic dirt in concave areas."""
    t = Tree.new_group(naming.SH_L_CAVITY, "SHADER")
    _channels_in(t)
    t.inp("Cavity", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Breakup", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.5, 0.0, 4.0)
    t.inp("Dirt Color", "COLOR", (0.05, 0.045, 0.04))
    _channels_out(t)
    m = t.mul(t.smooth(t.mul(t.I("Cavity"), t.add(0.5, t.I("Breakup"))), 0.2, 0.8), t.I("Amount"))
    m = t.clamp(m)
    t.O("Color", t.mix(m, t.I("Color"), t.I("Dirt Color")))
    t.O("Roughness", t.mixf(m, t.I("Roughness"), 0.92))
    t.O("Metallic", t.mixf(m, t.I("Metallic"), 0.0))
    t.O("Height", t.add(t.I("Height"), t.mul(m, 0.0004)))
    t.O("Mask", m)
    t.layout()
    return t.t


def build_grime():
    """Layer 5: contact and splash grime near the ground, plus dirty streaks on walls."""
    t = Tree.new_group(naming.SH_L_GRIME, "SHADER")
    _channels_in(t)
    t.inp("Contact", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Splash", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Streak", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Up", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Is Ground", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Breakup", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.5, 0.0, 4.0)
    t.inp("Streak Amount", "FLOAT", 0.0, 0.0, 4.0)
    t.inp("Grime Color", "COLOR", (0.12, 0.10, 0.075))
    _channels_out(t)
    splash = t.mul_all(t.pow(t.clamp(t.I("Splash")), 1.5), t.inv(t.mul(t.I("Up"), 0.8)), t.inv(t.I("Is Ground")))
    base = t.max(t.I("Contact"), splash)
    m = t.clamp(t.mul_all(base, t.add(0.35, t.mul(t.I("Breakup"), 0.9)), t.I("Amount")))
    sm = t.clamp(t.mul_all(t.I("Streak"), t.I("Streak Amount"), 0.6))
    c = t.mix(m, t.I("Color"), t.I("Grime Color"))
    c = t.mix(t.mul(sm, 0.5), c, (0.0, 0.0, 0.0))
    t.O("Color", c)
    t.O("Roughness", t.mixf(m, t.I("Roughness"), 0.9))
    t.O("Metallic", t.mixf(m, t.I("Metallic"), 0.0))
    t.O("Height", t.I("Height"))
    t.O("Mask", t.max(m, sm))
    t.layout()
    return t.t


def build_dust():
    """Layer 6: light desaturated dust on up-facing, dry, unsheltered surfaces (WX-10)."""
    t = Tree.new_group(naming.SH_L_DUST, "SHADER")
    _channels_in(t)
    t.inp("Up", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Breakup", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Shelter", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Wet", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Amount", "FLOAT", 0.3, 0.0, 4.0)
    t.inp("Dust Color", "COLOR", (0.55, 0.52, 0.48))
    _channels_out(t)
    raw = t.mul_all(t.I("Up"), t.add(0.25, t.I("Breakup")), t.I("Amount"),
                    t.inv(t.mul(t.I("Shelter"), 0.6)), t.inv(t.I("Wet")))
    m = t.smooth(raw, 0.1, 0.7)
    t.O("Color", t.mix(m, t.I("Color"), t.I("Dust Color")))
    t.O("Roughness", t.mixf(m, t.I("Roughness"), 0.95))
    t.O("Metallic", t.mixf(m, t.I("Metallic"), 0.0))
    t.O("Height", t.I("Height"))
    t.O("Mask", m)
    t.layout()
    return t.t


def build():
    return [build_breakup(), build_shading_masks(), build_bevel_edge(), build_ray_cavity(),
            build_edge_wear(), build_rust(), build_decal_apply(), build_cavity_dirt(),
            build_grime(), build_dust()]

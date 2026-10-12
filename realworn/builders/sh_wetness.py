"""Builds RW_L_Wetness: porosity darkening, clear coat at IOR 1.33, puddles, ripples.

w = clamp(wetness * (1 - shelter) * (1 - paint_G) + streak * rain)
color_wet = color * lerp(1, 0.2, (1 - metallic) * porosity * w)
States: damp (w < 0.35) rough x0.85, coat w, coat rough 0.25; wet (0.35..0.7) rough x0.6,
coat 1, coat rough 0.08; puddle: rough 0.3, coat 1, coat rough 0.01, base bump flattened,
ripples on the coat normal only (WX-1..WX-12).
The only driver in RealWorn lives here: RW::time = frame / 24 (WX-8), shared by every material.
"""

from ..core import naming
from ._dsl import Tree

TIME_NODE = "RW::time"


def _interface(t):
    t.inp("Color", "COLOR", (0.5, 0.5, 0.5))
    t.inp("Roughness", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Metallic", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Normal", "VECTOR", hide_value=True)
    t.inp("Coat Weight", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Coat Roughness", "FLOAT", 0.03, 0.0, 1.0)
    t.inp("Coat IOR", "FLOAT", 1.5, 1.0, 4.0)
    t.inp("Coat Normal", "VECTOR", hide_value=True)
    t.inp("Wetness", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Rain", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Shelter", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Keep Dry", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Porosity", "FLOAT", 0.3, 0.0, 1.0)
    t.inp("Streak", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Is Ground", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Normal Z", "FLOAT", 0.0, -1.0, 1.0)
    t.inp("Splash", "FLOAT", 0.0, 0.0, 1.0)
    t.inp("Puddle Height", "FLOAT", 0.5, 0.0, 1.0)
    t.inp("Puddle Edge", "FLOAT", 0.05, 0.001, 0.5)
    for name in ("Color", "Roughness", "Metallic"):
        t.out(name, "COLOR" if name == "Color" else "FLOAT")
    t.out("Normal", "VECTOR")
    t.out("Coat Weight", "FLOAT")
    t.out("Coat Roughness", "FLOAT")
    t.out("Coat IOR", "FLOAT")
    t.out("Coat Normal", "VECTOR")
    t.out("W", "FLOAT")
    t.out("Puddle", "FLOAT")


def build_dry():
    """Same interface, passes channels through. RW_Stack uses it while no scene is wet or
    raining, which removes ~110 nodes from every material's shader (Cycles cost is roughly
    linear in node count)."""
    t = Tree.new_group(naming.SH_L_WET_DRY, "SHADER")
    _interface(t)
    for name in ("Color", "Roughness", "Metallic", "Normal", "Coat Weight", "Coat Roughness", "Coat IOR",
                 "Coat Normal"):
        t.O(name, t.I(name))
    t.go.inputs["W"].default_value = 0.0
    t.go.inputs["Puddle"].default_value = 0.0
    t.layout()
    return t.t


def build():
    t = Tree.new_group(naming.SH_L_WET, "SHADER")
    _interface(t)
    wet, rain, shel, dry = t.I("Wetness"), t.I("Rain"), t.I("Shelter"), t.I("Keep Dry")
    metal, poro = t.I("Metallic"), t.I("Porosity")
    w = t.clamp(t.add(t.mul_all(wet, t.inv(shel), t.inv(dry)), t.mul_all(t.I("Streak"), rain, 0.8)))

    # WX-12 moisture climb: porous walls darken in the splash band whenever it is wet at all
    climb = t.mul_all(t.clamp(t.I("Splash")), t.inv(t.I("Is Ground")), t.clamp(t.mul(wet, 3.0)),
                      t.inv(shel), t.inv(dry))
    wdark = t.max(w, climb)
    dark_f = t.mul_all(t.inv(metal), poro, wdark)
    col = t.mix(dark_f, t.I("Color"), t.mix(0.8, t.I("Color"), (0.0, 0.0, 0.0)), label="porosity darkening")

    # roughness: damp x0.85 (by w=0.2), wet x0.6 (w 0.35 -> 0.7)
    f = t.sub(t.sub(1.0, t.mul(t.clamp(t.div(w, 0.2)), 0.15)), t.mul(t.maprange(w, 0.35, 0.7), 0.25))
    rough = t.mul(t.I("Roughness"), f)

    coat_w = t.clamp(t.div(w, 0.35))
    any_wet = t.clamp(t.mul(w, 1000.0))
    cr_wet = t.mixf(t.maprange(w, 0.35, 0.7), 0.25, 0.08)
    coat_r = t.mixf(any_wet, t.I("Coat Roughness"), t.min(t.I("Coat Roughness"), cr_wet))
    coat_ior = t.mixf(coat_w, t.I("Coat IOR"), 1.33)
    coat_weight = t.max(t.I("Coat Weight"), coat_w)

    # Puddles (WX-1..WX-6): ground objects, near-flat, unsheltered, not kept dry, low areas first
    flat = t.smooth(t.I("Normal Z"), 0.9, 0.94)
    elig = t.mul_all(t.I("Is Ground"), flat, t.inv(shel), t.inv(dry))
    level = t.maprange(wet, 0.6, 1.0)
    d = t.sub(level, t.I("Puddle Height"))
    edge = t.I("Puddle Edge")
    puddle = t.mul(elig, t.maprange(d, 0.0, edge, interp="SMOOTHSTEP"))
    depth = t.clamp(t.mul(d, 4.0))
    ring = t.mul_all(elig, t.maprange(d, t.mul(edge, -1.2), 0.0, interp="SMOOTHSTEP"), t.inv(puddle),
                     t.clamp(t.mul(level, 50.0)))

    col = t.mix(t.mul(ring, 0.35), col, (0.0, 0.0, 0.0), label="mud ring")
    mud = t.mix(1.0, col, (0.85, 0.80, 0.72), blend="MULTIPLY")
    mud = t.mix(t.mul(depth, 0.35), mud, (0.0, 0.0, 0.0))
    col = t.mix(puddle, col, mud, label="puddle tint")
    rough = t.mixf(t.mul(ring, 0.6), rough, 0.95)
    rough = t.mixf(puddle, rough, 0.3)
    coat_weight = t.max(coat_weight, puddle)
    coat_r = t.mixf(puddle, coat_r, 0.01)
    coat_ior = t.mixf(puddle, coat_ior, 1.33)

    geo = t.node("ShaderNodeNewGeometry")
    # standing water is level: world up, not the (possibly faceted) surface normal; puddles
    # only form where the surface is within ~20 degrees of flat, so this is always valid
    gn = t.comb(0.0, 0.0, 1.0)
    normal = t.mixv(puddle, t.I("Normal"), gn)  # base bump fades out under standing water

    # Rain: ripple rings in puddles, droplets on other up-facing wet surfaces (coat normal only)
    time = t.value(0.0, label="time (driver: frame / 24)", name=TIME_NODE)
    px, py, _ = t.sep(t.outp(geo, "Position"))
    vor = t.node("ShaderNodeTexVoronoi", t.comb(px, py, 0.0), Scale=5.0, props={"voronoi_dimensions": "3D"})
    cell = t.sep(t.outp(vor, "Color"))[0]
    phase = t.math("FRACT", t.add(t.mul(time, 0.9), cell))
    ring_d = t.math("ABSOLUTE", t.sub(t.outp(vor, "Distance"), t.mul(phase, 0.55)))
    ripple = t.mul_all(t.inv(t.smooth(ring_d, 0.0, 0.05)), t.inv(phase), puddle, rain)
    drops_v = t.node("ShaderNodeTexVoronoi", t.comb(t.mul(px, 1.0), t.mul(py, 1.0), t.mul(time, 0.5)),
                     Scale=45.0, props={"voronoi_dimensions": "3D"})
    drops = t.mul_all(t.inv(t.smooth(t.outp(drops_v, "Distance"), 0.0, 0.25)), rain, coat_w,
                      t.inv(puddle), t.smooth(t.I("Normal Z"), 0.5, 0.9))
    coat_base = t.mixv(coat_w, t.I("Coat Normal"), normal)  # water film follows the surface
    coat_base = t.mixv(puddle, coat_base, gn)
    bump = t.node("ShaderNodeBump", 1.0, 1.0, Height=t.add(t.mul(ripple, 0.0025), t.mul(drops, 0.0006)),
                  Normal=coat_base)
    coat_normal = t.outp(bump)

    t.O("Color", col)
    t.O("Roughness", rough)
    t.O("Metallic", metal)
    t.O("Normal", normal)
    t.O("Coat Weight", coat_weight)
    t.O("Coat Roughness", coat_r)
    t.O("Coat IOR", coat_ior)
    t.O("Coat Normal", coat_normal)
    t.O("W", w)
    t.O("Puddle", puddle)
    t.layout()

    fc = t.t.driver_add('nodes["{}"].outputs[0].default_value'.format(TIME_NODE))
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = "frame / 24"
    return [t.t, build_dry()]

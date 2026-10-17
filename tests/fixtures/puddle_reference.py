"""The puddle reference: the road's puddle look built by hand with plain Blender nodes, straight
from the puddle model's formulas. No RealWorn code is imported here.

This file defines what "correct" means for the Puddle layer: never change it to make RealWorn
pass. RealWorn rebuilds the same look with its Puddle layer (tests/test_puddles.py) and the two
renders are compared.

Per material (millimetres throughout):

  base     the road set, box mapped (Object coordinates, Mapping, Box projection Blend 0.3),
           colour through Hue/Saturation, roughness, height h = (map - 0.5) x BUMP metres
  marking  (asphalt) the painted RGBA marking over the base, alpha through a 0.25..0.75 ramp
  ground   H = Height Scale x (map - mid) / span     (mid, span: the map's 2nd / 98th percentiles)
  dips     H' = H - smoothstep(0.35, 0.65, noise(Object / Dip Size)) x Dip Depth   (if enabled)
  depth    d = Water Level - H', mixed toward -50 where the face is not flat
           (smoothstep from Flat Faces - 0.06 to Flat Faces + 0.02 on the normal's Z)
  zones    water = smoothstep(-0.1, 0.1, d), deep = smoothstep(0, Deep, d),
           edge = smoothstep(-Wet Edge, 0, d), halo = smoothstep(-(Wet Edge + Halo Width x Halo), -Wet Edge, d),
           wet = max(0.4 x halo, edge)
  colour   C x (1 - 0.8 x (1 - metallic) x porosity x wet x Darkening), porosity = clamp((r - 0.5) / 0.4);
           under water lerp(Tint, that, exp(-max(d, 0) / Depth Look)), mixed in by water
  rough    r x (1 - 0.15 halo) x (1 - (1 - 0.5 / 0.85) edge), then toward 0.3 by water
  coat     weight max(0, edge), roughness lerp(lerp(0.08, 0.02, water), 0.005, deep) by edge,
           IOR lerp(1.5, 1.33, edge); normal: the bumped normal toward the flat one by water
  relief   a Bump node (Distance 1) on the base height, Strength exp(-max(d, 0) / Depth Look) x (1 - deep)

The wet film (when Wet Film is above 0), a thin skin of water over every flat face:

  breakup  B(offset): noise(Object / Film Scale + offset; Scale 1, Detail 3, Roughness 0.5) through
           smoothstep(0.3, 0.7), or a grunge image (box projection, Non-Color) at the same coordinates;
           B1 = B(0), B2 = B((0.37, 0.71, 0.13)); film_uniform holds B2 at 0.5 (a test baseline: no patches)
  F        Wet Film x flat x (1 - Dry Patches x smoothstep(0.4, 0.6, B1))
  R        Relief Through Film x (0.2 + 0.8 B2) x (1 - deep)
  colour   wetness max(wet, F) in the porosity darkening
  rough    x (1 - 0.7 F) before the water
  coat     weight max(edge, F); roughness lerp(lerp(0.03, lerp(0.12, Film Gloss, F), flat), the zone's, edge);
           IOR lerp(1.5, 1.33, max(edge, flat)); normal: a second Bump (Distance 1, Strength R) of the
           same height, toward the flat normal by water
"""

import os

import bpy
import numpy as np

BOX_BLEND = 0.3
PAINT_UV = "RW_Paint"


class _T:
    def __init__(self, tree):
        self.t, self.n, self.l = tree, tree.nodes, tree.links

    def node(self, idname, **props):
        nd = self.n.new(idname)
        for k, v in props.items():
            setattr(nd, k, v)
        return nd

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.l.new(v, sock)
        else:
            if sock.type == "RGBA" and isinstance(v, (tuple, list)) and len(v) == 3:
                v = (*v, 1.0)
            if sock.type == "RGBA" and isinstance(v, (int, float)):
                v = (v, v, v, 1.0)
            if sock.type == "VECTOR" and isinstance(v, (int, float)):
                v = (v, v, v)
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(nd.inputs[0], a)
        if b is not None:
            self.set(nd.inputs[1], b)
        if c is not None:
            self.set(nd.inputs[2], c)
        return nd.outputs[0]

    def smooth(self, x, lo, hi):
        nd = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        self.set(nd.inputs["Value"], x)
        self.set(nd.inputs[1], lo)
        self.set(nd.inputs[2], hi)
        nd.inputs[3].default_value, nd.inputs[4].default_value = 0.0, 1.0
        return nd.outputs["Result"]

    def linear(self, x, lo, hi):
        nd = self.node("ShaderNodeMapRange", interpolation_type="LINEAR", clamp=True)
        self.set(nd.inputs["Value"], x)
        nd.inputs[1].default_value, nd.inputs[2].default_value = lo, hi
        nd.inputs[3].default_value, nd.inputs[4].default_value = 0.0, 1.0
        return nd.outputs["Result"]

    def mix(self, fac, a, b, dtype="RGBA", blend="MIX"):
        nd = self.node("ShaderNodeMix", data_type=dtype)
        if dtype == "RGBA":
            nd.blend_type = blend
        suffix = {"RGBA": "Color", "FLOAT": "Float", "VECTOR": "Vector"}[dtype]
        ins = {s.identifier: s for s in nd.inputs}
        self.set(ins["Factor_Float"], fac)
        self.set(ins["A_" + suffix], a)
        self.set(ins["B_" + suffix], b)
        return next(s for s in nd.outputs if s.identifier == "Result_" + suffix)


def _image(T, path, vector, non_color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    n = T.node("ShaderNodeTexImage", interpolation="Linear", projection="BOX", projection_blend=BOX_BLEND)
    n.image = img
    T.l.new(vector, n.inputs["Vector"])
    return n.outputs["Color"]


def build_material(obj, maps, scale, bump, height_range, puddle, marking=None):
    """The reference material on `obj`. `maps`: {color, roughness, height} files; `puddle`: the
    puddle settings (water_level_mm, height_scale_mm, dips, dip_depth_mm, dip_scale_m,
    depth_look_mm, halo, edge_width_mm, halo_width_mm, deep_threshold_mm, darkening,
    flat_threshold, tint; optionally the film: wet_film, film_relief, dry_patches, film_gloss,
    film_scale_m, film_grunge (an image path, None for noise)); `marking`: an RGBA image sampled
    through the paint UV, or None."""
    p = puddle
    mat = bpy.data.materials.new("Reference_Puddle")
    mat.displacement_method = "BUMP"
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    T = _T(nt)
    out = T.node("ShaderNodeOutputMaterial")
    bsdf = T.node("ShaderNodeBsdfPrincipled")
    tc = T.node("ShaderNodeTexCoord")
    geo = T.node("ShaderNodeNewGeometry")
    mp = T.node("ShaderNodeMapping")
    s = 1.0 / scale
    mp.inputs["Scale"].default_value = (s, s, s)
    T.l.new(tc.outputs["Object"], mp.inputs["Vector"])
    vec = mp.outputs["Vector"]
    # base
    hsv = T.node("ShaderNodeHueSaturation")
    hsv.inputs["Hue"].default_value, hsv.inputs["Saturation"].default_value = 0.5, 1.0
    hsv.inputs["Value"].default_value = 1.0
    T.set(hsv.inputs["Color"], _image(T, maps["color"], vec, False))
    color = hsv.outputs["Color"]
    rough = T.math("ADD", _image(T, maps["roughness"], vec, True), 0.0, clamp=True)
    v = _image(T, maps["height"], vec, True)
    v = T.math("ADD", v, 0.0)  # a Color socket read as a float
    height = T.math("MULTIPLY", T.math("SUBTRACT", v, 0.5), bump)
    if marking is not None:
        uv = T.node("ShaderNodeUVMap", uv_map=PAINT_UV)
        mk = T.node("ShaderNodeTexImage", interpolation="Linear")
        mk.image = marking
        T.l.new(uv.outputs["UV"], mk.inputs["Vector"])
        mhsv = T.node("ShaderNodeHueSaturation")
        mhsv.inputs["Hue"].default_value, mhsv.inputs["Saturation"].default_value = 0.5, 1.0
        mhsv.inputs["Value"].default_value = 1.0
        T.l.new(mk.outputs["Color"], mhsv.inputs["Color"])
        m = T.linear(mk.outputs["Alpha"], 0.25, 0.75)
        color = T.mix(m, color, mhsv.outputs["Color"])
        rough = T.mix(m, rough, 0.6, dtype="FLOAT")
    # ground and depth
    lo, hi = height_range
    span = max(hi - lo, 0.02)
    bn = T.math("MULTIPLY_ADD", v, 1.0 / span, -(lo + hi) / 2.0 / span)
    Hp = T.math("MULTIPLY", bn, p["height_scale_mm"])
    if p.get("dips"):
        dm = T.node("ShaderNodeMapping")
        ds = 1.0 / p["dip_scale_m"]
        dm.inputs["Scale"].default_value = (ds, ds, ds)
        T.l.new(tc.outputs["Object"], dm.inputs["Vector"])
        nz = T.node("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value, nz.inputs["Detail"].default_value = 1.0, 1.0
        nz.inputs["Roughness"].default_value = 0.5
        T.l.new(dm.outputs["Vector"], nz.inputs["Vector"])
        Hp = T.math("SUBTRACT", Hp, T.math("MULTIPLY", T.smooth(nz.outputs["Fac"], 0.35, 0.65), p["dip_depth_mm"]))
    d = T.math("SUBTRACT", p["water_level_mm"], Hp)
    sep = T.node("ShaderNodeSeparateXYZ")
    T.l.new(geo.outputs["Normal"], sep.inputs[0])
    gate = T.smooth(sep.outputs["Z"], p["flat_threshold"] - 0.06, p["flat_threshold"] + 0.02)
    d = T.mix(gate, -50.0, d, dtype="FLOAT")
    # zones
    W = T.smooth(d, -0.1, 0.1)
    D = T.smooth(d, 0.0, p["deep_threshold_mm"])
    E = T.smooth(d, -p["edge_width_mm"], 0.0)
    Hh = T.smooth(d, -(p["edge_width_mm"] + p["halo_width_mm"] * p["halo"]), -p["edge_width_mm"])
    wet = T.math("MAXIMUM", T.math("MULTIPLY", Hh, 0.4), E)
    # wet film
    F = R = None
    if p.get("wet_film", 0.0) > 0.0:
        fs = 1.0 / p["film_scale_m"]

        def breakup(offset):
            fm = T.node("ShaderNodeMapping")
            fm.inputs["Scale"].default_value = (fs, fs, fs)
            fm.inputs["Location"].default_value = offset
            T.l.new(tc.outputs["Object"], fm.inputs["Vector"])
            if p.get("film_grunge"):
                return _image(T, p["film_grunge"], fm.outputs["Vector"], True)
            fn = T.node("ShaderNodeTexNoise")
            fn.inputs["Scale"].default_value, fn.inputs["Detail"].default_value = 1.0, 3.0
            fn.inputs["Roughness"].default_value = 0.5
            T.l.new(fm.outputs["Vector"], fn.inputs["Vector"])
            return T.smooth(fn.outputs["Fac"], 0.3, 0.7)

        b1, b2 = breakup((0.0, 0.0, 0.0)), 0.5 if p.get("film_uniform") else breakup((0.37, 0.71, 0.13))
        dry = T.math("MULTIPLY", p["dry_patches"], T.smooth(b1, 0.4, 0.6))
        F = T.math("MULTIPLY", T.math("MULTIPLY", p["wet_film"], gate), T.math("SUBTRACT", 1.0, dry))
        R = T.math("MULTIPLY", T.math("MULTIPLY", p["film_relief"], T.math("MULTIPLY_ADD", b2, 0.8, 0.2)),
                   T.math("SUBTRACT", 1.0, D))
        wet_film = T.math("MAXIMUM", wet, F)
    # colour
    por = T.linear(rough, 0.5, 0.9)
    k = T.math("MULTIPLY", T.math("MULTIPLY", por, wet if F is None else wet_film), p["darkening"])  # metal 0
    keep = T.math("MULTIPLY_ADD", k, -0.8, 1.0)
    c_wet = T.mix(1.0, color, keep, blend="MULTIPLY")
    look = p["depth_look_mm"] * (0.5 if p.get("tint") == "MUDDY" else 1.0)
    a = T.math("EXPONENT", T.math("DIVIDE", T.math("MULTIPLY", T.math("MAXIMUM", d, 0.0), -1.0), look))
    c_under = T.mix(a, p.get("tint_rgb", (0.012, 0.016, 0.02)), c_wet)
    color = T.mix(W, c_wet, c_under)
    # roughness
    r = T.math("MULTIPLY", rough, T.math("MULTIPLY_ADD", Hh, -0.15, 1.0))
    r = T.math("MULTIPLY", r, T.math("MULTIPLY_ADD", E, -(1.0 - 0.5 / 0.85), 1.0))
    if F is not None:
        r = T.math("MULTIPLY", r, T.math("MULTIPLY_ADD", F, -0.7, 1.0))
    r = T.mix(W, r, 0.3, dtype="FLOAT")
    # coat
    cw = T.math("MAXIMUM", 0.0, E)
    cr = T.mix(D, T.mix(W, 0.08, 0.02, dtype="FLOAT"), 0.005, dtype="FLOAT")
    if F is None:
        cr = T.mix(E, 0.03, cr, dtype="FLOAT")
        cior = T.mix(E, 1.5, 1.33, dtype="FLOAT")
    else:
        cw = T.math("MAXIMUM", cw, F)
        film_r = T.mix(gate, 0.03, T.mix(F, 0.12, p["film_gloss"], dtype="FLOAT"), dtype="FLOAT")
        cr = T.mix(E, film_r, cr, dtype="FLOAT")
        cior = T.mix(T.math("MAXIMUM", E, gate), 1.5, 1.33, dtype="FLOAT")
    # relief
    fade = T.math("MULTIPLY", a, T.math("SUBTRACT", 1.0, D, clamp=True))
    strength = T.math("SUBTRACT", 1.0, T.math("SUBTRACT", 1.0, fade, clamp=True), clamp=True)
    bump = T.node("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 1.0
    T.set(bump.inputs["Strength"], strength)
    T.set(bump.inputs["Height"], height)
    T.set(bump.inputs["Normal"], geo.outputs["Normal"])
    ground = bump.outputs["Normal"]
    if R is not None:
        fb = T.node("ShaderNodeBump")
        fb.inputs["Distance"].default_value = 1.0
        T.set(fb.inputs["Strength"], R)
        T.set(fb.inputs["Height"], height)
        T.set(fb.inputs["Normal"], geo.outputs["Normal"])
        ground = fb.outputs["Normal"]
    flat_mix = T.mix(W, ground, geo.outputs["Normal"], dtype="VECTOR")
    norm = T.node("ShaderNodeVectorMath", operation="NORMALIZE")
    T.l.new(flat_mix, norm.inputs[0])
    for sock, val in (("Base Color", color), ("Roughness", r), ("Metallic", 0.0), ("Normal", bump.outputs["Normal"]),
                      ("Coat Weight", cw), ("Coat Roughness", cr), ("Coat IOR", cior),
                      ("Coat Normal", norm.outputs["Vector"])):
        T.set(bsdf.inputs[sock], val)
    T.l.new(bsdf.outputs[0], out.inputs["Surface"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat


def compare(a, b, block=32):
    """Mean absolute difference, and the worst 32 x 32 px block's mean difference."""
    d = np.abs(a.astype(np.float32) - b.astype(np.float32)).mean(axis=2)
    h, w = d.shape
    blocks = d[:h - h % block, :w - w % block].reshape(h // block, block, w // block, block).mean(axis=(1, 3))
    return float(d.mean()), float(blocks.max())


def save_rgb(arr, path):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("rw_tmp_save", w, h, alpha=False)
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = arr
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return os.path.abspath(path)

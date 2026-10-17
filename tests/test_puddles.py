"""Puddle layer: placement by depth, the look by zone, painting, True Depth, engines, and no change
to materials without a Puddle. Quantities are read through Mask View with the compiler's puddle
probe, rendered to linear EXR from a top orthographic camera."""

import os

import bpy
import numpy as np
import pytest

import metrics as M
import render_util as RU
from realworn.core import bake, compiler, images, injector, layers, puddle as P, setup, snapshot

OUT_SUB = "puddles"


# ------------------------------------------------------------------ helpers
def _out(out_dir, name):
    d = os.path.join(out_dir, OUT_SUB)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def make_set(out_dir, name, height, color=(0.45, 0.42, 0.38), rough=0.85):
    """A synthetic texture set folder: flat colour and roughness, `height` (2D, 0..1) as a float
    EXR height map. Returns the folder."""
    folder = _out(out_dir, "set_" + name)
    os.makedirs(folder, exist_ok=True)
    res = height.shape[0]

    def save(arr, fname, fmt, data=True):
        img = bpy.data.images.new("tmp_" + fname, res, res, alpha=False, float_buffer=(fmt == "OPEN_EXR"))
        if data:  # heights and roughness are data: written as they are, no colour conversion
            img.colorspace_settings.name = "Non-Color"
        rgba = np.ones((res, res, 4), np.float32)
        rgba[..., :3] = arr[..., None] if arr.ndim == 2 else arr
        img.pixels.foreach_set(rgba.ravel())
        img.filepath_raw = os.path.join(folder, fname)
        img.file_format = fmt
        img.save()
        bpy.data.images.remove(img)

    save(np.broadcast_to(np.asarray(color, np.float32), (res, res, 3)), name + "_diff.png", "PNG", data=False)
    save(np.full((res, res), rough, np.float32), name + "_rough.png", "PNG")
    save(height.astype(np.float32), name + "_disp.exr", "OPEN_EXR")
    return folder


def plane(sc, name="Ground", size=2.0, mat=None, uv_method="CUBE"):
    """A size x size plane from (0, 0) (texture coordinates = position / size with Scale = size)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new(name="UVMap")
    uv = me.uv_layers["UVMap"].data
    for i, co in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv[i].uv = co
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    m = mat or bpy.data.materials.new(name + "_Mat")
    me.materials.append(m)
    setup.setup_object(ob, uv_method)
    return ob, ob.material_slots[0].material


def top_camera(sc, size=2.0, res=128, engine="CYCLES", samples=4):
    RU.setup(sc, engine=engine, samples=samples, res=(res, res))
    sc.render.filter_size = 0.01 if engine == "CYCLES" else sc.render.filter_size
    cam = sc.camera
    if cam is None:
        cam = bpy.data.objects.new("TopCam", bpy.data.cameras.new("TopCam"))
        sc.collection.objects.link(cam)
        sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.clip_end = 100.0
    cam.data.ortho_scale = size
    cam.location = (size / 2, size / 2, 5.0)
    cam.rotation_euler = (0.0, 0.0, 0.0)  # straight down, image up = +Y (look_at is ambiguous here)
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    return cam


def render_exr(sc, path):
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[..., :3]


def probe(sc, mat, what, path):
    """One puddle quantity per pixel (linear), through Mask View."""
    compiler.PUDDLE_PROBE[mat.name] = what
    try:
        compiler.compile(mat)
        injector.set_mask_view(mat, True)
        px = render_exr(sc, path)
    finally:
        injector.set_mask_view(mat, False)
        compiler.PUDDLE_PROBE.pop(mat.name, None)
        compiler.compile(mat)
    return px[..., 0] if what != "color" else px


def puddle_layer(mat, **values):
    ly = layers.add_layer(mat, "PUDDLE")
    with compiler.batch(mat):
        for k, v in values.items():
            setattr(ly, k, v)
    compiler.compile(mat)
    return ly


def pixel_xy(res):
    """Plane coordinates (0..1) of the pixel centres of a top render (row 0 at the bottom)."""
    c = (np.arange(res) + 0.5) / res
    return np.meshgrid(c, c)


def pixel_uv(res):
    """Box-projection texture coordinates of those pixels: Blender maps a face pointing up (+Z)
    with u = 1 - y, v = x."""
    x, y = pixel_xy(res)
    return 1.0 - y, x


def sample(height, u, v):
    """Bilinear sample of a (n, n) map at texture coordinates (Blender's Linear, texel centres)."""
    n = height.shape[0]
    x, y = u * n - 0.5, v * n - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    x0c, x1c = np.clip(x0, 0, n - 1), np.clip(x0 + 1, 0, n - 1)
    y0c, y1c = np.clip(y0, 0, n - 1), np.clip(y0 + 1, 0, n - 1)
    return ((height[y0c, x0c] * (1 - fx) + height[y0c, x1c] * fx) * (1 - fy)
            + (height[y1c, x0c] * (1 - fx) + height[y1c, x1c] * fx) * fy)


def bowl(n=256):
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    return np.clip(((x - 0.5) ** 2 + (y - 0.5) ** 2) * 1.6 + 0.2, 0.0, 1.0)


def tiles(n=256, tile=32, grout=4, seed=1):
    i = np.arange(n) % tile
    line = (i < grout)
    h = np.where(line[None, :] | line[:, None], 0.25, 0.75).astype(np.float32)
    return h + np.random.default_rng(seed).normal(0.0, 0.01, h.shape).astype(np.float32), \
        (line[None, :] | line[:, None])


@pytest.fixture
def bowl_plane(empty_scene, out_dir):
    sc = empty_scene
    folder = make_set(out_dir, "bowl", bowl())
    ob, mat = plane(sc)
    layers.load_texture(mat, folder, scale=2.0)
    top_camera(sc)
    return sc, ob, mat


# ------------------------------------------------------------------ structure
def test_add_and_remove_a_puddle_leaves_the_material_as_it_was(empty_scene):
    """Coat channels and the relief bump exist only while a Puddle layer does."""
    sc = empty_scene
    ob, mat = plane(sc)
    m = mat.name
    before = snapshot.dumps(snapshot.serialize(mat.node_tree))
    ly = puddle_layer(mat)
    p = mat.node_tree.nodes["Principled BSDF"]
    for ch in ("Coat Weight", "Coat Roughness", "Coat IOR", "Coat Normal", "Thin Film Thickness"):
        assert p.inputs[ch].is_linked, ch
    assert compiler.has_coat(mat.realworn.stack) and ly.kind == "PUDDLE"
    assert mat.realworn.layers[-1].id == ly.id  # on top of the stack
    layers.remove_layer(mat, 0)
    assert not compiler.has_coat(mat.realworn.stack)
    assert snapshot.dumps(snapshot.serialize(bpy.data.materials[m].node_tree)) == before
    assert setup.remove_object(ob) == []


def test_round_trip_with_paint_and_true_depth(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = plane(sc)
    snap = snapshot.dumps(snapshot.serialize(mat.node_tree))
    folder = make_set(out_dir, "rt", bowl(64))
    layers.load_texture(mat, folder, scale=2.0)
    ly = puddle_layer(mat, true_depth=True)
    images.ensure_mask(ob, mat, ly)
    assert mat.displacement_method == "BOTH" and ob.modifiers.get("RW_TrueDepth") is not None
    assert setup.remove_object(ob) == []
    assert mat.displacement_method == "BUMP" and ob.modifiers.get("RW_TrueDepth") is None
    assert snapshot.dumps(snapshot.serialize(mat.node_tree)) == snap


def test_value_edits_do_not_recompile(bowl_plane):
    sc, ob, mat = bowl_plane
    ly = puddle_layer(mat, water_tint="CUSTOM")
    n = compiler.COMPILES["count"]
    ly.water_level_mm = 3.0
    ly.depth_look_mm = 4.0
    ly.halo = 2.0
    ly.edge_width_mm = 2.5
    ly.height_scale_mm = 12.0
    ly.tint_color = (0.2, 0.1, 0.05)
    ly.opacity = 0.5
    ly.darkening = 0.7
    assert compiler.COMPILES["count"] == n
    g = mat.realworn.stack
    assert g.nodes[f"RW::{ly.id}::pud.water_level_mm"].outputs[0].default_value == pytest.approx(3.0)
    ly.wind_ripple = 0.4  # crossing 0 adds the ripple nodes (lean)
    assert compiler.COMPILES["count"] == n + 1
    assert g.nodes.get(f"RW::{ly.id}::pud.ripple") is not None


def test_lean_paint_only_without_paint_shows_nothing(bowl_plane):
    sc, ob, mat = bowl_plane
    ly = puddle_layer(mat, puddle_source="PAINT")
    g = mat.realworn.stack
    assert not [n for n in g.nodes if n.name.startswith(f"RW::{ly.id}::")]
    assert not any(n.name.endswith("pud.dip_noise") for n in g.nodes)  # the base has a height map


# ------------------------------------------------------------------ placement
def test_placement_matches_the_water_level_on_a_bowl(bowl_plane, out_dir):
    """Water exactly where the ground is below the water level: IoU above 0.98."""
    sc, ob, mat = bowl_plane
    h = bowl()
    lo, hi = P.height_range(h[::4, ::4])
    u, v = pixel_uv(128)
    H = P.ground(P.base_norm(sample(h, u, v), lo, hi), 0.0, 10.0, "BASE")
    ly = puddle_layer(mat, height_scale_mm=10.0)
    for level in (-3.0, 0.0, 2.5):
        ly.water_level_mm = level
        w = probe(sc, mat, "water", _out(out_dir, "bowl_water_{}.exr".format(level)))
        water, truth = w > 0.5, H < level
        iou = (water & truth).sum() / max((water | truth).sum(), 1)
        print("\n[puddle] bowl level {} IoU {:.4f}".format(level, iou))
        assert iou > 0.98


def test_grout_fills_before_tile_faces(empty_scene, out_dir):
    sc = empty_scene
    h, grout_tex = tiles()
    ob, mat = plane(sc)
    layers.load_texture(mat, make_set(out_dir, "tiles", h), scale=2.0)
    top_camera(sc, res=256)
    u, v = pixel_uv(256)
    n = h.shape[0]
    grout = grout_tex[np.clip((v * n).astype(int), 0, n - 1), np.clip((u * n).astype(int), 0, n - 1)]
    ly = puddle_layer(mat, height_scale_mm=6.0)
    seen = []
    for level in (-2.5, -1.0, 0.5, 2.5, 4.0):
        ly.water_level_mm = level
        w = probe(sc, mat, "water", _out(out_dir, "tiles_{}.exr".format(level)))
        g, f = float(w[grout].mean()), float(w[~grout].mean())
        seen.append((level, g, f))
        assert g >= f - 0.01, (level, g, f)
    assert any(g > f + 0.3 for _, g, f in seen)  # a level where the grout is wet and the faces are not
    print("\n[puddle] grout vs faces wet fraction:", ["{}: {:.2f}/{:.2f}".format(*s) for s in seen])


def test_painted_puddles_follow_the_grain(empty_scene, out_dir):
    """Painting lowers the ground: inside the painted disc wetness follows low height (corr > 0.6)."""
    sc = empty_scene
    n = 256
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    grain = 0.5 + 0.35 * np.sin(x * 60) * np.cos(y * 53) + 0.05 * np.sin(x * 210 + y * 30)
    ob, mat = plane(sc, uv_method="EXISTING")  # the plane's own 0..1 UV: mask texel = surface point
    layers.load_texture(mat, make_set(out_dir, "grain", grain), scale=2.0)
    top_camera(sc, res=256)
    ly = puddle_layer(mat, water_level_mm=-7.0, paint_depth_mm=6.0, height_scale_mm=10.0, halo=0.0)
    ly.mask_res = 256
    img = images.ensure_mask(ob, mat, ly)
    disc = ((x - 0.5) ** 2 + (y - 0.45) ** 2) < 0.08
    mask = np.where(disc, 1.0, 0.5).astype(np.float32)
    rgba = np.ones((n, n, 4), np.float32)
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = mask
    img.pixels.foreach_set(rgba.ravel())
    img.update()
    wet = probe(sc, mat, "wet", _out(out_dir, "grain_wet.exr"))
    px, py = pixel_xy(256)  # the mask is on the plane's own UV: disc in plane coordinates
    inside = ((px - 0.5) ** 2 + (py - 0.45) ** 2) < 0.07
    outside = ((px - 0.5) ** 2 + (py - 0.45) ** 2) > 0.09
    gh = sample(grain, *pixel_uv(256))
    r = np.corrcoef(wet[inside], -gh[inside])[0, 1]
    print("\n[puddle] painted: wet inside {:.3f} outside {:.3f}, corr with low ground {:.3f}".format(
        wet[inside].mean(), wet[outside].mean(), r))
    assert wet[inside].mean() > 3 * wet[outside].mean() + 0.05
    assert r > 0.6
    assert 0.05 < (wet[inside] > 0.5).mean() < 0.95  # not a flat sticker: part of the disc stays dry


def test_flat_faces_only(empty_scene):
    """Walls and kerb sides never hold water, the top does."""
    sc = empty_scene
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.0, 1.0, 0.5))
    ob = bpy.context.active_object
    ob.data.materials.append(bpy.data.materials.new("Kerb"))
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    puddle_layer(mat, height_source="NONE", water_level_mm=5.0)
    top_camera(sc, res=64)
    top = probe(sc, mat, "wet", _out(bpy.app.tempdir or ".", "kerb_top.exr"))
    cam = sc.camera
    RU.look_at(cam, (1.0, -5.0, 0.5), (1.0, 1.0, 0.5), ortho_scale=0.8)
    side = probe(sc, mat, "wet", _out(bpy.app.tempdir or ".", "kerb_side.exr"))
    assert top[24:40, 24:40].mean() > 0.99
    assert side[16:48, 16:48].max() < 0.01


# ------------------------------------------------------------------ look
def _slope(n=256):
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    return x.astype(np.float32)  # a ramp: height rises along x


def test_depth_look_ground_and_relief_fade_with_depth(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = plane(sc)
    layers.load_texture(mat, make_set(out_dir, "slope", _slope(), color=(0.6, 0.5, 0.4), rough=0.8), scale=2.0)
    top_camera(sc, res=128)
    puddle_layer(mat, height_scale_mm=40.0, water_level_mm=0.0, halo=0.0)
    d = (probe(sc, mat, "depth", _out(out_dir, "slope_depth.exr")) - 0.5) * 40.0
    col = probe(sc, mat, "color", _out(out_dir, "slope_color.exr")).mean(axis=2)
    rel = probe(sc, mat, "relief", _out(out_dir, "slope_relief.exr"))
    under = d > 0.3
    order = np.argsort(d[under])
    bins = np.array_split(order, 8)
    c = [float(col[under][b].mean()) for b in bins]
    r = [float(rel[under][b].mean()) for b in bins]
    print("\n[puddle] by depth: colour", ["%.3f" % x for x in c], "relief", ["%.3f" % x for x in r])
    assert all(b <= a + 1e-3 for a, b in zip(c, c[1:])) and c[-1] < 0.5 * c[0]
    assert all(b <= a + 1e-3 for a, b in zip(r, r[1:])) and r[-1] < 0.05


def test_water_tints_colour_deep_water(empty_scene, out_dir):
    """Deep water fades the ground into the tint: Clear near black-blue, Muddy brown, Custom its
    colour; Oily adds a thin film in patches."""
    sc = empty_scene
    ob, mat = plane(sc)
    layers.load_texture(mat, make_set(out_dir, "slope_tint", _slope(), color=(0.6, 0.5, 0.4), rough=0.8), scale=2.0)
    top_camera(sc, res=64)
    ly = puddle_layer(mat, height_scale_mm=40.0, water_level_mm=40.0, halo=0.0)
    d = (probe(sc, mat, "depth", _out(out_dir, "tint_depth.exr")) - 0.5) * 40.0
    deep = d > 15.0  # absorption below exp(-15 / 8 * 2) for Muddy, exp(-15 / 8) otherwise
    assert deep.mean() > 0.2
    for tint, custom in (("CLEAR", None), ("MUDDY", None), ("CUSTOM", (0.3, 0.05, 0.05))):
        ly.water_tint = tint
        if custom:
            ly.tint_color = custom
        col = probe(sc, mat, "color", _out(out_dir, "tint_{}.exr".format(tint.lower())))[deep].mean(axis=0)
        want = np.array(custom or P.TINTS[tint])
        print("\n[puddle] {} deep water colour {} (tint {})".format(tint, np.round(col, 3), want))
        assert np.abs(col - want).max() < 0.05, (tint, col)
    ly.water_tint = "OILY"
    assert mat.realworn.stack.nodes.get(f"RW::{ly.id}::pud.oil") is not None
    assert mat.node_tree.nodes["Principled BSDF"].inputs["Thin Film Thickness"].is_linked


def _flat_material(name, color, rough, metal):
    m = bpy.data.materials.new(name)
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    return m


def test_porosity_rough_ground_darkens_metal_barely(empty_scene):
    sc = empty_scene
    top_camera(sc, res=32)
    out = {}
    for name, rough, metal in (("Concrete", 0.9, 0.0), ("Metal", 0.2, 1.0)):
        ob, mat = plane(sc, name, mat=_flat_material(name, (0.5, 0.5, 0.5), rough, metal))
        ly = puddle_layer(mat, height_source="NONE", water_level_mm=-0.15)  # in the wet edge
        wet = probe(sc, mat, "color", os.path.join(bpy.app.tempdir or ".", name + "_wet.exr")).mean()
        ly.opacity = 0.0
        dry = probe(sc, mat, "color", os.path.join(bpy.app.tempdir or ".", name + "_dry.exr")).mean()
        out[name] = 1.0 - wet / dry
        ob.hide_render = True
    print("\n[puddle] darkening in the wet edge: concrete {:.2f}, metal {:.2f}".format(out["Concrete"], out["Metal"]))
    assert out["Concrete"] > 0.4 and out["Metal"] < 0.1


def test_waterline_is_the_sharpest_transition(empty_scene, out_dir):
    """Measured with the edge-width metric on the zone masks of a gentle slope."""
    sc = empty_scene
    ob, mat = plane(sc)
    layers.load_texture(mat, make_set(out_dir, "slope2", _slope()), scale=2.0)
    top_camera(sc, res=256)
    puddle_layer(mat, height_scale_mm=60.0, water_level_mm=0.0, halo=1.0)
    w = {z: M.edge_width(probe(sc, mat, z, _out(out_dir, "line_{}.exr".format(z)))) for z in ("water", "edge", "halo")}
    print("\n[puddle] edge widths (px): water {water:.2f}, wet edge {edge:.2f}, halo {halo:.2f}".format(**w))
    assert w["water"] < w["edge"] < w["halo"]


def test_mask_view_shows_the_zones_in_colour(bowl_plane, out_dir):
    sc, ob, mat = bowl_plane
    ly = puddle_layer(mat, water_level_mm=-2.0, deep_threshold_mm=2.0, halo=0.0)
    mat.realworn.mask_view = True
    try:
        px = render_exr(sc, _out(out_dir, "maskview.exr"))
    finally:
        mat.realworn.mask_view = False
    centre, corner = px[60:68, 60:68].mean(axis=(0, 1)), px[2:6, 2:6].mean(axis=(0, 1))
    assert np.allclose(centre, P.VIEW_COLORS["deep"], atol=0.03)  # the bowl's middle is deep water
    assert np.allclose(corner, P.VIEW_COLORS["dry"], atol=0.03)
    assert ly.kind == "PUDDLE"


# ------------------------------------------------------------------ True Depth and engines
def test_true_depth_water_is_flat(bowl_plane, out_dir):
    """From a top camera the displaced surface inside deep water varies by under 0.2 mm, while the
    dry ground varies by the Height Scale."""
    sc, ob, mat = bowl_plane
    ly = puddle_layer(mat, height_scale_mm=20.0, water_level_mm=0.0, true_depth=True)
    ob.modifiers["RW_TrueDepth"].render_levels = 6  # a 2 m plane: give the dicing vertices to move
    deep = probe(sc, mat, "deep", _out(out_dir, "td_deep.exr")) > 0.99
    nt = mat.node_tree
    out = nt.nodes["Material Output"]
    keep = out.inputs["Surface"].links[0].from_socket
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    sc_ = nt.nodes.new("ShaderNodeMath")
    sc_.operation = "MULTIPLY_ADD"
    sc_.inputs[1].default_value, sc_.inputs[2].default_value = 10.0, 0.5  # 1 = 5 cm
    nt.links.new(sep.outputs["Z"], sc_.inputs[0])
    nt.links.new(sc_.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    try:
        z = (render_exr(sc, _out(out_dir, "td_z.exr"))[..., 0] - 0.5) / 10.0 * 1000.0  # mm
    finally:
        nt.links.new(keep, out.inputs["Surface"])
        for n in (geo, sep, em, sc_):
            nt.nodes.remove(n)
    inner = deep.copy()
    inner[:2, :] = inner[-2:, :] = inner[:, :2] = inner[:, -2:] = False
    dry = ~(probe(sc, mat, "wet", _out(out_dir, "td_wet.exr")) > 0.01)
    print("\n[puddle] True Depth: water surface range {:.3f} mm over {} px; dry ground range {:.2f} mm".format(
        float(np.ptp(z[inner])), int(inner.sum()), float(np.ptp(z[dry]))))
    assert inner.sum() > 200
    assert np.ptp(z[inner]) < 0.2
    assert np.ptp(z[dry]) > 5.0
    assert ly.true_depth


def test_engines_agree_on_the_water(bowl_plane, out_dir):
    sc, ob, mat = bowl_plane
    puddle_layer(mat, water_level_mm=0.5)
    cyc = probe(sc, mat, "wet", _out(out_dir, "parity_cycles.exr"))
    top_camera(sc, engine="BLENDER_EEVEE", samples=4)
    eev = probe(sc, mat, "wet", _out(out_dir, "parity_eevee.exr"))
    r = RU.corr(cyc, eev)
    print("\n[puddle] Cycles vs EEVEE wet zones correlation {:.4f}".format(r))
    assert r > 0.95


# ------------------------------------------------------------------ paint, bake, persistence
def test_puddle_mask_is_float_neutral_and_persists(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = plane(sc)
    ly = puddle_layer(mat)
    img = images.ensure_mask(ob, mat, ly)
    assert img.is_float and np.allclose(images.pixels(img)[..., 0], 0.5)
    px = images.pixels(img)
    px[:8, :8, :3] = 0.9
    img.pixels.foreach_set(px.ravel())
    img.update()
    path = os.path.join(out_dir, "puddle_persist.blend")
    name = mat.name
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    mat = bpy.data.materials[name]
    img = mat.realworn.layers[0].mask_image
    assert images.pixels(img)[0, 0, 0] == pytest.approx(0.9, abs=1e-3)
    images.fill(img, 0.0, kind="PUDDLE")
    assert np.allclose(images.pixels(img)[..., 0], 0.5)


def test_bake_material_keeps_the_water(bowl_plane, out_dir):
    sc, ob, mat = bowl_plane
    puddle_layer(mat, water_level_mm=1.0)
    res = bake.bake_material(ob, mat, sc, resolution=256, folder=_out(out_dir, "bake"), samples=4)
    assert "coat_weight" in res and "coat_roughness" in res
    cw = images.pixels(res["coat_weight"])[..., 0]
    assert cw.max() > 0.95 and cw.min() < 0.05
    p = mat.node_tree.nodes["Principled BSDF"]
    assert p.inputs["Coat Weight"].links[0].from_node.image == res["coat_weight"]
    assert p.inputs["Coat IOR"].links[0].from_node.outputs[0].default_value == pytest.approx(1.33)
    bake.restore_live(mat)
    assert injector.stacks(mat.node_tree)[0].name in p.inputs["Coat Weight"].links[0].from_node.name
    assert setup.remove_object(ob) == []


# ------------------------------------------------------------------ the reference road
def test_reference_road_matches_the_plain_node_tree(empty_scene, out_dir):
    """The road's puddles built by RealWorn's Puddle layer against the plain-node reference, Cycles
    at a fixed seed: mean difference under 0.02, no 32 px block above 0.06, in both framings."""
    from fixtures import make_road as MR
    from fixtures import puddle_reference as PR
    import puddle_realworn as PW
    if not MR.available():
        pytest.skip("road sets not downloaded (python tests/corpus/fetch.py --road)")
    sc = empty_scene
    pairs = PW.build_pair(sc)
    for which in ("WIDE", "LOW"):
        MR.frame(sc, which)
        PW.show(pairs, "reference")
        a = MR.render(sc, _out(out_dir, "road_ref_{}.png".format(which)), samples=64, res=(512, 288))
        PW.show(pairs, "realworn")
        b = MR.render(sc, _out(out_dir, "road_rw_{}.png".format(which)), samples=64, res=(512, 288))
        mad, block = PR.compare(a, b)
        PR.save_rgb(np.concatenate([a, b], axis=1), _out(out_dir, "road_reference_vs_realworn_{}.png".format(which)))
        diff = np.clip(np.abs(a - b).mean(axis=2) * 5.0, 0.0, 1.0)
        PR.save_rgb(np.dstack([diff] * 3), _out(out_dir, "road_diff_x5_{}.png".format(which)))
        print("\n[puddle] reference road {}: MAD {:.4f}, worst 32 px block {:.4f}".format(which, mad, block))
        from perf_log import record
        record("Puddle reference road {}: mean abs difference".format(which), mad, "", 0.02,
               "Cycles CPU 64 spp 512x288; plain-node reference vs RealWorn")
        record("Puddle reference road {}: worst 32 px block".format(which), block, "", 0.06, "")
        assert mad < 0.02 and block < 0.06

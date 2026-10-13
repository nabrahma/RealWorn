"""Core (kept from v2, PRD v3 G6 and success criterion 3): Setup / Remove round trips, the empty
stack invisible to the pixel, compiler determinism, value edits without recompiling, lean compile,
layer list editing with default stack positions, and the v3 Setup changes (RW_<object>, Cube
Projection and Pack Islands, the scale check)."""

import glob
import os
import time

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import compiler, images, injector, layers, naming, nodeutil, setup, snapshot

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def uv_cube(scene, name="Cube", size=1.0, cuts=4, loc=(0, 0, 0.5), material=None):
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=size, calc_uvs=True)
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    return ms._link(scene, name, bm, loc, material)


def state_of(obj):
    """Everything Setup may touch on an object: slots, trees, UV layers and their data."""
    me = obj.data
    out = {"slots": [(s.material.name if s.material else None, s.link) for s in obj.material_slots],
           "uv": [(u.name, u.active_render) for u in me.uv_layers],
           "uv_active": me.uv_layers.active.name if me.uv_layers.active else None,
           "modifiers": [m.name for m in obj.modifiers]}
    for u in me.uv_layers:
        buf = np.empty(len(me.loops) * 2, np.float32)
        u.data.foreach_get("uv", buf)
        out["uvdata_" + u.name] = buf.round(6).tobytes()
    for s in obj.material_slots:
        if s.material is not None and s.material.node_tree is not None:
            out["tree_" + s.material.name] = snapshot.dumps(snapshot.serialize(s.material.node_tree))
            out["disp_" + s.material.name] = s.material.displacement_method
    return out


def roundtrip(obj):
    before = state_of(obj)
    mats_before = set(bpy.data.materials.keys())
    rep = setup.setup_object(obj)
    assert not [r for r in rep if r[0] == "ERROR"], rep
    me = obj.data
    assert naming.UV_PAINT in me.uv_layers
    assert (me.uv_layers.active.name if me.uv_layers.active else None) == before["uv_active"]
    assert [u.name for u in me.uv_layers if u.active_render] == [n for n, r in before["uv"] if r]
    for m in setup.materials_of(obj):
        assert injector.is_setup(m), m.name
        assert injector.stacks(m.node_tree)
        assert m.realworn.stack is not None and m.realworn.stack.name == naming.stack_group_name(m.name)
    assert setup.remove_object(obj) == []
    after = state_of(obj)
    assert after == before
    assert set(bpy.data.materials.keys()) == mats_before
    assert not [g for g in bpy.data.node_groups if g.name.startswith(naming.STACK_PREFIX)]
    for m in setup.materials_of(obj):
        assert not nodeutil.owned_nodes(m.node_tree)


# ---------------------------------------------------------------- round trips
@pytest.mark.parametrize("name", sorted(GENERATED))
def test_setup_remove_generated(empty_scene, name):
    roundtrip(uv_cube(empty_scene, material=GENERATED[name]()))


def _polyhaven():
    return sorted(glob.glob(os.path.join(CORPUS, "*", "*.blend")))


@pytest.mark.parametrize("path", _polyhaven() or [pytest.param(None, marks=pytest.mark.skip(
    reason="Poly Haven corpus not downloaded (python tests/corpus/fetch.py)"))])
def test_setup_remove_polyhaven(empty_scene, path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.materials = list(src.materials)
    mats = [m for m in dst.materials if m is not None and m.node_tree is not None]
    assert mats
    ob = uv_cube(empty_scene, material=mats[0])
    for m in mats[1:]:
        ob.data.materials.append(m)
    roundtrip(ob)


def test_roundtrip_with_layers_and_texture(empty_scene, tmp_path):
    """Layers of every kind, a texture on the Base, a painted mask and True depth: Remove is still exact."""
    ob = uv_cube(empty_scene, material=GENERATED["image_based"]())
    before = state_of(ob)
    mats_before = set(bpy.data.materials.keys())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    folder = _texture_folder(tmp_path)
    layers.load_texture(mat, folder)
    for kind in ("VARIATION", "PAINT", "REVEAL", "DECALS", "EDGE_WEAR", "DIRT"):
        ly = layers.add_layer(mat, kind)
        if kind in ("PAINT", "REVEAL", "DECALS"):
            images.ensure_mask(ob, mat, ly)
    rev = next(ly for ly in mat.realworn.layers if ly.kind == "REVEAL")
    rev.true_depth = True
    assert mat.displacement_method == "BOTH" and ob.modifiers.get(naming.MOD_SUBDIV)
    assert setup.remove_object(ob) == []
    assert state_of(ob) == before
    assert set(bpy.data.materials.keys()) == mats_before


def _texture_folder(tmp_path, name="painted_plaster_2m", size=16):
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    for suffix, val in (("diff", 0.6), ("rough", 0.7), ("disp", 0.5)):
        img = bpy.data.images.new("tex_" + suffix, size, size)
        img.pixels.foreach_set(np.full(size * size * 4, val, np.float32))
        img.filepath_raw = str(folder / "{}_{}_1k.png".format(name, suffix))
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
    return str(folder)


def test_object_without_material_gets_rw_object(empty_scene):
    """SET-1: no material -> RW_<object>, a neutral grey Base; Remove deletes it."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = ms._link(empty_scene, "Bare", bm)
    before = state_of(ob)
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    assert mat.name == "RW_Bare" and injector.is_setup(mat)
    p = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    assert tuple(p.inputs["Base Color"].default_value)[:3] == pytest.approx((0.5, 0.5, 0.5))
    assert naming.UV_PAINT in ob.data.uv_layers and len(ob.material_slots) == 1
    setup.remove_object(ob)
    assert state_of(ob) == before and not ob.data.uv_layers and "RW_Bare" not in bpy.data.materials


def test_multi_material_and_empty_slot(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["image_based"]())
    ob.data.materials.append(None)
    ob.data.materials.append(GENERATED["procedural"]())
    before = state_of(ob)
    setup.setup_object(ob)
    assert ob.material_slots[1].material.name == "RW_Cube"
    assert all(injector.is_setup(s.material) for s in ob.material_slots)
    setup.remove_object(ob)
    assert state_of(ob) == before
    assert "RW_Cube" not in bpy.data.materials


def test_shared_material_made_unique(empty_scene):
    shared = GENERATED["principled_basic"]()
    a = uv_cube(empty_scene, "A", material=shared)
    b = uv_cube(empty_scene, "B", material=shared, loc=(2, 0, 0.5))
    tree_b = snapshot.dumps(snapshot.serialize(shared.node_tree))
    rep = setup.setup_object(a)
    assert a.material_slots[0].material.name == naming.unique_material_name(shared.name)
    assert b.material_slots[0].material is shared and not injector.is_setup(shared)
    assert any("made unique" in r[1] for r in rep)
    assert snapshot.dumps(snapshot.serialize(shared.node_tree)) == tree_b
    setup.remove_object(a)
    assert a.material_slots[0].material is shared
    assert naming.unique_material_name(shared.name) not in bpy.data.materials


def test_several_objects_each_get_their_own_images(empty_scene):
    """SET-7: Setup on a selection sets up each object; each gets its own paint images."""
    shared = GENERATED["principled_basic"]()
    a = uv_cube(empty_scene, "A", material=shared)
    b = uv_cube(empty_scene, "B", material=shared, loc=(2, 0, 0.5))
    assert bpy.ops.realworn.setup(objects="A,B") == {"FINISHED"}
    ma, mb = a.material_slots[0].material, b.material_slots[0].material
    assert ma is not mb and injector.is_setup(ma) and injector.is_setup(mb)
    la, lb = layers.add_layer(ma, "PAINT"), layers.add_layer(mb, "PAINT")
    assert images.ensure_mask(a, ma, la) is not images.ensure_mask(b, mb, lb)


def test_linked_duplicate_mesh(empty_scene):
    a = uv_cube(empty_scene, "A", material=GENERATED["principled_basic"]())
    b = bpy.data.objects.new("B", a.data)
    empty_scene.collection.objects.link(b)
    before_a, before_b = state_of(a), state_of(b)
    setup.setup_object(a)
    assert a.material_slots[0].link == "OBJECT"           # B's look is untouched
    assert b.material_slots[0].material.name == "C_PrincipledBasic"
    setup.remove_object(a)
    assert state_of(a) == before_a and state_of(b) == before_b


def test_use_existing_uv_copies_layout(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob, uv_method="EXISTING")
    me = ob.data
    a = np.empty(len(me.loops) * 2, np.float32)
    b = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", a)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", b)
    assert np.allclose(a, b)


@pytest.mark.parametrize("method", ["CUBE", "SMART"])
def test_paint_uv_is_non_overlapping(empty_scene, method):
    """SET-2 / suite Paint UV: Cube Projection plus Pack Islands (default) and Smart UV give no
    overlapping islands; the render UV is untouched."""
    ob = ms.l_block(empty_scene, material=ms.principled("L"))
    ob.data.uv_layers.new(name="UVMap")
    uv_before = state_of(ob)["uvdata_UVMap"]
    setup.setup_object(ob, uv_method=method)
    ov = setup.uv_overlap_ratio(ob)
    print("\n[uv] {} RW_Paint overlap ratio on the L-block {:.4f}".format(method, ov))
    assert ov < 0.01
    assert state_of(ob)["uvdata_UVMap"] == uv_before
    co = np.empty(len(ob.data.loops) * 2, np.float32)
    ob.data.uv_layers[naming.UV_PAINT].data.foreach_get("uv", co)
    assert co.min() >= -1e-4 and co.max() <= 1 + 1e-4


def _face_uv_areas(ob):
    me = ob.data
    co = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", co)
    co = co.reshape(-1, 2)
    out = []
    for p in me.polygons:
        pts = co[list(p.loop_indices)]
        x, y = pts[:, 0], pts[:, 1]
        out.append(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    return np.sort(np.asarray(out))


def test_cube_projection_matches_the_tutorial_fixture(empty_scene):
    """Setup's paint UV is the tutorial's (the reference fixture's, made by hand): every face gets the
    same UV area, so the same texel density, with no overlap. Pack Islands may place equal islands
    in different slots depending on the window context, so positions are not compared."""
    from fixtures import reference_wall as R
    a = R.build_scene(empty_scene, "WallA")
    R.paint_uv(a)
    b = R.build_scene(empty_scene, "WallB")
    setup.setup_object(b)
    assert np.allclose(_face_uv_areas(a), _face_uv_areas(b), rtol=1e-4, atol=1e-7)
    assert setup.uv_overlap_ratio(a) < 0.01 and setup.uv_overlap_ratio(b) < 0.01


def test_scale_check(empty_scene):
    """SET-5: an unapplied scale is reported and the Setup operator applies it (single-user mesh)."""
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    ob.scale = (2.0, 1.0, 1.0)
    assert setup.needs_scale_apply(ob)
    ob2 = uv_cube(empty_scene, "Scaled2", material=GENERATED["principled_basic"](), loc=(3, 0, 0.5))
    ob2.scale = (3.0, 3.0, 3.0)
    rep = setup.setup_object(ob2)
    assert any("scale is not applied" in r[1] for r in rep)
    assert bpy.ops.realworn.setup(objects=ob.name, apply_scale=True) == {"FINISHED"}
    assert not setup.needs_scale_apply(ob) and tuple(ob.dimensions) == pytest.approx((2.0, 1.0, 1.0))


# ---------------------------------------------------------------- invisible
def _scene_for_pixels(sc):
    floor, obs = ms.demo_props(sc)
    for o in [floor] + obs:
        if not o.data.uv_layers:
            o.data.uv_layers.new(name="UVMap")
    obs[0].data.materials.clear()
    obs[0].data.materials.append(GENERATED["image_based"]())
    obs[1].data.materials.clear()
    obs[1].data.materials.append(GENERATED["procedural"]())
    return [floor] + obs


@pytest.mark.parametrize("engine", ["CYCLES", "BLENDER_EEVEE"])
def test_empty_stack_is_invisible(empty_scene, out_dir, engine):
    sc = empty_scene
    obs = _scene_for_pixels(sc)
    ru.setup(sc, engine=engine, samples=8, res=(160, 90))
    clean = ru.render(sc, os.path.join(out_dir, "core_clean_{}.png".format(engine)))
    for o in obs:
        setup.setup_object(o)
    layered = ru.render(sc, os.path.join(out_dir, "core_setup_{}.png".format(engine)))
    d = float(np.abs(clean - layered).max())
    print("\n[invisible] {} max pixel difference after Setup: {:.6f}".format(engine, d))
    assert d == 0.0


# ---------------------------------------------------------------- compiler
def paint_half(ob, ly, res=64):
    img = images.create_mask(ob, ly, res=res)
    px = np.zeros((res, res, 4), np.float32)
    px[..., 3] = 1.0
    px[:res // 2, :, :3] = 1.0  # bottom half painted
    img.pixels.foreach_set(px.ravel())
    ly.mask_image = img
    return img


def _layered(sc, kinds=("PAINT", "REVEAL", "VARIATION", "DIRT")):
    ob = uv_cube(sc, material=GENERATED["image_based"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    for k in kinds:
        ly = layers.add_layer(mat, k)
        if k in ("PAINT", "REVEAL"):
            paint_half(ob, ly)
    return ob, mat


def _tree(mat):
    return snapshot.dumps(snapshot.serialize(mat.realworn.stack, include_owned=True))


def test_compile_is_deterministic(empty_scene):
    ob, mat = _layered(empty_scene)
    a = _tree(mat)
    compiler.compile(mat)
    assert _tree(mat) == a
    mat.realworn.layers[0].opacity = mat.realworn.layers[0].opacity  # no-op edit
    assert _tree(mat) == a
    names = [n.name for n in mat.realworn.stack.nodes]
    assert len(names) == len(set(names))
    ids = {ly.id for ly in mat.realworn.layers} | {"stack", "base"}
    for n in names:
        if n.startswith(naming.NODE_PREFIX) and n not in ("RW::in", "RW::out"):
            assert n.split("::")[1] in ids, n


def test_value_edits_do_not_recompile(empty_scene):
    ob, mat = _layered(empty_scene, ("PAINT", "REVEAL"))
    g = mat.realworn.stack
    paint, rev = (ly for ly in mat.realworn.layers)
    paint.content = "COLOR"  # structural
    c0 = compiler.COMPILES["count"]
    paint.opacity = 0.4
    paint.color = (0.9, 0.1, 0.1)
    paint.roughness = 0.12
    paint.hue = 0.2
    paint.threshold = 0.3
    paint.sharpness = 0.9
    rev.depth_mm = 4.0
    rev.edge_dark = 0.5
    assert compiler.COMPILES["count"] == c0
    lid = paint.id
    assert g.nodes[naming.layer_node(lid, "opacity")].inputs[1].default_value == pytest.approx(0.4)
    assert tuple(g.nodes[naming.layer_node(lid, "color")].outputs[0].default_value)[:3] == pytest.approx((0.9, 0.1, 0.1))
    assert g.nodes[naming.layer_node(lid, "rough")].outputs[0].default_value == pytest.approx(0.12)
    assert g.nodes[naming.layer_node(lid, "hsv")].inputs["Hue"].default_value == pytest.approx(0.7)
    els = g.nodes[naming.layer_node(lid, "ramp")].color_ramp.elements
    w = 0.5 + (0.01 - 0.5) * 0.9
    assert (els[0].position, els[1].position) == pytest.approx((0.3 - w / 2, 0.3 + w / 2), abs=1e-5)
    assert g.nodes[naming.layer_node(rev.id, "depth")].inputs[1].default_value == pytest.approx(0.004)
    paint.visible = False  # structural
    assert compiler.COMPILES["count"] == c0 + 1


def test_lean_compile(empty_scene):
    ob, mat = _layered(empty_scene, ("PAINT", "REVEAL"))
    g = mat.realworn.stack
    paint, rev = (ly for ly in mat.realworn.layers)
    rev.visible = False
    assert not [n for n in g.nodes if rev.id in n.name]  # hidden: no nodes at all
    rev.visible = True
    assert not g.nodes.get(naming.layer_node(paint.id, "breakup.sub"))  # Breakup Amount 0: no nodes
    paint.breakup_amount = 0.5  # crossing 0 recompiles and adds the subtract
    assert g.nodes.get(naming.layer_node(paint.id, "breakup.sub"))
    assert g.nodes[naming.layer_node(paint.id, "breakup.sub")].blend_type == "SUBTRACT"
    rev.edge_dark = 0.0
    assert not g.nodes.get(naming.layer_node(rev.id, "edgedark"))
    fresh = layers.add_layer(mat, "PAINT")  # nothing painted: no nodes
    assert not [n for n in g.nodes if fresh.id in n.name]


def test_empty_stack_is_pass_through(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["coat_material"]())
    setup.setup_object(ob)
    g = ob.material_slots[0].material.realworn.stack
    go = g.nodes["RW::out"]
    for name in naming.CHANNELS:
        assert go.inputs[name].links[0].from_node.name == "RW::in", name
    assert len(g.nodes) == 2


def test_layer_list_editing_and_default_positions(empty_scene):
    """UI-1: a new layer drops into its kind's usual place; the user can move it anywhere."""
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    order = lambda: [ly.kind for ly in mat.realworn.layers]  # noqa: E731
    d_id = layers.add_layer(mat, "DIRT").id
    layers.add_layer(mat, "PAINT")
    layers.add_layer(mat, "VARIATION")
    layers.add_layer(mat, "DECALS")
    layers.add_layer(mat, "REVEAL")
    layers.add_layer(mat, "EDGE_WEAR")
    v2 = layers.add_layer(mat, "VARIATION")
    assert order() == ["VARIATION", "VARIATION", "PAINT", "EDGE_WEAR", "REVEAL", "DECALS", "DIRT"]
    assert mat.realworn.layers[mat.realworn.active_layer_index].id == v2.id
    assert mat.realworn.layers[0].breakup_grunge != mat.realworn.layers[1].breakup_grunge  # VAR-3
    assert mat.realworn.layers[0].breakup_offset != mat.realworn.layers[1].breakup_offset
    layers.move_layer(mat, 6, -1)  # drag Dirt below Decals
    assert order()[-2:] == ["DIRT", "DECALS"]
    dup = layers.duplicate_layer(mat, 5)
    assert dup.name == "Dirt 2" and dup.id != d_id and dup.kind == "DIRT"
    layers.remove_layer(mat, 6)
    assert [ly.id for ly in mat.realworn.layers][5] == d_id


def test_presets(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    wo = layers.add_layer(mat, "VARIATION", "WASHED_OUT")
    dp = layers.add_layer(mat, "VARIATION", "DARK_PATCHES")
    dirt = layers.add_layer(mat, "VARIATION", "DIRT_PATCHES")
    sec = layers.add_layer(mat, "VARIATION", "SECOND_MATERIAL")
    sc = layers.add_layer(mat, "REVEAL", "SCRATCHES")
    assert (wo.name, wo.content, wo.saturation) == ("Washed Out", "TINT_BELOW", pytest.approx(-0.3))
    assert (dp.content, dp.value) == ("TINT_BELOW", pytest.approx(-0.25))
    assert (dirt.content, dirt.roughness) == ("COLOR", pytest.approx(0.9))
    assert sec.content == "TEXTURE"
    assert (sc.name, sc.depth_mm) == ("Scratches", pytest.approx(0.3))


def test_operators_drive_without_mouse(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    assert bpy.ops.realworn.setup(objects=ob.name) == {"FINISHED"}
    mat = ob.material_slots[0].material
    assert bpy.ops.realworn.layer_add(kind="DIRT", object=ob.name, material=mat.name) == {"FINISHED"}
    assert bpy.ops.realworn.layer_add(kind="VARIATION", preset="WASHED_OUT", object=ob.name,
                                      material=mat.name) == {"FINISHED"}
    lid = mat.realworn.layers[1].id
    assert bpy.ops.realworn.layer_move(direction="DOWN", object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert mat.realworn.layers[0].id == lid
    assert bpy.ops.realworn.layer_duplicate(object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert bpy.ops.realworn.layer_remove(object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert len(mat.realworn.layers) == 2
    assert bpy.ops.realworn.layer_select(object=ob.name, material=mat.name, index=-1) == {"FINISHED"}
    assert mat.realworn.base_active
    assert bpy.ops.realworn.remove(objects=ob.name) == {"FINISHED"}
    assert not setup.is_setup(ob)


def test_paint_layer_shows_only_where_painted(empty_scene, out_dir):
    """Level 1: synthetic paint (left half of the plane) darkens only painted texels."""
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=1.0)
    ob = ms._link(sc, "Plane", bm, (0, 0, 0), ms.principled("PlaneMat", (0.8, 0.8, 0.8), roughness=0.6))
    ms.camera_light(sc, cam_loc=(0, 0, 4), target=(0, 0, 0))
    ru.setup(sc, engine="BLENDER_EEVEE", samples=4, res=(96, 96))
    ru.look_at(sc.camera, (0, 0, 4), (0, 0, 0), ortho_scale=2.0)
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "PAINT")
    ly.content, ly.color = "COLOR", (0.02, 0.02, 0.02)
    img = images.create_mask(ob, ly, res=128)
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    xs = np.array([me.vertices[lp.vertex_index].co.x for lp in me.loops])
    px = np.zeros((128, 128, 4), np.float32)
    px[..., 3] = 1.0
    left = uv[xs < -0.01]
    u0, u1, v0, v1 = left[:, 0].min(), left[:, 0].max(), left[:, 1].min(), left[:, 1].max()
    px[int(v0 * 128):int(np.ceil(v1 * 128)), int(u0 * 128):int(np.ceil(u1 * 128)), :3] = 1.0
    img.pixels.foreach_set(px.ravel())
    ly.mask_image = img
    out = ru.render(sc, os.path.join(out_dir, "core_half_paint.png"))
    lum = out.mean(axis=2)
    lft, rgt = lum[20:76, 10:40].mean(), lum[20:76, 56:86].mean()
    print("\n[paint] left (painted) {:.3f}, right {:.3f}".format(lft, rgt))
    assert lft < rgt * 0.5


# ---------------------------------------------------------------- perf
def test_setup_performance(empty_scene):
    sc = empty_scene
    times = []
    for i in range(2):  # best of two fresh objects: inside the full suite the first one can be slow
        ob = uv_cube(sc, "Dense%d" % i, size=1.0, cuts=40, loc=(3 * i, 0, 0.5), material=GENERATED["image_based"]())
        nverts = len(ob.data.vertices)
        t = time.perf_counter()
        setup.setup_object(ob)
        times.append(time.perf_counter() - t)
    dt = min(times)
    record("v3 Setup one object, {}k verts (Cube Projection + Pack Islands)".format(nverts // 1000), dt, "s", 2.0,
           "best of 2 fresh objects; worst {:.2f} s; v2.1: 0.58 s with Smart UV".format(max(times)))
    mat = ob.material_slots[0].material
    for k in ("PAINT", "REVEAL", "VARIATION"):
        ly = layers.add_layer(mat, k)
        if k != "VARIATION":
            ly.mask_image = images.create_mask(ob, ly, res=256)
    t = time.perf_counter()
    layers.add_layer(mat, "VARIATION")
    compiler.compile(mat)
    dc = (time.perf_counter() - t) / 2
    record("v3 Add layer (compile, 4 layers)", dc, "s", 0.3, "compiler time only, no EEVEE compile")
    print("\n[perf] setup {} verts {:.3f} s; add-layer compile {:.4f} s".format(nverts, dt, dc))
    assert dt < 2.0 and dc < 0.3


def test_duplicate_many_layers(empty_scene):
    """Regression: duplicate_layer held a layer reference across layers.add(); once the collection
    reallocated it read freed memory (v2 stateful suite hang, 12 Oct 2026)."""
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "VARIATION")
    ly.hue = 0.25
    for _ in range(24):
        layers.duplicate_layer(mat, 0)
    assert len(mat.realworn.layers) == 25
    assert all(L.hue == pytest.approx(0.25) and L.kind == "VARIATION" for L in mat.realworn.layers)
    assert len({L.id for L in mat.realworn.layers}) == 25

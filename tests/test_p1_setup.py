"""P1 acceptance: Setup / Remove round trips (suite 1), empty stack invisible to the pixel
(suite 4), compiler determinism (suite 2), value edits without recompiling (CMP-4), lean
compile (CMP-2), layer list editing, setup performance budgets."""

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


# ---------------------------------------------------------------- suite 1
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


def test_multi_material_and_empty_slot(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["image_based"]())
    ob.data.materials.append(None)
    ob.data.materials.append(GENERATED["procedural"]())
    before = state_of(ob)
    setup.setup_object(ob)
    assert ob.material_slots[1].material.name.startswith(naming.DEFAULT_MATERIAL)
    assert all(injector.is_setup(s.material) for s in ob.material_slots)
    setup.remove_object(ob)
    assert state_of(ob) == before
    assert not [m for m in bpy.data.materials if m.name.startswith(naming.DEFAULT_MATERIAL)]


def test_object_without_slots_or_uvs(empty_scene):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = ms._link(empty_scene, "Bare", bm)
    before = state_of(ob)
    setup.setup_object(ob)
    assert naming.UV_PAINT in ob.data.uv_layers and len(ob.material_slots) == 1
    setup.remove_object(ob)
    assert state_of(ob) == before and not ob.data.uv_layers


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
    setup.setup_object(ob, use_existing_uv=True)
    me = ob.data
    a = np.empty(len(me.loops) * 2, np.float32)
    b = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", a)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", b)
    assert np.allclose(a, b)


def test_smart_uv_is_non_overlapping(empty_scene):
    ob = ms.l_block(empty_scene, material=ms.principled("L"))
    setup.setup_object(ob)
    ov = setup.uv_overlap_ratio(ob)
    print("\n[uv] RW_Paint overlap ratio on the L-block {:.4f}".format(ov))
    assert ov < 0.01


# ---------------------------------------------------------------- suite 4
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
    clean = ru.render(sc, os.path.join(out_dir, "p1_clean_{}.png".format(engine)))
    for o in obs:
        setup.setup_object(o)
    layered = ru.render(sc, os.path.join(out_dir, "p1_setup_{}.png".format(engine)))
    d = float(np.abs(clean - layered).max())
    print("\n[invisible] {} max pixel difference after Setup: {:.6f}".format(engine, d))
    assert d == 0.0


# ---------------------------------------------------------------- compiler
def _layered(sc, kinds=("DIRT", "WEAR", "RUST", "CUSTOM")):
    ob = uv_cube(sc, material=GENERATED["image_based"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    for k in kinds:
        ly = layers.add_layer(mat, k)
        img = images.create_mask(ob, ly, res=64)
        px = np.zeros((64, 64, 4), np.float32)
        px[:32, :, :] = 1.0  # bottom half painted
        img.pixels.foreach_set(px.ravel())
        ly.mask_image = img
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
    ids = {ly.id for ly in mat.realworn.layers} | {"stack"}
    for n in names:
        if n.startswith(naming.NODE_PREFIX) and n not in ("RW::in", "RW::out"):
            assert n.split("::")[1] in ids, n


def test_value_edits_do_not_recompile(empty_scene):
    ob, mat = _layered(empty_scene)
    g = mat.realworn.stack
    ly = mat.realworn.layers[0]
    c0 = compiler.COMPILES["count"]
    ly.opacity = 0.4
    ly.color.color = (0.9, 0.1, 0.1)
    ly.roughness.value = 0.12
    ly.threshold = 0.3
    ly.softness = 0.2
    ly.height.value = 0.7
    assert compiler.COMPILES["count"] == c0
    lid = ly.id
    assert g.nodes[naming.layer_node(lid, "opacity")].outputs[0].default_value == pytest.approx(0.4)
    assert tuple(g.nodes[naming.layer_node(lid, "color.value")].outputs[0].default_value)[:3] == \
        pytest.approx((0.9, 0.1, 0.1))
    assert g.nodes[naming.layer_node(lid, "roughness.value")].outputs[0].default_value == pytest.approx(0.12)
    assert g.nodes[naming.layer_node(lid, "levels")].inputs["Threshold"].default_value == pytest.approx(0.3)
    ly.visible = False  # structural
    assert compiler.COMPILES["count"] == c0 + 1


def test_lean_compile(empty_scene):
    ob, mat = _layered(empty_scene, ("DIRT", "CUSTOM"))
    g = mat.realworn.stack
    dirt, custom = mat.realworn.layers[0], mat.realworn.layers[1]
    n_full = len(g.nodes)
    custom.visible = False
    assert not [n for n in g.nodes if custom.id in n.name]  # hidden: no nodes at all
    custom.visible = True
    custom.metallic.enabled = False
    assert not g.nodes.get(naming.layer_node(custom.id, "metallic.value"))
    assert len(g.nodes) < n_full
    fresh = layers.add_layer(mat, "DUST")  # nothing painted, no ingredient: no nodes
    assert not [n for n in g.nodes if fresh.id in n.name]


def test_empty_stack_is_pass_through(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["coat_material"]())
    setup.setup_object(ob)
    g = ob.material_slots[0].material.realworn.stack
    go = g.nodes["RW::out"]
    for name in naming.CHANNELS:
        assert go.inputs[name].links[0].from_node.name == "RW::in", name
    assert len(g.nodes) == 2


def test_layer_list_editing(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    d_id = layers.add_layer(mat, "DIRT").id
    w_id = layers.add_layer(mat, "WEAR").id  # keep ids: collection items move in memory
    assert [ly.name for ly in mat.realworn.layers] == ["Dirt", "Wear"]  # new layer goes above the active one
    assert mat.realworn.active_layer_index == 1
    layers.move_layer(mat, 1, -1)
    assert [ly.name for ly in mat.realworn.layers] == ["Wear", "Dirt"]
    dup = layers.duplicate_layer(mat, 0)
    assert dup.name == "Wear 2" and dup.id != w_id and dup.lock_source == "EDGE"
    assert [ly.name for ly in mat.realworn.layers] == ["Wear", "Wear 2", "Dirt"]
    layers.remove_layer(mat, 1)
    assert [ly.id for ly in mat.realworn.layers] == [w_id, d_id]


def test_operators_drive_without_mouse(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    assert bpy.ops.realworn.setup(objects=ob.name) == {"FINISHED"}
    mat = ob.material_slots[0].material
    assert bpy.ops.realworn.layer_add(type="DIRT", object=ob.name, material=mat.name) == {"FINISHED"}
    assert bpy.ops.realworn.layer_add(type="WATER", object=ob.name, material=mat.name) == {"FINISHED"}
    lid = mat.realworn.layers[1].id
    assert bpy.ops.realworn.layer_move(direction="DOWN", object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert mat.realworn.layers[0].id == lid
    assert bpy.ops.realworn.layer_duplicate(object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert bpy.ops.realworn.layer_remove(object=ob.name, material=mat.name, layer=lid) == {"FINISHED"}
    assert len(mat.realworn.layers) == 2
    assert bpy.ops.realworn.remove(objects=ob.name) == {"FINISHED"}
    assert not setup.is_setup(ob)


def test_flat_layer_shows_only_where_painted(empty_scene, out_dir):
    """Level 1: synthetic paint (left half of the RW_Paint UV) darkens only painted texels."""
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=1.0)
    ob = ms._link(sc, "Plane", bm, (0, 0, 0), ms.principled("PlaneMat", (0.8, 0.8, 0.8), roughness=0.6))
    ms.camera_light(sc, cam_loc=(0, 0, 4), target=(0, 0, 0))
    ru.setup(sc, engine="BLENDER_EEVEE", samples=4, res=(96, 96))
    ru.look_at(sc.camera, (0, 0, 4), (0, 0, 0), ortho_scale=2.0)
    setup.setup_object(ob, use_existing_uv=False)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "DIRT")
    ly.color.blend = "MIX"
    ly.color.color = (0.02, 0.02, 0.02)
    img = images.create_mask(ob, ly, res=128)
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    xs = np.array([me.vertices[lp.vertex_index].co.x for lp in me.loops])
    # paint the texels whose islands belong to the left half of the plane (x < 0)
    px = np.zeros((128, 128, 4), np.float32)
    left = uv[xs < -0.01]
    u0, u1, v0, v1 = left[:, 0].min(), left[:, 0].max(), left[:, 1].min(), left[:, 1].max()
    px[int(v0 * 128):int(np.ceil(v1 * 128)), int(u0 * 128):int(np.ceil(u1 * 128))] = 1.0
    img.pixels.foreach_set(px.ravel())
    ly.mask_image = img
    out = ru.render(sc, os.path.join(out_dir, "p1_half_dirt.png"))
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
    record("v2 Setup one object, {}k verts (Smart UV Project)".format(nverts // 1000), dt, "s", 1.0,
           "best of 2 fresh objects; worst {:.2f} s".format(max(times)))
    mat = ob.material_slots[0].material
    for k in ("DIRT", "WEAR", "RUST"):
        ly = layers.add_layer(mat, k)
        ly.mask_image = images.create_mask(ob, ly, res=256)
    t = time.perf_counter()
    layers.add_layer(mat, "CUSTOM")
    compiler.compile(mat)
    dc = (time.perf_counter() - t) / 2
    record("v2 Add layer (compile, 4 layers)", dc, "s", 0.3, "compiler time only, no EEVEE compile")
    print("\n[perf] setup {} verts {:.3f} s; add-layer compile {:.4f} s".format(nverts, dt, dc))
    assert dt < 1.0 and dc < 0.3


def test_group_upgrade_recompiles_stacks(empty_scene):
    """An older shared group in the file is replaced and every stack is rewired against it."""
    from realworn.core import assets
    ob, mat = _layered(empty_scene, ("DIRT",))
    g = bpy.data.node_groups[naming.SH_LEVELS]
    g["rw_build"] = "old"  # pretend the file came from an older build
    c0 = compiler.COMPILES["count"]
    assert assets.upgrade_open_file() >= 1
    assert compiler.COMPILES["count"] > c0
    assert mat.realworn.stack.nodes[naming.layer_node(mat.realworn.layers[0].id, "levels")].node_tree.get(
        "rw_build") == assets.asset_build()


def test_duplicate_many_layers_with_ingredients(empty_scene):
    """Regression: duplicate_layer held a layer reference across layers.add(); once the collection
    reallocated, copying its ingredients looped forever (stateful suite hang, 12 Oct 2026)."""
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "RUST")
    for kind in ("EDGE", "CAVITY", "UP"):
        ing = ly.ingredients.add()
        ing.kind, ing.amount = kind, 0.3
    for _ in range(24):
        layers.duplicate_layer(mat, 0)
    assert len(mat.realworn.layers) == 25
    assert all([i.kind for i in L.ingredients] == [i.kind for i in mat.realworn.layers[0].ingredients]
               for L in mat.realworn.layers)
    assert len({L.id for L in mat.realworn.layers}) == 25

"""P5 acceptance: generators on demand (ING-1), Edge / Cavity / Contact / Up / Reference ingredients,
Edge Lock (ING-2), mask presets (ING-6), engine parity (suite 9) and files that render without the
add-on (suite 9)."""

import os
import subprocess

import bpy
import numpy as np
import pytest
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import compiler, images, layers, mask_presets, masks, naming, setup


def _add_ing(mat, ly, kind, amount=1.0, **kw):
    with compiler.batch(mat):
        ing = ly.ingredients.add()
        ing.kind = kind
        ing.amount = amount
        for k, v in kw.items():
            setattr(ing, k, v)
    compiler.compile(mat)
    return ing


def _cube(sc, name="Cube", loc=(0, 0, 1)):
    ob = ms.sharp_cube(sc, name=name, size=2.0, cuts=12, location=loc,
                       material=ms.principled(name + "Mat", (0.4, 0.4, 0.4)))
    ob.data.uv_layers.new(name="UVMap")
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def _view(sc, engine="BLENDER_EEVEE", res=128, samples=4, cam=(5.0, -6.0, 5.0), target=(0, 0, 1)):
    if sc.camera is None:
        ms.camera_light(sc, cam_loc=cam, target=target)
    ru.look_at(sc.camera, cam, target)
    sc.camera.data.type = "PERSP"
    ru.setup(sc, engine=engine, samples=samples, res=(res, res))
    sc.view_settings.view_transform = "Raw"
    sc.render.image_settings.file_format = "OPEN_EXR"  # linear float: the mask values themselves
    sc.render.image_settings.color_depth = "32"
    sc.render.film_transparent = True  # background reads 0, not the world colour


def _mask(sc, mat, path, **kw):
    mat.realworn.mask_view = True
    _view(sc, **kw)
    out = ru.render(sc, path).mean(axis=2)
    mat.realworn.mask_view = False
    return out


def _px(sc, world, res=128):
    p = world_to_camera_view(sc, sc.camera, Vector(world))
    return int(p.y * res), int(p.x * res)  # row 0 = bottom


# ---------------------------------------------------------------- ING-1
def test_generators_added_and_removed_on_demand(empty_scene):
    ob, mat = _cube(empty_scene)
    assert masks.masks_modifier(ob) is None  # nothing uses a generator: no modifier
    ly = layers.add_layer(mat, "DIRT")
    ing = _add_ing(mat, ly, "CAVITY", width=0.05)
    mod = masks.masks_modifier(ob)
    assert mod is not None and masks.get_input(mod, "Cavity Width") == pytest.approx(0.05)
    ing.width = 0.08  # value edit reaches the modifier
    assert masks.get_input(mod, "Cavity Width") == pytest.approx(0.08)
    ly.visible = False
    assert masks.masks_modifier(ob) is None  # hidden layers do not count
    ly.visible = True
    layers.add_layer(mat, "UP" if False else "DUST")  # Up is computed in the shader: no modifier needed
    wear = layers.add_layer(mat, "WEAR")  # Edge Lock source EDGE
    assert wear.lock_source == "EDGE" and masks.masks_modifier(ob) is not None
    setup.remove_object(ob)
    assert masks.masks_modifier(ob) is None


# ----------------------------------------------------------- Edge Lock
def test_edge_lock_turns_careless_strokes_into_chips(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = _cube(sc)
    wear = layers.add_layer(mat, "WEAR")
    wear.lock_width = 0.06  # a band a few pixels wide on a 2 m cube at 128 px
    images.fill(images.ensure_mask(ob, mat, wear), 1.0)  # "careless strokes": paint everywhere
    wear.lock_strength = 0.0
    free = _mask(sc, mat, os.path.join(out_dir, "p5_lock0.exr"))
    wear.lock_strength = 1.0
    locked = _mask(sc, mat, os.path.join(out_dir, "p5_lock1.exr"))
    edge = _px(sc, (1.0, -1.0, 1.0))      # midpoint of the vertical front-right edge
    face = _px(sc, (0.0, -1.0, 1.0))      # centre of the front face
    top = _px(sc, (0.0, 0.0, 2.0))        # centre of the top face
    e, f, t = [float(locked[r - 1:r + 2, c - 1:c + 2].max()) for r, c in (edge, face, top)]
    print("\n[lock] lock 0: face {:.2f}; lock 1: edge {:.2f}, face {:.2f}, top {:.2f}".format(
        float(free[face]), e, f, t))
    assert float(free[face]) > 0.9  # without the lock the paint is everywhere
    assert e > 0.6 and f < 0.05 and t < 0.05  # with it, only the edges keep paint


# --------------------------------------------------------- generators
def test_cavity_contact_up_reference(empty_scene, out_dir):
    sc = empty_scene
    floor = ms.street(sc, size=(6, 6), material=ms.principled("Floor"))
    lb = ms.l_block(sc, location=(0, 0, 0), material=ms.principled("LMat"))
    lb.data.uv_layers.new(name="UVMap")
    masks.mark_ground(floor)
    setup.setup_object(lb)
    mat = lb.material_slots[0].material
    cav = layers.add_layer(mat, "DIRT", name="Cav")
    _add_ing(mat, cav, "CAVITY", width=0.08)
    ev = lb.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert naming.ATTR_CAVITY in ev.data.attributes and naming.ATTR_CONTACT in ev.data.attributes
    con = layers.add_layer(mat, "DIRT", name="Con")
    _add_ing(mat, con, "CONTACT", width=0.2)
    up = layers.add_layer(mat, "DUST", name="Up")
    _add_ing(mat, up, "UP", angle=0.5)
    ref = layers.add_layer(mat, "RUST", name="Ref")
    _add_ing(mat, ref, "REFERENCE", ref_layer_id=up.id)
    assert ref.ingredients[0].ref_layer_id == up.id
    cam = (4.0, -5.0, 3.5)
    shots = {}
    for i, name in enumerate(("Cav", "Con", "Up", "Ref")):
        mat.realworn.active_layer_index = i
        shots[name] = _mask(sc, mat, os.path.join(out_dir, "p5_{}.exr".format(name)), cam=cam, target=(0, 0, 0.5))
    # Up: tops lit, walls dark; Reference to Up reproduces Up
    assert ru.corr(shots["Up"], shots["Ref"]) > 0.99
    assert shots["Up"].max() > 0.9
    # Contact: the bottom band of the walls, not their tops
    low, high = _px(sc, (1.0, -0.5, 0.05)), _px(sc, (1.0, -0.5, 0.9))
    print("\n[contact] low {:.2f} high {:.2f}".format(float(shots["Con"][low]), float(shots["Con"][high])))
    assert float(shots["Con"][low]) > 0.3 and float(shots["Con"][high]) < 0.05
    assert shots["Cav"].max() > 0.6 and float(shots["Cav"].mean()) < 0.2  # only the inside corner


def test_mask_preset_roundtrip(empty_scene, tmp_path):
    mask_presets.FOLDER = str(tmp_path)
    try:
        ob, mat = _cube(empty_scene)
        base = layers.add_layer(mat, "WEAR", name="Chips")
        src = layers.add_layer(mat, "RUST", name="Rusty")
        from realworn.core import grunge
        grunge.use("FILL", "rust_spots", ob, mat, src, amount=0.7, scale=0.3)
        _add_ing(mat, src, "REFERENCE", 0.5, ref_layer_id=base.id)
        _add_ing(mat, src, "EDGE", 0.4, width=0.03)
        src.lock_source, src.lock_strength, src.threshold, src.softness = "CAVITY", 0.7, 0.4, 0.2
        mask_presets.save(mat, src, "Rust in chips")
        assert "Rust in chips" in mask_presets.list_presets()
        target = layers.add_layer(mat, "DIRT", name="Target")  # above Chips: the reference resolves
        mask_presets.load(mat, target, "Rust in chips")
        kinds = [(i.kind, round(i.amount, 3)) for i in target.ingredients]
        assert kinds == [("GRUNGE", 0.7), ("REFERENCE", 0.5), ("EDGE", 0.4)]
        assert target.ingredients[0].image.name.startswith("rust_spots")
        assert target.ingredients[1].ref_layer_id == base.id
        assert (target.lock_source, round(target.lock_strength, 3), round(target.threshold, 3)) == ("CAVITY", 0.7, 0.4)
        assert target.mask_image is None  # painted images are never part of a preset
        low = layers.add_layer(mat, "DIRT", name="Low", index=0)  # nothing below: reference dropped
        mask_presets.load(mat, low, "Rust in chips")
        assert [i.kind for i in low.ingredients] == ["GRUNGE", "EDGE"]
    finally:
        mask_presets.FOLDER = None


# ------------------------------------------------------- suite 9: parity
@pytest.mark.parametrize("kind", ["EDGE", "CAVITY", "CONTACT", "UP"])
def test_engine_parity(empty_scene, out_dir, kind):
    sc = empty_scene
    floor = ms.street(sc, size=(6, 6), material=ms.principled("Floor"))
    masks.mark_ground(floor)
    lb = ms.l_block(sc, location=(0, 0, 0), material=ms.principled("LMat"))
    lb.data.uv_layers.new(name="UVMap")
    setup.setup_object(lb)
    mat = lb.material_slots[0].material
    ly = layers.add_layer(mat, "CUSTOM")
    _add_ing(mat, ly, kind, width=0.1 if kind == "CONTACT" else 0.05)
    imgs = {}
    for eng in ("CYCLES", "BLENDER_EEVEE"):
        imgs[eng] = _mask(sc, mat, os.path.join(out_dir, "p5_parity_{}_{}.exr".format(kind, eng)), engine=eng,
                          samples=8, cam=(4.0, -5.0, 3.5), target=(0, 0, 0.5))
    a, b = imgs["CYCLES"], imgs["BLENDER_EEVEE"]
    on = (a > 0.0) | (b > 0.0)
    c = ru.corr(a[on], b[on])
    print("\n[parity] {} correlation {:.4f}".format(kind, c))
    assert a.std() > 0.05 and c > 0.9


# ------------------------------------------------- suite 9: independence
RENDER_EXPR = (
    "import bpy, sys; sc = bpy.context.scene; "
    "assert not hasattr(bpy.types.Material, 'realworn'), 'add-on must not be loaded'; "
    "sc.render.filepath = sys.argv[-1]; bpy.ops.render.render(write_still=True)"
)


def test_renders_without_addon(empty_scene, out_dir):
    sc = empty_scene
    floor = ms.street(sc, size=(6, 6), material=ms.principled("Floor"))
    masks.mark_ground(floor)
    ob, mat = _cube(sc)
    for kind, fill in (("WEAR", 1.0), ("DIRT", 0.6), ("WATER", 1.0)):
        ly = layers.add_layer(mat, kind)
        img = images.ensure_mask(ob, mat, ly)
        images.fill(img, 1.0)
        if kind == "DIRT":
            _add_ing(mat, ly, "CONTACT", 0.8, width=0.3)
    mat.realworn.layers[1].opacity = fill
    ms.camera_light(sc, cam_loc=(5, -6, 4), target=(0, 0, 1))
    ru.setup(sc, samples=16, res=(160, 120))
    path = os.path.join(out_dir, "p5_indep.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    with_addon = ru.render(sc, os.path.join(out_dir, "p5_indep_with.png"))
    out_png = os.path.join(out_dir, "p5_indep_without.png")
    if os.path.exists(out_png):
        os.remove(out_png)
    r = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", path, "--python-expr",
                        RENDER_EXPR, "--", out_png], capture_output=True, text=True, timeout=600)
    assert os.path.exists(out_png), r.stdout[-2000:] + r.stderr[-2000:]
    d = ru.mad(with_addon, ru.load(out_png))
    print("\n[independence] with vs without the add-on MAD {:.5f}".format(d))
    assert d < 0.002

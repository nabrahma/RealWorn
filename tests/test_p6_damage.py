"""P6 acceptance: Damage depth modes from one painted mask (Shader dents with inner material and rim,
Displacement with material displacement + adaptive subdivision, Geometry Boolean cutters only
inside painted areas), inner materials (DMG-1), dirt in damage (DMG-6), debris (DMG-7), Apply
(DMG-8), closed-mesh guard (DMG-9), and Remove leaving nothing behind."""

import math
import os

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import compiler, damage, images, layers, masks, naming, nodeutil, setup


def cube(sc, name="Block", cuts=10, loc=(0, 0, 0.5), size=1.0):
    ob = ms.sharp_cube(sc, name=name, size=size, cuts=cuts, location=loc,
                       material=ms.principled(name + "Mat", (0.05, 0.15, 0.45), roughness=0.5))
    ob.data.uv_layers.new(name="UVMap")
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def paint_faces(ob, img, pred, value=1.0):
    """Synthetic paint: fill the RW_Paint texels of every face whose world centre passes `pred`."""
    me = ob.data
    w, h = img.size
    px = images.pixels(img).copy()
    uvl = me.uv_layers[naming.UV_PAINT].data
    mw = ob.matrix_world
    for p in me.polygons:
        if not pred(mw @ p.center):
            continue
        uv = np.array([uvl[i].uv[:] for i in p.loop_indices])
        x0, y0 = np.floor(uv.min(axis=0) * (w, h)).astype(int)
        x1, y1 = np.ceil(uv.max(axis=0) * (w, h)).astype(int)
        px[max(y0, 0):y1, max(x0, 0):x1] = (value, value, value, 1.0)
    img.pixels.foreach_set(px.ravel())
    img.update()
    return img


def damage_layer(ob, mat, mode="SHADER", pred=None):
    ly = layers.add_layer(mat, "DAMAGE")
    ly.mask_res = 512
    img = images.ensure_mask(ob, mat, ly)
    paint_faces(ob, img, pred or (lambda c: c.y < -0.49 and abs(c.x) < 0.25 and abs(c.z - 0.5) < 0.25))
    ly.damage.depth_mode = mode
    return ly


def front_camera(sc, res=96, engine="BLENDER_EEVEE", samples=4):
    ms.camera_light(sc, cam_loc=(0, -3, 0.5), target=(0, 0, 0.5))
    ru.look_at(sc.camera, (0, -3, 0.5), (0, 0, 0.5), ortho_scale=1.2)
    sun = bpy.data.objects["Sun"]
    sun.rotation_euler = (math.radians(80), 0, math.radians(-60))  # grazing: shows dents
    ru.setup(sc, engine=engine, samples=samples, res=(res, res))
    sc.view_settings.view_transform = "Standard"


# ------------------------------------------------------------------ shader
def test_shader_dents_inner_material_and_rim(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = cube(sc)
    front_camera(sc)
    clean = ru.render(sc, os.path.join(out_dir, "p6_clean.png"))
    ly = damage_layer(ob, mat, "SHADER")
    assert ly.damage.inner == "CONCRETE" and tuple(ly.color.color) == pytest.approx(damage.INNER_LOOK["CONCRETE"][0])
    g = mat.realworn.stack
    assert g.nodes.get(naming.layer_node(ly.id, "damage")) is not None
    hit = ru.render(sc, os.path.join(out_dir, "p6_shader.png"))
    inside, outside = hit[36:60, 36:60], hit[8:24, 8:24]
    blue = lambda im: float((im[..., 2] - im[..., 0]).mean())
    print("\n[shader] blue dominance painted {:.3f} vs unpainted {:.3f}; MAD vs clean outside {:.4f}".format(
        blue(inside), blue(outside), ru.mad(clean[8:24, 8:24], outside)))
    assert blue(inside) < blue(outside) - 0.1    # the broken area shows the grey inner material
    assert ru.mad(clean[8:24, 8:24], outside) < 0.005  # nothing changes where nothing was painted
    ly.damage.depth_mm = 9.0  # value edit: no recompile
    assert g.nodes[naming.layer_node(ly.id, "damage")].inputs["Depth"].default_value == pytest.approx(9.0)


def test_inner_material_choice(empty_scene):
    ob, mat = cube(empty_scene)
    ly = damage_layer(ob, mat)
    ly.damage.inner = "STEEL"
    col, metal, rough = damage.INNER_LOOK["STEEL"]
    assert tuple(ly.color.color) == pytest.approx(col, abs=1e-6)
    assert ly.metallic.value == pytest.approx(metal) and ly.roughness.value == pytest.approx(rough)


# ----------------------------------------------------------- displacement
def test_displacement_mode(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = cube(sc)
    before = mat.displacement_method
    ly = damage_layer(ob, mat, "DISPLACEMENT")
    out = nodeutil.output_node(mat.node_tree)
    disp = nodeutil.find(mat.node_tree, "disp")
    assert disp is not None and out.inputs["Displacement"].links[0].from_node == disp
    assert mat.displacement_method == "BOTH"
    sub = damage.subdiv_modifier(ob)
    assert sub is not None and sub.subdivision_type == "SIMPLE" and sub.use_adaptive_subdivision
    front_camera(sc, engine="CYCLES", samples=8)
    ru.look_at(sc.camera, (1.6, -2.2, 1.4), (0, 0, 0.5))  # oblique: a flat dent floor only shows at its walls
    sc.camera.data.type = "PERSP"
    ly.damage.depth_mm = 20.0
    a = ru.render(sc, os.path.join(out_dir, "p6_disp20.png"))
    ly.damage.depth_mm, ly.damage.rim_height = 0.0, 0.0
    z = ru.render(sc, os.path.join(out_dir, "p6_disp0.png"))
    d = np.abs(a - z).mean(axis=2)
    print("\n[displacement] 20 mm vs 0 mm: max change {:.3f}, clearly changed pixels {}".format(
        float(d.max()), int((d > 0.05).sum())))
    assert d.max() > 0.15 and (d > 0.05).sum() >= 10  # the dent walls show real depth
    ly.damage.depth_mode = "SHADER"  # same painted mask, back to Shader
    assert nodeutil.find(mat.node_tree, "disp") is None and damage.subdiv_modifier(ob) is None
    assert mat.displacement_method == before and not out.inputs["Displacement"].is_linked


# ---------------------------------------------------------------- geometry
def _evaluated(ob):
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        mw = ob.matrix_world
        co = np.array([(mw @ v.co)[:] for v in me.vertices])
        a = me.attributes.get(naming.ATTR_DAMAGE)
        dmg = np.array([d.value for d in a.data]) if a is not None else np.zeros(len(co))
        mats = {m.name for m in me.materials if m is not None}
        return co, dmg, mats
    finally:
        ev.to_mesh_clear()


def test_geometry_cutters_only_where_painted(empty_scene):
    sc = empty_scene
    ob, mat = cube(sc, cuts=16)
    n0 = len(ob.data.vertices)
    ly = damage_layer(ob, mat, "GEOMETRY")
    mod = damage.damage_modifier(ob)
    assert mod is not None and masks.get_input(mod, "Mask") == ly.mask_image
    co, dmg, mats = _evaluated(ob)
    broken = co[dmg > 0.5]
    print("\n[geometry] verts {} -> {}, break verts {}, x {:.2f}..{:.2f}, z {:.2f}..{:.2f}".format(
        n0, len(co), len(broken), broken[:, 0].min(), broken[:, 0].max(), broken[:, 2].min(), broken[:, 2].max()))
    assert len(broken) > 50
    assert naming.inner_material_name("concrete") in mats
    # every break lies on the painted front patch (|x| < 0.25, 0.25 < z < 0.75), plus cutter radius
    assert broken[:, 1].max() < -0.4 and np.abs(broken[:, 0]).max() < 0.33
    assert broken[:, 2].min() > 0.15 and broken[:, 2].max() < 0.85  # painted faces + cutter radius
    c0 = compiler.COMPILES["count"]
    ly.damage.threshold = 0.99  # a value edit reaches the modifier without a shader recompile
    assert masks.get_input(mod, "Threshold") == pytest.approx(0.99) and compiler.COMPILES["count"] == c0


def test_unpainted_geometry_damage_changes_nothing(empty_scene):
    ob, mat = cube(empty_scene)
    n0 = len(ob.data.vertices)
    ly = layers.add_layer(mat, "DAMAGE")
    ly.damage.depth_mode = "GEOMETRY"
    images.ensure_mask(ob, mat, ly)
    co, dmg, mats = _evaluated(ob)
    assert len(co) == n0 and dmg.max() == 0.0


def test_debris_lands_on_ground(empty_scene):
    sc = empty_scene
    floor = ms.street(sc, size=(4, 4), material=ms.principled("Floor"))
    masks.mark_ground(floor)
    ob, mat = cube(sc, cuts=16, loc=(0, 0, 0.6))
    ly = damage_layer(ob, mat, "GEOMETRY", pred=lambda c: c.y < -0.49)
    ly.damage.size_min, ly.damage.size_max, ly.damage.debris = 0.03, 0.08, True
    co, dmg, mats = _evaluated(ob)
    low = co[co[:, 2] < 0.08]
    print("\n[debris] vertices on the ground: {}".format(len(low)))
    assert len(low) > 0 and low[:, 2].min() > -0.1


def test_non_manifold_refused(empty_scene):
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=1.0)
    ob = ms._link(sc, "Open", bm, (0, 0, 0), ms.principled("OpenMat"))
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = damage_layer(ob, mat, "GEOMETRY", pred=lambda c: True)
    assert damage.damage_modifier(ob) is None
    assert "closed mesh" in ly.damage.get("rw_warning", "")


def test_dirt_in_damage_and_apply(empty_scene):
    sc = empty_scene
    ob, mat = cube(sc, cuts=16)
    ly = damage_layer(ob, mat, "GEOMETRY")
    dirt = damage.add_dirt_in_damage(mat, ly)
    assert dirt.ingredients[0].kind == "REFERENCE" and dirt.ingredients[0].ref_layer_id == ly.id
    assert layers.index_of(mat, dirt.id) == layers.index_of(mat, ly.id) + 1
    n_eval = len(_evaluated(ob)[0])
    assert damage.apply_geometry(ob)
    assert damage.damage_modifier(ob) is None and len(ob.data.vertices) == n_eval


def test_remove_leaves_nothing(empty_scene):
    ob, mat = cube(empty_scene, cuts=8)
    method = mat.displacement_method
    damage_layer(ob, mat, "DISPLACEMENT")
    layers.add_layer(mat, "DAMAGE").damage.depth_mode = "GEOMETRY"
    setup.remove_object(ob)
    assert not ob.modifiers and mat.displacement_method == method
    assert not nodeutil.owned_nodes(mat.node_tree)

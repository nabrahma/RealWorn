"""P7 acceptance: decal layers via placement (DEC-1), paintable masks (DEC-2), channel-only Grime
mode (DEC-3), layer order covers decals (DEC-4), Bake Decal into Layer (DEC-5), 16-decal limit
(DEC-6), facing fade, rotation without recompiling, deletion, Remove."""

import os

import bmesh
import bpy
import numpy as np
import pytest
from mathutils import Euler

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import compiler, decals, images, layers, naming, setup


@pytest.fixture
def wall(empty_scene):
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(3.0, 0.3, 2.4), verts=bm.verts[:])
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=12, use_grid_fill=True)
    ob = ms._link(sc, "Wall", bm, (0, 0, 1.2), ms.principled("WallMat", (0.6, 0.6, 0.58), roughness=0.85))
    setup.setup_object(ob)
    ms.camera_light(sc, cam_loc=(0, -4, 1.2), target=(0, 0, 1.2))
    ru.look_at(sc.camera, (0, -4, 1.2), (0, 0, 1.2), ortho_scale=1.4)
    ru.setup(sc, engine="BLENDER_EEVEE", samples=4, res=(96, 96))
    sc.view_settings.view_transform = "Standard"
    return sc, ob, ob.material_slots[0].material


def _place(sc, ob, image="poster_01.png", mode="FULL", size=0.9):
    return decals.place(ob, image, (0, -0.15, 1.2), (0, -1, 0), size=size, mode=mode, scene=sc)


def _centre(img, half=0.15):
    h, w = img.shape[:2]
    return img[int(h * (0.5 - half)):int(h * (0.5 + half)), int(w * (0.5 - half)):int(w * (0.5 + half))]


def test_place_creates_a_decal_layer(wall, out_dir):
    sc, ob, mat = wall
    base = ru.render(sc, os.path.join(out_dir, "p7_base.png"))
    empty, made, rep = _place(sc, ob)
    assert len(made) == 1 and empty.name.startswith(naming.DECAL_PREFIX)
    ly = mat.realworn.layers[-1]  # added on top
    assert ly.type == "DECAL" and ly.decal.empty == empty and ly.decal.image.name.startswith("poster_01")
    assert empty.name in bpy.data.collections[naming.COLL_DECALS].objects
    out = ru.render(sc, os.path.join(out_dir, "p7_poster.png"))
    d_centre = ru.mad(_centre(out), _centre(base))
    d_corner = ru.mad(out[:8, :8], base[:8, :8])  # outside the decal box
    print("\n[decal] centre change {:.3f}, outside {:.4f}".format(d_centre, d_corner))
    assert d_centre > 0.05 and d_corner < 0.002


def test_facing_fade_side_faces(wall, out_dir):
    sc, ob, mat = wall
    _place(sc, ob, size=1.2)
    ru.look_at(sc.camera, (4, 0, 1.2), (0, 0, 1.2), ortho_scale=1.4)  # the wall's thin side face
    side = ru.render(sc, os.path.join(out_dir, "p7_side.png"))
    rg = float((side[..., 0] - side[..., 1]).mean())
    print("\n[facing] side face R-G {:.4f}".format(rg))
    assert rg < 0.03  # no stretched poster colour on faces turned away from the projector


def test_grime_mode_is_channel_only(wall, out_dir):
    sc, ob, mat = wall
    base = _centre(ru.render(sc, os.path.join(out_dir, "p7_g0.png")))
    _place(sc, ob, mode="GRIME")
    ly = mat.realworn.layers[-1]
    assert not ly.color.enabled  # DEC-3
    g = _centre(ru.render(sc, os.path.join(out_dir, "p7_grime.png")))
    hue = abs(float((g[..., 0] - g[..., 1]).mean()) - float((base[..., 0] - base[..., 1]).mean()))
    print("\n[grime] brightness {:.3f} -> {:.3f}, R-G shift {:.4f}".format(float(base.mean()), float(g.mean()), hue))
    assert g.mean() < base.mean() - 0.03 and hue < 0.02


def test_paint_tears_the_decal(wall, out_dir):
    sc, ob, mat = wall
    _place(sc, ob)
    ly = mat.realworn.layers[-1]
    full = ru.render(sc, os.path.join(out_dir, "p7_full.png"))
    img = images.ensure_mask(ob, mat, ly)
    w = img.size[0]
    px = np.zeros((w, w, 4), np.float32)
    px[..., 3] = 1.0  # Erase everywhere (black at full alpha): the decal is torn off completely
    img.pixels.foreach_set(px.ravel())
    img.update()
    torn = ru.render(sc, os.path.join(out_dir, "p7_torn.png"))
    ly.visible = False
    hidden = ru.render(sc, os.path.join(out_dir, "p7_hidden.png"))
    print("\n[tear] full vs torn {:.3f}; torn vs no decal {:.4f}".format(ru.mad(full, torn), ru.mad(torn, hidden)))
    assert ru.mad(full, torn) > 0.02 and ru.mad(torn, hidden) < 0.002


def test_dirt_above_covers_the_decal(wall, out_dir):
    sc, ob, mat = wall
    _place(sc, ob)
    clean = _centre(ru.render(sc, os.path.join(out_dir, "p7_c.png")))
    dirt = layers.add_layer(mat, "DIRT", index=len(mat.realworn.layers))  # above the decal (DEC-4)
    images.fill(images.ensure_mask(ob, mat, dirt), 1.0)
    dirty = _centre(ru.render(sc, os.path.join(out_dir, "p7_dirty.png")))
    layers.move_layer(mat, len(mat.realworn.layers) - 1, -1)  # dirt below the decal now
    under = _centre(ru.render(sc, os.path.join(out_dir, "p7_under.png")))
    print("\n[order] decal {:.3f}, dirt above {:.3f}, dirt below {:.3f}".format(clean.mean(), dirty.mean(),
                                                                             under.mean()))
    assert dirty.mean() < clean.mean() - 0.1
    assert abs(float(under.mean() - clean.mean())) < abs(float(dirty.mean() - clean.mean())) * 0.5


def test_rotation_updates_without_recompile(wall):
    sc, ob, mat = wall
    empty, made, _ = _place(sc, ob)
    node = mat.realworn.stack.nodes[naming.layer_node(made[0].id, "decal.normal")]
    c0 = compiler.COMPILES["count"]
    empty.rotation_euler = Euler((empty.rotation_euler.x + 0.5, empty.rotation_euler.y, empty.rotation_euler.z))
    bpy.context.view_layer.update()
    decals.update_normal(empty)
    n = decals.projection_normal(empty)
    assert [node.inputs[a].default_value for a in "XYZ"] == pytest.approx(list(n), abs=1e-5)
    assert compiler.COMPILES["count"] == c0


def test_limit_and_delete(wall):
    sc, ob, mat = wall
    for i in range(naming.MAX_DECALS_PER_MATERIAL):
        decals.place(ob, "stain_01.png", (-1.2 + i * 0.15, -0.15, 1.0), (0, -1, 0), size=0.2, scene=sc)
    e, made, rep = decals.place(ob, "stain_01.png", (0, -0.15, 2.0), (0, -1, 0), size=0.2, scene=sc)
    assert not made and any("16 decal layers" in m for _, m in rep)
    n = len(mat.realworn.layers)
    first = decals.decal_layers(mat)[0].decal.empty
    first_name = first.name
    decals.delete_decal(first)
    assert len(mat.realworn.layers) == n - 1 and first_name not in bpy.data.objects


def test_bake_into_layer(wall, out_dir):
    sc, ob, mat = wall
    empty, made, _ = _place(sc, ob)
    ly, empty_name = made[0], empty.name
    before = ru.render(sc, os.path.join(out_dir, "p7_before_bake.png"))
    decals.bake_into_layer(ob, mat, ly, sc)
    ly = mat.realworn.layers[-1]
    assert ly.type == "PAINT" and ly.content_image is not None and ly.decal.empty is None
    assert empty_name not in bpy.data.objects
    after = ru.render(sc, os.path.join(out_dir, "p7_after_bake.png"))
    d = ru.mad(before, after)
    print("\n[bake] decal vs baked Paint layer MAD {:.4f}".format(d))
    assert d < 0.03


def test_remove_deletes_decals(wall):
    sc, ob, mat = wall
    empty, made, _ = _place(sc, ob)
    name = empty.name
    setup.remove_object(ob)
    assert name not in bpy.data.objects and naming.COLL_DECALS not in bpy.data.collections


def test_operator_explicit_placement(wall):
    sc, ob, mat = wall
    assert bpy.ops.realworn.decal_place(image="scrape_01.png", location=(0.4, -0.15, 1.4), normal=(0, -1, 0),
                                        size=0.3, mode="DAMAGE", object=ob.name) == {"FINISHED"}
    ly = mat.realworn.layers[-1]
    assert ly.type == "DECAL" and ly.decal.mode == "DAMAGE"

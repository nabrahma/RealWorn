"""M5 acceptance: projector decals (placement, facing fade, inheritance, modes), Auto Leaks,
the 16-decal limit, clean-up and exact removal."""

import os

import bmesh
import bpy
import numpy as np
import pytest
from mathutils import Vector

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import decals, injector, naming, nodeutil, snapshot, weathering


def _wall(scene, color=(0.5, 0.5, 0.5), name="Wall", preset="concrete"):
    bm = bmesh.new()
    ms._box(bm, (3.0, 0.3, 2.5))
    ms._subdivide(bm, 10)
    ob = ms._link(scene, name, bm, (0, 0, 1.25), ms.principled(name + "Mat", color, roughness=0.8))
    weathering.apply_object(ob, scene, preset)
    return ob


def _front(scene, out_dir, tag, res=128):
    cam = scene.camera or ms.camera_light(scene)
    ru.look_at(cam, (0, -6, 1.2), (0, 0, 1.2), ortho_scale=2.0)
    ru.setup(scene, samples=16, res=(res, res))
    return ru.render(scene, os.path.join(out_dir, tag + ".png"))


def _centre(img, frac=0.2):
    h, w = img.shape[:2]
    return img[int(h * (0.5 - frac)):int(h * (0.5 + frac)), int(w * (0.5 - frac)):int(w * (0.5 + frac))]


@pytest.fixture
def wall_scene(empty_scene):
    sc = empty_scene
    ms.camera_light(sc)
    sc.realworn.dirt = 0.3
    sc.realworn.dust = 0.0
    return sc


def test_place_full_decal_and_naming(wall_scene, out_dir):
    wall = _wall(wall_scene)
    before = _centre(_front(wall_scene, out_dir, "decal_none"))
    e, rep = decals.place(wall_scene, "poster_01.png", (0, -0.15, 1.2), (0, -1, 0), size=0.9)
    assert e.name.startswith(naming.DECAL_PREFIX + "poster_01")
    assert e.empty_display_type == "CUBE" and naming.COLL_DECALS in bpy.data.collections
    mat = wall.data.materials[0]
    assert e.name in decals.material_decals(mat)
    assert any(n.name == "RW::decal.0" for n in mat.node_tree.nodes)
    after = _centre(_front(wall_scene, out_dir, "decal_poster"))
    r_minus_g = float((after[..., 0] - after[..., 1]).mean())
    print("\n[decal] centre R-G before {:.3f}, after {:.3f}".format(float((before[..., 0] - before[..., 1]).mean()),
                                                                     r_minus_g))
    assert r_minus_g > 0.15  # the red poster shows up


def test_facing_fade_no_stretching(wall_scene, out_dir):
    """A decal box straddling the wall's side face must not paint the perpendicular face (DEC-3)."""
    _wall(wall_scene)
    e, _ = decals.place(wall_scene, "poster_01.png", (1.4, -0.15, 1.2), (0, -1, 0), size=0.9, depth=1.0)
    cam = wall_scene.camera
    ru.look_at(cam, (6, 0, 1.2), (0, 0, 1.2), ortho_scale=1.2)  # looking at the +X side face
    ru.setup(wall_scene, samples=16, res=(96, 96))
    side = ru.render(wall_scene, os.path.join(out_dir, "decal_side.png"))
    rg = float((side[..., 0] - side[..., 1]).mean())
    print("\n[facing] side face R-G {:.4f}".format(rg))
    assert rg < 0.03


def test_decal_inherits_wetness_and_dirt(wall_scene, out_dir):
    _wall(wall_scene)
    decals.place(wall_scene, "poster_01.png", (0, -0.15, 1.2), (0, -1, 0), size=0.9)
    dry = _centre(_front(wall_scene, out_dir, "decal_dry"))
    wall_scene.realworn.wetness = 0.7
    wet = _centre(_front(wall_scene, out_dir, "decal_wet"))
    print("\n[inherit] decal brightness dry {:.3f}, wet {:.3f}".format(float(dry.mean()), float(wet.mean())))
    assert wet.mean() < dry.mean() - 0.02


def test_grime_decal_is_channel_only(wall_scene, out_dir):
    _wall(wall_scene, color=(0.5, 0.5, 0.5))
    base = _centre(_front(wall_scene, out_dir, "grime_none"))
    decals.place(wall_scene, "poster_01.png", (0, -0.15, 1.2), (0, -1, 0), size=0.9, mode="GRIME")
    g = _centre(_front(wall_scene, out_dir, "grime_poster"))
    hue_shift = abs(float((g[..., 0] - g[..., 1]).mean()) - float((base[..., 0] - base[..., 1]).mean()))
    print("\n[grime] brightness {:.3f} -> {:.3f}, R-G shift {:.4f}".format(float(base.mean()), float(g.mean()),
                                                                          hue_shift))
    assert g.mean() < base.mean() - 0.03  # darkens
    assert hue_shift < 0.02                # but adds no colour of its own


def test_damage_decal_reveals_underlayer(wall_scene, out_dir):
    _wall(wall_scene, color=(0.05, 0.12, 0.45), preset="painted_metal")
    base = _centre(_front(wall_scene, out_dir, "dmg_none"), 0.08)
    decals.place(wall_scene, "bullet_01.png", (0, -0.15, 1.2), (0, -1, 0), size=0.5, mode="DAMAGE")
    hit = _centre(_front(wall_scene, out_dir, "dmg_bullet"), 0.08)
    blue = lambda im: float((im[..., 2] - im[..., 0]).mean())
    print("\n[damage] blue dominance {:.3f} -> {:.3f}".format(blue(base), blue(hit)))
    assert blue(hit) < blue(base) - 0.05  # paint chipped away to primer/steel inside the decal
    mat = bpy.data.materials["WallMat"]
    assert mat.node_tree.nodes["RW::decal_nrm.0"].image.name.startswith("bullet_01_nrm")


def test_auto_leaks_under_overhangs(empty_scene):
    sc = empty_scene
    wall = ms.wall_with_window(sc, material=ms.principled("Plaster", (0.6, 0.6, 0.58), roughness=0.9))
    weathering.apply_object(wall, sc, "concrete")
    made, rep = decals.auto_leaks(sc, [wall], seed=3, spacing=0.8)
    assert made, rep
    normals = [decals.projection_normal(e) for e in made]
    assert all(abs(n.z) < 0.1 for n in normals)  # leaks run down vertical faces
    under_sill = [e for e in made if abs(e.location.x) < 0.75 and e.location.z < 1.0
                  and decals.projection_normal(e).y < -0.9]
    print("\n[leaks] {} decals, {} under the window sill".format(len(made), len(under_sill)))
    assert under_sill
    assert all(e["rw_decal_mode"] == "GRIME" for e in made)
    assert len(decals.material_decals(wall.data.materials[0])) <= naming.MAX_DECALS_PER_MATERIAL
    # seeded: same seed, same layout
    locs = sorted(tuple(round(c, 4) for c in e.location) for e in made)
    decals.remove_all_decals()
    again, _ = decals.auto_leaks(sc, [wall], seed=3, spacing=0.8)
    assert sorted(tuple(round(c, 4) for c in e.location) for e in again) == locs


def test_decal_limit_per_material(wall_scene):
    wall = _wall(wall_scene)
    for i in range(naming.MAX_DECALS_PER_MATERIAL):
        decals.place(wall_scene, "stain_01.png", (-1.2 + i * 0.15, -0.15, 1.0), (0, -1, 0), size=0.2)
    e, rep = decals.place(wall_scene, "stain_01.png", (0, -0.15, 2.0), (0, -1, 0), size=0.2)
    assert not e["rw_targets"]
    assert any("decals already" in m for _, m in rep)
    assert len(decals.material_decals(wall.data.materials[0])) == naming.MAX_DECALS_PER_MATERIAL


def test_cleanup_and_exact_remove(wall_scene):
    wall = _wall(wall_scene)
    mat = wall.data.materials[0]
    weathering.remove_object(wall, wall_scene)
    original = snapshot.serialize(mat.node_tree)
    weathering.apply_object(wall, wall_scene, "concrete")
    a, _ = decals.place(wall_scene, "poster_01.png", (0, -0.15, 1.2), (0, -1, 0))
    b, _ = decals.place(wall_scene, "soot_01.png", (0.8, -0.15, 1.6), (0, -1, 0), mode="GRIME")
    a_name = a.name
    bpy.data.objects.remove(a)  # user deletes the Empty
    decals.cleanup()
    assert decals.material_decals(mat) == [b.name]
    assert not any(n.get("rw_decal") == a_name for n in mat.node_tree.nodes)
    # move decal b away from the wall and re-target
    b.location = (10, 10, 10)
    decals.cleanup(wall_scene, retarget=True)
    assert decals.material_decals(mat) == []
    weathering.remove_object(wall, wall_scene)
    assert snapshot.diff(original, snapshot.serialize(mat.node_tree)) == []
    weathering.remove_all()
    assert not decals.decal_objects() and naming.COLL_DECALS not in bpy.data.collections


def test_shared_material_reports_other_users(wall_scene):
    shared = ms.principled("SharedWall")
    a = ms.sharp_cube(wall_scene, name="A", cuts=4, material=shared)
    b = ms.sharp_cube(wall_scene, name="B", cuts=4, location=(5, 0, 1), material=shared)
    for o in (a, b):
        weathering.apply_object(o, wall_scene, "concrete")
    e, rep = decals.place(wall_scene, "stain_01.png", (0, -1.0, 1.0), (0, -1, 0), size=0.5)
    assert e["rw_targets"] == ["SharedWall"]
    assert any("also used by B" in m for _, m in rep)

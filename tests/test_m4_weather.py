"""M4 acceptance: scene sliders without drivers, wetness states, puddles, dust/splash/streak
placement, shelter, rain ripples, property sync across save/reload."""

import os

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import naming, weather, weathering


def _mean(v, m):
    return float(v[m].mean()) if m.any() else float("nan")


def _box(scene, name, size, loc, mat_color=(0.5, 0.5, 0.5)):
    bm = bmesh.new()
    ms._box(bm, size)
    ms._subdivide(bm, 8)
    return ms._link(scene, name, bm, loc, ms.principled(name + "Mat", mat_color, roughness=0.8))


@pytest.fixture
def yard(empty_scene):
    """Ground slab, a box on it, a tall wall, a roof over part of the ground, a camera."""
    sc = empty_scene
    ground = ms.street(sc, size=(8.0, 8.0), tiles=8, material=ms.principled("GroundMat", (0.3, 0.3, 0.3)))
    box = _box(sc, "Box", (1.0, 1.0, 1.0), (-2.0, 0.0, 0.5))
    wall = _box(sc, "Wall", (3.0, 0.3, 3.0), (2.0, 3.0, 1.5))
    roof = _box(sc, "Roof", (2.0, 2.0, 0.1), (-2.0, -2.5, 2.5))
    ms.camera_light(sc)
    for o in (ground, box, wall):
        weathering.apply_object(o, sc, "concrete")
    weather.mark_ground(ground, sc)
    weather.mark_occluder(roof)
    sc.realworn.dirt = 0.8
    sc.realworn.dust = 0.8
    sc.realworn.age = 0.6
    return dict(scene=sc, ground=ground, box=box, wall=wall, roof=roof)


def _drivers():
    out = []
    for coll in (bpy.data.node_groups, bpy.data.materials, bpy.data.objects, bpy.data.scenes, bpy.data.meshes):
        for idb in coll:
            for ad in (getattr(idb, "animation_data", None),
                       getattr(getattr(idb, "node_tree", None), "animation_data", None)):
                if ad is not None:
                    out += [(idb.name, d.data_path) for d in ad.drivers]
    return out


def test_no_drivers_except_shared_time(yard):
    yard["scene"].realworn.wetness = 0.9  # full wetness group in use
    drv = _drivers()
    assert {d[0] for d in drv} == {naming.SH_L_WET}, drv
    assert len(drv) == 1  # one per file, shared by every material (WX-8)


def test_sliders_mirror_to_custom_properties(yard):
    sc = yard["scene"]
    for prop, key, val in (("age", naming.SC_AGE, 0.33), ("dirt", naming.SC_DIRT, 0.66),
                           ("dust", naming.SC_DUST, 0.11), ("wetness", naming.SC_WETNESS, 0.77)):
        setattr(sc.realworn, prop, val)
        assert sc[key] == pytest.approx(val)
    sc.realworn.rain = True
    assert sc[naming.SC_RAIN] == 1.0
    assert yard["ground"][naming.OB_GROUND] == 1.0
    assert sc[naming.SC_GROUND_Z] == pytest.approx(-0.01, abs=1e-3)  # lowest point of the ground grooves


def test_wet_variant_follows_sliders(yard):
    sc = yard["scene"]
    node = bpy.data.node_groups[naming.SH_STACK].nodes[naming.STACK_WET_NODE]
    sc.realworn.wetness = 0.0
    sc.realworn.rain = False
    assert node.node_tree.name == naming.SH_L_WET_DRY
    sc.realworn.wetness = 0.2
    assert node.node_tree.name == naming.SH_L_WET
    sc.realworn.wetness = 0.0
    sc.realworn.rain = True
    assert node.node_tree.name == naming.SH_L_WET


def test_sync_survives_save_and_reload(yard, out_dir):
    sc = yard["scene"]
    sc.realworn.wetness = 0.42
    sc[naming.SC_WETNESS] = 0.0  # out of sync on purpose, then save and reload
    path = os.path.join(out_dir, "sync.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    assert sc.realworn.wetness == pytest.approx(0.42)
    assert sc[naming.SC_WETNESS] == pytest.approx(0.42)  # load handler re-synced it


def test_dust_only_on_up_faces(yard, out_dir):
    sc = yard["scene"]
    top, cov_t = ru.preview(sc, "DUST", os.path.join(out_dir, "dust_top"), (-2, 0, 5), (-2, 0, 0), 0.9)
    side, cov_s = ru.preview(sc, "DUST", os.path.join(out_dir, "dust_side"), (-2, -5, 0.5), (-2, 0, 0.5), 0.9)
    print("\n[dust] top face {:.3f}, side face {:.3f}".format(_mean(top, cov_t), _mean(side, cov_s)))
    assert _mean(top, cov_t) > 0.2
    assert _mean(side, cov_s) < 0.02


def test_splash_grime_near_ground_and_streaks_on_vertical(yard, out_dir):
    sc = yard["scene"]
    g, cov = ru.preview(sc, "GRIME", os.path.join(out_dir, "grime_wall"), (2, -5, 1.4), (2, 3, 1.4), 2.8)
    rows = np.array([_mean(g[r], cov[r]) for r in range(g.shape[0])])  # row 0 = bottom of the image
    px = 2.8 / g.shape[0]
    first = int(np.argmax(cov.any(axis=1)))  # first row where the wall starts
    low = np.nanmean(rows[first:first + int(0.3 / px)])
    high = np.nanmean(rows[first + int(1.0 / px):])
    print("\n[splash] wall grime bottom 0.3 m {:.3f}, above 1 m {:.3f}".format(low, high))
    assert low > 0.15 and high < 0.02
    s, cov = ru.preview(sc, "STREAK", os.path.join(out_dir, "streak_wall"), (2, -5, 1.5), (2, 3, 1.5), 2.8)
    t, cov_t = ru.preview(sc, "STREAK", os.path.join(out_dir, "streak_top"), (-2, 0, 5), (-2, 0, 0), 0.9)
    print("[streak] wall {:.3f}, box top {:.3f}".format(_mean(s, cov), _mean(t, cov_t)))
    assert _mean(s, cov) > 0.03 and _mean(t, cov_t) == pytest.approx(0.0, abs=1e-4)


def test_wetness_states_and_puddles(yard, out_dir):
    sc = yard["scene"]
    view = ((0, 0, 8), (0, 0, 0), 8.0)
    covs = {}
    for w in (0.0, 0.3, 0.55, 0.75, 1.0):
        sc.realworn.wetness = w
        p, cov = ru.preview(sc, "PUDDLE", os.path.join(out_dir, "puddle_{:.2f}".format(w)), *view)
        covs[w] = float((p[cov] > 0.5).mean())
    print("\n[puddles] coverage by wetness", {k: round(v, 3) for k, v in covs.items()})
    assert covs[0.0] == 0 and covs[0.3] == 0 and covs[0.55] == 0  # no standing water below 0.6
    assert 0 < covs[0.75] < covs[1.0]                              # low areas first, then broad sheets
    sc.realworn.wetness = 1.0
    p, cov = ru.preview(sc, "PUDDLE", os.path.join(out_dir, "puddle_box"), (-2, 0, 5), (-2, 0, 0), 0.9)
    assert _mean(p, cov) < 1e-3  # the (non-ground) box top never holds water
    w_sh, cov = ru.preview(sc, "WETNESS", os.path.join(out_dir, "wet_shelter"), (-2, -2.5, 2.3), (-2, -2.5, 0), 1.2)
    print("[shelter] wetness on the ground under the roof {:.3f}".format(_mean(w_sh, cov)))
    assert _mean(w_sh, cov) < 0.05


def test_puddles_only_on_near_flat_faces(empty_scene, out_dir):
    sc = empty_scene
    ramp = _box(sc, "Ramp", (4.0, 4.0, 0.1), (0, 0, 0))
    ramp.rotation_euler = (0.5, 0, 0)  # ~29 degrees
    ms.camera_light(sc)
    weathering.apply_object(ramp, sc, "concrete")
    weather.mark_ground(ramp, sc)
    sc.realworn.wetness = 1.0
    p, cov = ru.preview(sc, "PUDDLE", os.path.join(out_dir, "puddle_ramp"), (0, -3, 3), (0, 0, 0), 4.0)
    assert _mean(p, cov) < 1e-3


def test_low_areas_flood_first(empty_scene, out_dir):
    """With a height texture (gradient in X), puddles appear on the low side first (WX-3/WX-4)."""
    sc = empty_scene
    mat = ms.principled("Graded", (0.4, 0.4, 0.4))
    nt = mat.node_tree
    tc, grad = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeTexGradient")
    disp = nt.nodes.new("ShaderNodeDisplacement")
    disp.inputs["Scale"].default_value = 0.0
    nt.links.new(tc.outputs["Generated"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], disp.inputs["Height"])
    nt.links.new(disp.outputs[0], nt.nodes["Material Output"].inputs["Displacement"])
    ground = ms.street(sc, size=(6.0, 6.0), tiles=6, material=mat)
    ms.camera_light(sc)
    weathering.apply_object(ground, sc, "concrete")
    weather.mark_ground(ground, sc)
    sc.realworn.wetness = 0.78
    p, cov = ru.preview(sc, "PUDDLE", os.path.join(out_dir, "puddle_gradient"), (0, 0, 8), (0, 0, 0), 6.0)
    half = p.shape[1] // 2
    low, high = _mean(p[:, :half], cov[:, :half]), _mean(p[:, half:], cov[:, half:])
    print("\n[low-first] puddle on low side {:.3f}, high side {:.3f}".format(low, high))
    assert low > high + 0.1


def test_wetness_darkens_porous_and_rain_animates(yard, out_dir):
    sc = yard["scene"]
    sc.camera.data.type = "PERSP"
    ru.setup(sc, samples=16, res=(96, 96))
    ru.look_at(sc.camera, (2, -3, 1.0), (2, 3, 1.0))
    vals = []
    for w in (0.0, 0.3, 0.7):
        sc.realworn.wetness = w
        img = ru.render(sc, os.path.join(out_dir, "wall_wet_{}.png".format(w)))
        vals.append(float(img.mean()))
    print("\n[states] wall brightness at wetness 0 / 0.3 / 0.7:", [round(v, 4) for v in vals])
    assert vals[0] > vals[1] > vals[2]
    # rain: ripples animate the puddle coat normal; nothing animates without rain
    sc.realworn.wetness = 1.0
    wnt = sc.world.node_tree  # a checkered sky: ripples only show through what water reflects
    chk = wnt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 12.0
    tcw = wnt.nodes.new("ShaderNodeTexCoord")
    wnt.links.new(tcw.outputs["Generated"], chk.inputs["Vector"])
    wnt.links.new(chk.outputs["Color"], wnt.nodes["Background"].inputs["Color"])
    ru.look_at(sc.camera, (0.5, -1.2, 1.2), (0.5, 0.6, 0.0))
    ru.setup(sc, samples=16, res=(192, 192))
    frames = {}
    for rain in (False, True):
        sc.realworn.rain = rain
        imgs = []
        for f in (1, 13):
            sc.frame_set(f)
            imgs.append(ru.render(sc, os.path.join(out_dir, "rain_{}_{}.png".format(rain, f))))
        diff = np.abs(imgs[0] - imgs[1]).mean(axis=2)
        frames[rain] = (float(diff.mean()), float((diff > 0.01).mean()))
    print("[rain] frame 1 vs 13: rain off mean {:.5f} / changed px {:.3f}; rain on mean {:.5f} / changed px {:.3f}"
          .format(*frames[False], *frames[True]))
    assert frames[False][0] < 1e-5
    assert frames[True][1] > 0.01  # ripples visibly change at least 1% of the puddle pixels

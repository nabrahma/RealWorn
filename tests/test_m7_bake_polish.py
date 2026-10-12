"""M7 acceptance: Bake + Restore Live Stack, baked render cost, Validate Scene, Rainy Night
preset, and the 20x apply/tweak/remove stress cycle from the success criteria."""

import os
import time

import bmesh
import bpy
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import (bake, damage, decals, injector, masks, naming, nodeutil, snapshot, validate,
                           weathering)


def _uv_cube(scene, name="UVCube", size=1.0, loc=(0, 0, 0.5), color=(0.1, 0.25, 0.5)):
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=size, calc_uvs=True)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=8, use_grid_fill=True)
    return ms._link(scene, name, bm, loc, ms.principled(name + "Mat", color, roughness=0.45))


def test_bake_swap_and_restore(empty_scene, out_dir):
    sc = empty_scene
    ob = _uv_cube(sc)
    ms.camera_light(sc, cam_loc=(2.2, -2.4, 1.8), target=(0, 0, 0.45))
    weathering.apply_object(ob, sc, "painted_metal")
    sc["rw_age"] = 0.9
    ru.setup(sc, samples=16, res=(128, 128))
    live = ru.render(sc, os.path.join(out_dir, "bake_live.png"))
    mat = ob.data.materials[0]
    t = time.perf_counter()
    imgs = bake.bake_object(ob, sc, resolution=256, folder=os.path.join(out_dir, "bake"))
    dt = time.perf_counter() - t
    record("Bake one object, 256 px, 9 images (CPU)", dt, "s", None)
    assert set(imgs) == {"base_color", "roughness", "metallic", "normal", naming.ATTR_EDGE, naming.ATTR_CAVITY,
                         naming.ATTR_CONTACT, naming.ATTR_DAMAGE}
    for key, img in imgs.items():
        assert os.path.exists(bpy.path.abspath(img.filepath_raw)), key
    import numpy as np
    px = np.empty(256 * 256 * 4, np.float32)
    imgs[naming.ATTR_EDGE].pixels.foreach_get(px)
    assert px[0::4].max() > 0.9 and px[0::4].mean() < 0.5  # a real edge mask, not blank or full
    assert mat.realworn.baked
    p = mat.node_tree.nodes["Principled BSDF"]
    assert p.inputs["Base Color"].links[0].from_node.name == "RW::bake_img.base_color"
    assert p.inputs["Normal"].links[0].from_node.name == "RW::bake_nmap"
    baked = ru.render(sc, os.path.join(out_dir, "bake_baked.png"))
    d_baked = ru.mad(live, baked)
    bake.restore_live(mat)
    restored = ru.render(sc, os.path.join(out_dir, "bake_restored.png"))
    print("\n[bake] {:.1f} s; live vs baked MAD {:.4f}; live vs restored {:.5f}".format(dt, d_baked,
                                                                                      ru.mad(live, restored)))
    assert d_baked < 0.03
    assert ru.mad(live, restored) < 1e-4
    assert not mat.realworn.baked
    # Remove after a bake still restores the original material exactly
    bake.bake_object(ob, sc, resolution=64, folder=os.path.join(out_dir, "bake"), masks=False)
    assert injector.remove(mat) == []
    assert not nodeutil.owned_nodes(mat.node_tree)


def test_bake_refuses_without_uvs(empty_scene):
    ob = ms.sharp_cube(empty_scene, cuts=2, material=ms.principled("NoUV"))
    weathering.apply_object(ob, empty_scene)
    with pytest.raises(bake.BakeError, match="UV"):
        bake.bake_object(ob, empty_scene, resolution=32)


def test_baked_render_overhead(empty_scene, out_dir):
    """Render speed path: baked materials should cost about the same as clean ones."""
    sc = empty_scene
    obs = [_uv_cube(sc, "B%d" % i, 0.8, ((i % 3) * 1.1 - 1.1, (i // 3) * 1.1, 0.4)) for i in range(6)]
    ms.camera_light(sc, cam_loc=(3.5, -4.0, 3.0), target=(0, 0.5, 0.3))
    ru.setup(sc, samples=64, res=(480, 480))
    # renders take ~0.6 s, so take the best of 3 to keep background load out of the ratio
    clean = min(_timed_render(sc, os.path.join(out_dir, "ovh_clean.png")) for _ in range(3))
    for o in obs:
        weathering.apply_object(o, sc, "painted_metal")
    live = min(_timed_render(sc, os.path.join(out_dir, "ovh_live.png")) for _ in range(3))
    for o in obs:
        bake.bake_object(o, sc, resolution=256, folder=os.path.join(out_dir, "bake"), masks=False)
    ru.setup(sc, samples=64, res=(480, 480))
    baked = min(_timed_render(sc, os.path.join(out_dir, "ovh_baked.png")) for _ in range(3))
    ov_live, ov_baked = (live - clean) / clean * 100, (baked - clean) / clean * 100
    print("\n[overhead] clean {:.2f} s, live {:.2f} s (+{:.0f}%), baked {:.2f} s (+{:.0f}%)".format(
        clean, live, ov_live, baked, ov_baked))
    record("Cycles render overhead, baked materials (6 cubes, 480 px, 64 spp, CPU)", ov_baked, "%", 25,
           "after Bake; live stack on the same scene was +{:.0f}%".format(ov_live))
    assert ov_baked < 25


def _timed_render(sc, path):
    t = time.perf_counter()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return time.perf_counter() - t


def test_validate_scene(empty_scene):
    sc = empty_scene
    floor, obs = ms.demo_props(sc)
    for o in [floor] + obs:
        weathering.apply_object(o, sc)
    masks.mark_ground(floor)
    issues = validate.validate(sc)
    assert not [i for i in issues if i[0] == "ERROR"], issues
    stray = ms.principled("Stray")
    nodeutil.new(stray.node_tree, "ShaderNodeValue", "leftover")
    assert any("orphan" in m for _, m in validate.validate(sc))


def test_twenty_apply_tweak_remove_cycles(empty_scene):
    """Success criterion 2: 20 cycles on a production-like scene, no crash, no leftover node."""
    sc = empty_scene
    d = ms.demo_alley(sc)
    meshes = [d["floor"], d["kerb"]] + d["walls"] + [d["roof"]] + d["crates"]
    originals = {m.name: snapshot.dumps(snapshot.serialize(m.node_tree)) for m in bpy.data.materials}
    t = time.perf_counter()
    for i in range(20):
        for o in meshes:
            weathering.apply_object(o, sc, ("AUTO", "concrete", "painted_metal", "wood")[i % 4])
        masks.mark_ground(d["floor"])
        for o in meshes:
            weathering.update_object(o, sc, "plastic" if i % 3 == 0 else None)
        if i % 4 == 0:
            decals.place(sc, "stain_01.png", (0, 2.47, 1.5), (0, -1, 0), size=0.5, mode="GRIME")
            damage.add_damage(d["kerb"], sc, {"Strength": 0.4, "Seed": i})
        bpy.context.evaluated_depsgraph_get().update()
        if i % 2:
            for o in meshes:
                weathering.remove_object(o, sc)
            decals.remove_all_decals()
        else:
            weathering.remove_all()
    dt = time.perf_counter() - t
    print("\n[stress] 20 apply/tweak/remove cycles on the alley: {:.1f} s".format(dt))
    for m in bpy.data.materials:
        if m.name in originals:
            assert snapshot.dumps(snapshot.serialize(m.node_tree)) == originals[m.name], m.name
        assert not nodeutil.owned_nodes(m.node_tree), m.name
    assert not [o for o in sc.objects if o.modifiers]
    weathering.remove_all()
    assert not [g for g in bpy.data.node_groups if g.name.startswith("RW_")]

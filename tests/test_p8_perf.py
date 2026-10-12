"""Suite 10 (PRD v2 "Compatibility and performance"): Cycles overhead of 4 typical painted layers
(budget +40%), after Bake (+15%), mask memory for 8 layers at 2048 px (200 MB). Setup, add-layer
compile and slider-without-recompile budgets are measured in test_p1_setup.py; EEVEE recompile and
viewport FPS are measured in an interactive session. Run with the live Blender idle: a
viewport rendering Cycles at the same time skews every timing here."""

import os
import time

import bpy
import numpy as np

import render_util as ru
from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import bake, grunge, images, layers, naming, setup
from test_p1_setup import uv_cube


def _render(sc, path):
    t = time.perf_counter()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return time.perf_counter() - t


def _best(sc, path, n=3):
    return min(_render(sc, path) for _ in range(n))


def _typical_layers(ob, mat):
    """Dirt (cavity-free painted band), Wear (edge-locked), Rust (tinted grunge fill), Water patch."""
    for kind, band in (("DIRT", 0), ("WEAR", 1), ("RUST", 2), ("WATER", 3)):
        ly = layers.add_layer(mat, kind)
        ly.mask_res = 512
        img = images.ensure_mask(ob, mat, ly)
        px = np.zeros((512, 512, 4), np.float32)
        px[:, band * 128:(band + 1) * 128 + 40] = 1.0
        img.pixels.foreach_set(px.ravel())
        img.update()
        if kind == "RUST":
            grunge.use("FILL", "rust_spots", ob, mat, ly, amount=0.4, scale=0.4)


def test_cycles_overhead_live_and_baked(empty_scene, out_dir):
    sc = empty_scene
    obs = [uv_cube(sc, "Q%d" % i, size=0.8, cuts=6, loc=((i % 3) * 1.1 - 1.1, (i // 3) * 1.1, 0.4),
                   material=GENERATED["image_based"]()) for i in range(6)]
    ms.camera_light(sc, cam_loc=(3.5, -4.0, 3.0), target=(0, 0.5, 0.3))
    ru.setup(sc, samples=128, res=(640, 640))  # ~1 s renders: per-render fixed costs stay small
    clean = _best(sc, os.path.join(out_dir, "p8_ovh_clean.png"))
    for o in obs:
        setup.setup_object(o)
        _typical_layers(o, o.material_slots[0].material)
    live = _best(sc, os.path.join(out_dir, "p8_ovh_live.png"))
    for o in obs:
        bake.bake_material(o, o.material_slots[0].material, sc, resolution=256,
                           folder=os.path.join(out_dir, "p8_ovh_bake"))
    ru.setup(sc, samples=128, res=(640, 640))
    baked = _best(sc, os.path.join(out_dir, "p8_ovh_baked.png"))
    ov_live, ov_baked = (live - clean) / clean * 100, (baked - clean) / clean * 100
    print("\n[overhead] clean {:.2f} s, 4 layers live {:.2f} s (+{:.0f}%), baked {:.2f} s (+{:.0f}%)".format(
        clean, live, ov_live, baked, ov_baked))
    record("v2 Cycles overhead, 4 typical layers (6 objects, 640 px, 128 spp, CPU)", ov_live, "%", 40,
           "best of 3; Dirt, edge-locked Wear, Rust with grunge fill, Water")
    record("v2 Cycles overhead after Bake (same scene)", ov_baked, "%", 15, "best of 3")
    assert ov_live < 40
    assert ov_baked < 15


def test_mask_memory_eight_layers(empty_scene):
    ob = uv_cube(empty_scene, "M", size=2.0, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    for i in range(8):
        ly = layers.add_layer(mat, "CUSTOM")
        ly.mask_res = 2048
        images.ensure_mask(ob, mat, ly)
    total = sum(img.size[0] * img.size[1] * img.channels * (4 if img.is_float else 1)
                for img in bpy.data.images if img.get(naming.IMG_MASK))
    mb = total / 1024 / 1024
    print("\n[memory] 8 masks at 2048 px: {:.0f} MB".format(mb))
    record("v2 Mask memory, 8 layers at 2048 px", mb, "MB", 200, "8-bit RGBA masks (uncompressed in RAM)")
    assert mb < 200

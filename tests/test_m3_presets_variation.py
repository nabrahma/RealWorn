"""M3 acceptance: presets differ visibly, duplicates vary, paint override adds/removes wear."""

import itertools
import os

import bpy

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import injector, paint, presets, weathering


def _cube_scene(scene, name="PresetCube"):
    ob = ms.bevel_cube(scene, name=name, size=1.0, bevel=0.02, cuts=10, location=(0, 0, 0.5),
                       material=ms.principled(name + "Mat", (0.15, 0.3, 0.55), roughness=0.4))
    ms.camera_light(scene, cam_loc=(2.0, -2.2, 1.7), target=(0, 0, 0.45), lens=50)
    scene["rw_age"] = 0.8
    scene["rw_dirt"] = 0.7
    scene["rw_dust"] = 0.5
    return ob


def test_six_presets_visibly_different(empty_scene, out_dir):
    ob = _cube_scene(empty_scene)
    weathering.apply_object(ob, empty_scene, "AUTO")
    ru.setup(empty_scene, samples=16, res=(128, 128))
    imgs = {}
    for pid in presets.USER_PRESETS + ("AUTO",):
        weathering.update_object(ob, empty_scene, pid)
        imgs[pid] = ru.render(empty_scene, os.path.join(out_dir, "preset_{}.png".format(pid)))
    ru.save_sheet([imgs[p] for p in presets.USER_PRESETS + ("AUTO",)], os.path.join(out_dir, "presets_sheet.png"))
    pairs = {}
    for a, b in itertools.combinations(presets.USER_PRESETS, 2):
        pairs[(a, b)] = ru.mad(imgs[a], imgs[b])
    print("\n[presets] min pairwise MAD {:.4f} {}".format(min(pairs.values()), min(pairs, key=pairs.get)))
    assert min(pairs.values()) > 0.004
    auto = injector.resolve_preset(ob.data.materials[0], "AUTO", ob.name)
    assert ru.mad(imgs["AUTO"], imgs[auto]) < 1e-4  # Auto is exactly the preset it picks


def test_ten_duplicates_wear_differently(empty_scene, out_dir):
    src = ms.crate(empty_scene, name="Crate", material=ms.principled("CrateMat", (0.12, 0.3, 0.16), roughness=0.45),
                   location=(0, 0, 0.5))
    crates = [src]
    for i in range(1, 10):
        c = src.copy()  # shares mesh and material, like Alt+D
        c.location.x = i * 1.25
        empty_scene.collection.objects.link(c)
        crates.append(c)
    for c in crates:
        weathering.apply_object(c, empty_scene, "painted_metal")
    assert len({c.realworn.seed for c in crates}) == 10
    cam = ms.camera_light(empty_scene)
    ru.look_at(cam, (5.625, -6, 0.5), (5.625, 0, 0.5), ortho_scale=12.6)
    empty_scene["rw_age"] = 0.9
    ru.setup(empty_scene, samples=16, res=(1000, 120))
    img = ru.render(empty_scene, os.path.join(out_dir, "ten_crates.png"))
    w = img.shape[1] / 10.08  # 12.6 m / 1.25 m per crate
    crops = [img[20:100, int(i * w + 0.12 * w):int(i * w + 0.88 * w)] for i in range(10)]
    n = min(c.shape[1] for c in crops)
    crops = [c[:, :n] for c in crops]
    diffs = [ru.mad(a, b) for a, b in itertools.combinations(crops, 2)]
    print("\n[duplicates] pairwise crop MAD min {:.4f} mean {:.4f}".format(min(diffs), sum(diffs) / len(diffs)))
    assert min(diffs) > 0.002


def test_paint_adds_and_removes_wear(empty_scene, out_dir):
    ob = _cube_scene(empty_scene, "PaintCube")
    ru.setup(empty_scene, samples=16, res=(128, 128))
    clean = ru.render(empty_scene, os.path.join(out_dir, "paint_clean.png"))
    weathering.apply_object(ob, empty_scene, "painted_metal")
    default = ru.render(empty_scene, os.path.join(out_dir, "paint_default.png"))
    paint.fill(ob.data, (1.0, 0.0, 0.0))
    red = ru.render(empty_scene, os.path.join(out_dir, "paint_red.png"))
    paint.fill(ob.data, (0.0, 0.0, 1.0))
    blue = ru.render(empty_scene, os.path.join(out_dir, "paint_blue.png"))
    d_def, d_red, d_blue = ru.mad(default, clean), ru.mad(red, default), ru.mad(blue, clean)
    print("\n[paint] weathered vs clean {:.4f}, red vs weathered {:.4f}, blue vs clean {:.4f}".format(
        d_def, d_red, d_blue))
    assert d_def > 0.005     # weathering is visible (mean over a frame that is mostly background)
    assert d_red > 0.02      # red forces wear everywhere
    assert d_blue < 0.003    # blue removes layers 2-6: back to the clean look (dry scene)

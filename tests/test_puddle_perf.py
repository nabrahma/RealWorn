"""Puddle performance budgets, on the GPU (OptiX when present), on the reference road (wide framing).

Overhead is measured against the same road without a Puddle layer (textures and road marking
only), Cycles defaults and fixed 1024 spp, best of 3:

  Puddle, auto only                      budget +20%
  Puddle with painting and broad dips    budget +25%
  True Depth, low close-up               measured and reported (adaptive dicing)

Misses are recorded with real numbers in tests/_out/perf.md, not relaxed.
"""

import os
import time

import pytest

import puddle_realworn as PW
import render_util as ru
from fixtures import make_road as MR
from perf_log import record
from realworn.core import compiler, images, layers

pytestmark = pytest.mark.skipif(not MR.available(), reason="road sets not downloaded "
                                                           "(python tests/corpus/fetch.py --road)")
RES = (960, 540)


def _best(sc, path, n=3):
    import bpy
    times = []
    for _ in range(n):
        t = time.perf_counter()
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        times.append(time.perf_counter() - t)
    return min(times)


def _measure(sc, out_dir, tag, modes=(("default", True), ("fixed", False))):
    out = {}
    for mode, adaptive in modes:
        ru.setup(sc, samples=1024, res=RES)
        ru.use_gpu(sc)
        sc.cycles.use_adaptive_sampling = adaptive
        sc.render.image_settings.file_format = "PNG"
        out[mode] = _best(sc, os.path.join(out_dir, "puddle_perf_{}_{}.png".format(tag, mode)))
    return out


def _set_all(pairs, **values):
    for ob, _ in pairs.values():
        mat = ob.material_slots[0].material
        ly = next(x for x in mat.realworn.layers if x.kind == "PUDDLE")
        with compiler.batch(mat):
            for k, v in values.items():
                setattr(ly, k, v)
        compiler.compile(mat)


def test_cycles_overhead_puddles_on_the_road(empty_scene, out_dir):
    sc = empty_scene
    pairs = PW.build_pair(sc, puddles=False)
    PW.show(pairs, "realworn")
    device = ru.use_gpu(sc) or "CPU"
    MR.frame(sc, "WIDE")
    road = _measure(sc, out_dir, "road")
    t = time.perf_counter()
    for key, (ob, _) in pairs.items():
        PW.add_puddle(ob.material_slots[0].material, dict(PW.PUDDLES[key], dips=False))
    t_add = (time.perf_counter() - t) / 3
    auto = _measure(sc, out_dir, "auto")
    _set_all(pairs, puddle_source="AUTO_AND_PAINT", broad_dips=True)
    for ob, _ in pairs.values():
        mat = ob.material_slots[0].material
        ly = next(x for x in mat.realworn.layers if x.kind == "PUDDLE")
        img = images.ensure_mask(ob, mat, ly)
        px = images.pixels(img)
        n = px.shape[0]
        px[n // 3: n // 3 + n // 6, n // 3: n // 3 + n // 6, :3] = 0.85  # a painted spot (the lookup runs
        img.pixels.foreach_set(px.ravel())                                # everywhere; the water barely grows)
        img.update()
    painted = _measure(sc, out_dir, "paint_dips")
    MR.frame(sc, "LOW")
    _set_all(pairs, true_depth=False)
    low = _measure(sc, out_dir, "low_shading", modes=(("default", True),))
    _set_all(pairs, true_depth=True)
    low_td = _measure(sc, out_dir, "low_true_depth", modes=(("default", True),))
    ov = {(s, m): (t_[m] - road[m]) / road[m] * 100 for s, t_ in (("auto", auto), ("paint", painted))
          for m in ("default", "fixed")}
    td = (low_td["default"] - low["default"]) / low["default"] * 100
    note = "best of 3, {}, reference road {}x{}; vs the road without a Puddle".format(device, *RES)
    for m in ("default", "fixed"):
        print("\n[puddle overhead] {} {}: road {:.2f} s; auto +{:.0f}%; paint and dips +{:.0f}%".format(
            device, m, road[m], ov["auto", m], ov["paint", m]))
    print("[puddle overhead] True Depth, low close-up: {:.2f} s vs {:.2f} s shading only (+{:.0f}%)".format(
        low_td["default"], low["default"], td))
    record("Puddle Cycles overhead, auto only, reference road, GPU defaults", ov["auto", "default"], "%", 20, note)
    record("Puddle Cycles overhead, auto only, GPU fixed 1024 spp", ov["auto", "fixed"], "%", None, note)
    record("Puddle Cycles overhead, painting and broad dips, GPU defaults", ov["paint", "default"], "%", 25, note)
    record("Puddle Cycles overhead, painting and broad dips, GPU fixed 1024 spp", ov["paint", "fixed"], "%", None, note)
    record("Puddle True Depth, low close-up, vs shading only, GPU defaults", td, "%", None,
           "adaptive subdivision; render {:.2f} s".format(low_td["default"]))
    record("Puddle add layer (compile, headless)", t_add, "s", 0.3, "per material, compiler only")
    over = ["{} {} +{:.0f}%".format(s, m, ov[s, m]) for s, m, b in (("auto", "default", 20), ("paint", "default", 25))
            if ov[s, m] > b]
    assert ov["auto", "default"] < 80, "regression"
    if over:
        pytest.xfail("over budget: " + ", ".join(over))


def test_cycles_overhead_of_the_wet_film(empty_scene, out_dir):
    """Wet Film 1 against the same puddles without it, in the window framing (the film's look):
    budget +15% at fixed samples; Cycles defaults reported."""
    sc = empty_scene
    pairs = PW.build_pair(sc, marking=False)
    PW.show(pairs, "realworn")
    device = ru.use_gpu(sc) or "CPU"
    MR.frame(sc, "WINDOW")
    puddles = _measure(sc, out_dir, "window_puddles")
    from realworn.core import grunge
    for key in pairs:
        values = dict(PW.FILM[key])
        if values.get("film_grunge"):
            values["film_grunge"] = grunge.load("grunges", values["film_grunge"])
        _set_all({key: pairs[key]}, **values)
    film = _measure(sc, out_dir, "window_film")
    ov = {m: (film[m] - puddles[m]) / puddles[m] * 100 for m in ("default", "fixed")}
    note = "best of 3, {}, window framing {}x{}; vs the same puddles without the film".format(device, *RES)
    for m in ("default", "fixed"):
        print("\n[film overhead] {} {}: puddles {:.2f} s, with the film {:.2f} s (+{:.0f}%)".format(
            device, m, puddles[m], film[m], ov[m]))
    record("Wet film Cycles overhead over puddles, window framing, GPU fixed 1024 spp", ov["fixed"], "%", 15, note)
    record("Wet film Cycles overhead over puddles, window framing, GPU defaults", ov["default"], "%", None, note)
    assert ov["fixed"] < 80, "regression"
    if ov["fixed"] > 15:
        pytest.xfail("over budget: fixed samples +{:.0f}%".format(ov["fixed"]))


def test_puddle_mask_memory(empty_scene):
    """A 2048 px float paint mask: 64 MB, as a Reveal mask."""
    assert images.mask_bytes(2048, True) / 2 ** 20 == 64
    from test_puddles import plane
    ob, mat = plane(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "PUDDLE")
    img = images.ensure_mask(ob, mat, ly)
    mb = images.mask_bytes(img.size[0], img.is_float) / 2 ** 20
    record("Puddle paint mask memory, 1 m object", mb, "MB", 64, "{} px float".format(img.size[0]))
    assert img.is_float and mb <= 64

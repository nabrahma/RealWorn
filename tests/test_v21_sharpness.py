"""PRD v2.1 sharpness acceptance (T1, T2) on the close-up of S1: a 30 cm crate, camera 30 cm from
its front face, 1920 x 1080 Mask View renders (EEVEE, 32-bit EXR), edge width W from
tests/metrics.py. Q0 records the v2.0 baseline (Edge Detail does not exist / is off)."""

import os

import pytest

import sharp_util as su
from metrics import edge_report
from perf_log import record
from realworn.core import layers

FACE = (0.0, -0.15, 0.15)  # centre of the crate's front face (crate 0.3 m, standing on the origin)


@pytest.fixture
def closeup(empty_scene):
    sc = empty_scene
    base = su.corpus_material("metal_plate")
    ob, mat = su.crate(sc, material=base)
    su.closeup_camera(sc, target=FACE)
    su.setup_render(sc)
    return sc, ob, mat


def _w(sc, mat, idx, out_dir, tag):
    img = su.render_mask_view(sc, mat, idx, os.path.join(out_dir, "v21_{}.exr".format(tag)))
    return edge_report(su.crop(img, 0.9))


# ------------------------------------------------------------------ T1
def t1_stroke(ob, res):
    """A 4 cm disk whose soft edge is 3 mask texels wide: the softness of a brush stroke painted
    at that mask resolution, so physically 4x wider at 512 px than at 2048 px."""
    c = su.uv_at(ob, FACE)
    k = su.uv_per_metre(ob, FACE)
    return su.soft_disk(res, c, 0.04 * k, 3.0 / res)


def measure_t1(sc, ob, mat, out_dir, tag):
    layers.add_layer(mat, "RUST", index=len(mat.realworn.layers))
    idx = len(mat.realworn.layers) - 1
    out = {}
    for res in (512, 1024, 2048):
        su.paint_layer(ob, mat, mat.realworn.layers[idx], lambda r: t1_stroke(ob, r), res=res)
        out[res] = _w(sc, mat, idx, out_dir, "t1_{}_{}".format(tag, res))["W"]
    return out


def test_t1_baseline_mask_resolution_limits_sharpness(closeup, out_dir):
    sc, ob, mat = closeup
    w = measure_t1(sc, ob, mat, out_dir, "v20")
    print("\n[T1 v2.0] W px at mask 512/1024/2048: {:.2f} / {:.2f} / {:.2f}".format(w[512], w[1024], w[2048]))
    for res in (512, 1024, 2048):
        record("v2.1 T1 baseline (v2.0, no Edge Detail): W at mask {} px".format(res), w[res], "px", None,
               "4 cm stroke, 3-texel soft edge, 30 cm crate close-up, 1920 px EEVEE Mask View")
    assert w[512] >= 1.8 * w[2048]  # the test can see what mask resolution does


# ------------------------------------------------------------------ T2
def t2_stroke(ob, res):
    """A soft brush stroke: 5 cm radius, smooth falloff over the outer 2.5 cm (physical size)."""
    c = su.uv_at(ob, FACE)
    k = su.uv_per_metre(ob, FACE)
    return su.soft_disk(res, c, 0.05 * k, 0.025 * k)


def test_t2_baseline_closeup_dirt_and_rust(closeup, out_dir):
    sc, ob, mat = closeup
    out = {}
    for kind in ("DIRT", "RUST"):
        ly = layers.add_layer(mat, kind, index=len(mat.realworn.layers))
        idx = len(mat.realworn.layers) - 1
        su.paint_layer(ob, mat, ly, lambda r: t2_stroke(ob, r))
        out[kind] = _w(sc, mat, idx, out_dir, "t2_v20_" + kind.lower())
        mat.realworn.layers[idx].visible = False  # measure each layer on its own
    print("\n[T2 v2.0] W px: Dirt {:.1f}, Rust {:.1f} (mask {} px)".format(
        out["DIRT"]["W"], out["RUST"]["W"], mat.realworn.layers[0].mask_image.size[0]))
    for kind in ("DIRT", "RUST"):
        record("v2.1 T2 baseline (v2.0 defaults): {} W, 30 cm crate close-up".format(kind.title()),
               out[kind]["W"], "px", None, "soft 5 cm stroke; 1920 px EEVEE Mask View; S1 target 3 px")
    assert all(out[k]["W"] is not None for k in out)

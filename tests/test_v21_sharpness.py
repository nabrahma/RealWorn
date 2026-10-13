"""PRD v2.1 sharpness acceptance (T1, T2) on the close-up of S1: a 30 cm crate, camera 30 cm from
its front face, 1920 x 1080 Mask View renders (EEVEE, 32-bit EXR), edge width W from
tests/metrics.py. The baseline tests turn the material back into a v2.0 one (no Edge Detail, v2.0
layer defaults); the v2.1 tests use the per-type defaults new layers get after Setup."""

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


def v20(mat):
    """New layers get v2.0 defaults (what a v2.0 file has)."""
    mat.realworn.v21 = False


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
    v20(mat)
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


def measure_t2(sc, ob, mat, out_dir, tag, painted_area=False, res=None):
    """W per layer; with painted_area, also the coverage of the same layer with Edge Detail off
    (the plain stroke), so v2.1 can prove the stroke still reads as the stroke."""
    out = {}
    for kind in ("DIRT", "RUST"):
        ly = layers.add_layer(mat, kind, index=len(mat.realworn.layers))
        idx = len(mat.realworn.layers) - 1
        su.paint_layer(ob, mat, ly, lambda r: t2_stroke(ob, r), res=res)
        out[kind] = _w(sc, mat, idx, out_dir, "t2_{}_{}".format(tag, kind.lower()))
        if painted_area:
            ly = mat.realworn.layers[idx]
            s, ly.detail.strength = ly.detail.strength, 0.0
            out[kind]["painted"] = _w(sc, mat, idx, out_dir, "t2_{}_{}_off".format(tag, kind.lower()))["coverage"]
            ly.detail.strength = s
        mat.realworn.layers[idx].visible = False  # measure each layer on its own
    return out


def test_t2_baseline_closeup_dirt_and_rust(closeup, out_dir):
    sc, ob, mat = closeup
    v20(mat)
    out = measure_t2(sc, ob, mat, out_dir, "v20", res=512)  # v2.0's density gave a 30 cm crate 512 px
    print("\n[T2 v2.0] W px: Dirt {:.1f}, Rust {:.1f} (mask {} px)".format(
        out["DIRT"]["W"], out["RUST"]["W"], mat.realworn.layers[0].mask_image.size[0]))
    for kind in ("DIRT", "RUST"):
        record("v2.1 T2 baseline (v2.0 defaults): {} W, 30 cm crate close-up".format(kind.title()),
               out[kind]["W"], "px", None, "soft 5 cm stroke; 1920 px EEVEE Mask View; S1 target 3 px")
    assert all(out[k]["W"] is not None for k in out)


# ------------------------------------------------------------------ v2.1 (Q1)
def test_t1_edge_detail_makes_sharpness_resolution_independent(closeup, out_dir):
    """T1 / S2: with Edge Detail on (Rust defaults), W varies by under 15% across mask 512..2048."""
    sc, ob, mat = closeup
    w = measure_t1(sc, ob, mat, out_dir, "v21")
    spread = (max(w.values()) - min(w.values())) / min(w.values())
    print("\n[T1 v2.1] W px at mask 512/1024/2048: {:.2f} / {:.2f} / {:.2f} (spread {:.0%})".format(
        w[512], w[1024], w[2048], spread))
    for res in (512, 1024, 2048):
        record("v2.1 T1 Edge Detail on (Rust defaults): W at mask {} px".format(res), w[res], "px", None,
               "same stroke as the v2.0 baseline row")
    record("v2.1 T1 W spread across mask 512..2048, Edge Detail on", spread * 100, "%", 15, "S2")
    assert spread < 0.15


def test_t2_closeup_dirt_and_rust_are_crisp(closeup, out_dir):
    """T2 / S1: Dirt and Rust with v2.1 defaults, W at most 3 px on the close-up."""
    sc, ob, mat = closeup
    out = measure_t2(sc, ob, mat, out_dir, "v21", painted_area=True)
    print("\n[T2 v2.1] W px: Dirt {:.2f}, Rust {:.2f}; kept area: Dirt {:.0%}, Rust {:.0%}".format(
        out["DIRT"]["W"], out["RUST"]["W"], out["DIRT"]["coverage"] / out["DIRT"]["painted"],
        out["RUST"]["coverage"] / out["RUST"]["painted"]))
    for kind in ("DIRT", "RUST"):
        record("v2.1 T2 {} W with v2.1 defaults, 30 cm crate close-up".format(kind.title()), out[kind]["W"], "px", 3,
               "S1; coverage {:.1%}".format(out[kind]["coverage"]))
        assert out[kind]["W"] <= 3.0
        # the stroke still reads as the stroke: Edge Detail breaks its edge up, it does not erase it
        assert out[kind]["coverage"] >= 0.25 * out[kind]["painted"]

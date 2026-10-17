"""The Puddle model's reference math: placement by depth, zones, look and relief."""

import numpy as np
import pytest

from realworn.core import kinds as K
from realworn.core import puddle as P


def _grid(n=256):
    y, x = np.mgrid[0:n, 0:n] / (n - 1.0)
    return x, y


def test_puddle_is_the_seventh_kind_and_on_top():
    assert "PUDDLE" in K.KINDS and K.ORDER[-1] == "PUDDLE"
    assert K.paintable("PUDDLE") and K.paint_optional("PUDDLE")
    assert K.INFO["PUDDLE"]["paint"] == "RW Puddle"
    assert K.insert_index(["VARIATION", "PAINT", "DECALS", "DIRT"], "PUDDLE") == 4


def test_presets_raise_the_water_in_order():
    water = [(k, v) for k, _, v in P.PRESETS if k not in P.FILM_PRESETS]
    levels = [v["water_level_mm"] for _, v in water]
    assert levels == sorted(levels) and [k for k, _ in water] == ["DAMP", "WET", "PUDDLES", "SOAKED"]
    assert all(v["wet_film"] == 0.0 for _, v in water)  # 3.3 presets keep the film off
    assert K.defaults("PUDDLE")["water_level_mm"] == P.preset_values(P.DEFAULT_PRESET)["water_level_mm"]
    assert K.defaults("PUDDLE", "SOAKED")["water_level_mm"] > K.defaults("PUDDLE", "DAMP")["water_level_mm"]


def test_smoothstep_matches_blender_map_range():
    x = np.linspace(-1.0, 2.0, 61)
    t = np.clip(x, 0, 1)
    assert np.allclose(P.smoothstep(0.0, 1.0, x), t * t * (3 - 2 * t))
    assert P.smoothstep(0.0, 1.0, 0.5) == pytest.approx(0.5)


def test_height_range_and_normalisation():
    v = np.linspace(0.3, 0.7, 10001)
    lo, hi = P.height_range(v)
    assert lo == pytest.approx(0.308, abs=1e-3) and hi == pytest.approx(0.692, abs=1e-3)
    assert P.base_norm(0.5, lo, hi) == pytest.approx(0.0, abs=1e-6)
    assert P.base_norm(hi, lo, hi) == pytest.approx(0.5, abs=1e-6)


def test_placement_on_a_bowl_matches_the_analytic_region():
    """Water exactly where the ground is below the water level (IoU above 0.98)."""
    x, y = _grid()
    bowl = ((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.5 - 0.5  # -0.5 centre .. 0.5 corners
    H = P.ground(bowl, 0.0, 10.0, "BASE")
    for level in (-3.0, -1.0, 1.0):
        d = P.depth(level, P.lowered(H, mode="AUTO"))
        water = P.zones(d)["water"] > 0.5
        truth = H < level
        iou = (water & truth).sum() / max((water | truth).sum(), 1)
        assert iou > 0.98, (level, iou)


def _tiles(n=256, tile=32, grout=3):
    """Flat tile faces at +0.5 with grout lines at -0.5 (a normalised height)."""
    i = np.arange(n) % tile
    line = (i < grout)
    return np.where(line[None, :] | line[:, None], -0.5, 0.5)


def test_grout_fills_before_tile_faces():
    h = _tiles() + np.random.default_rng(1).normal(0.0, 0.05, (256, 256))
    grout = _tiles() < 0
    H = P.ground(h, 0.0, 6.0, "BASE")
    for level in np.linspace(-4.0, 4.0, 17):
        wet = P.zones(P.depth(level, P.lowered(H, mode="AUTO")))["water"]
        g, f = wet[grout].mean(), wet[~grout].mean()
        assert g >= f, (level, g, f)
        if 0 < g < 1:
            assert g > f


def test_painted_puddles_follow_the_grain():
    """Painting lowers the ground, so inside a painted area wetness still follows low height."""
    rng = np.random.default_rng(3)
    x, y = _grid()
    grain = np.sin(x * 40) * np.cos(y * 37) * 0.5 + rng.normal(0, 0.05, x.shape)
    H = P.ground(grain, 0.0, 10.0, "BASE")
    paint = np.where((x - 0.5) ** 2 + (y - 0.5) ** 2 < 0.09, 1.0, 0.0)  # a painted disc, white
    d = P.depth(-6.0, P.lowered(H, P.paint_signed(0.5 + 0.5 * paint), 4.0, "AUTO_AND_PAINT"))
    wet = P.zones(d)["wet"]
    inside = paint > 0.5
    assert wet[inside].mean() > 3 * wet[~inside].mean()
    r = np.corrcoef(wet[inside], -H[inside])[0, 1]
    assert r > 0.6, r


def test_paint_only_and_neutral_grey():
    assert P.paint_signed(0.5) == pytest.approx(0.0) and P.paint_signed(1.0) == 1.0 and P.paint_signed(0.0) == -1.0
    # Paint only: unpainted ground (grey) is lifted far out of any water level
    assert P.depth(10.0, P.lowered(0.0, 0.0, 20.0, "PAINT")) < -50
    assert P.depth(1.0, P.lowered(0.0, 1.0, 20.0, "PAINT")) > 0
    # Auto and Paint: black dries a spot out
    assert P.depth(1.0, P.lowered(0.0, -1.0, 20.0, "AUTO_AND_PAINT")) < 0 < P.depth(1.0, P.lowered(0.0))


def test_flat_faces_only():
    for nz in (0.0, 0.5, 0.8):  # walls, kerb sides, steep slopes
        d = P.depth(10.0, -10.0, P.flat_gate(nz, 0.92))
        assert all(v < 0.01 for v in P.zones(d).values())
    assert P.flat_gate(1.0, 0.92) == pytest.approx(1.0)


def test_zones_and_waterline_is_the_sharpest_transition():
    d = np.linspace(-12.0, 12.0, 24001)
    z = P.zones(d, edge_mm=1.5, halo_mm=6.0, halo=1.0, deep_mm=6.0)

    def width(w):  # the band where the weight is between 0.1 and 0.9, in mm of depth
        band = (w > 0.1) & (w < 0.9)
        return float(np.ptp(d[band])) if band.any() else 0.0
    ww, we, wh, wd = width(z["water"]), width(z["edge"]), width(z["halo"]), width(z["deep"])
    assert ww < we < wh and ww < wd
    assert ww < 0.2
    # order along d: halo starts first, then the wet edge, then water, then deep
    first = lambda w: d[np.argmax(w > 0.5)]  # noqa: E731
    assert first(z["halo"]) < first(z["edge"]) < first(z["water"]) < first(z["deep"])


def test_porosity_rough_ground_darkens_metal_barely():
    z = P.zones(np.array([-0.05]))  # in the wet edge, just outside the water
    rough, _ = P.look([0.5, 0.5, 0.5], 0.9, 0.0, np.array([-0.05]), z)
    metal, _ = P.look([0.5, 0.5, 0.5], 0.2, 1.0, np.array([-0.05]), z)
    assert 1.0 - rough[0][0] / 0.5 > 0.4
    assert 1.0 - metal[0][0] / 0.5 < 0.1


def test_depth_look_ground_and_relief_fade_with_depth():
    d = np.linspace(0.2, 20.0, 50)
    z = P.zones(d)
    col, _ = P.look([0.6, 0.5, 0.4], 0.8, 0.0, d, z)
    rel = P.relief(d, z)
    assert np.all(np.diff(col[0]) <= 1e-9) and col[0][-1] < 0.2 * col[0][0]
    assert np.all(np.diff(rel) <= 1e-9) and rel[-1] < 0.01


def test_roughness_and_coat_by_zone():
    d = np.array([-20.0, -4.0, -0.5, 1.0, 12.0])  # dry, halo, edge, shallow, deep
    z = P.zones(d)
    _, r = P.look([0.5] * 3, 0.8, 0.0, d, z)
    cw, cr, ior = P.coat(z)
    assert r[0] == pytest.approx(0.8) and r[1] < r[0] and r[2] < r[1]
    assert r[3] == pytest.approx(P.WATER_ROUGHNESS, abs=0.02)
    assert cw[0] == pytest.approx(0.0) and cw[3] == pytest.approx(1.0) and cw[4] == pytest.approx(1.0)
    assert cr[4] < cr[3] < 0.1 and ior[4] == pytest.approx(1.33)


def test_true_depth_water_is_flat():
    rng = np.random.default_rng(5)
    H = rng.normal(0.0, 4.0, 10000)
    level = 2.0
    top = P.true_height(H, level)
    assert np.ptp(top[H < level]) == pytest.approx(0.0)
    assert np.allclose(top[H >= level], H[H >= level])


def test_opacity_zero_is_no_change():
    d = np.linspace(-10, 10, 101)
    z = P.zones(d)
    col, r = P.look([0.4, 0.3, 0.2], 0.7, 0.0, d, z, opacity=0.0)
    assert np.allclose(col[0], 0.4) and np.allclose(r, 0.7)
    assert np.allclose(P.relief(d, z, opacity=0.0), 1.0)


# ------------------------------------------------------------------ wet film
def test_film_presets_match_the_table():
    want = {"RAIN_SOAKED": (1.0, 0.6, 0.0, -4.0), "JUST_RAINED": (0.8, 0.5, 0.2, -2.0),
            "DRYING": (0.5, 0.4, 0.6, -4.0)}
    for k, (w, r, dry, level) in want.items():
        v = P.preset_values(k)
        assert (v["wet_film"], v["film_relief"], v["dry_patches"], v["water_level_mm"]) == (w, r, dry, level)
    assert K.defaults("PUDDLE")["wet_film"] == 0.0  # new layers: no film unless asked


def test_film_weight_dry_patches_and_flat_faces():
    b1 = np.linspace(0.0, 1.0, 101)
    assert np.allclose(P.film_weight(1.0, b1), 1.0)  # Dry Patches 0: wet everywhere
    f = P.film_weight(1.0, b1, dry_patches=0.6)
    assert f.min() == pytest.approx(0.4) and f.max() == pytest.approx(1.0) and np.all(np.diff(f) <= 1e-9)
    assert P.film_weight(1.0, 0.2, gate=0.0) == 0.0  # walls and kerb sides stay dry
    assert P.film_weight(0.5, 0.2, opacity=0.5) == pytest.approx(0.25)


def test_film_relief_varies_in_patches_and_vanishes_in_deep_water():
    assert P.film_relief(0.6, 0.0) == pytest.approx(0.6 * P.FILM_RELIEF_MIN)
    assert P.film_relief(0.6, 1.0) == pytest.approx(0.6)
    assert P.film_relief(0.6, 1.0, deep=1.0) == 0.0
    assert P.film_relief(0.0, 0.7) == 0.0
    nz = np.linspace(0.0, 1.0, 11)
    b = P.film_breakup_noise(nz)
    assert b[0] == 0.0 and b[-1] == 1.0 and np.all(np.diff(b) >= 0)


def test_film_channels_out_of_the_water():
    d = np.array([-30.0])  # dry ground, far from any puddle
    z = P.zones(d)
    (c,), r = P.look([np.array([0.5])], np.array([0.8]), 0.0, d, z, film=1.0)
    (c0,), r0 = P.look([np.array([0.5])], np.array([0.8]), 0.0, d, z)
    assert c < c0 and r == pytest.approx(r0 * (1.0 - P.FILM_ROUGHNESS))
    w, cr, ior = P.coat(z, film=np.array([1.0]), gloss=0.02)
    assert w == pytest.approx(1.0) and cr == pytest.approx(0.02) and ior == pytest.approx(P.COAT_IOR)
    w, cr, ior = P.coat(z, film=np.array([0.0]), gloss=0.02)
    assert w == pytest.approx(0.0) and cr == pytest.approx(P.FILM_COAT_ROUGHNESS)
    w, cr, ior = P.coat(z, film=np.array([0.5]), gloss=0.02, gate=0.0, roughness_in=0.3)  # a wall
    assert cr == pytest.approx(0.3) and ior == pytest.approx(1.5)


def test_film_leaves_standing_water_alone():
    d = np.array([10.0])  # deep water
    z = P.zones(d)
    col = [np.array([0.5]), np.array([0.4]), np.array([0.3])]
    a, ra = P.look(col, np.array([0.8]), 0.0, d, z)
    b, rb = P.look(col, np.array([0.8]), 0.0, d, z, film=1.0)
    assert all(np.allclose(x, y) for x, y in zip(a, b)) and np.allclose(ra, rb)
    assert np.allclose(P.coat(z), P.coat(z, film=np.array([1.0]), gloss=0.05))

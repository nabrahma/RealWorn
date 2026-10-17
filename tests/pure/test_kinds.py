"""The seven kinds, their default stack positions and presets, and the mask recipe's reference math."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from realworn.core import kinds as K


def test_kinds_and_their_order():
    assert K.KINDS == ("VARIATION", "PAINT", "REVEAL", "DECALS", "EDGE_WEAR", "DIRT", "PUDDLE")
    assert K.ORDER[-1] == "PUDDLE"  # water lies on top of everything on the ground
    assert set(K.ORDER) == set(K.KINDS) and set(K.INFO) == set(K.KINDS) and set(K.DEFAULTS) == set(K.KINDS)
    # the reference's order: variation over the base, paint over that, worn edges, damage breaking
    # through, decals over the damage, dirt settling on top
    assert K.ORDER.index("VARIATION") < K.ORDER.index("PAINT") < K.ORDER.index("REVEAL") \
        < K.ORDER.index("DECALS") < K.ORDER.index("DIRT")


def test_paintable_kinds():
    assert not K.paintable("VARIATION")  # VAR-1: grunge only
    assert all(K.paintable(k) for k in ("PAINT", "REVEAL", "DECALS", "EDGE_WEAR", "DIRT"))
    assert K.paint_optional("EDGE_WEAR") and K.paint_optional("DIRT") and not K.paint_optional("PAINT")
    assert K.INFO["REVEAL"]["paint"] == "RW Damage" and K.INFO["DECALS"]["paint"] == "RW Stencil"
    assert K.INFO["PAINT"]["paint"] == "RW Soft"


def test_breakup_defaults():
    """MSK-2: Breakup off on Paint and Reveal, on with a grunge for Variation, Edge Wear and Dirt."""
    for k in ("PAINT", "REVEAL", "DECALS"):
        assert K.DEFAULTS[k]["breakup_amount"] == 0.0
    for k in ("VARIATION", "EDGE_WEAR", "DIRT"):
        assert K.DEFAULTS[k]["breakup_amount"] > 0.0 and K.DEFAULTS[k]["breakup"]


def test_kind_defaults():
    assert K.DEFAULTS["VARIATION"]["content"] == "TINT_BELOW"            # VAR-1
    assert K.DEFAULTS["PAINT"]["content"] == "TINT_BELOW" and K.DEFAULTS["PAINT"]["hue"] != 0  # PNT-7
    assert K.DEFAULTS["REVEAL"]["content"] == "COLOR" and K.DEFAULTS["REVEAL"]["depth_mm"] == 2.0  # REV-1, REV-2
    assert 0 < K.DEFAULTS["REVEAL"]["edge_dark"] <= 0.3                  # REV-6: on, low
    assert K.DEFAULTS["DECALS"]["roughness"] == 0.6 and K.DEFAULTS["DECALS"]["decal_blend"] == "NORMAL"  # DEC-4
    assert K.DEFAULTS["EDGE_WEAR"]["width_mm"] == 5.0                    # EDW-2
    assert K.DEFAULTS["EDGE_WEAR"]["saturation"] < 0 < K.DEFAULTS["EDGE_WEAR"]["value"]  # lighter, less saturated
    assert K.DEFAULTS["DIRT"]["distance_cm"] == 20.0 and K.DEFAULTS["DIRT"]["roughness"] == 0.9  # DRT-2
    assert K.DEFAULTS["DIRT"]["content"] == "COLOR"


def test_presets():
    assert [p for p, _ in K.preset_items("VARIATION")] == ["WASHED_OUT", "DARK_PATCHES", "DIRT_PATCHES",
                                                            "SECOND_MATERIAL"]
    assert K.defaults("VARIATION", "WASHED_OUT")["saturation"] == -0.3
    assert K.defaults("VARIATION", "DARK_PATCHES")["value"] == -0.25
    d = K.defaults("VARIATION", "DIRT_PATCHES")
    assert d["content"] == "COLOR" and d["roughness"] == 0.9
    assert K.defaults("VARIATION", "SECOND_MATERIAL")["content"] == "TEXTURE"
    assert K.defaults("REVEAL", "SCRATCHES")["depth_mm"] == pytest.approx(0.3)  # REV-4
    assert K.defaults("DECALS", "GRIME")["decal_blend"] == "DARKEN"  # DEC-4


@pytest.mark.parametrize("stack,kind,want", [
    ([], "DIRT", 0),
    (["DIRT"], "PAINT", 0),
    (["PAINT", "DIRT"], "VARIATION", 0),
    (["VARIATION", "PAINT", "DIRT"], "REVEAL", 2),
    (["VARIATION", "PAINT", "REVEAL", "DIRT"], "PAINT", 2),
    (["DIRT", "PAINT"], "DECALS", 2),  # the user dragged Dirt down: respected, nothing reorders
])
def test_insert_index(stack, kind, want):
    assert K.insert_index(stack, kind) == want


# ------------------------------------------------------------------ recipe
def test_width_range():
    assert K.width(0.0) == pytest.approx(0.5) and K.width(1.0) == pytest.approx(0.01)
    lo, hi = K.ramp_stops(0.5, 0.0)
    assert (lo, hi) == pytest.approx((0.25, 0.75))
    assert K.breakup_stops(0.0) == (0.0, 1.0)


def test_recipe_examples():
    # painted, no breakup: the outer ramp alone
    assert K.recipe(1.0, 0.0, 0.0, 0.0, 0.5, 0.5) == 1.0
    assert K.recipe(0.0, 1.0, 0.0, 0.0, 0.5, 0.5) == 0.0
    # Variation: S = 1, the mask is the ramped (inverted) grunge
    assert K.recipe(1.0, 0.0, 1.0, 0.0, 0.75, 0.6) == 1.0
    assert K.recipe(1.0, 1.0, 1.0, 0.0, 0.75, 0.6) == 0.0
    # the grunge chips the paint
    assert K.recipe(1.0, 1.0, 1.0, 0.0, 0.5, 0.5) == 0.0
    assert K.recipe(1.0, 0.2, 1.0, 0.0, 0.5, 0.5) == 1.0
    assert K.recipe(1.0, 0.0, 0.0, 0.0, 0.5, 0.5, opacity=0.3) == pytest.approx(0.3)


@given(s=st.floats(0, 1), g=st.floats(0, 1), a=st.floats(0, 1), c=st.floats(0, 0.95), t=st.floats(0, 1),
       sh=st.floats(0, 1))
def test_recipe_is_a_mask(s, g, a, c, t, sh):
    m = K.recipe(s, g, a, c, t, sh)
    assert 0.0 <= m <= 1.0
    assert K.recipe(min(s + 0.1, 1.0), g, a, c, t, sh) >= m - 1e-9  # more paint never shows less


def test_dirt_is_a_less_than():
    """DRT-1: AO, Color Ramp, Less Than a grunge through Map Range. With Sharpness 1 the recipe is
    that comparison: x < m0 + G (m1 - m0) with t = 1 - m0, a = m0 - m1."""
    m0, m1 = 0.55, 0.25
    t, a = 1 - m0, m0 - m1
    for ao in (0.3, 0.6, 0.7, 0.8, 0.99):
        for g in (0.0, 0.3, 0.7, 1.0):
            x = min(max((ao - 0.5) / 0.45, 0.0), 1.0)
            want = 1.0 if x < m0 + g * (m1 - m0) else 0.0
            got = K.recipe(K.ao_source(ao), g, a, 0.0, t, 1.0)
            if abs(x - (m0 + g * (m1 - m0))) > 0.01:  # away from the 1 % transition band
                assert got == pytest.approx(want), (ao, g)


def test_edge_and_hsv_helpers():
    assert K.edge_source(1.0) == 0.0 and K.edge_source(0.9) == pytest.approx(1.0)
    assert K.edge_radius(0.005, 0.0, 0.3) == pytest.approx(0.005)
    assert K.edge_radius(0.006, 2 / 3, 0.0) == pytest.approx(0.002)
    assert K.hsv_inputs(0, 0, 0) == (0.5, 1.0, 1.0) and K.hsv_inputs(0.5, -0.3, -0.25) == (1.0, 0.7, 0.75)

"""Layer type defaults (PRD v2 table) and the reference mask formula."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from realworn.core import layer_types as LT


@pytest.mark.parametrize("kind", LT.ORDER)
def test_every_type_is_valid(kind):
    assert LT.validate(kind) == []


def test_table_matches_prd():
    d = LT.defaults
    assert d("DIRT")["color"]["blend"] == "MULTIPLY" and d("DIRT")["roughness"]["value"] == 0.9
    assert d("DIRT")["use_height_blend"] is True
    assert d("DUST")["roughness"]["value"] == 1.0
    assert d("RUST")["color"]["source"] == "TINTED_GRUNGE" and d("RUST")["height"]["value"] == 0.5
    assert d("WEAR")["metallic"]["value"] == 1.0 and d("WEAR")["lock_source"] == "EDGE"
    assert d("WEAR")["lock_strength"] == 0.6 and d("WEAR")["height"]["blend"] == "SUBTRACT"
    assert d("WATER")["roughness"]["value"] == 0.03
    assert d("SCRATCHES")["metallic"]["enabled"] is False  # keeps base metallic
    assert d("CUSTOM")["height"]["enabled"] and d("CUSTOM")["color"]["value"] == (0.5, 0.5, 0.5)
    assert set(LT.ORDER) == set(LT.TYPES)


def test_blend_modes_per_channel():
    assert LT.blends_for("color") == ("MIX", "MULTIPLY", "OVERLAY", "ADD", "DARKEN")
    assert LT.blends_for("roughness") == ("MIX", "MIN", "MAX")
    assert LT.blends_for("height") == ("ADD", "SUBTRACT", "MAX", "REPLACE")


def test_unknown_type_rejected():
    with pytest.raises(KeyError):
        LT.defaults("SNOW")


unit = st.floats(0.0, 1.0)


@given(P=unit, paint=unit)
def test_new_layer_is_pure_painting(P, paint):
    """Ingredients at 0 and nothing painted: the mask is 0, so nothing shows."""
    assert LT.mask_formula(0.0, paint, 0.0, 1.0, 0.0, 0.5, 1.0, 1.0) == 0.0


@given(P=unit, paint=unit)
def test_painting_overrides_procedural(P, paint):
    """Painted alpha 1 replaces the procedural value with the painted one (paint wins)."""
    full = LT.mask_formula(P, paint, 1.0, 1.0, 0.0, 0.5, 1.0, 1.0)
    assert full == pytest.approx(paint, abs=1e-9)


@given(P=unit, lock=unit)
def test_edge_lock_one_keeps_paint_only_on_lock(P, lock):
    m = LT.mask_formula(0.0, 1.0, 1.0, lock, 1.0, 0.5, 1.0, 1.0)
    assert m == pytest.approx(lock, abs=1e-9)


@given(m=unit, t=st.floats(0.05, 0.95))
def test_levels_low_softness_is_crisp(m, t):
    v = LT.mask_formula(m, 0.0, 0.0, 1.0, 0.0, t, 0.0, 1.0)
    if abs(m - t) > 0.001:
        assert v in (0.0, 1.0)


@given(P=unit, paint=unit, a=unit, op=unit)
def test_opacity_scales_and_mask_stays_in_range(P, paint, a, op):
    v = LT.mask_formula(P, paint, a, 1.0, 0.0, 0.5, 1.0, op)
    assert 0.0 <= v <= op + 1e-9

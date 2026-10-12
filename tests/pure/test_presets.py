import copy

import pytest

from realworn.core import presets


def test_all_bundled_presets_validate():
    allp = presets.load_all()
    for pid in presets.USER_PRESETS + ("inner",):
        assert pid in allp
        assert presets.validate(allp[pid]) == []


def test_six_user_presets_produce_different_stack_inputs():
    vals = [presets.stack_inputs(presets.get(p)) for p in presets.USER_PRESETS]
    keys = [tuple(sorted((k, str(v)) for k, v in v.items())) for v in vals]
    assert len(set(keys)) == len(presets.USER_PRESETS)


def test_metal_presets_rust_and_others_do_not():
    for p in presets.USER_PRESETS:
        rust = presets.stack_inputs(presets.get(p))["Rust"]
        assert (rust > 0) == (p in ("painted_metal", "bare_metal")), p


def test_bare_metal_polishes():
    assert presets.stack_inputs(presets.get("bare_metal"))["Polish"] == 1.0
    assert presets.stack_inputs(presets.get("painted_metal"))["Polish"] == 0.0


@pytest.mark.parametrize("mutate, needle", [
    (lambda p: p.pop("porosity"), "porosity"),
    (lambda p: p["layers"].pop("dust"), "missing layer 'dust'"),
    (lambda p: p["layers"]["dust"].update(color=[2, 0, 0]), "dust.color"),
    (lambda p: p["layers"]["edge_wear"].update(underlayer="gold"), "underlayer"),
    (lambda p: p["layers"].update(moss={"enabled": True}), "unknown layer 'moss'"),
    (lambda p: p["layers"]["rust"].update(enabled="yes"), "rust.enabled"),
])
def test_validation_catches_errors(mutate, needle):
    p = copy.deepcopy(presets.get("painted_metal"))
    mutate(p)
    errs = presets.validate(p)
    assert any(needle in e for e in errs), errs


def test_auto_rule():
    assert presets.choose_auto(0.9, 0.3, "Anything") == "bare_metal"
    assert presets.choose_auto(0.0, 0.5, "SteelBeam") == "painted_metal"
    assert presets.choose_auto(0.0, 0.5, "Crate.001") == "wood"
    assert presets.choose_auto(0.0, 0.5, "WheelieBin") == "plastic"
    assert presets.choose_auto(0.0, 0.5, "Wall") == "concrete"


def test_unknown_preset_raises():
    with pytest.raises(presets.PresetError):
        presets.get("nope")

import copy

from realworn.core import snapshot


def _snap():
    return {"schema": 1, "nodes": {
        "Principled BSDF": {"type": "ShaderNodeBsdfPrincipled", "label": "", "location": [10.0, 0.0], "width": 240.0,
                            "parent": None, "mute": False, "hide": False, "props": {"distribution": "MULTI_GGX"},
                            "inputs": [["Base Color", 0, [0.8, 0.8, 0.8, 1.0]], ["Roughness", 2, 0.5]],
                            "outputs": []},
        "Material Output": {"type": "ShaderNodeOutputMaterial", "label": "", "location": [300.0, 0.0],
                            "width": 140.0, "parent": None, "mute": False, "hide": False, "props": {},
                            "inputs": [], "outputs": []}},
        "links": [["Principled BSDF", "BSDF", "Material Output", "Surface", False]]}


def test_identical_is_empty():
    assert snapshot.diff(_snap(), _snap()) == []


def test_detects_value_link_node_and_prop_changes():
    b = copy.deepcopy(_snap())
    b["nodes"]["Principled BSDF"]["inputs"][1][2] = 0.7
    b["nodes"]["Principled BSDF"]["props"]["distribution"] = "GGX"
    b["links"] = []
    b["nodes"]["Extra"] = dict(b["nodes"]["Material Output"])
    d = snapshot.diff(_snap(), b)
    assert any("Roughness" in x for x in d)
    assert any("distribution" in x for x in d)
    assert any(x.startswith("link removed") for x in d)
    assert any(x.startswith("node added: Extra") for x in d)


def test_rounding_is_stable():
    assert snapshot._round(0.1 + 0.2) == 0.3
    assert snapshot._round(-0.0000001) == 0.0
    assert snapshot.dumps(_snap()) == snapshot.dumps(copy.deepcopy(_snap()))

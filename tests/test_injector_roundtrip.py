"""M2 injector acceptance: apply/remove round trips, idempotency, modes, shared materials."""

import glob
import os

import bpy
import pytest

from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from realworn.core import injector, naming, nodeutil, snapshot, weathering

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def _roundtrip(mat):
    before = snapshot.serialize(mat.node_tree)
    state = injector.apply(mat, "AUTO", "Thing")
    assert state == "applied"
    assert injector.stacks(mat.node_tree), "no RW_Stack inserted"
    assert all(nodeutil.is_owned(n) for n in mat.node_tree.nodes if n.name.startswith("RW::"))
    diffs = injector.remove(mat)
    after = snapshot.serialize(mat.node_tree)
    assert diffs == []
    assert snapshot.diff(before, after) == []
    assert snapshot.dumps(before) == snapshot.dumps(after)
    assert not any(nodeutil.is_owned(n) for n in mat.node_tree.nodes)
    assert not mat.realworn.applied and mat.realworn.snapshot == ""


@pytest.mark.parametrize("name", sorted(GENERATED))
def test_generated_corpus_roundtrip(empty_scene, name):
    _roundtrip(GENERATED[name]())


def _polyhaven_materials():
    out = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "*", "*.blend"))):
        out.append(path)
    return out


@pytest.mark.parametrize("path", _polyhaven_materials() or [pytest.param(None, marks=pytest.mark.skip(
    reason="Poly Haven corpus not downloaded (python tests/corpus/fetch.py)"))])
def test_polyhaven_corpus_roundtrip(empty_scene, path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.materials = list(src.materials)
    mats = [m for m in dst.materials if m is not None and m.node_tree is not None]
    assert mats, "no materials in " + path
    for m in mats:
        _roundtrip(m)


def test_modes_and_stack_count(empty_scene):
    assert len(injector.find_principled(GENERATED["multi_principled"]().node_tree)[1]) == 2
    m = GENERATED["multi_principled"]()
    injector.apply(m)
    assert m.realworn.mode == "CHANNEL" and len(injector.stacks(m.node_tree)) == 2
    for name in ("toon", "emission_only", "grouped_principled", "empty_surface"):
        t = GENERATED[name]()
        injector.apply(t)
        assert t.realworn.mode == "SHADER", name
        assert len(injector.stacks(t.node_tree)) == 1
        out = nodeutil.output_node(t.node_tree)
        assert out.inputs["Surface"].links[0].from_node.name == "RW::overlay_mix"


def test_apply_twice_equals_once(empty_scene):
    m = GENERATED["image_based"]()
    injector.apply(m, "concrete")
    once = snapshot.dumps(snapshot.serialize(m.node_tree, include_owned=True))
    state = injector.apply(m, "concrete")
    assert state == "updated"
    twice = snapshot.dumps(snapshot.serialize(m.node_tree, include_owned=True))
    assert once == twice
    # changing the preset only changes values, never adds a second stack
    injector.apply(m, "painted_metal")
    assert len(injector.stacks(m.node_tree)) == 1
    assert m.realworn.preset == "painted_metal"


def test_channels_are_rewired(empty_scene):
    m = GENERATED["image_based"]()
    injector.apply(m)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    st = injector.stacks(nt)[0]
    for ch in naming.CHANNELS:
        assert b.inputs[ch].links[0].from_node == st, ch
    assert st.inputs["Base Color"].links[0].from_node.bl_idname == "ShaderNodeTexImage"
    assert st.inputs["Normal"].links[0].from_node.bl_idname == "ShaderNodeNormalMap"
    assert st.inputs["Coat Normal"].links[0].from_node.name == "RW::geom.0"


def test_existing_coat_and_height_detected(empty_scene):
    m = GENERATED["coat_material"]()
    injector.apply(m)
    st = injector.stacks(m.node_tree)[0]
    assert st.inputs["Coat Weight"].links[0].from_node.bl_idname == "ShaderNodeValue"
    assert abs(st.inputs["Coat IOR"].default_value - 1.6) < 1e-6
    d = GENERATED["displacement_material"]()
    injector.apply(d)
    st = injector.stacks(d.node_tree)[0]
    assert st.inputs["Has Surface Height"].default_value == 1.0
    assert st.inputs["Surface Height"].links[0].from_node.bl_idname == "ShaderNodeTexNoise"


def test_muted_link_treated_as_unlinked(empty_scene):
    m = GENERATED["muted_link"]()
    injector.apply(m)
    st = injector.stacks(m.node_tree)[0]
    assert not st.inputs["Base Color"].is_linked


def test_presets_change_stack_values(empty_scene):
    m = GENERATED["principled_basic"]()
    injector.apply(m, "bare_metal")
    st = injector.stacks(m.node_tree)[0]
    assert st.inputs["Polish"].default_value == 1.0
    injector.apply(m, "concrete")
    assert st.inputs["Polish"].default_value == 0.0
    assert st.inputs["Porosity"].default_value == pytest.approx(0.8)


def test_auto_preset_rule(empty_scene):
    a = GENERATED["principled_basic"]()
    a.node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 1.0
    assert injector.resolve_preset(a, "AUTO", "Box") == "bare_metal"
    b = GENERATED["principled_basic"]()
    assert injector.resolve_preset(b, "AUTO", "SteelPipe") == "painted_metal"
    assert injector.resolve_preset(b, "AUTO", "Wall") == "concrete"


def test_multi_material_and_shared_material(empty_scene):
    shared = ms.principled("Shared")
    other = ms.principled("Other")
    a = ms.sharp_cube(empty_scene, name="A", cuts=2, material=shared)
    a.data.materials.append(other)
    a.data.materials.append(None)
    b = ms.sharp_cube(empty_scene, name="B", cuts=2, location=(3, 0, 1), material=shared)
    reps = weathering.apply_object(a, empty_scene, "painted_metal")
    weathering.apply_object(b, empty_scene, "painted_metal")
    assert shared.realworn.applied and other.realworn.applied
    assert any("shared by 2" in m for _, m in reps)
    assert a.realworn.seed != b.realworn.seed
    # removing A keeps the shared material for B, restores the unshared one
    weathering.remove_object(a, empty_scene)
    assert shared.realworn.applied and not other.realworn.applied
    assert not a.modifiers
    weathering.remove_object(b, empty_scene)
    assert not shared.realworn.applied
    assert naming.OB_SEED not in b


def test_linked_library_material_skipped(empty_scene, out_dir):
    lib_path = os.path.join(out_dir, "lib_mat.blend")
    m = bpy.data.materials.new("LibMat")
    bpy.data.libraries.write(lib_path, {m}, fake_user=True)
    bpy.data.materials.remove(m)
    with bpy.data.libraries.load(lib_path, link=True) as (src, dst):
        dst.materials = ["LibMat"]
    linked = dst.materials[0]
    ok, why = injector.can_edit(linked)
    assert not ok and "library" in why
    with pytest.raises(injector.InjectError):
        injector.apply(linked)


def test_remove_all_leaves_no_trace(empty_scene):
    floor, obs = ms.demo_props(empty_scene)
    for o in [floor] + obs:
        weathering.apply_object(o, empty_scene)
    assert any(g.name.startswith("RW_") for g in bpy.data.node_groups)
    weathering.remove_all()
    for o in empty_scene.objects:
        assert not o.modifiers
        assert naming.OB_SEED not in o
    for m in bpy.data.materials:
        assert not any(nodeutil.is_owned(n) for n in m.node_tree.nodes)
    assert not [g for g in bpy.data.node_groups if g.name.startswith("RW_")]
    assert naming.COLL_GROUND not in bpy.data.collections
    assert naming.SC_AGE not in empty_scene

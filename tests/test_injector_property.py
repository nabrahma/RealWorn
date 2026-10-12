"""Property-based injector test (PRD required suite 3).

Hypothesis generates random valid shader trees (textures, math, mixes, one or more
Principled BSDFs, optional coat and normal map) and checks that apply -> remove restores
the tree exactly and that applying twice equals applying once.
"""

import random

import bpy
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from realworn.core import injector, snapshot

TEX = ("ShaderNodeTexNoise", "ShaderNodeTexVoronoi", "ShaderNodeTexWave", "ShaderNodeTexMagic",
       "ShaderNodeTexGradient", "ShaderNodeTexChecker")
MATH_OPS = ("ADD", "MULTIPLY", "POWER", "MAXIMUM", "SINE", "ABSOLUTE")


def _float_out(n):
    outs = [s for s in n.outputs if s.type == "VALUE"]
    return outs[0] if outs else None


def _color_out(n):
    outs = [s for s in n.outputs if s.type == "RGBA"]
    return outs[0] if outs else None


def build_random(seed, n_principled, n_tex, n_math, coat, normal_map, mixer):
    rng = random.Random(seed)
    mat = bpy.data.materials.new("H_{}".format(seed))
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    texs = []
    for i in range(n_tex):
        t = nt.nodes.new(rng.choice(TEX))
        t.location = (-900, i * 200)
        texs.append(t)
    vals = [o for o in (_float_out(t) for t in texs) if o is not None]
    cols = [o for o in (_color_out(t) for t in texs) if o is not None]
    for i in range(n_math):
        m = nt.nodes.new("ShaderNodeMath")
        m.operation = rng.choice(MATH_OPS)
        m.inputs[1].default_value = round(rng.uniform(0, 2), 3)
        if vals:
            nt.links.new(rng.choice(vals), m.inputs[0])
        vals.append(m.outputs[0])
    bsdfs = []
    for i in range(n_principled):
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        b.location = (0, -i * 700)
        b.inputs["Metallic"].default_value = rng.choice((0.0, 1.0))
        b.inputs["Roughness"].default_value = round(rng.random(), 3)
        if cols and rng.random() < 0.7:
            nt.links.new(rng.choice(cols), b.inputs["Base Color"])
        if vals and rng.random() < 0.6:
            nt.links.new(rng.choice(vals), b.inputs["Roughness"])
        if coat:
            if vals and rng.random() < 0.5:
                nt.links.new(rng.choice(vals), b.inputs["Coat Weight"])
            else:
                b.inputs["Coat Weight"].default_value = round(rng.random(), 3)
        if normal_map and cols:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(rng.choice(cols), nm.inputs["Color"])
            nt.links.new(nm.outputs[0], b.inputs["Normal"])
        bsdfs.append(b)
    shader = bsdfs[0].outputs[0]
    for b in bsdfs[1:]:
        node = nt.nodes.new("ShaderNodeMixShader" if mixer == "mix" else "ShaderNodeAddShader")
        ins = [s for s in node.inputs if s.type == "SHADER"]
        nt.links.new(shader, ins[0])
        nt.links.new(b.outputs[0], ins[1])
        if mixer == "mix" and vals:
            nt.links.new(rng.choice(vals), node.inputs[0])
        shader = node.outputs[0]
    nt.links.new(shader, out.inputs["Surface"])
    return mat


trees = st.builds(dict, seed=st.integers(0, 10 ** 6), n_principled=st.integers(1, 3), n_tex=st.integers(0, 4),
                  n_math=st.integers(0, 4), coat=st.booleans(), normal_map=st.booleans(),
                  mixer=st.sampled_from(("mix", "add")))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(params=trees)
def test_random_trees_roundtrip_and_idempotent(empty_scene, params):
    mat = build_random(**params)
    before = snapshot.serialize(mat.node_tree)
    injector.apply(mat, "AUTO")
    assert len(injector.stacks(mat.node_tree)) == params["n_principled"]
    once = snapshot.dumps(snapshot.serialize(mat.node_tree, include_owned=True))
    assert injector.apply(mat, "AUTO") == "updated"
    assert snapshot.dumps(snapshot.serialize(mat.node_tree, include_owned=True)) == once
    assert injector.remove(mat) == []
    assert snapshot.diff(before, snapshot.serialize(mat.node_tree)) == []
    bpy.data.materials.remove(mat)

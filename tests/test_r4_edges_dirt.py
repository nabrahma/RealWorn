"""R4: Edge Wear and Dirt (EDW-1..EDW-3, DRT-1..DRT-3) and Bake Edges and AO (ENG-1..ENG-4): the
tutorial's Bevel and AO recipes, live controls, touch-up paint, Baked versus Live in Cycles, Baked
in EEVEE versus Baked in Cycles, and the EEVEE warning."""

import os
import types

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import bake, compiler, images, kinds as K, layers, naming, setup
from realworn.ui import panels

RES = 192


@pytest.fixture
def block(empty_scene):
    """An L-shaped block on a ground plane: convex edges for wear, concave corners and ground
    contact for dirt."""
    sc = empty_scene
    ob = ms.l_block(sc, material=ms.principled("Block", (0.7, 0.68, 0.62), roughness=0.6))
    ob.data.uv_layers.new(name="UVMap")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=4.0)
    ms._link(sc, "Ground", bm, (0, 0, 0), ms.principled("GroundMat", (0.3, 0.3, 0.3)))
    setup.setup_object(ob)
    ms.camera_light(sc, cam_loc=(4.2, -4.8, 3.4), target=(0.4, 0.2, 0.5))
    return sc, ob, ob.material_slots[0].material


def _layers(mat):
    ew = layers.add_layer(mat, "EDGE_WEAR")
    ew.content, ew.color, ew.roughness = "COLOR", (0.85, 0.82, 0.75), 0.3
    dirt = layers.add_layer(mat, "DIRT")
    return ew, dirt


def test_recipes_are_the_tutorials_nodes(block):
    """EDW-1 / DRT-1: Bevel normal . Geometry normal through a ramp, the grunge through a Map Range
    into the Bevel radius; AO through a Color Ramp; ENG-4 Bevel samples 8."""
    sc, ob, mat = block
    ew, dirt = _layers(mat)
    g = mat.realworn.stack
    bevel = g.nodes[naming.layer_node(ew.id, "bevel")]
    assert bevel.samples == K.BEVEL_SAMPLES == 8
    radius = g.nodes[naming.layer_node(ew.id, "edge.radius")]
    assert radius.bl_idname == "ShaderNodeMapRange"  # Breakup on by default (MSK-2)
    assert radius.inputs[4].default_value == pytest.approx(0.005)  # Width 5 mm (EDW-2)
    dot = bevel.outputs["Normal"].links[0].to_node
    assert dot.bl_idname == "ShaderNodeVectorMath" and dot.operation == "DOT_PRODUCT"
    assert {lk.from_node.bl_idname for s in dot.inputs for lk in s.links} == {"ShaderNodeBevel",
                                                                               "ShaderNodeNewGeometry"}
    ao = g.nodes[naming.layer_node(dirt.id, "ao")]
    assert ao.inputs["Distance"].default_value == pytest.approx(0.2)  # 20 cm (DRT-2)
    assert ao.outputs["AO"].links[0].to_node.bl_idname == "ShaderNodeValToRGB"
    assert not ao.only_local
    c = compiler.COMPILES["count"]
    ew.width_mm, ew.breakup_amount, dirt.distance_cm, dirt.only_local, ew.bevel_samples = 8.0, 0.3, 35.0, True, 16
    assert compiler.COMPILES["count"] == c  # all value edits
    assert radius.inputs[3].default_value == pytest.approx(0.008 * 0.7) and radius.inputs[4].default_value == pytest.approx(0.008)
    assert ao.inputs["Distance"].default_value == pytest.approx(0.35) and ao.only_local and bevel.samples == 16
    ew.breakup_amount = 0.0  # no grunge in the radius: a plain value, recompiles
    assert compiler.COMPILES["count"] == c + 1
    assert g.nodes[naming.layer_node(ew.id, "edge.radius")].bl_idname == "ShaderNodeValue"


def test_touch_up_paint_adds_to_the_generated_mask(block):
    """EDW-3 / DRT-3: an optional painted mask is added on top of the Bevel / AO mask."""
    sc, ob, mat = block
    ew, dirt = _layers(mat)
    assert ew.mask_image is None and K.paint_optional("EDGE_WEAR")
    ew.mask_res = 256
    images.fill(images.ensure_mask(ob, mat, ew), 1.0)
    cov = bake.new_image("rw_t_cov", 64, float_buffer=True)
    for ly in mat.realworn.layers:
        ly.visible = ly is ew or ly.id == ew.id
    bake.bake_socket(sc, ob, mat, bake.stack_output("Coverage"), cov)
    px = images.pixels(cov)[..., 0]
    islands = px[px > 0.01]  # texels outside the UV islands bake to 0
    assert float(islands.mean()) > 0.98  # painted everywhere: the whole object worn


def _render(sc, path, engine="CYCLES", samples=128):
    ru.setup(sc, engine=engine, samples=samples, res=(RES, RES))
    return ru.render(sc, path)


def test_baked_matches_live_in_cycles(block, out_dir):
    """ENG-2 suite: Baked versus Live in Cycles, mean difference under 0.03."""
    sc, ob, mat = block
    _layers(mat)
    live = _render(sc, os.path.join(out_dir, "r4_live.png"))
    import time
    t = time.perf_counter()
    assert bpy.ops.realworn.bake_sources(object=ob.name, material=mat.name, resolution=1024) == {"FINISHED"}
    dt = time.perf_counter() - t
    srcs = [ly for ly in mat.realworn.layers if ly.kind in ("EDGE_WEAR", "DIRT")]
    assert all(ly.edge_source == "BAKED" and ly.baked_image is not None for ly in srcs)
    assert all(ly.baked_image.get(naming.IMG_BAKED_SOURCE) for ly in srcs)
    g = mat.realworn.stack
    assert not [n for n in g.nodes if n.bl_idname in ("ShaderNodeBevel", "ShaderNodeAmbientOcclusion")]
    baked = _render(sc, os.path.join(out_dir, "r4_baked.png"))
    d = ru.mad(live, baked)
    record("v3 Bake Edges and AO, L-block (2 masks, {} px)".format(srcs[0].baked_image.size[0]), dt, "s", None,
           "Cycles 32 samples per mask, CPU")
    record("v3 Edge Wear + Dirt, Baked vs Live in Cycles (mean abs difference)", d, "", 0.03, "L-block, 128 spp")
    print("\n[ENG-2] baked in {:.2f} s; Baked vs Live in Cycles: mean difference {:.4f}".format(dt, d))
    assert d < 0.03


def test_baked_eevee_matches_baked_cycles(block, out_dir):
    """ENG-2 suite: Baked masks look the same in EEVEE: correlation above 0.95 with Cycles."""
    sc, ob, mat = block
    ew, dirt = _layers(mat)
    bake.bake_sources(ob, mat, sc, resolution=1024)
    corr = {}
    for ly in (ew, dirt):
        mat.realworn.active_layer_index = layers.index_of(mat, ly.id)
        mat.realworn.mask_view = True
        a = _render(sc, os.path.join(out_dir, "r4_{}_cycles.png".format(ly.kind)), "CYCLES", 32).mean(axis=2)
        b = _render(sc, os.path.join(out_dir, "r4_{}_eevee.png".format(ly.kind)), "BLENDER_EEVEE", 16).mean(axis=2)
        corr[ly.kind] = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        mat.realworn.mask_view = False
    for k, c in corr.items():
        record("v3 {} Baked: EEVEE vs Cycles Mask View correlation".format(K.label(k)), c, "", None, "budget: above 0.95")
    print("\n[ENG-2] Baked EEVEE vs Cycles correlation: {}".format({k: round(v, 4) for k, v in corr.items()}))
    assert all(c > 0.95 for c in corr.values())


def test_eevee_warning_and_status():
    """ENG-3: a Live Edge Wear or Dirt layer warns in Material Preview."""
    ly = types.SimpleNamespace(kind="DIRT", edge_source="LIVE", content="COLOR", texture=None, mask_image=None)
    mp = types.SimpleNamespace(space_data=types.SimpleNamespace(shading=types.SimpleNamespace(type="MATERIAL")))
    rend = types.SimpleNamespace(space_data=types.SimpleNamespace(shading=types.SimpleNamespace(type="RENDERED")))
    assert panels.status(None, ly, mp) == "Live - Bake for EEVEE"
    assert panels.status(None, ly, rend) == "Live"
    ly.edge_source = "BAKED"
    assert panels.status(None, ly, mp) == "Baked"


def test_remove_after_baking_is_exact(block):
    from test_core_setup import state_of
    sc, ob, mat = block
    setup.remove_object(ob)
    after_plain = state_of(ob)
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    _layers(mat)
    bake.bake_sources(ob, mat, sc, resolution=256)
    names = [ly.baked_image.name for ly in mat.realworn.layers]
    assert setup.remove_object(ob) == []
    assert state_of(ob) == after_plain
    assert not [n for n in names if n in bpy.data.images]

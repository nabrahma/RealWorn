"""PRD v2.1 shared bump and normals: BMP-1 (one Bump for the stack), BMP-2 (normal maps blended
into the normal below), BMP-3 (Height toggle removes a layer's share), BMP-4 (displacement and
bump use one height), acceptance test T7."""

import os

import bpy
import numpy as np
import pytest

import render_util as ru
import sharp_util as su
from realworn.core import compiler, grunge, injector, layers, naming

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")


def _bumps(mat):
    return [n for n in mat.realworn.stack.nodes if n.bl_idname == "ShaderNodeBump"]


def _painted(ob, mat, kind):
    ly = layers.add_layer(mat, kind)
    su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.5, 0.5), 0.3, 0.1))
    return mat.realworn.layers[ly.name]


def test_bmp1_bmp3_one_bump_and_height_toggle(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    rust = _painted(ob, mat, "RUST")
    wear = _painted(ob, mat, "WEAR")
    assert len(_bumps(mat)) == 1
    bump = _bumps(mat)[0]
    before = bump.inputs["Height"].links[0].from_node.name
    rust.height.enabled = False  # BMP-3: the layer leaves the shared sum
    assert len(_bumps(mat)) == 1
    g = mat.realworn.stack
    assert not any(n.name == naming.layer_node(rust.id, "height.value") for n in g.nodes)
    assert before


def test_t7_v21_without_detail_matches_v20(empty_scene, out_dir):
    """T7: Edge Detail and looks off, a v2.1 material renders like the v2.0 stack (one shared bump)."""
    sc = empty_scene
    ob, mat = su.crate(sc, size=1.0)
    for kind in ("RUST", "WEAR", "DIRT"):
        ly = _painted(ob, mat, kind)
        ly.detail.strength, ly.look.enabled = 0.0, False
    ms_cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(ms_cam)
    ms_cam.location, ms_cam.rotation_euler = (2.2, -2.4, 1.8), (np.radians(62), 0, np.radians(42))
    sc.camera = ms_cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sc.collection.objects.link(sun)
    sun.rotation_euler = (0.9, 0.2, 0.6)
    ru.setup(sc, samples=16, res=(160, 160))
    sc.render.image_settings.file_format = "OPEN_EXR"
    a = ru.render(sc, os.path.join(out_dir, "t7_v21.exr"))
    mat.realworn.v21 = False
    compiler.compile(mat)
    b = ru.render(sc, os.path.join(out_dir, "t7_v20.exr"))
    d = float(np.abs(a - b).mean())
    print("\n[T7] v2.1 stack (detail and looks off) vs v2.0 stack: mean difference {:.5f}".format(d))
    assert d < 0.01


def test_bmp2_normal_maps_add_detail_on_v21_only(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = _painted(ob, mat, "CUSTOM")
    ly.normal_image = grunge.load("cracks")  # any image works as a stand-in normal map
    ly.color.use_uv = True  # tangent-space maps need a UV mapping
    g = mat.realworn.stack
    nm = g.nodes[naming.layer_node(ly.id, "normal.map")]
    users = [lk.to_node for lk in nm.outputs["Normal"].links]
    assert any(n.bl_idname == "ShaderNodeVectorMath" and n.operation == "SUBTRACT" for n in users)
    assert g.nodes.get(naming.layer_node("stack", "geom")) is not None
    mat.realworn.v21 = False
    compiler.compile(mat)
    nm = g.nodes[naming.layer_node(ly.id, "normal.map")]
    assert any(n.bl_idname == "ShaderNodeMix" for n in (lk.to_node for lk in nm.outputs["Normal"].links))


def test_bmp4_displacement_and_bump_share_one_height(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    _painted(ob, mat, "RUST")  # 0.5 mm height
    dmg = _painted(ob, mat, "DAMAGE")
    dmg.damage.depth_mode = "DISPLACEMENT"
    g = mat.realworn.stack
    assert _bumps(mat) == []  # Blender bumps the fine detail from the displacement itself
    disp_src = g.nodes["RW::out"].inputs["Displacement"].links[0].from_node
    # the displacement output sums the layer heights and the damage height
    assert disp_src.bl_idname == "ShaderNodeMath" and disp_src.operation == "ADD"
    assert injector.nodeutil.find(mat.node_tree, "disp") is not None
    dmg.damage.depth_mode = "SHADER"
    assert len(_bumps(mat)) == 1

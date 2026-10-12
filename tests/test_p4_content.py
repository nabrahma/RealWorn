"""P4 acceptance: all layer types render, PBR Set detection and content (LAY-2/LAY-5), Water layer
(WAT-1..WAT-4, suite 7 specular test), Height Blend (ING-4), Colour Variation (LAY-4), Paint layer
paints its own colour image (PNT-10)."""

import math
import os

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import images, layer_types as LT, layers, naming, pbrset, setup

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def sheet(sc, color=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.9, segs=24):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=segs, y_segments=segs, size=1.0)
    ob = ms._link(sc, "Sheet", bm, (0, 0, 0), ms.principled("SheetMat", color, metallic, roughness))
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def top_camera(sc, res=96, engine="BLENDER_EEVEE", samples=4):
    ms.camera_light(sc, cam_loc=(0, 0, 4), target=(0, 0, 0))
    ru.look_at(sc.camera, (0, 0, 4), (0, 0, 0), ortho_scale=1.9)
    ru.setup(sc, engine=engine, samples=samples, res=(res, res))
    sc.view_settings.view_transform = "Standard"


def fill(ob, mat, ly, value=1.0):
    images.fill(images.ensure_mask(ob, mat, ly), value)


# ------------------------------------------------------------------ types
@pytest.mark.parametrize("kind", [k for k in LT.ORDER if k != "DECAL"])
def test_every_type_compiles_and_shows(empty_scene, out_dir, kind):
    sc = empty_scene
    ob, mat = sheet(sc)
    top_camera(sc)
    base = ru.render(sc, os.path.join(out_dir, "p4_base_{}.png".format(kind)))
    ly = layers.add_layer(mat, kind)
    if kind == "CUSTOM":  # neutral grey on a grey base: give it a colour to see
        ly.color.color = (0.8, 0.2, 0.1)
    if kind == "PAINT":
        img = images.ensure_content(ob, mat, ly)
        images._fill(img, (0.9, 0.1, 0.1, 1.0))
        img.update()
    else:
        fill(ob, mat, ly)
    out = ru.render(sc, os.path.join(out_dir, "p4_{}.png".format(kind)))
    d = ru.mad(base, out)
    print("\n[type] {} changes the look by MAD {:.4f}".format(kind, d))
    assert d > 0.005, kind


# --------------------------------------------------------------- PBR sets
def test_pbr_detection_names():
    files = ["wall_diff_1k.jpg", "wall_rough_1k.exr", "wall_nor_gl_1k.exr", "wall_nor_dx_1k.exr",
             "wall_disp_1k.png", "wall_metal_1k.exr", "wall_ao_1k.jpg", "readme.txt"]
    det = pbrset.detect(["/x/" + f for f in files])
    assert {k: os.path.basename(v) for k, v in det.items()} == {
        "color": "wall_diff_1k.jpg", "roughness": "wall_rough_1k.exr", "normal": "wall_nor_gl_1k.exr",
        "height": "wall_disp_1k.png", "metallic": "wall_metal_1k.exr"}
    assert pbrset.classify("Bricks_BaseColor.png") == "color"
    assert pbrset.classify("T_Rock_Albedo.tga") == "color"
    assert pbrset.classify("rock_Roughness.png") == "roughness"
    assert pbrset.classify("rock_Displacement.exr") == "height"


@pytest.mark.skipif(not os.path.isdir(os.path.join(CORPUS, "metal_plate", "textures")),
                    reason="Poly Haven corpus not downloaded")
def test_pbr_set_as_layer_content(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = sheet(sc, color=(0.1, 0.3, 0.6))
    ly = layers.add_layer(mat, "WEAR")
    ly.lock_source = "NONE"
    done = pbrset.assign(mat, ly, os.path.join(CORPUS, "metal_plate", "textures"), scale=0.5)
    assert set(done) == {"color", "roughness", "metallic", "height", "normal"}
    g = mat.realworn.stack
    fill(ob, mat, ly)
    tex = g.nodes[naming.layer_node(ly.id, "color.img")]
    assert tex.projection == "BOX" and tex.image.colorspace_settings.name == "sRGB"  # LAY-5
    assert g.nodes[naming.layer_node(ly.id, "roughness.img")].image.colorspace_settings.name == "Non-Color"
    m = g.nodes[naming.layer_node(ly.id, "color.map")]
    assert tuple(m.inputs["Scale"].default_value) == pytest.approx((2.0, 2.0, 2.0))
    ly.color.scale = 0.25  # value edit: the mapping node follows without a recompile
    assert tuple(m.inputs["Scale"].default_value) == pytest.approx((4.0, 4.0, 4.0))
    top_camera(sc)
    img = ru.render(sc, os.path.join(out_dir, "p4_pbr.png"))
    assert float(img.std()) > 0.02  # the metal plate texture shows


# ----------------------------------------------------------------- water
def _specular_setup(sc):
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy, sun.data.angle = 4.0, math.radians(6)
    sun.rotation_euler = (math.radians(-45), 0, 0)  # light travels towards -Y, 45 degrees down
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    ru.look_at(cam, (0, -2.5, 2.5), (0, 0, 0))  # on the mirror direction (light travels to -Y, down)
    cam.data.lens = 50
    w = sc.world or bpy.data.worlds.new("W")
    sc.world = w
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.02, 0.02, 0.02, 1)
    ru.setup(sc, engine="CYCLES", samples=32, res=(96, 96))
    sc.view_settings.view_transform = "Standard"


def test_water_gives_a_specular_highlight(empty_scene, out_dir):
    """Suite 7: Water at roughness 0.03 shows a measured highlight where the rough base shows none."""
    sc = empty_scene
    ob, mat = sheet(sc, roughness=0.9)
    _specular_setup(sc)
    dry = ru.render(sc, os.path.join(out_dir, "p4_spec_dry.png")).mean(axis=2)
    ly = layers.add_layer(mat, "WATER")
    fill(ob, mat, ly)
    wet = ru.render(sc, os.path.join(out_dir, "p4_spec_wet.png")).mean(axis=2)
    hd, hw = int((dry > 0.97).sum()), int((wet > 0.97).sum())
    print("\n[water] highlight pixels dry {}, wet {}; peak dry {:.3f}, wet {:.3f}".format(
        hd, hw, float(dry.max()), float(wet.max())))
    assert hd == 0 and hw >= 6  # the sun's reflection appears only on the wet surface


def test_water_darkens_porous_more_than_metal(empty_scene, out_dir):
    sc = empty_scene
    res = {}
    for name, metal, rough in (("concrete", 0.0, 0.9), ("metal", 1.0, 0.3)):
        bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
        sc = bpy.context.scene
        ob, mat = sheet(sc, color=(0.6, 0.6, 0.6), metallic=metal, roughness=rough)
        top_camera(sc)
        a = ru.render(sc, os.path.join(out_dir, "p4_dark_{}_a.png".format(name))).mean()
        ly = layers.add_layer(mat, "WATER")
        ly.roughness.enabled = False  # isolate WAT-1 darkening from the gloss
        ly.water.edge = 0.0
        fill(ob, mat, ly)
        mat.realworn.stack.nodes[naming.layer_node(ly.id, "water")].inputs["Coat Weight"].default_value = 0.0
        b = ru.render(sc, os.path.join(out_dir, "p4_dark_{}_b.png".format(name))).mean()
        res[name] = (a - b) / a
    print("\n[water] darkening concrete {:.3f}, metal {:.3f}".format(res["concrete"], res["metal"]))
    assert res["concrete"] > 0.15 and abs(res["metal"]) < res["concrete"] * 0.4


def test_standing_water_flattens_relief(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = sheet(sc, roughness=0.6)
    top_camera(sc)
    bumps = layers.add_layer(mat, "CUSTOM")
    bumps.color.enabled = False
    bumps.height.source = "IMAGE"
    from realworn.core import grunge
    bumps.height.image = grunge.load("chips_large")  # blobs several pixels wide at this zoom
    bumps.height.value = 6.0
    bumps.height.scale = 0.8
    fill(ob, mat, bumps)
    sun = bpy.data.objects["Sun"]
    sun.rotation_euler = (math.radians(75), 0, math.radians(30))  # grazing light shows relief
    rough = ru.render(sc, os.path.join(out_dir, "p4_relief.png")).mean(axis=2)
    ly = layers.add_layer(mat, "WATER")
    ly.water.depth = 1.0
    fill(ob, mat, ly)
    flat = ru.render(sc, os.path.join(out_dir, "p4_relief_water.png")).mean(axis=2)
    print("\n[depth] relief std {:.4f} -> under standing water {:.4f}".format(rough.std(), flat.std()))
    assert flat.std() < rough.std() * 0.5


# --------------------------------------------------------- height blend
def test_height_blend_fills_low_spots_first(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = sheet(sc)
    nt = mat.node_tree  # base height: an X gradient feeding the Principled bump (captured by Setup)
    setup.remove_object(ob)
    tc, gr = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeTexGradient")
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.0
    nt.links.new(tc.outputs["Generated"], gr.inputs["Vector"])
    nt.links.new(gr.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "DIRT")
    assert ly.use_height_blend
    img = images.ensure_mask(ob, mat, ly)
    images._fill(img, (0.5, 0.5, 0.5, 1.0))  # an even half-strength stroke everywhere
    img.update()
    ly.threshold, ly.softness, ly.height_blend = 0.5, 0.1, 1.0
    top_camera(sc)
    mat.realworn.mask_view = True
    m = ru.render(sc, os.path.join(out_dir, "p4_hblend.png")).mean(axis=2)
    low, high = float(m[20:76, 8:40].mean()), float(m[20:76, 56:88].mean())
    print("\n[height blend] mask on low side {:.3f}, high side {:.3f}".format(low, high))
    assert low > high + 0.4


def test_colour_variation(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = sheet(sc)
    top_camera(sc)
    ly = layers.add_layer(mat, "CUSTOM")
    ly.color.color = (0.4, 0.3, 0.2)
    ly.height.enabled = False
    fill(ob, mat, ly)
    plain = ru.render(sc, os.path.join(out_dir, "p4_var0.png"))
    ly.use_variation = True
    ly.variation, ly.variation_scale = 0.8, 0.3
    varied = ru.render(sc, os.path.join(out_dir, "p4_var1.png"))
    diff = (varied - plain)[16:80, 16:80].mean(axis=2)  # lighting cancels out, the jitter remains
    print("\n[variation] std of the change {:.4f}, mean change {:.4f}".format(float(diff.std()),
                                                                           float(diff.mean())))
    assert float(diff.std()) > 0.02 and abs(float(diff.mean())) < 0.05  # varies around the set colour


def test_paint_layer_paints_its_colour(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = sheet(sc, color=(0.5, 0.5, 0.5))
    top_camera(sc)
    ly = layers.add_layer(mat, "PAINT")
    img = images.ensure_content(ob, mat, ly)
    w = img.size[0]
    px = np.zeros((w, w, 4), np.float32)
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", uv)
    px[...] = (0.0, 0.0, 0.0, 0.0)
    px[:, : w // 2] = (0.9, 0.05, 0.05, 1.0)  # paint the left half of the RW_Paint UV red
    img.pixels.foreach_set(px.ravel())
    img.update()
    out = ru.render(sc, os.path.join(out_dir, "p4_paint_layer.png"))
    red = out[..., 0] - out[..., 1]
    assert float((red > 0.3).mean()) > 0.1  # red where painted
    assert float((np.abs(red) < 0.05).mean()) > 0.1  # base grey elsewhere

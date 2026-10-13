"""R1: Load Texture (LT-1..LT-5), box mapping everywhere (SET-3), Bump by default (SET-4), Variation
layers (VAR-1..VAR-3), and the mask recipe rendered against its pure-Python reference (MSK-1)."""

import os
import time

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import compiler, images, kinds as K, layers, naming, nodeutil, pbrset, setup
from test_core_setup import uv_cube

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")


def write_set(folder, files, size=16, value=0.5):
    os.makedirs(folder, exist_ok=True)
    for f in files:
        path = os.path.join(folder, f)
        if os.path.exists(path):
            continue
        img = bpy.data.images.new("tmp_set", size, size, alpha=True)
        img.pixels.foreach_set(np.full(size * size * 4, value, np.float32))
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
    return folder


# ------------------------------------------------------------------ LT-1, LT-2
def test_detection_names():
    ph = ["rust_coarse_01_diff_1k.png", "rust_coarse_01_rough_1k.png", "rust_coarse_01_nor_dx_1k.png",
          "rust_coarse_01_disp_1k.png", "rust_coarse_01_arm_1k.png"]
    m = pbrset.detect(ph)
    assert set(m) == {"color", "roughness", "normal", "normal_is_dx", "height", "packed"}
    acg = ["Rust004_1K-PNG_Color.png", "Rust004_1K-PNG_Roughness.png", "Rust004_1K-PNG_NormalGL.png",
           "Rust004_1K-PNG_NormalDX.png", "Rust004_1K-PNG_Displacement.png", "Rust004_1K-PNG_AmbientOcclusion.png",
           "Rust004_1K-PNG_Metalness.png"]
    m = pbrset.detect(acg)
    assert m["normal"].endswith("NormalGL.png") and "normal_is_dx" not in m  # OpenGL preferred
    assert {"color", "roughness", "metallic", "height", "ao"} <= set(m)
    g = pbrset.detect(["old_paint_albedo.png", "old_paint_glossiness.png"])
    assert "gloss" in g and "roughness" not in g
    assert pbrset.detect(["wall_basecolor.png", "wall_ORM.png"])["packed"].endswith("wall_ORM.png")


@pytest.mark.parametrize("name, size", [("Rust004_2K_1m", 1.0), ("rust_50cm", 0.5), ("Paint 2.5m", 2.5),
                                        ("Rust004_1K-PNG", None), ("metal_plate_1k", None)])
def test_scale_from_name(name, size):
    assert pbrset.scale_from_name(os.path.join("C:/lib", name, "x_Color.png")) == size


@pytest.fixture
def wall(empty_scene):
    ob = uv_cube(empty_scene, "Wall", size=1.0, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def test_load_texture_into_the_base_box_maps_everything(wall):
    """SET-3 / SET-4 / LT-1: Object coordinates, Mapping in metres, Box projection Blend 0.3; the
    height goes to the material's Displacement through an owned node; the material stays on Bump."""
    ob, mat = wall
    folder = write_set(os.path.join(OUT, "sets", "plaster_red_2m"),
                       ["plaster_red_diff_1k.png", "plaster_red_rough_1k.png", "plaster_red_disp_1k.png"])
    done = layers.load_texture(mat, folder)
    assert set(done) == {"color", "roughness", "height"}
    st = mat.realworn
    assert st.base.loaded() and st.base.scale == pytest.approx(2.0) and st.base.name == "plaster red 2m"
    g = st.stack
    imgs = [n for n in g.nodes if n.bl_idname == "ShaderNodeTexImage"]
    assert len(imgs) == 3 and all(n.projection == "BOX" and n.projection_blend == pytest.approx(0.3) for n in imgs)
    mp = g.nodes[naming.layer_node("base", "tex.map")]
    assert tuple(mp.inputs["Scale"].default_value) == pytest.approx((0.5, 0.5, 0.5))
    assert mp.inputs["Vector"].links[0].from_socket.name == "Object"
    assert next(n for n in imgs if n.image.name.startswith("plaster_red_diff")).image.colorspace_settings.name == "sRGB"
    assert next(n for n in imgs if "rough" in n.image.name).image.colorspace_settings.name == "Non-Color"
    out = nodeutil.output_node(mat.node_tree)
    disp = out.inputs["Displacement"].links[0].from_node
    assert disp.name == naming.node_name("disp") and disp.inputs["Scale"].default_value == 1.0
    assert mat.displacement_method == "BUMP"
    st.base.scale = 4.0  # live
    assert tuple(mp.inputs["Scale"].default_value) == pytest.approx((0.25, 0.25, 0.25))
    c = compiler.COMPILES["count"]
    st.base_saturation, st.base.bump, st.base.roughness_offset = -0.4, 0.05, 0.1
    assert compiler.COMPILES["count"] == c
    assert g.nodes[naming.layer_node("base", "hsv")].inputs["Saturation"].default_value == pytest.approx(0.6)
    assert g.nodes[naming.layer_node("base", "tex.bump")].inputs[1].default_value == pytest.approx(0.05)


def test_arm_orm_split_and_gloss(wall):
    ob, mat = wall
    folder = write_set(os.path.join(OUT, "sets", "steel_packed"),
                       ["steel_albedo.png", "steel_glossiness.png", "steel_arm.png"])
    ly = layers.add_layer(mat, "VARIATION", "SECOND_MATERIAL")
    done = layers.load_texture(mat, folder, ly)
    assert "packed" in done and ly.texture.gloss and ly.content == "TEXTURE"
    g = mat.realworn.stack
    split = g.nodes[naming.layer_node(ly.id, "tex.split")]
    assert split.bl_idname == "ShaderNodeSeparateColor"
    assert split.outputs["Blue"].is_linked  # metallic from B
    rough = g.nodes[naming.layer_node(ly.id, "tex.roff")].inputs[0].links[0].from_node
    assert rough.bl_idname == "ShaderNodeMath" and rough.operation == "SUBTRACT"  # gloss used inverted


def test_swap_keeps_settings_and_paint(wall, tmp_path):
    """LT-5: loading over a set replaces its maps and keeps all other settings and paint."""
    ob, mat = wall
    a = write_set(str(tmp_path / "set_a"), ["a_diff.png", "a_rough.png"])
    b = write_set(str(tmp_path / "set_b_50cm"), ["b_diff.png", "b_disp.png"])
    ly = layers.add_layer(mat, "PAINT")
    layers.load_texture(mat, a, ly)
    ly.texture.scale, ly.hue, ly.sharpness, ly.texture.bump = 3.0, 0.2, 0.8, 0.04
    img = images.ensure_mask(ob, mat, ly)
    images.fill(img, 1.0)
    layers.load_texture(mat, b, ly)
    assert ly.texture.color.name.startswith("b_diff") and ly.texture.roughness is None and ly.texture.height
    assert ly.texture.scale == pytest.approx(0.5)  # the new set's size from its name
    assert (ly.hue, ly.sharpness, ly.texture.bump) == pytest.approx((0.2, 0.8, 0.04))
    assert ly.mask_image == img and images.pixels(img)[..., 0].min() == 1.0
    layers.load_texture(mat, a, ly)
    assert ly.texture.scale == pytest.approx(0.5)  # no size in the name: Scale kept


def test_library_and_recent(empty_scene, tmp_path):
    pbrset._recent_fallback.clear()  # unregistered: Recent is one list for the whole run
    lib = tmp_path / "lib"
    write_set(str(lib / "Plaster" / "red_plaster_2m"), ["red_plaster_diff_1k.png"])
    write_set(str(lib / "concrete_floor"), ["concrete_floor_Color.png", "concrete_floor_Displacement.png"])
    write_set(str(lib / "notes"), ["screenshot.png"])  # not a set
    entries = pbrset.library(str(lib))
    assert [e["name"] for e in entries] == ["concrete floor", "red plaster 2m"]
    assert {e["category"] for e in entries} == {"", "Plaster"}
    pbrset.add_recent(entries[1]["path"])
    items = pbrset.library_enum_items(str(lib))
    assert items[0][1].startswith("Recent: red plaster") and len(items) == 2


def test_load_texture_operator_and_time(wall):
    """LT-1 via the operator; the PRD budget is under 1 s for a 2K set."""
    ob, mat = wall
    folder = write_set(os.path.join(OUT, "sets", "big_2k_1m"), ["big_diff_2k.png", "big_rough_2k.png",
                                                               "big_disp_2k.png"], size=2048, value=0.4)
    for img in [i for i in bpy.data.images if i.name.startswith("big_")]:
        bpy.data.images.remove(img)
    t = time.perf_counter()
    assert bpy.ops.realworn.use_texture(object=ob.name, material=mat.name, layer="BASE", path=folder) == {"FINISHED"}
    dt = time.perf_counter() - t
    record("v3 Load Texture, 2K set (3 maps) into the Base", dt, "s", 1.0, "operator: detect, load, compile")
    print("\n[load] 2K set {:.3f} s".format(dt))
    assert mat.realworn.base.loaded() and dt < 1.0


# ------------------------------------------------------------------ Variation
def test_variation_has_no_paint_and_tints_below(wall):
    ob, mat = wall
    ly = layers.add_layer(mat, "VARIATION", "WASHED_OUT")
    g = mat.realworn.stack
    assert ly.mask_image is None and ly.breakup_grunge is not None and ly.breakup_amount == 1.0
    hsv = g.nodes[naming.layer_node(ly.id, "hsv")]
    src = hsv.inputs["Color"].links[0].from_node
    assert src.name == "RW::in"  # Tint Below: the stack's colour so far (here the base)
    assert hsv.inputs["Saturation"].default_value == pytest.approx(0.7)
    sub = g.nodes[naming.layer_node(ly.id, "breakup.sub")]
    assert sub.blend_type == "SUBTRACT" and sub.inputs[0].default_value == pytest.approx(1.0)
    ramp = g.nodes[naming.layer_node(ly.id, "ramp")]
    assert ramp.bl_idname == "ShaderNodeValToRGB"
    assert g.nodes[naming.layer_node(ly.id, "breakup.img")].projection == "BOX"


# ------------------------------------------------------------------ mask recipe
GRID = 8


def _image(name, values, res=64):
    """A float image: `values` (res, res) in R, G, B, alpha 1."""
    img = bpy.data.images.get(name) or bpy.data.images.new(name, res, res, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    px = np.ones((res, res, 4), np.float32)
    px[..., :3] = values[..., None]
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.pack()
    return img


def _recipe_plane(sc):
    """A 1 m plane in XY whose paint UV is x, y + 0.5 (texel column i sits at x = i / res - 0.5)."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    ob = ms._link(sc, "Grid", bm, (0, 0, 0), ms.principled("GridMat"))
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        co = me.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (co.x + 0.5, co.y + 0.5)
    setup.setup_object(ob, uv_method="EXISTING")
    ms.camera_light(sc, cam_loc=(0, 0, 3), target=(0, 0, 0))
    ru.look_at(sc.camera, (0, 0, 3), (0, 0, 0), ortho_scale=1.0)
    ru.setup(sc, engine="CYCLES", samples=1, res=(GRID * 8, 16))
    sc.render.resolution_y = 16
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filter_size = 0.01
    return ob, ob.material_slots[0].material


@pytest.mark.parametrize("amount,contrast,threshold,sharpness", [
    (0.0, 0.0, 0.5, 0.5), (1.0, 0.0, 0.5, 0.5), (0.6, 0.4, 0.4, 0.2), (1.0, 0.0, 0.7, 0.9), (0.3, 0.8, 0.3, 0.0)])
def test_mask_recipe_matches_reference(empty_scene, out_dir, amount, contrast, threshold, sharpness):
    """MSK-1 / suite Mask recipe: rendered over a grid of source and grunge values, the Mask View
    matches kinds.recipe within 0.02. The source S (a painted mask) steps along x in GRID values; the
    grunge G is a uniform image, one render per value (box mapping then needs no alignment)."""
    sc = empty_scene
    ob, mat = _recipe_plane(sc)
    ly = layers.add_layer(mat, "PAINT")
    steps = (np.floor(np.linspace(0, GRID, 64, endpoint=False)) / (GRID - 1)).astype(np.float32)
    ly.mask_image = _image("S_ramp", np.tile(steps[None, :], (64, 1)))
    grunge = _image("G_flat", np.zeros((64, 64), np.float32))
    ly.breakup_grunge = grunge
    ly.breakup_amount, ly.breakup_contrast, ly.threshold, ly.sharpness = amount, contrast, threshold, sharpness
    mat.realworn.mask_view = True
    worst = 0.0
    for j in range(GRID):
        gv = j / (GRID - 1)
        _image("G_flat", np.full((64, 64), gv, np.float32))
        path = os.path.join(out_dir, "r1_recipe_{}_{}_{}_{}_{}.exr".format(amount, contrast, threshold, sharpness, j))
        px = ru.render(sc, path).mean(axis=2)
        for i in range(GRID):
            got = float(px[8, i * 8 + 4])
            want = K.recipe(i / (GRID - 1), gv, amount, contrast, threshold, sharpness)
            worst = max(worst, abs(got - want))
    print("\n[recipe] a={} c={} t={} s={}: worst difference {:.4f}".format(amount, contrast, threshold, sharpness, worst))
    assert worst < 0.02

"""PRD v2.1 Q3: textured content looks (CNT-1..CNT-4), PBR set loading (CNT-5, CNT-7) and the
content library (CNT-6)."""

import os

import bpy
import numpy as np
import pytest

import sharp_util as su
from perf_log import record
from realworn.core import compiler, detail, layer_types as LT, layers, naming, pbrset

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")


def _flat_plate(sc, size=0.6):
    """A plane facing the camera, set up, with a fully painted layer helper."""
    ob, mat = su.wall(sc, width=size, height=size)
    return ob, mat


def _render_layer_color(sc, mat, idx, path):
    """Mask View's colour channel: the layer's own colour, unlit."""
    st = mat.realworn
    st.view_channel = "COLOR"
    try:
        return su.render_mask_view_rgb(sc, mat, idx, path)
    finally:
        st.view_channel = "MASK"


# ------------------------------------------------------------------ CNT-1, CNT-2
def test_every_effect_type_has_a_look_group(empty_scene):
    from realworn.core import assets
    names = [naming.content_group(k) for k in naming.CONTENT_TYPES]
    assets.ensure_groups(tuple(names))
    for n in names:
        g = bpy.data.node_groups[n]
        outs = [i.name for i in g.interface.items_tree if i.item_type == "SOCKET" and i.in_out == "OUTPUT"]
        assert outs == ["Color", "Roughness", "Height"], n
    assert set(LT.LOOK) == set(naming.CONTENT_TYPES)


def test_look_is_lean_live_and_routes_colour_roughness_and_relief(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "DIRT")
    assert ly.look.enabled  # v2.1 default for effect types
    ly.look.micro = 0.6  # Dirt's relief is off by default (Q4 cost); on here to test the route
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    g = mat.realworn.stack
    look = g.nodes[naming.layer_node(ly.id, "look")]
    assert look.node_tree.name == "RW_Content_Dirt"
    assert look.inputs["Color"].links[0].from_node.name == naming.layer_node(ly.id, "color.value")
    assert look.inputs["Roughness"].links[0].from_node.name == naming.layer_node(ly.id, "roughness.value")
    assert look.outputs["Color"].is_linked and look.outputs["Roughness"].is_linked
    assert look.outputs["Height"].is_linked  # micro relief joins the shared height sum
    bumps = [n for n in g.nodes if n.bl_idname == "ShaderNodeBump"]
    assert len(bumps) == 1  # rule 15: one shared bump
    c0 = compiler.COMPILES["count"]
    ly.look.color_var, ly.look.rough_var, ly.look.scale, ly.look.micro = 0.8, 0.1, 0.5, 1.2
    ly.color.color = (0.2, 0.1, 0.05)  # the channel value still drives the look live
    assert compiler.COMPILES["count"] == c0
    assert look.inputs["Color Variation"].default_value == pytest.approx(0.8)
    ly.look.micro = 0.0
    assert compiler.COMPILES["count"] == c0 + 1 and not g.nodes[naming.layer_node(ly.id, "look")].outputs["Height"].is_linked
    ly.look.enabled = False
    assert g.nodes.get(naming.layer_node(ly.id, "look")) is None


def test_four_looked_layers_one_bump(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    for kind in ("DIRT", "RUST", "WEAR", "WATER"):
        ly = layers.add_layer(mat, kind)
        su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    g = mat.realworn.stack
    assert len([n for n in g.nodes if n.bl_idname == "ShaderNodeBump"]) == 1
    assert len([n for n in g.nodes if n.name.endswith("::look")]) == 4


# ------------------------------------------------------------------ variation, CNT-4
def test_look_varies_the_colour(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = _flat_plate(sc)
    ly = layers.add_layer(mat, "DIRT")
    ly.color.blend = "MIX"  # look at the layer colour itself
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    from test_v21_sources import _ortho_front
    _ortho_front(sc, (0, 0, 0.3), 0.5, res=(256, 256))
    su.setup_render(sc, samples=4)
    on = _render_layer_color(sc, mat, 0, os.path.join(out_dir, "look_on.exr"))
    ly.look.enabled = False
    off = _render_layer_color(sc, mat, 0, os.path.join(out_dir, "look_off.exr"))
    lum_on, lum_off = on.mean(axis=2), off.mean(axis=2)
    s_on, s_off = float(lum_on.std() / lum_on.mean()), float(lum_off.std() / max(lum_off.mean(), 1e-6))
    print("\n[look] Dirt colour variation (std / mean): {:.3f} with the look, {:.3f} flat".format(s_on, s_off))
    record("v2.1 Content look: Dirt colour variation (std / mean)", s_on, "", None, "flat colour: {:.3f}".format(s_off))
    assert s_off < 0.01 and s_on > 0.08


def test_rust_rim_is_orange(empty_scene, out_dir):
    """CNT-4: Rust's colour across the edge band: the rim (where the soft stroke is weak but Edge
    Detail kept the rust) is more orange than the core."""
    sc = empty_scene
    ob, mat = _flat_plate(sc)
    ly = layers.add_layer(mat, "RUST")
    ly.detail.strength = 0.0  # a clean disk, so rim and core are easy to separate
    su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.3, 0.3), 0.2, 0.12))
    from test_v21_sources import _ortho_front
    _ortho_front(sc, (0, 0, 0.3), 0.5, res=(256, 256))
    su.setup_render(sc, samples=4)
    col = _render_layer_color(sc, mat, 0, os.path.join(out_dir, "rust_rim.exr"))
    yy, xx = np.mgrid[0:256, 0:256]
    d = np.hypot(xx - 127.5, yy - 127.5) / 256 * 0.5  # metres from the stroke centre
    core, rim = col[d < 0.04], col[(d > 0.135) & (d < 0.16)]
    orange = lambda c: float((c[:, 0] / np.maximum(c[:, 2], 1e-4)).mean())  # noqa: E731  red over blue
    print("\n[rust] core R/B {:.1f}, rim R/B {:.1f}; core luminance {:.3f}, rim {:.3f}".format(
        orange(core), orange(rim), core.mean(), rim.mean()))
    assert rim.mean() > core.mean() * 1.3  # brighter orange rim, dark brown core


# ------------------------------------------------------------------ CNT-5, CNT-7
def _write_set(folder, names):
    os.makedirs(folder, exist_ok=True)
    for n in names:
        img = bpy.data.images.new(n, 16, 16)
        img.pixels.foreach_set(np.full(16 * 16 * 4, 0.5, np.float32))
        img.filepath_raw, img.file_format = os.path.join(folder, n), "PNG"
        img.save()
        bpy.data.images.remove(img)
    return folder


def test_detect_poly_haven_and_ambientcg_names():
    ph = ["rust_coarse_01_diff_1k.png", "rust_coarse_01_rough_1k.png", "rust_coarse_01_nor_dx_1k.png",
          "rust_coarse_01_disp_1k.png", "rust_coarse_01_ao_1k.png"]
    m = pbrset.detect(ph)
    assert set(m) == {"color", "roughness", "normal", "normal_is_dx", "height", "ao"}
    acg = ["Rust004_1K-PNG_Color.png", "Rust004_1K-PNG_Roughness.png", "Rust004_1K-PNG_NormalGL.png",
           "Rust004_1K-PNG_NormalDX.png", "Rust004_1K-PNG_Displacement.png", "Rust004_1K-PNG_AmbientOcclusion.png",
           "Rust004_1K-PNG_Metalness.png"]
    m = pbrset.detect(acg)
    assert m["normal"].endswith("NormalGL.png") and "normal_is_dx" not in m
    assert {"color", "roughness", "metallic", "height", "ao"} <= set(m)
    g = pbrset.detect(["old_paint_albedo.png", "old_paint_glossiness.png"])
    assert "gloss" in g and "roughness" not in g


@pytest.mark.parametrize("name, size", [("Rust004_2K_1m", 1.0), ("rust_50cm", 0.5), ("Paint 2.5m", 2.5),
                                        ("Rust004_1K-PNG", None), ("metal_plate_1k", None)])
def test_scale_from_name(name, size):
    assert pbrset.scale_from_name(os.path.join("C:/lib", name, "x_Color.png")) == size


def test_assign_gloss_dx_ao_and_content_height(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "WEAR")
    folder = _write_set(os.path.join(OUT, "pbr_sets", "steel_scuffed_2K_30cm"),
                        ["steel_albedo.png", "steel_glossiness.png", "steel_normal_dx.png", "steel_height.png",
                         "steel_ao.png"])
    done = pbrset.assign(mat, ly, folder)
    assert ly.roughness.invert and ly.roughness.source == "PBRSET"
    assert ly.normal_dx and ly.ao_image is not None
    assert ly.color.scale == pytest.approx(0.3)
    assert ly.detail.source == "CONTENT_HEIGHT"  # CNT-7
    assert any("gloss" in d for d in done)
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    assert detail.resolve(mat, ly)[0] == "CONTENT_HEIGHT"


# ------------------------------------------------------------------ CNT-6
def test_content_library_categories_and_items(empty_scene):
    root = os.path.join(OUT, "content_lib")
    _write_set(os.path.join(root, "Rust", "Rust004_1K-PNG"), ["Rust004_1K-PNG_Color.png", "Rust004_1K-PNG_Roughness.png"])
    _write_set(os.path.join(root, "mud_cracked_2k"), ["mud_cracked_diff_2k.png", "mud_cracked_disp_2k.png"])
    _write_set(os.path.join(root, "Metal", "brushed_alu"), ["brushed_alu_basecolor.png"])
    _write_set(os.path.join(root, "notes"), ["readme_screenshot.png"])  # not a set: no colour map
    lib = pbrset.library(root)
    cats = {e["name"]: e["category"] for e in lib}
    assert cats == {"Rust004_1K-PNG": "RUST", "mud_cracked_2k": "DIRT", "brushed_alu": "WEAR"}
    rust_items = [i[1] for i in pbrset.library_enum_items(root, "RUST")]
    assert rust_items == ["Rust004 1K-PNG"]
    assert len(pbrset.library_enum_items(root, "ALL")) == 3

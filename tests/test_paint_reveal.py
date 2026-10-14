"""Paint (PNT-7, PNT-8) and Reveal (REV-1..REV-6): Tint Below with a hue shift, Breakup, the
Damage brush and its alpha library, Depth measured on a bake of the stack's height, edge
darkening, Scratches, True depth, and no stepping in Depth (float masks)."""

import os

import bmesh
import bpy
import numpy as np
import pytest

from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from realworn.builders import gen_alphas
from realworn.core import bake, compiler, grunge, images, kinds as K, layers, naming, nodeutil, reveal, setup
from test_core_setup import uv_cube

RES = 64


def _plane(sc, name="Plane", cuts=1):
    """A 1 m plane in XY whose RW_Paint is x + 0.5, y + 0.5 (mask column i sits at x = i / RES - 0.5)."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=0.5)
    ob = ms._link(sc, name, bm, (0, 0, 0), ms.principled(name + "Mat", (0.8, 0.8, 0.8), roughness=0.5))
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        co = me.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (co.x + 0.5, co.y + 0.5)
    setup.setup_object(ob, uv_method="EXISTING")
    return ob, ob.material_slots[0].material


def _write(img, values):
    res = img.size[0]
    px = np.ones((res, res, 4), np.float32)
    px[..., :3] = values[..., None]
    img.pixels.foreach_set(px.ravel())
    img.update()


def _bake(sc, ob, mat, socket, res=RES):
    img = bake.new_image("rw_test_bake", res, "Non-Color", float_buffer=True)
    bake.bake_socket(sc, ob, mat, bake.stack_output(socket), img)
    return images.pixels(img)


# ------------------------------------------------------------------ Paint
def test_paint_defaults_and_content_swap_keeps_paint(empty_scene):
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "PAINT")
    assert ly.content == "TINT_BELOW" and ly.hue == pytest.approx(0.5)  # PNT-7: plaster turned to paint
    assert ly.breakup_amount == 0.0 and ly.breakup_grunge is not None  # MSK-2: off, ready to raise
    img = images.ensure_mask(ob, mat, ly)
    images.fill(img, 1.0)
    for content in ("COLOR", "TEXTURE", "TINT_BELOW"):  # PNT-8
        ly.content = content
        assert ly.mask_image == img and images.pixels(img)[..., 0].min() == 1.0
    g = mat.realworn.stack
    assert g.nodes[naming.layer_node(ly.id, "hsv")].inputs["Hue"].default_value == pytest.approx(1.0)


# ------------------------------------------------------------------ Reveal
def test_reveal_depth_is_under_height_minus_depth(empty_scene):
    """REV-2: where the mask is white the height is the under-material's height minus Depth; the
    rest keeps the height below. Measured on a bake of the stack's Displacement output (metres)."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "REVEAL")
    ly.mask_res = RES
    ly.sharpness = 1.0
    img = images.ensure_mask(ob, mat, ly)
    half = np.zeros((RES, RES), np.float32)
    half[:, : RES // 2] = 1.0  # the left half is damaged
    _write(img, half)
    assert mat.realworn.layers[0].kind == "REVEAL"
    h = _bake(sc, ob, mat, "Displacement")[..., 0]
    left, right = float(h[8:-8, 4:RES // 2 - 4].mean()), float(h[8:-8, RES // 2 + 4:-4].mean())
    print("\n[depth] damaged {:.5f} m, intact {:.5f} m".format(left, right))
    assert left == pytest.approx(-0.002, abs=2e-5) and right == pytest.approx(0.0, abs=2e-5)
    c = compiler.COMPILES["count"]
    ly.depth_mm = 5.0  # a value edit
    assert compiler.COMPILES["count"] == c
    h = _bake(sc, ob, mat, "Displacement")[..., 0]
    assert float(h[8:-8, 4:RES // 2 - 4].mean()) == pytest.approx(-0.005, abs=2e-5)
    out = nodeutil.output_node(mat.node_tree)
    assert out.inputs["Displacement"].links[0].from_node.name == naming.node_name("disp")
    assert mat.displacement_method == "BUMP"  # SET-4; True depth is off by default (REV-5)


def test_edge_darkening_band(empty_scene):
    """REV-6: a thin darker band where the hole meets the surface (on by default, low)."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "REVEAL")
    assert 0 < ly.edge_dark <= 0.3 + 1e-6
    ly.mask_res, ly.sharpness = RES, 0.0  # a soft ramp makes the band wide enough to sample
    ly.color = (0.5, 0.5, 0.5)
    ramp = np.tile(np.linspace(0.0, 1.0, RES, dtype=np.float32)[None, :], (RES, 1))
    _write(images.ensure_mask(ob, mat, ly), ramp)
    on = _bake(sc, ob, mat, "Base Color")[RES // 2, :, 0]
    ly.edge_dark = 0.0
    off = _bake(sc, ob, mat, "Base Color")[RES // 2, :, 0]
    darkest = int(np.argmin(on - off))
    print("\n[edge] darkening at the band centre {:.3f}, at the ends {:.3f} / {:.3f}".format(
        float((on - off)[darkest]), float((on - off)[2]), float((on - off)[-3])))
    assert (on - off)[darkest] < -0.05
    assert abs((on - off)[2]) < 0.01 and abs((on - off)[-3]) < 0.01  # only at the edge
    assert RES * 0.25 < darkest < RES * 0.75


def test_float_mask_has_no_steps(empty_scene):
    """MSK-3: Reveal masks are float, so a slow ramp of Depth has no 8-bit terraces."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "REVEAL")
    ly.mask_res, ly.sharpness, ly.threshold, ly.depth_mm = 512, 0.0, 0.5, 2.0
    img = images.ensure_mask(ob, mat, ly)
    assert img.is_float
    x = np.linspace(0.40, 0.42, 512, dtype=np.float32)  # 5 grey levels in 8 bits across the plane
    _write(img, np.tile(x[None, :], (512, 1)))
    h = _bake(sc, ob, mat, "Displacement", res=512)[256, 40:-40, 0]
    flat = float((np.abs(np.diff(h)) < 1e-9).mean())
    print("\n[steps] flat neighbouring texels along the ramp: {:.0%}".format(flat))
    assert flat < 0.1


# ------------------------------------------------------------------ brushes, presets
def test_damage_alpha_library():
    lib = grunge.library("alphas")
    names = {os.path.splitext(k)[0] for k, _, _ in lib}
    assert {"chips", "chips_small", "cracks", "scratches", "gouges", "impact"} <= names
    for name, a in gen_alphas.make_all(128).items():
        assert a.max() > 0.5, name
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        assert edge.max() < 0.01, name  # black at the border: no square stamp


def test_picking_an_alpha_changes_the_brush_instantly(empty_scene):
    """REV-3 / PNT-5: switching the damage alpha in the library changes the brush instantly."""
    sc = empty_scene
    sc.realworn.damage_alpha = "cracks.png"
    b = bpy.data.brushes["RW Damage"]
    assert os.path.basename(b.mask_texture.image.filepath).startswith("cracks")
    sc.realworn.damage_alpha = "gouges.png"
    assert os.path.basename(b.mask_texture.image.filepath).startswith("gouges")
    assert b.mask_texture_slot.mask_map_mode == "VIEW_PLANE" and b.mask_texture_slot.use_rake


def test_scratches_preset(empty_scene):
    """REV-4: Scratches is a Reveal with a scratch alpha and about 0.3 mm of depth."""
    ob = uv_cube(empty_scene, material=GENERATED["principled_basic"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    assert bpy.ops.realworn.layer_add(material=mat.name, kind="REVEAL", preset="SCRATCHES") == {"FINISHED"}
    ly = mat.realworn.layers[mat.realworn.active_layer_index]
    assert ly.name == "Scratches" and ly.depth_mm == pytest.approx(0.3)
    b = bpy.data.brushes["RW Damage"]
    assert os.path.basename(b.mask_texture.image.filepath).startswith("scratches")


def test_true_depth(empty_scene):
    """REV-5: True depth switches the material to Displacement and Bump and adds an adaptive Simple
    subdivision; off restores the material and removes the modifier."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "REVEAL")
    assert mat.displacement_method == "BUMP" and not reveal.subdiv_modifier(ob)
    ly.true_depth = True
    mod = reveal.subdiv_modifier(ob)
    assert mat.displacement_method == "BOTH" and mod is not None
    assert mod.subdivision_type == "SIMPLE" and getattr(mod, "use_adaptive_subdivision", True)
    assert "Coarse mesh" in reveal.density_warning(ob)  # a 1 m quad
    ly.visible = False  # a hidden layer does not keep it
    assert mat.displacement_method == "BUMP" and reveal.subdiv_modifier(ob) is None
    ly.visible = True
    assert mat.displacement_method == "BOTH"
    ly.true_depth = False
    assert mat.displacement_method == "BUMP" and reveal.subdiv_modifier(ob) is None
    dense, _ = _plane(sc, "Dense", cuts=100)
    assert reveal.density_warning(dense) == ""


def test_reveal_defaults():
    d = K.defaults("REVEAL")
    assert d["content"] == "COLOR" and d["color"] == K.PLASTER_GREY  # REV-1
    assert d["depth_mm"] == 2.0 and d["breakup_amount"] == 0.0

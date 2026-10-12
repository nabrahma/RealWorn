"""P3 acceptance: grunge library (GRN-1), Stamp / Projected / Stencil brush setup (GRN-2..4), Grunge
Fill ingredient (GRN-5) that painting can erase and Reset brings back, contrast and invert
(GRN-7), Tinted Grunge content (LAY-2). Real stamped strokes are checked by hand."""

import os

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.builders import gen_grunges
from realworn.core import grunge, images, layers, naming, setup


def test_library_has_twenty_tileable_grunges():
    lib = grunge.library()
    assert len(lib) >= 20
    arrays = gen_grunges.make_all(128)
    assert set(os.path.splitext(n)[0] for n, _ in lib) >= set(arrays)
    for name, a in arrays.items():
        assert a.min() >= 0 and a.max() <= 1 and a.max() > 0.3, name
        # seamless: stepping across the wrap is no bigger than the largest step between two
        # neighbouring columns (rows) inside the image
        inner_x = np.abs(np.diff(a, axis=1)).mean(axis=0).max()
        wrap_x = np.abs(a[:, 0] - a[:, -1]).mean()
        inner_y = np.abs(np.diff(a, axis=0)).mean(axis=1).max()
        wrap_y = np.abs(a[0, :] - a[-1, :]).mean()
        assert wrap_x <= inner_x + 0.02, (name, wrap_x, inner_x)
        assert wrap_y <= inner_y + 0.02, (name, wrap_y, inner_y)


def test_load_is_non_color_and_reused(empty_scene):
    a = grunge.load("spots_medium")
    b = grunge.load("spots_medium.png")
    assert a is b and a.colorspace_settings.name == "Non-Color" and tuple(a.size) == (512, 512)
    with pytest.raises(KeyError):
        grunge.load("no_such_grunge")


@pytest.mark.parametrize("mode,mapping,brush", [("STAMP", "RANDOM", "RW Grunge"), ("PROJECTED", "VIEW_PLANE", "RW Grunge"),
                                                ("STENCIL", "STENCIL", "RW Cracks")])
def test_brush_modes(empty_scene, mode, mapping, brush):
    b = grunge.use(mode, "spots_medium", contrast=1.6, invert=True)
    assert b.name == brush and b.mask_texture.image.name.startswith("spots_medium")
    assert b.mask_texture_slot.mask_map_mode == mapping
    assert b.mask_texture_slot.use_random == (mapping == "RANDOM")
    assert b.mask_texture.contrast == pytest.approx(1.6) and b.mask_texture.use_color_ramp
    assert tuple(b.mask_texture.color_ramp.elements[0].color)[:3] == (1.0, 1.0, 1.0)  # inverted
    assert b.spacing >= 25 or mode == "STENCIL"  # spike v2 (c): wide spacing keeps stamps patchy
    assert b.asset_data is not None
    assert grunge.chosen_brush() == b.name  # activated by Paint Enter (activation needs paint mode)


def _sheet(sc):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=16, y_segments=16, size=1.0)
    ob = ms._link(sc, "Sheet", bm, (0, 0, 0), ms.principled("SheetMat", (0.5, 0.5, 0.5)))
    ms.camera_light(sc, cam_loc=(0, 0, 4), target=(0, 0, 0))
    ru.look_at(sc.camera, (0, 0, 4), (0, 0, 0), ortho_scale=1.9)
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def _mask_render(sc, mat, path):
    mat.realworn.mask_view = True
    ru.setup(sc, engine="BLENDER_EEVEE", samples=1, res=(96, 96))
    sc.view_settings.view_transform = "Standard"
    out = ru.render(sc, path).mean(axis=2)
    mat.realworn.mask_view = False
    return out


def test_fill_then_erase_then_reset(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = _sheet(sc)
    ly = layers.add_layer(mat, "DIRT")
    ing = grunge.use("FILL", "spots_medium", ob, mat, ly, amount=1.0, scale=0.6)
    assert ing.kind == "GRUNGE" and ing.amount == 1.0
    full = _mask_render(sc, mat, os.path.join(out_dir, "p3_fill.png"))
    cov = float((full > 0.5).mean())
    print("\n[fill] coverage {:.3f}, std {:.3f}".format(cov, full.std()))
    assert 0.15 < cov < 0.85 and full.std() > 0.25  # patchy, not a flat fill
    img = images.ensure_mask(ob, mat, ly)
    w = img.size[0]
    px = np.zeros((w, w, 4), np.float32)
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", uv)
    px[..., 3] = 1.0  # Erase everywhere: painted black at full alpha
    img.pixels.foreach_set(px.ravel())
    img.update()
    erased = _mask_render(sc, mat, os.path.join(out_dir, "p3_erased.png"))
    assert float(erased.max()) < 0.05
    px[..., 3] = 0.0  # Reset (Erase Alpha): back to the procedural fill
    img.pixels.foreach_set(px.ravel())
    img.update()
    reset = _mask_render(sc, mat, os.path.join(out_dir, "p3_reset.png"))
    assert np.abs(reset - full).mean() < 0.01


def test_tinted_grunge_varies_colour(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = _sheet(sc)
    ly = layers.add_layer(mat, "RUST")
    assert ly.color.source == "TINTED_GRUNGE" and ly.color.grunge is not None
    assert ly.color.grunge.name.startswith("rust_spots")
    ly.height.enabled = False
    images.fill(images.ensure_mask(ob, mat, ly), 1.0)
    ru.setup(sc, engine="BLENDER_EEVEE", samples=1, res=(96, 96))
    sc.view_settings.view_transform = "Standard"
    tinted = ru.render(sc, os.path.join(out_dir, "p3_tinted.png"))
    ly.color.source = "FLAT"
    flat = ru.render(sc, os.path.join(out_dir, "p3_flat.png"))
    s_t, s_f = float(tinted[20:76, 20:76].mean(axis=2).std()), float(flat[20:76, 20:76].mean(axis=2).std())
    print("\n[tinted] brightness std tinted {:.4f}, flat {:.4f}".format(s_t, s_f))
    assert s_t > s_f * 5 and s_t > 0.01  # relative: the rust colour itself is dark
    assert float(tinted[..., 0].mean()) > float(tinted[..., 2].mean())  # still rust-coloured


def test_ingredient_operators(empty_scene):
    ob, mat = _sheet(empty_scene)
    layers.add_layer(mat, "DIRT")
    ly = layers.add_layer(mat, "RUST")
    assert bpy.ops.realworn.ingredient_add(object=ob.name, material=mat.name, kind="REFERENCE") == {"FINISHED"}
    assert ly.ingredients[0].ref_layer_id == mat.realworn.layers[0].id  # the layer below
    assert bpy.ops.realworn.ingredient_add(object=ob.name, material=mat.name, kind="GRUNGE") == {"FINISHED"}
    assert ly.ingredients[1].image is not None and ly.ingredients[1].amount == 0.0
    assert bpy.ops.realworn.grunge_select(object=ob.name, material=mat.name, grunge="cracks",
                                          mode="FILL") == {"FINISHED"}
    assert ly.ingredients[1].image.name.startswith("cracks") and ly.ingredients[1].amount == 1.0
    assert bpy.ops.realworn.ingredient_remove(object=ob.name, material=mat.name, index=0) == {"FINISHED"}
    assert len(ly.ingredients) == 1

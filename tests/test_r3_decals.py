"""R3: Decals (DEC-1..DEC-8): the transparent RGBA image, the Stencil brush and decal library with
categories, Erase Alpha, Normal and Darken blends, Breakup on decals, the px-per-metre readout."""

import os
import types

import bmesh
import bpy
import numpy as np
import pytest

from fixtures import make_scenes as ms
from realworn.builders import gen_decals
from realworn.core import bake, grunge, images, kinds as K, layers, paint, setup

RES = 64


def _plane(sc, size=0.5):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    ob = ms._link(sc, "Plane", bm, (0, 0, 0), ms.principled("PlaneMat", (0.8, 0.8, 0.8)))
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        co = me.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (co.x / (2 * size) + 0.5, co.y / (2 * size) + 0.5)
    setup.setup_object(ob, uv_method="EXISTING")
    return ob, ob.material_slots[0].material


def _bake(sc, ob, mat, socket, res=RES):
    img = bake.new_image("rw_test_bake", res, "Non-Color", float_buffer=True)
    bake.bake_socket(sc, ob, mat, bake.stack_output(socket), img)
    return images.pixels(img)


def _checker_base(mat, tmp_path):
    """A texture set whose colour is a checker, loaded onto the Base (a visible surface texture)."""
    folder = tmp_path / "checker_1m"
    folder.mkdir()
    n = 64
    yy, xx = np.mgrid[0:n, 0:n]
    c = (((yy // 8) + (xx // 8)) % 2).astype(np.float32) * 0.6 + 0.2
    img = bpy.data.images.new("checker", n, n)
    px = np.ones((n, n, 4), np.float32)
    px[..., :3] = c[..., None]
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = str(folder / "checker_diff.png")
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    layers.load_texture(mat, str(folder))


def test_library_categories():
    """DEC-7: categories from subfolders; RealWorn ships drips, dirt, graffiti, stickers, mold and cracks."""
    lib = grunge.library("decals")
    cats = {c for _, _, c in lib}
    assert {"Drips", "Dirt", "Graffiti", "Stickers", "Mold", "Cracks"} <= cats
    items = grunge.library_enum_items("decals")
    assert any(item[1].startswith("Drips: ") for item in items)
    for key, rgba in gen_decals.make_all(128).items():
        a = rgba[..., 3]
        assert a.max() > 0.5 and a.min() == 0.0, key  # transparent background


def test_picking_a_decal_sets_the_stencil(empty_scene):
    """DEC-3: the decal becomes the Stencil brush's texture, Image Aspect applied, Override Overlay on."""
    sc = empty_scene
    sc.realworn.decal_image = "Graffiti/graffiti_01.png"
    b = bpy.data.brushes["RW Stencil"]
    assert os.path.basename(b.texture.image.filepath) == "graffiti_01.png"
    assert b.texture_slot.map_mode == "STENCIL" and b.use_primary_overlay_override
    w, h = b.texture.image.size
    assert b.stencil_dimension[0] / b.stencil_dimension[1] == pytest.approx(w / h, rel=1e-3)
    assert b.texture.image.colorspace_settings.name == "sRGB"


def test_erase_alpha(empty_scene):
    """DEC-5: erasing on a Decals layer removes alpha; Ctrl + drag runs the same Erase Alpha stroke."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "DECALS")
    bpy.context.view_layer.objects.active = ob
    paint.enter(ob, mat, ly)
    brush = sc.tool_settings.image_paint.brush
    assert brush.name == "RW Stencil"
    paint.set_mode(ob, "ERASE")
    assert brush.blend == "ERASE_ALPHA"
    paint.set_mode(ob, "PAINT")
    assert brush.blend == "MIX"
    paint.exit(ob)
    assert hasattr(bpy.types, "REALWORN_OT_decal_erase_stroke")
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:  # background sessions may have no add-on keyconfig
        km = kc.keymaps.get("Image Paint")
        assert any(k.idname == "realworn.decal_erase_stroke" and k.ctrl and k.type == "LEFTMOUSE"
                   for k in km.keymap_items)


def test_darken_keeps_the_surface_texture(empty_scene, tmp_path):
    """DEC-4: Normal covers the surface with the decal's colour; Darken multiplies it, so the
    surface texture below stays visible."""
    sc = empty_scene
    ob, mat = _plane(sc)
    _checker_base(mat, tmp_path)
    ly = layers.add_layer(mat, "DECALS")
    ly.decal_res = "2048"
    img = images.ensure_mask(ob, mat, ly)
    px = np.zeros((2048, 2048, 4), np.float32)
    px[..., :3], px[..., 3] = 0.3, 1.0  # one opaque grey decal over everything
    img.pixels.foreach_set(px.ravel())
    img.update()
    covered = _bake(sc, ob, mat, "Base Color")[..., 0]
    ly.visible = False
    plain = _bake(sc, ob, mat, "Base Color")[..., 0]
    ly.visible = True
    ly.decal_blend = "DARKEN"
    dark = _bake(sc, ob, mat, "Base Color")[..., 0]
    s_plain, s_norm, s_dark = float(plain.std()), float(covered.std()), float(dark.std())
    print("\n[decal] surface texture std: none {:.3f}, Normal {:.3f}, Darken {:.3f}".format(s_plain, s_norm, s_dark))
    assert s_norm < 0.02 * s_plain + 1e-4        # Normal: the decal covers it
    rel_plain, rel_dark = s_plain / float(plain.mean()), s_dark / float(dark.mean())
    print("[decal] relative variation (std / mean): none {:.3f}, Darken {:.3f}".format(rel_plain, rel_dark))
    assert rel_dark == pytest.approx(rel_plain, rel=0.05)  # Darken multiplies: the checker still shows
    assert float(dark.mean()) < float(plain.mean())


def test_breakup_fades_decals(empty_scene):
    """DEC-6: Breakup works on decals too (a grunge fades or chips old graffiti)."""
    sc = empty_scene
    ob, mat = _plane(sc)
    ly = layers.add_layer(mat, "DECALS")
    ly.decal_res = "2048"
    images.fill(images.ensure_mask(ob, mat, ly), 1.0)
    full = float(_bake(sc, ob, mat, "Coverage")[..., 0].mean())
    ly.breakup_grunge = grunge.load("grunges", "chips_large.png")
    ly.breakup_scale, ly.breakup_amount, ly.sharpness = 0.3, 1.0, 0.8
    chipped = float(_bake(sc, ob, mat, "Coverage")[..., 0].mean())
    print("\n[decal] coverage {:.3f} -> {:.3f} with Breakup".format(full, chipped))
    assert full > 0.99 and 0.3 < chipped < 0.97


def test_decal_resolution_readout(empty_scene):
    """DEC-2: 4096 px default (2048, 8192 options); px per metre shown, warning below 400."""
    sc = empty_scene
    wall, mat = _plane(sc, size=1.5)  # a 3 m wall
    ly = layers.add_layer(mat, "DECALS")
    assert ly.decal_res == "4096"
    assert images.decal_density(wall, ly) == pytest.approx(4096 / 3.0, rel=1e-3)
    facade = types.SimpleNamespace(dimensions=(12.0, 0.3, 9.0))
    assert images.decal_density(facade, ly) < images.DECAL_MIN_DENSITY  # 341 px per metre: warn
    ly.decal_res = "8192"
    assert images.decal_density(facade, ly) > images.DECAL_MIN_DENSITY


def test_presets_and_tips():
    assert K.defaults("DECALS", "GRIME")["decal_blend"] == "DARKEN"
    assert K.defaults("DECALS", "GRAFFITI")["decal_blend"] == "NORMAL"
    assert "ledges" in K.TIPS["DECALS"]  # DEC-8

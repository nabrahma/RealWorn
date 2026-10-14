"""Libraries and brushes:
the generated grunge library, loading, and RealWorn's three brushes with the reference's exact
settings, read back from the brush assets."""

import os

import bpy
import numpy as np
import pytest

from realworn.builders import gen_grunges
from realworn.core import grunge


def test_library_has_tileable_grunges():
    lib = grunge.library("grunges")
    assert len(lib) >= 20
    arrays = gen_grunges.make_all(128)
    assert set(os.path.splitext(k)[0] for k, _, _ in lib) >= set(arrays)
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
    a = grunge.load("grunges", "spots_medium")
    b = grunge.load("grunges", "spots_medium.png")
    assert a is b and a.colorspace_settings.name == "Non-Color"
    assert tuple(a.size) == (gen_grunges.SIZE, gen_grunges.SIZE)
    with pytest.raises(KeyError):
        grunge.load("grunges", "no_such_grunge")
    assert grunge.suggested_scale("chips_large") == pytest.approx(0.4)


def test_soft_brush(empty_scene):
    b = grunge.ensure_brush("RW Soft")
    assert b.curve_distance_falloff_preset == "SMOOTH" and b.asset_data is not None and b.get("rw_brush")
    assert b.mask_texture is None and b.texture is None


def test_damage_brush_settings(empty_scene):
    """REV-3: Texture Mask from the damage alpha, Mask Mapping View Plane, Rake on, Falloff Constant."""
    path = grunge.path_of("grunges", "chips_large.png")  # any image works as an alpha
    b = grunge.set_damage_alpha(path)
    assert b.name == "RW Damage" and b.asset_data is not None
    assert b.mask_texture is not None and b.mask_texture.image is not None
    assert os.path.normcase(bpy.path.abspath(b.mask_texture.image.filepath)) == os.path.normcase(path)
    slot = b.mask_texture_slot
    assert slot.mask_map_mode == "VIEW_PLANE" and slot.use_rake and not slot.use_random
    assert b.curve_distance_falloff_preset == "CONSTANT"


def test_stencil_brush_settings(empty_scene):
    """DEC-3: Texture from the decal, Mapping Stencil, Image Aspect applied, Override Overlay on."""
    img = bpy.data.images.new("wide_decal", 400, 100, alpha=True)
    img.filepath_raw = os.path.join(bpy.app.tempdir, "wide_decal.png")
    img.file_format = "PNG"
    img.save()
    b = grunge.set_stencil_decal(img.filepath_raw)
    assert b.name == "RW Stencil" and b.texture is not None and b.texture.image is not None
    assert b.texture_slot.map_mode == "STENCIL"
    assert b.use_primary_overlay and b.use_primary_overlay_override
    w, h = b.stencil_dimension
    assert w / h == pytest.approx(4.0, rel=1e-3)  # Image Aspect: the stencil keeps the decal's proportions


def test_brushes_are_never_the_users(empty_scene):
    mine = bpy.data.brushes.new("MyBrush", mode="TEXTURE_PAINT")
    mine.strength = 0.33
    for name in grunge.BRUSHES:
        grunge.ensure_brush(name)
    grunge.set_damage_alpha(grunge.path_of("grunges", "cracks.png"))
    assert mine.strength == pytest.approx(0.33) and mine.mask_texture is None
    assert {b.name for b in bpy.data.brushes if b.get("rw_brush")} == set(grunge.BRUSHES)

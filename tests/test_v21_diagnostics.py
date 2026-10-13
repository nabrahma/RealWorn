"""PRD v2.1 DIA-1..DIA-4 and acceptance test T9 (texture limit warning and one-click fix)."""

import bpy
import pytest

import sharp_util as su
from realworn.core import diagnostics, images, layers


@pytest.fixture
def system():
    s = bpy.context.preferences.system
    saved = (s.gl_texture_limit, s.anisotropic_filter)
    yield s
    s.gl_texture_limit, s.anisotropic_filter = saved


@pytest.fixture
def painted(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "DIRT")
    ly.mask_res = 2048
    images.ensure_mask(ob, mat, ly)
    return empty_scene, ob, mat, ly


def _ids(found):
    return [f["id"] for f in found]


def test_t9_texture_limit_warning_and_fix(painted, system):
    sc, ob, mat, ly = painted
    system.gl_texture_limit, system.anisotropic_filter = "CLAMP_OFF", "FILTER_16"
    assert diagnostics.check(system, sc, [mat]) == []
    system.gl_texture_limit = "CLAMP_1024"
    found = diagnostics.check(system, sc, [mat])
    assert _ids(found) == ["DIA-1"] and "1024" in found[0]["text"] and "2048" in found[0]["text"]
    assert bpy.ops.realworn.fix_texture_limit() == {"FINISHED"}
    assert system.gl_texture_limit == "CLAMP_OFF"
    assert diagnostics.check(system, sc, [mat]) == []


def test_limit_above_largest_texture_is_fine(painted, system):
    sc, ob, mat, ly = painted
    system.gl_texture_limit, system.anisotropic_filter = "CLAMP_4096", "FILTER_8"
    assert diagnostics.check(system, sc, [mat]) == []


def test_simplify_texture_limits_viewport_and_render_separately(painted, system):
    sc, ob, mat, ly = painted
    system.gl_texture_limit, system.anisotropic_filter = "CLAMP_OFF", "FILTER_16"
    sc.render.use_simplify = True
    sc.cycles.texture_limit = "512"
    found = diagnostics.check(system, sc, [mat])
    assert _ids(found) == ["DIA-2"] and "viewport" in found[0]["text"]
    sc.cycles.texture_limit_render = "1024"
    assert [f["text"].split()[3] for f in diagnostics.check(system, sc, [mat])] == ["viewport", "render"]
    sc.cycles.texture_resolution_render = 0.5
    assert len(diagnostics.check(system, sc, [mat])) == 3
    assert bpy.ops.realworn.fix_simplify_textures() == {"FINISHED"}
    assert diagnostics.check(system, sc, [mat]) == []
    sc.render.use_simplify = False


def test_anisotropic_tip(painted, system):
    sc, ob, mat, ly = painted
    system.gl_texture_limit, system.anisotropic_filter = "CLAMP_OFF", "FILTER_2"
    found = diagnostics.check(system, sc, [mat])
    assert _ids(found) == ["DIA-3"] and found[0]["level"] == "INFO"
    bpy.ops.realworn.fix_anisotropic()
    assert system.anisotropic_filter == "FILTER_16"


def test_texel_density_readout(painted):
    sc, ob, mat, ly = painted
    k = diagnostics.uv_units_per_metre(ob)
    assert 0.1 < k < 1.0  # a 1 m cube's six faces share the 0..1 UV square
    px = diagnostics.mask_px_per_cm(ob, ly)
    assert px == pytest.approx(2048 * k / 100.0)
    assert diagnostics.readout(ob, ly)[0][0] == "Mask"
    assert diagnostics.grunge_px_per_cm(ly.mask_image, 0.5) == pytest.approx(2048 / 50.0)

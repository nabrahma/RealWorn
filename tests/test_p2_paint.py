"""P2 acceptance: mask images and texel density (PNT-1/2), paint enter / exit state (PNT-4/9),
Paint / Erase / Reset (PNT-5/6), Fill / Clear (PNT-7), Mask View (PNT-8), vertex-colour fallback
(PNT-11), paint persistence in packed and PNG modes (suite 5, SAV-1/2), texel-to-surface
(painting level 2), resize keeps paint."""

import os
import shutil

import bmesh
import bpy
import numpy as np
import pytest
from bpy_extras.object_utils import world_to_camera_view

import render_util as ru
from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from realworn.core import compiler, images, injector, layers, naming, nodeutil, paint, setup
from test_p1_setup import uv_cube


@pytest.fixture
def painted(empty_scene):
    ob = uv_cube(empty_scene, "Prop", size=1.0, material=GENERATED["image_based"]())
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "DIRT")
    return empty_scene, ob, mat, ly


def _q(px):
    return np.round(px * 255.0)  # byte images: compare at 8-bit precision


# ------------------------------------------------------------------ images
@pytest.mark.parametrize("dim,res", [(1.0, 1024), (1.5, 2048), (4.0, 4096), (9.0, 4096), (0.2, 1024)])
def test_texel_density(empty_scene, dim, res):
    """v2.1 RES-1 clamps 1024..4096 (v2.0: 512..4096); density given explicitly here."""
    ob = uv_cube(empty_scene, size=dim)
    assert images.texel_resolution(ob, 1024) == res


def test_mask_image_format(painted):
    sc, ob, mat, ly = painted
    img = images.ensure_mask(ob, mat, ly)
    assert img.name == naming.mask_image_name(ob.name, ly.name)
    assert tuple(img.size) == (2048, 2048)  # v2.1 RES-1: 2048 px per metre (1 m cube)
    assert img.colorspace_settings.name == "Non-Color" and img.alpha_mode == "CHANNEL_PACKED"
    assert img.packed_file is not None and img[naming.IMG_MASK] == "{}/{}".format(ob.name, ly.id)
    assert float(images.pixels(img)[..., 3].max()) == 0.0  # transparent: nothing painted
    g = mat.realworn.stack
    tex = g.nodes[naming.layer_node(ly.id, "mask")]
    assert tex.inputs["Vector"].links[0].from_node.uv_map == naming.UV_PAINT  # PNT-3


# ---------------------------------------------------------- enter and exit
def test_enter_and_exit_restore_everything(painted):
    sc, ob, mat, ly = painted
    ts = sc.tool_settings
    ip, ups = ts.image_paint, ts.image_paint.unified_paint_settings
    other = bpy.data.images.new("SomethingElse", 8, 8)
    ip.mode, ip.canvas = "MATERIAL", other
    ups.color, ups.secondary_color = (0.2, 0.3, 0.4), (0.5, 0.6, 0.7)
    me = ob.data
    uv_before = me.uv_layers.active.name
    bpy.context.view_layer.objects.active = ob
    img = paint.enter(ob, mat, ly)
    assert ob.mode == "TEXTURE_PAINT"
    assert me.uv_layers.active.name == naming.UV_PAINT
    assert [u.name for u in me.uv_layers if u.active_render] == ["UVMap"]  # render UV untouched
    assert ip.mode == "IMAGE" and ip.canvas == img == ly.mask_image
    assert tuple(ups.color) == pytest.approx((1, 1, 1)) and tuple(ups.secondary_color) == pytest.approx((0, 0, 0))
    assert ip.brush is not None and ip.brush.name == "RW Soft"
    paint.set_mode(ob, "ERASE")
    assert tuple(ups.color) == pytest.approx((0, 0, 0)) and ip.brush.blend == "MIX"
    paint.set_mode(ob, "RESET")
    assert ip.brush.blend == "ERASE_ALPHA"
    assert paint.exit(ob)
    assert ob.mode == "OBJECT" and me.uv_layers.active.name == uv_before
    assert ip.mode == "MATERIAL" and ip.canvas == other
    assert tuple(ups.color) == pytest.approx((0.2, 0.3, 0.4))
    assert not paint.painting(ob)


def test_switching_layer_switches_canvas(painted):
    sc, ob, mat, ly = painted
    first = ly.id
    second = layers.add_layer(mat, "WEAR").id
    bpy.context.view_layer.objects.active = ob
    paint.enter(ob, mat, layers.compiler.layer_by_id(mat, first))
    mat.realworn.active_layer_index = layers.index_of(mat, second)
    assert sc.tool_settings.image_paint.canvas == compiler.layer_by_id(mat, second).mask_image
    paint.exit(ob)


def test_fill_clear_and_resize_keep_paint(painted):
    sc, ob, mat, ly = painted
    img = images.ensure_mask(ob, mat, ly)
    images.fill(img, 1.0)
    assert float(images.pixels(img)[..., 3].min()) == 1.0
    images.fill(img, 0.0)
    assert float(images.pixels(img)[..., 3].max()) == 0.0
    w = img.size[0]
    px = np.zeros((w, w, 4), np.float32)
    px[: w // 2] = 1.0
    img.pixels.foreach_set(px.ravel())
    images.resize(img, w // 2)
    a = images.pixels(img)[..., 3]
    assert tuple(img.size) == (w // 2, w // 2)
    assert a.mean() == pytest.approx(0.5, abs=0.02)  # paint kept, resampled


# ---------------------------------------------------------------- mask view
def test_mask_view_follows_active_layer_and_is_never_saved(painted, out_dir):
    sc, ob, mat, ly = painted
    images.fill(images.ensure_mask(ob, mat, ly), 1.0)
    second = layers.add_layer(mat, "WEAR")
    images.ensure_mask(ob, mat, second)
    mat.realworn.mask_view = True
    out = nodeutil.output_node(mat.node_tree)
    assert out.inputs["Surface"].links[0].from_node.name == "RW::maskview"
    go = mat.realworn.stack.nodes["RW::out"]
    src = go.inputs["Mask View"].links[0].from_node.name
    assert second.id in src or "stack" not in src
    mat.realworn.active_layer_index = 0  # recompiles: fetch the output node again
    go = mat.realworn.stack.nodes["RW::out"]
    assert ly.id in go.inputs["Mask View"].links[0].from_node.name
    path = os.path.join(out_dir, "maskview.blend")
    mat_name = mat.name
    bpy.ops.wm.save_as_mainfile(filepath=path)
    assert mat.realworn.mask_view and out.inputs["Surface"].links[0].from_node.name == "RW::maskview"
    bpy.ops.wm.open_mainfile(filepath=path)
    m2 = bpy.data.materials[mat_name]
    assert m2.realworn.mask_view is False
    out2 = nodeutil.output_node(m2.node_tree)
    assert out2.inputs["Surface"].links[0].from_node.bl_idname != "ShaderNodeEmission"


# --------------------------------------------------------------- persistence
def _paint_pattern(img, seed=1):
    w, h = img.size
    rng = np.random.default_rng(seed)
    px = np.zeros((h, w, 4), np.float32)
    px[..., 0:3] = rng.random((h, w, 1)).round(3)
    px[..., 3] = (rng.random((h, w)) > 0.5)
    img.pixels.foreach_set(px.ravel())
    return images.pixels(img)  # what Blender stored (8-bit), not what numpy asked for


@pytest.mark.parametrize("mode", ["PACKED", "PNG"])
def test_paint_persists_through_save_and_reopen(painted, out_dir, mode):
    sc, ob, mat, ly = painted
    folder = os.path.join(out_dir, "persist_" + mode.lower())
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    images.FORCE_STORAGE = mode
    try:
        ly.mask_res = 256
        img = images.ensure_mask(ob, mat, ly)
        want = _q(_paint_pattern(img))
        name = img.name
        path = os.path.join(folder, "persist.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)  # the user never saves the image by hand
        # more paint after the first save: only the save handler can keep it (crash-style test)
        want2 = _q(_paint_pattern(bpy.data.images[name], seed=2))
        bpy.ops.wm.save_mainfile()
        bpy.ops.wm.open_mainfile(filepath=path)
        got = bpy.data.images[name]
        assert np.array_equal(_q(images.pixels(got)), want2)
        assert not np.array_equal(want, want2)
        if mode == "PNG":
            png = os.path.join(folder, "textures", "realworn", "Prop", bpy.path.clean_name(name) + ".png")
            assert os.path.exists(png), os.listdir(folder)
            assert got.packed_file is None
            assert got.filepath.replace("\\", "/").startswith("//textures/realworn/")
        else:
            assert got.packed_file is not None
    finally:
        images.FORCE_STORAGE = None


# ----------------------------------------------------------- texel to surface
def test_texel_to_surface(empty_scene, out_dir):
    """Level 2: one painted texel block shows up exactly where its surface point projects."""
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
    ob = ms._link(sc, "Sheet", bm, (0, 0, 0), ms.principled("SheetMat"))
    ms.camera_light(sc, cam_loc=(0, 0, 4), target=(0, 0, 0))
    ru.look_at(sc.camera, (0, 0, 4), (0, 0, 0), ortho_scale=2.2)
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "CUSTOM")
    ly.mask_res = 256
    img = images.ensure_mask(ob, mat, ly)
    me = ob.data
    target_face = me.polygons[37]
    uv = np.mean([me.uv_layers[naming.UV_PAINT].data[i].uv[:] for i in target_face.loop_indices], axis=0)
    px = np.zeros((256, 256, 4), np.float32)
    cx, cy = int(uv[0] * 256), int(uv[1] * 256)
    px[cy - 2:cy + 3, cx - 2:cx + 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    mat.realworn.mask_view = True
    ru.setup(sc, engine="BLENDER_EEVEE", samples=1, res=(128, 128))
    sc.view_settings.view_transform = "Standard"
    out = ru.render(sc, os.path.join(out_dir, "p2_texel.png")).mean(axis=2)
    world = ob.matrix_world @ target_face.center
    p = world_to_camera_view(sc, sc.camera, world)
    ex, ey = p.x * 128, p.y * 128  # row 0 = bottom
    ys, xs = np.nonzero(out > 0.9)  # the grey world border around the sheet is ~0.5
    print("\n[texel] expected ({:.1f}, {:.1f}), lit {} px, centroid ({:.1f}, {:.1f})".format(
        ex, ey, len(xs), xs.mean() if len(xs) else -1, ys.mean() if len(ys) else -1))
    assert len(xs) > 0
    assert abs(xs.mean() + 0.5 - ex) < 2.0 and abs(ys.mean() + 0.5 - ey) < 2.0
    assert len(xs) < 60  # nothing else lights up


# -------------------------------------------------------- vertex-colour mask
def test_vertex_colour_fallback(painted):
    sc, ob, mat, ly = painted
    ly.use_vertex_mask = True
    bpy.context.view_layer.objects.active = ob
    assert paint.enter(ob, mat, ly) is None
    assert ob.mode == "VERTEX_PAINT"
    name = naming.ATTR_VMASK + ly.id
    assert ob.data.color_attributes.active_color_name == name
    assert mat.realworn.stack.nodes[naming.layer_node(ly.id, "vmask")].layer_name == name
    paint.exit(ob)
    assert ob.mode == "OBJECT"
    setup.remove_object(ob)
    assert name not in ob.data.color_attributes


def test_operators(painted):
    sc, ob, mat, ly = painted
    bpy.context.view_layer.objects.active = ob
    assert bpy.ops.realworn.paint_enter(object=ob.name, material=mat.name, layer=ly.id) == {"FINISHED"}
    assert bpy.ops.realworn.paint_mode(mode="ERASE", object=ob.name) == {"FINISHED"}
    assert bpy.ops.realworn.paint_exit(object=ob.name) == {"FINISHED"}
    assert bpy.ops.realworn.mask_fill(object=ob.name, material=mat.name, layer=ly.id, value=1.0) == {"FINISHED"}
    assert float(images.pixels(ly.mask_image)[..., 3].mean()) == 1.0
    assert bpy.ops.realworn.mask_resize(object=ob.name, material=mat.name, layer=ly.id,
                                        resolution=512) == {"FINISHED"}
    assert tuple(ly.mask_image.size) == (512, 512)

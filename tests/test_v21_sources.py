"""PRD v2.1 Q2: more detail sources (Base AO, Content Height, Second Grunge), anti-tiling, grunge
size metadata, Refresh Base, and acceptance test T3 (Dirt follows the base material's grooves)."""

import json
import os

import bpy
import numpy as np
import pytest

import render_util as ru
import sharp_util as su
from perf_log import record
from realworn.core import compiler, detail, grunge, images, injector, layers, naming, nodeutil, setup
from test_p1_setup import state_of

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")


def _ortho_front(sc, centre, width, res=(960, 576)):
    cam = bpy.data.objects.new("Ortho", bpy.data.cameras.new("Ortho"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = width
    cam.location = (centre[0], centre[1] - 2.0, centre[2])
    cam.rotation_euler = (np.pi / 2, 0, 0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.color = (0, 0, 0)
    return cam


def _render_socket(sc, mat, sock, path):
    """Render `sock` (any colour / float socket of the material tree) as flat emission."""
    tree = mat.node_tree
    out = nodeutil.output_node(tree)
    old = nodeutil.link_source(out.inputs["Surface"])
    em = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(sock, em.inputs["Color"])
    tree.links.new(em.outputs[0], out.inputs["Surface"])
    try:
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        return np.flipud(ru.load(path)[..., 0])
    finally:
        tree.nodes.remove(em)
        if old is not None:
            tree.links.new(old, out.inputs["Surface"])


# ------------------------------------------------------------------ T3
def test_t3_dirt_pools_in_the_mortar(empty_scene, out_dir):
    """T3 / S3: a soft Dirt stroke across bricks and mortar of a Poly Haven brick wall, Height
    Compare on Base Height: at least 70% of the covered pixels are below the base height median."""
    sc = empty_scene
    base = su.corpus_material("red_brick")
    if base is None:
        pytest.skip("Poly Haven corpus not downloaded")
    ob, mat = su.wall(sc, width=1.0, height=0.6, material=base)
    assert mat.realworn.base_height_kind == "IMAGE"
    ly = layers.add_layer(mat, "DIRT")
    assert (ly.detail.mode, ly.detail.source) == ("HEIGHT", "BASE_HEIGHT")
    su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.5, 0.3), 0.22, 0.12))
    _ortho_front(sc, (0, 0, 0.3), 0.9)
    su.setup_render(sc)
    m = su.render_mask_view(sc, mat, 0, os.path.join(out_dir, "t3_mask.exr"))
    h = _render_socket(sc, mat, detail.base_height_socket(mat), os.path.join(out_dir, "t3_height.exr"))
    low = h < np.median(h)
    covered = m > 0.5
    share = float((covered & low).sum()) / max(int(covered.sum()), 1)
    ly.detail.strength = 0.0  # the same stroke without Edge Detail (v2.0 behaviour of the mask)
    m0 = su.render_mask_view(sc, mat, 0, os.path.join(out_dir, "t3_mask_off.exr"))
    c0 = m0 > 0.5
    share0 = float((c0 & low).sum()) / max(int(c0.sum()), 1)
    print("\n[T3] covered pixels below the base-height median: {:.0%} with Edge Detail ({:.1%} of frame); "
          "{:.0%} without".format(share, covered.mean(), share0))
    record("v2.1 T3 Dirt coverage in low base height (brick wall)", share * 100, "%", None,
           "S3 target >= 70%; same stroke without Edge Detail: {:.0f}%".format(share0 * 100))
    assert covered.mean() > 0.02
    assert share >= 0.70


# ------------------------------------------------------------------ Base AO
def _textured_base(folder, with_ao_node=False):
    """A base material whose colour image lives in `folder`; an AO map sits next to it."""
    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(3)
    for name, arr in (("tiles_diff.png", rng.random((64, 64))), ("tiles_ao.png", 0.3 + 0.6 * rng.random((64, 64)))):
        img = bpy.data.images.new(name, 64, 64)
        px = np.ones((64, 64, 4), np.float32)
        px[..., :3] = arr[..., None]
        img.pixels.foreach_set(px.ravel())
        img.filepath_raw = os.path.join(folder, name)
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
    mat = bpy.data.materials.new("Tiles")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(os.path.join(folder, "tiles_diff.png"))
    mp, tc = nt.nodes.new("ShaderNodeMapping"), nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    if with_ao_node:
        ao = nt.nodes.new("ShaderNodeTexImage")
        ao.image = bpy.data.images.load(os.path.join(folder, "tiles_ao.png"))
    return mat


@pytest.mark.parametrize("where", ["folder", "tree"])
def test_base_ao_detected_linked_and_removed_exactly(empty_scene, where):
    from test_p1_setup import uv_cube
    mat = _textured_base(os.path.join(OUT, "ao_" + where), with_ao_node=(where == "tree"))
    ob = uv_cube(empty_scene, material=mat)
    before = state_of(ob)
    setup.setup_object(ob)
    m = ob.material_slots[0].material
    st = m.realworn
    assert st.base_ao_kind == "IMAGE" and "ao" in st.base_ao_image
    assert detail.has_base_ao(m)
    src = detail.base_ao_socket(m)
    if where == "folder":  # a RealWorn node reusing the base colour's mapping
        assert nodeutil.is_owned(src.node)
        assert src.node.inputs["Vector"].links[0].from_node.bl_idname == "ShaderNodeMapping"
    ly = layers.add_layer(m, "DIRT")
    ly.detail.source = "BASE_AO"
    su.paint_layer(ob, m, ly, lambda r: np.ones((r, r)))
    g = st.stack
    assert g.nodes.get(naming.layer_node("stack", "ao")) is not None
    lo, hi = np.percentile(0.3 + 0.6 * np.random.default_rng(3).random((64, 64)), (2, 98))
    assert (st.base_ao_lo, st.base_ao_hi) == pytest.approx((lo, hi), abs=0.01)
    assert setup.remove_object(ob) == []
    assert state_of(ob) == before


def test_pick_ao_image(empty_scene):
    from test_p1_setup import uv_cube
    ob = uv_cube(empty_scene, material=_textured_base(os.path.join(OUT, "ao_pick")))
    setup.setup_object(ob)
    m = ob.material_slots[0].material
    assert detail.has_base_ao(m)  # found next to the colour map at Setup
    # simulate a base without AO next to it: unlink what Setup found, then pick one
    for st_node in injector.stacks(m.node_tree):
        for lk in list(st_node.inputs["AO"].links):
            m.node_tree.links.remove(lk)
    assert not detail.has_base_ao(m)
    path = os.path.join(OUT, "ao_pick", "tiles_ao.png")
    assert bpy.ops.realworn.pick_ao(filepath=path, material=m.name) == {"FINISHED"}
    assert detail.has_base_ao(m) and m.realworn.base_ao_kind == "IMAGE"


# ------------------------------------------------------------------ Content Height
def test_content_height_source_shares_the_channel_lookup(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "WEAR")
    img = grunge.load("cracks")
    ly.height.source, ly.height.image, ly.height.enabled = "IMAGE", img, True
    ly.detail.source = "CONTENT_HEIGHT"
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    assert detail.resolve(mat, ly)[0] == "CONTENT_HEIGHT"
    g = mat.realworn.stack
    looks = [n for n in g.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image == img]
    assert len(looks) == 1  # one lookup feeds both the height channel and Edge Detail
    edge = g.nodes[naming.layer_node(ly.id, "edge")]  # contrast 0: the lookup feeds the stage directly
    assert edge.inputs["Detail"].links[0].from_node == looks[0]


# ------------------------------------------------------------------ Second Grunge
def test_second_grunge_mix_is_lean_and_live(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "RUST")
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    g = mat.realworn.stack
    det = ly.detail
    det.image2 = grunge.load("breakup_fine")
    assert g.nodes.get(naming.layer_node(ly.id, "edge2.img")) is None  # Mix 0: no nodes
    det.mix2 = 0.4
    assert g.nodes.get(naming.layer_node(ly.id, "edge2.img")) is not None
    c0 = compiler.COMPILES["count"]
    det.mix2, det.scale2 = 0.6, 0.05
    assert compiler.COMPILES["count"] == c0
    assert g.nodes[naming.layer_node(ly.id, "edge.mix2")].outputs[0].default_value == pytest.approx(0.6)
    assert g.nodes[naming.layer_node(ly.id, "edge2.map")].inputs["Scale"].default_value[0] == pytest.approx(20.0)
    det.source = "GRUNGE2"
    assert detail.resolve(mat, ly) == ("GRUNGE2", det.image2)
    det.mix2 = 0.0
    assert g.nodes.get(naming.layer_node(ly.id, "edge2.img")) is None


# ------------------------------------------------------------------ anti-tiling
def test_anti_tiling_breaks_the_repeat(empty_scene, out_dir):
    """A 1 m grunge on a 6 m wall: without anti-tiling the pattern repeats every metre (shifted
    correlation near 1); with it the repeat is gone (correlation well below)."""
    sc = empty_scene
    ob, mat = su.wall(sc, width=6.0, height=1.0)
    ly = layers.add_layer(mat, "CUSTOM")
    det = ly.detail
    det.image, det.scale, det.strength, det.width, det.protect = grunge.load("breakup_rust"), 1.0, 1.0, 0.5, False
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    _ortho_front(sc, (0, 0, 0.5), 6.0, res=(1200, 200))
    su.setup_render(sc, samples=4)

    def repeat_corr(tag):
        img = su.render_mask_view(sc, mat, 0, os.path.join(out_dir, "antitile_{}.exr".format(tag)))
        a, b = img[40:160, 100:900], img[40:160, 300:1100]  # 200 px = 1 m = one tile
        a, b = a - a.mean(), b - b.mean()
        return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))

    plain = repeat_corr("off")
    det.anti_tile = True
    broken = repeat_corr("on")
    g = mat.realworn.stack
    print("\n[anti-tile] correlation with the image shifted by one tile: {:.2f} off, {:.2f} on".format(plain, broken))
    record("v2.1 Anti-tiling: correlation at a one-tile shift (6 m wall, 1 m grunge)", broken, "", None,
           "without anti-tiling {:.2f}".format(plain))
    assert g.nodes.get(naming.layer_node(ly.id, "edge.img2")) is not None
    assert plain > 0.9 and broken < 0.4


# ------------------------------------------------------------------ SRC-7, SRC-8
def test_grunge_size_metadata(empty_scene, tmp_path):
    assert grunge.suggested_scale("chips_small") == pytest.approx(0.2)
    assert grunge.suggested_scale("leaks") == pytest.approx(1.0)
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "WEAR")
    assert ly.detail.scale == pytest.approx(grunge.suggested_scale(ly.detail.image))
    # a user grunge with a sidecar
    arr = np.ones((8, 8, 4), np.float32)
    img = bpy.data.images.new("mine", 8, 8)
    img.pixels.foreach_set(arr.ravel())
    path = str(tmp_path / "mine.png")
    img.filepath_raw, img.file_format = path, "PNG"
    img.save()
    with open(str(tmp_path / "mine.json"), "w", encoding="utf-8") as fh:
        json.dump({"size_m": 0.07}, fh)
    assert grunge.suggested_scale(bpy.data.images.load(path)) == pytest.approx(0.07)
    assert grunge.suggested_scale(img, 0.5) in (0.07, 0.5)


def test_refresh_base_recaptures_without_touching_layers(empty_scene):
    base = su.corpus_material("red_brick")
    if base is None:
        pytest.skip("Poly Haven corpus not downloaded")
    ob, mat = su.wall(empty_scene, material=base)
    ly = layers.add_layer(mat, "DIRT")
    img = su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.5, 0.3), 0.2, 0.1))
    px0 = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(px0)
    lo0 = mat.realworn.base_height_lo
    # the user swaps the base height texture for a brighter one
    src = detail.base_height_socket(mat).node
    bright = bpy.data.images.new("bright_disp", 32, 32)
    bright.pixels.foreach_set((np.full(32 * 32 * 4, 0.8) + np.tile([0, 0, 0, 0.2], 32 * 32)).astype(np.float32))
    src.image = bright
    assert bpy.ops.realworn.refresh_base(material=mat.name) == {"FINISHED"}
    assert mat.realworn.base_height_lo == pytest.approx(0.8, abs=0.01) and mat.realworn.base_height_lo != lo0
    px1 = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(px1)
    assert len(mat.realworn.layers) == 1 and mat.realworn.layers[0].mask_image == img
    assert np.array_equal(px0, px1)

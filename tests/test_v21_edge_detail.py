"""PRD v2.1 Q1: the Edge Detail stage (EDG-1..EDG-10), Base Height sharing and normalisation
(SRC-1, SRC-2), acceptance tests T4 (sample once), T5 (lean compile) and T6 (v2.0 files unchanged
until Apply v2.1 Defaults)."""

import os
import subprocess

import bpy
import numpy as np
import pytest

import render_util as ru
import sharp_util as su
from realworn.core import compiler, detail, layer_types as LT, layers, naming, snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _paint_disk(ob, mat, ly, r=0.3):
    su.paint_layer(ob, mat, ly, lambda res: su.soft_disk(res, su.uv_at(ob, (0, -0.5, 0.5)),
                                                         r * su.uv_per_metre(ob, (0, -0.5, 0.5)), 0.05))


def _edge_nodes(mat, ly):
    g = mat.realworn.stack
    return [n for n in g.nodes if n.name.startswith(naming.layer_node(ly.id, "edge"))]


@pytest.fixture
def plate(empty_scene):
    base = su.corpus_material("metal_plate")
    if base is None:
        pytest.skip("Poly Haven corpus not downloaded")
    ob, mat = su.crate(empty_scene, size=1.0, material=base)
    return empty_scene, ob, mat


# ------------------------------------------------------------------ defaults, data
def test_new_layers_get_per_type_defaults(plate):
    sc, ob, mat = plate
    assert mat.realworn.v21
    for kind, d in LT.DETAIL.items():
        ly = layers.add_layer(mat, kind)
        det = ly.detail
        assert (det.mode, det.source) == (d["mode"], d["source"]), kind
        assert det.strength == pytest.approx(d["strength"]) and det.width == pytest.approx(d["width"])
        assert det.protect == d["protect"]
        assert det.image is not None and det.image.name.startswith(d["grunge"]), kind
    for kind in ("PAINT", "CUSTOM", "DECAL"):
        assert layers.add_layer(mat, kind).detail.strength == 0.0
    assert not next(ly for ly in mat.realworn.layers if ly.type == "DIRT").use_height_blend


def test_base_height_capture_normalises_with_percentiles(plate):
    sc, ob, mat = plate
    st = mat.realworn
    assert st.base_height_kind == "IMAGE" and "disp" in st.base_height_image
    img = bpy.data.images[st.base_height_image]
    px = np.empty(img.size[0] * img.size[1] * img.channels, np.float32)
    img.pixels.foreach_get(px)
    lo, hi = np.percentile(px.reshape(-1, img.channels)[:, 0], (2, 98))
    assert st.base_height_lo == pytest.approx(lo, abs=1e-4) and st.base_height_hi == pytest.approx(hi, abs=1e-4)


def test_procedural_base_height_uses_socket_range(empty_scene):
    mat = bpy.data.materials.new("Proc")
    mat.use_nodes = True
    nt = mat.node_tree
    p = nt.nodes["Principled BSDF"]
    noise, bump = nt.nodes.new("ShaderNodeTexNoise"), nt.nodes.new("ShaderNodeBump")
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    ob, mat = su.crate(empty_scene, size=1.0, material=mat)
    st = mat.realworn
    assert st.base_height_kind == "SOCKET" and (st.base_height_lo, st.base_height_hi) == (0.0, 1.0)
    st.base_height_lo, st.base_height_hi = 0.3, 0.7  # SRC-3: user range, kept on recapture
    detail.capture_base(mat)
    assert (round(st.base_height_lo, 3), round(st.base_height_hi, 3)) == (0.3, 0.7)
    ly = layers.add_layer(mat, "DIRT")
    assert detail.resolve(mat, ly)[0] == "BASE_HEIGHT"
    _paint_disk(ob, mat, ly)
    bh = mat.realworn.stack.nodes[naming.layer_node("stack", "bh")]
    assert (bh.inputs[1].default_value, bh.inputs[2].default_value) == pytest.approx((0.3, 0.7))
    st.base_height_hi = 0.9  # live value, shared node
    assert bh.inputs[2].default_value == pytest.approx(0.9)


def test_no_base_height_falls_back_to_grunge(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)  # plain Principled: no height anywhere
    assert mat.realworn.base_height_kind == "NONE"
    ly = layers.add_layer(mat, "DIRT")
    assert detail.resolve(mat, ly)[0] == "LAYER_GRUNGE"
    _paint_disk(ob, mat, ly)
    assert any(n.bl_idname == "ShaderNodeTexImage" for n in _edge_nodes(mat, ly))


# ------------------------------------------------------------------ T4, T5
def test_t4_base_height_sampled_once(plate):
    """T4 / SRC-1: four layers on Base Height add no texture lookup; the base's own height image
    node is the only Image Texture for it, and one shared Map Range normalises it."""
    sc, ob, mat = plate
    img_name = mat.realworn.base_height_image
    for kind in ("DIRT", "WATER", "DAMAGE", "DIRT"):
        ly = layers.add_layer(mat, kind)
        assert ly.detail.source == "BASE_HEIGHT"
        _paint_disk(ob, mat, ly)
    g = mat.realworn.stack
    trees = [mat.node_tree, g]
    count = sum(1 for t in trees for n in t.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image is not None
                and n.image.name == img_name)
    assert count == 1
    bh = [n for n in g.nodes if n.name == naming.layer_node("stack", "bh")]
    # one shared normaliser; its users are the 4 Edge Detail stages (and the content looks that
    # read the base height too, CNT-3)
    assert len(bh) == 1 and len(bh[0].outputs["Result"].links) >= 4


def test_t5_lean_and_deterministic(plate):
    sc, ob, mat = plate
    ly = layers.add_layer(mat, "RUST")
    _paint_disk(ob, mat, ly)
    assert _edge_nodes(mat, ly)
    ly.detail.strength = 0.0
    assert _edge_nodes(mat, ly) == []
    g = mat.realworn.stack
    before = snapshot.dumps(snapshot.serialize(g, include_owned=True))
    compiler.compile(mat)
    assert snapshot.dumps(snapshot.serialize(g, include_owned=True)) == before
    ly.detail.strength = 0.6
    assert _edge_nodes(mat, ly)
    before = snapshot.dumps(snapshot.serialize(g, include_owned=True))
    compiler.compile(mat)
    assert snapshot.dumps(snapshot.serialize(g, include_owned=True)) == before


def test_edg10_values_update_live_structure_recompiles(plate):
    sc, ob, mat = plate
    ly = layers.add_layer(mat, "RUST")
    _paint_disk(ob, mat, ly)
    edge = mat.realworn.stack.nodes[naming.layer_node(ly.id, "edge")]
    c0 = compiler.COMPILES["count"]
    det = ly.detail
    det.width, det.threshold, det.strength, det.contrast, det.scale, det.protect = 0.2, 0.4, 0.5, 0.3, 0.7, True
    assert compiler.COMPILES["count"] == c0  # no recompile, no EEVEE shader rebuild
    assert edge.inputs["Width"].default_value == pytest.approx(0.2)
    assert edge.inputs["Threshold"].default_value == pytest.approx(0.4)
    assert edge.inputs["Strength"].default_value == pytest.approx(0.5)
    assert edge.inputs["Protect"].default_value == 1.0
    mp = mat.realworn.stack.nodes[naming.layer_node(ly.id, "edge.map")]
    assert mp.inputs["Scale"].default_value[0] == pytest.approx(1 / 0.7)
    det.mode = "HEIGHT"
    assert compiler.COMPILES["count"] == c0 + 1
    assert mat.realworn.stack.nodes[naming.layer_node(ly.id, "edge")].node_tree.name == naming.SH_EDGE_HEIGHT
    det.strength = 0.0
    assert compiler.COMPILES["count"] == c0 + 2 and not _edge_nodes(mat, ly)
    mat.realworn.base_height_lo = 0.1  # material-level value: no recompile
    assert compiler.COMPILES["count"] == c0 + 2


# ------------------------------------------------------------------ the formulas in the shader
@pytest.mark.parametrize("mode", ["ERODE", "BURN", "HEIGHT"])
def test_groups_match_reference_formula(empty_scene, mode):
    """Evaluate each Edge Detail group on a grid of (m, d) through an emission render and compare
    with layer_types.edge_detail (the pure Python reference)."""
    sc = empty_scene
    mat = bpy.data.materials.new("Probe")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    from realworn.core import assets
    name = {"ERODE": naming.SH_EDGE_ERODE, "BURN": naming.SH_EDGE_BURN, "HEIGHT": naming.SH_EDGE_HEIGHT}[mode]
    assets.ensure_groups((name,))
    grp = nt.nodes.new("ShaderNodeGroup")
    grp.node_tree = bpy.data.node_groups[name]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Window"], sep.inputs[0])
    nt.links.new(sep.outputs["X"], grp.inputs["Mask"])
    nt.links.new(sep.outputs["Y"], grp.inputs["Detail"])
    s, w, t = 0.7, 0.2, 0.5
    grp.inputs["Strength"].default_value, grp.inputs["Width"].default_value = s, w
    grp.inputs["Threshold"].default_value = t
    if mode == "ERODE":
        grp.inputs["Protect"].default_value = 1.0
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(grp.outputs["Mask"], em.inputs["Color"])
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    import bmesh
    from fixtures import make_scenes as ms
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=5.0)
    plane = ms._link(sc, "P", bm, (0, 0, 0), mat)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    cam.location = (0, 0, 5)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.0
    sc.camera = cam
    su.setup_render(sc, engine="CYCLES", samples=1)
    sc.render.resolution_x = sc.render.resolution_y = 64
    sc.cycles.pixel_filter_type = "BOX"
    sc.render.filter_size = 0.01
    sc.render.filepath = os.path.join(ROOT, "tests", "_out", "edge_ref_{}.exr".format(mode))
    bpy.ops.render.render(write_still=True)
    img = ru.load(sc.render.filepath)[..., 0]  # rows bottom-up: y = (row + 0.5) / 64
    errs = []
    for row in range(0, 64, 7):
        for col in range(0, 64, 7):
            m, d = (col + 0.5) / 64, (row + 0.5) / 64
            ref = LT.edge_detail(mode, m, d, s, w, t, protect=True)
            errs.append(abs(img[row, col] - ref))
    assert max(errs) < 0.02, max(errs)


# ------------------------------------------------------------------ EDG-8
def test_edg8_split_preview(plate, out_dir):
    sc, ob, mat = plate
    ly = layers.add_layer(mat, "RUST")
    _paint_disk(ob, mat, ly)
    st = mat.realworn
    st.mask_view, st.detail_split = True, True
    g = st.stack
    assert g.nodes.get(naming.layer_node(ly.id, "split.tc")) is not None
    st.detail_split = False
    assert g.nodes.get(naming.layer_node(ly.id, "split.tc")) is None
    st.mask_view = False


# ------------------------------------------------------------------ T6
V20_SCRIPT = r'''
import sys
src, blend, ref = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, src)
import bpy, numpy as np, bmesh, math
import realworn
realworn.register()
from realworn.core import setup, layers, images, injector
bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
sc = bpy.context.scene
mat = bpy.data.materials.new("Base")
mat.use_nodes = True
nt = mat.node_tree
p = nt.nodes["Principled BSDF"]
p.inputs["Base Color"].default_value = (0.08, 0.2, 0.38, 1)
noise, bump = nt.nodes.new("ShaderNodeTexNoise"), nt.nodes.new("ShaderNodeBump")
noise.inputs["Scale"].default_value = 25.0
nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=4, use_grid_fill=True)
me = bpy.data.meshes.new("Crate")
bm.to_mesh(me)
ob = bpy.data.objects.new("Crate", me)
sc.collection.objects.link(ob)
ob.location = (0, 0, 0.5)
me.materials.append(mat)
setup.setup_object(ob)
mat = ob.material_slots[0].material
for i, kind in enumerate(("DIRT", "RUST", "WEAR", "WATER", "DAMAGE")):
    ly = layers.add_layer(mat, kind, index=len(mat.realworn.layers))
    ly.mask_res = 256
    img = images.ensure_mask(ob, mat, ly)
    t = (np.arange(256) + 0.5) / 256
    u, v = np.meshgrid(t, t)
    a = np.clip(1.0 - np.hypot(u - 0.2 - 0.15 * i, v - 0.5) / 0.25, 0, 1)
    px = np.ones((256, 256, 4), np.float32)
    px[..., 3] = a
    img.pixels.foreach_set(px.ravel())
    img.update()
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
sc.collection.objects.link(cam)
cam.location = (2.0, -2.4, 1.8)
cam.rotation_euler = (math.radians(62), 0, math.radians(40))
sc.camera = cam
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sc.collection.objects.link(sun)
sun.rotation_euler = (0.8, 0.2, 0.5)
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 16
sc.cycles.use_denoising = False
sc.cycles.seed = 0
sc.render.resolution_x = sc.render.resolution_y = 160
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "OPEN_EXR"
sc.render.filepath = ref
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=blend)
'''


def _git_v20(out_dir):
    dst = os.path.join(out_dir, "v20_src")
    if os.path.isdir(os.path.join(dst, "realworn")):
        return dst
    os.makedirs(dst, exist_ok=True)
    tar = os.path.join(out_dir, "v20.tar")
    r = subprocess.run(["git", "-C", ROOT, "archive", "-o", tar, "v2.0-p8", "realworn"], capture_output=True,
                       text=True)
    if r.returncode != 0:
        return None
    import tarfile
    with tarfile.open(tar) as tf:
        tf.extractall(dst, filter="data")
    return dst


def test_t6_v20_file_renders_unchanged_until_apply(empty_scene, out_dir):
    src = _git_v20(out_dir)
    if src is None:
        pytest.skip("git / tag v2.0-p8 not available")
    blend, ref = os.path.join(out_dir, "v20_file.blend"), os.path.join(out_dir, "v20_ref.exr")
    script = os.path.join(out_dir, "make_v20.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(V20_SCRIPT)
    r = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python", script, "--",
                        src, blend, ref], capture_output=True, text=True, timeout=600)
    assert os.path.exists(blend) and os.path.exists(ref), r.stdout[-1500:] + r.stderr[-1500:]
    bpy.ops.wm.open_mainfile(filepath=blend)
    sc = bpy.context.scene
    mat = bpy.data.objects["Crate"].material_slots[0].material
    assert not mat.realworn.v21 and all(ly.detail.strength == 0.0 for ly in mat.realworn.layers)
    compiler.compile(mat)  # what opening in v2.1 does (stack upgrade): must change nothing visible
    now = os.path.join(out_dir, "v20_in_v21.exr")
    sc.render.filepath = now
    bpy.ops.render.render(write_still=True)
    a, b = ru.load(ref), ru.load(now)
    d = float(np.abs(a - b).mean())
    print("\n[T6] v2.0 file, v2.0 render vs v2.1 render: mean difference {:.6f}".format(d))
    assert d < 0.0005
    detail.apply_v21_defaults(mat)
    assert mat.realworn.v21 and any(ly.detail.strength > 0 for ly in mat.realworn.layers)
    after = os.path.join(out_dir, "v20_applied_v21.exr")
    sc.render.filepath = after
    bpy.ops.render.render(write_still=True)
    d2 = float(np.abs(a - ru.load(after)).mean())
    print("[T6] after Apply v2.1 Defaults: mean difference {:.4f}".format(d2))
    assert d2 > 0.002  # the button does change the look

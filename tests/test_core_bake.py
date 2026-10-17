"""Bake and safety: Bake Material + Restore
Live Stack, Export Textures with engine presets, v0.7 files cleaned, and 20 x Setup / paint /
Remove without leftovers."""

import os
import shutil
import subprocess

import bmesh
import bpy
import numpy as np
import pytest

import render_util as ru
from corpus.generated import GENERATED
from fixtures import make_scenes as ms
from realworn.core import bake, images, layers, migrate, naming, nodeutil, setup, snapshot
from test_core_setup import _texture_folder, state_of, uv_cube

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def painted_cube(sc, name="Prop", tmp=None):
    ob = uv_cube(sc, name, size=1.0, cuts=8, material=ms.principled(name + "Mat", (0.05, 0.2, 0.5), roughness=0.4))
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    for kind, half in (("PAINT", 0), ("REVEAL", 1), ("DIRT", 2)):
        ly = layers.add_layer(mat, kind)
        ly.mask_res = 256
        if kind == "PAINT":
            ly.content, ly.color, ly.roughness = "COLOR", (0.6, 0.1, 0.05), 0.8
        if kind == "DIRT":
            ly.edge_source = "LIVE"
        img = images.ensure_mask(ob, mat, ly)
        px = np.zeros((256, 256, 4), np.float32)
        px[..., 3] = 1.0
        px[:, half * 85:(half + 1) * 85, :3] = 1.0  # three vertical bands of the RW_Paint layout
        img.pixels.foreach_set(px.ravel())
        img.update()
    return ob, mat


def _camera(sc, res=(128, 128), samples=16):
    ms.camera_light(sc, cam_loc=(2.2, -2.4, 1.8), target=(0, 0, 0.45))
    ru.setup(sc, samples=samples, res=res)


# ------------------------------------------------------------- Bake Material
def test_bake_material_swap_restore_remove(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = painted_cube(sc)
    before_tree = snapshot.dumps(snapshot.serialize(mat.node_tree))
    _camera(sc)
    live = ru.render(sc, os.path.join(out_dir, "p8_live.png"))
    imgs = bake.bake_material(ob, mat, sc, resolution=256, folder=os.path.join(out_dir, "p8_bake"))
    assert set(imgs) == {"base_color", "roughness", "metallic", "height", "normal"}
    for img in imgs.values():
        assert os.path.exists(bpy.path.abspath(img.filepath_raw)), img.name
    p = mat.node_tree.nodes["Principled BSDF"]
    assert p.inputs["Base Color"].links[0].from_node.name == "RW::baked.base_color"
    assert p.inputs["Normal"].links[0].from_node.name == "RW::baked.nmap" and mat.realworn.baked
    assert mat.node_tree.nodes["RW::baked.uv"].uv_map == naming.UV_PAINT
    out = nodeutil.output_node(mat.node_tree)
    assert not out.inputs["Displacement"].is_linked  # the baked normal map carries the relief
    baked = ru.render(sc, os.path.join(out_dir, "p8_baked.png"))
    bake.restore_live(mat)
    restored = ru.render(sc, os.path.join(out_dir, "p8_restored.png"))
    d_b, d_r = ru.mad(live, baked), ru.mad(live, restored)
    print("\n[bake] live vs baked MAD {:.4f}; live vs restored {:.6f}".format(d_b, d_r))
    assert d_b < 0.03 and d_r < 1e-4 and not mat.realworn.baked
    bake.bake_material(ob, mat, sc, resolution=64, folder=os.path.join(out_dir, "p8_bake"))
    assert setup.remove_object(ob) == []  # Remove after a bake still restores exactly
    assert snapshot.dumps(snapshot.serialize(mat.node_tree)) == before_tree
    assert not nodeutil.owned_nodes(mat.node_tree)


def test_baked_normal_map_matches_the_live_normal(empty_scene, out_dir):
    """The baked normal map, read through RW_Paint, gives the live shading normal back, even where
    Cube Projection turned RW_Paint against the object's own UV map (the bake must take its tangents
    from RW_Paint)."""
    from test_puddles import make_set, plane, render_exr, top_camera
    sc = empty_scene
    n = 256
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    grain = (0.5 + 0.3 * np.sin(x * 40) * np.cos(y * 37)).astype(np.float32)
    ob, mat = plane(sc)
    assert ob.data.uv_layers.active.name != naming.UV_PAINT
    layers.load_texture(mat, make_set(out_dir, "nrm_grain", grain), scale=2.0)
    mat.realworn.base.bump = 0.2
    top_camera(sc, res=128, samples=4)
    nt = mat.node_tree
    out = nodeutil.output_node(nt)
    surface = out.inputs["Surface"].links[0].from_socket

    def normal_view(sock, name):
        """Render a normal (world space) as colour, then put the surface back."""
        view = nt.nodes.new("ShaderNodeVectorMath")
        view.operation = "MULTIPLY_ADD"
        view.inputs[1].default_value = view.inputs[2].default_value = (0.5, 0.5, 0.5)
        em = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(sock, view.inputs[0])
        nt.links.new(view.outputs[0], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        try:
            return render_exr(sc, os.path.join(out_dir, "nrm_{}.exr".format(name)))[16:112, 16:112] * 2 - 1
        finally:
            nt.nodes.remove(view)
            nt.nodes.remove(em)
            nt.links.new(surface, out.inputs["Surface"])

    geo = nt.nodes.new("ShaderNodeNewGeometry")  # the shading normal, bumped by the live height
    live = normal_view(geo.outputs["Normal"], "live")
    nt.nodes.remove(geo)
    bake.bake_material(ob, mat, sc, resolution=512, folder=os.path.join(out_dir, "nrm_bake"), samples=4)
    assert ob.data.uv_layers.active.name != naming.UV_PAINT  # the selection is put back
    baked = normal_view(nt.nodes["RW::baked.nmap"].outputs["Normal"], "baked")
    assert live[..., :2].std() > 0.05  # the relief is there to compare
    for i, axis in enumerate("xy"):
        r = float(np.corrcoef(live[..., i].ravel(), baked[..., i].ravel())[0, 1])
        d = float(np.abs(live[..., i] - baked[..., i]).mean())
        print("\n[bake] normal {}: correlation live vs baked {:.4f}, mean difference {:.4f}".format(axis, r, d))
        assert r > 0.99 and d < 0.02
    bake.restore_live(mat)
    assert setup.remove_object(ob) == []


# ------------------------------------------------------------- Export
def test_export_presets(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = painted_cube(sc)
    bake.bake_material(ob, mat, sc, resolution=64, folder=os.path.join(out_dir, "p8_exp"))
    folder = os.path.join(out_dir, "p8_export")
    shutil.rmtree(folder, ignore_errors=True)
    expect = {"UNITY_URP": ("BaseMap", "MetallicSmoothness", "Normal"),
              "UNITY_HDRP": ("BaseColor", "MaskMap", "Normal"),
              "UNREAL": ("BaseColor", "ORM", "Normal"),
              "GLTF": ("baseColor", "metallicRoughness", "normal")}
    loaded = {}
    for preset, names in expect.items():
        paths = bake.export_textures(mat, os.path.join(folder, preset), preset)
        assert [os.path.basename(p) for p in paths] == ["{}_{}.png".format(bpy.path.clean_name(mat.name), n)
                                                        for n in names]
        loaded[preset] = {n: ru.load_rgba(p) for n, p in zip(names, paths)}
    rough = bake.pixels(bpy.data.images[bpy.path.clean_name(mat.name) + "_roughness"])[..., 0]
    metal = bake.pixels(bpy.data.images[bpy.path.clean_name(mat.name) + "_metallic"])[..., 0]
    orm = loaded["UNREAL"]["ORM"]
    assert np.abs(orm[..., 1] - rough).max() < 0.01 and np.abs(orm[..., 2] - metal).max() < 0.01
    ms_ = loaded["UNITY_URP"]["MetallicSmoothness"]
    assert np.abs(ms_[..., 3] - (1 - rough)).max() < 0.01
    gl, dx = loaded["GLTF"]["normal"], loaded["UNREAL"]["Normal"]
    assert np.abs(gl[..., 1] - (1 - dx[..., 1])).max() < 0.01  # DirectX flips green


# ------------------------------------------------------- v0.7 files
V07_SCRIPT = r'''
import sys, bpy
sys.path.insert(0, sys.argv[-3])
import realworn
realworn.register()
from realworn.core import weathering
bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
me = bpy.data.meshes.new("C")
import bmesh
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bm.to_mesh(me)
ob = bpy.data.objects.new("Crate", me); bpy.context.scene.collection.objects.link(ob)
mat = bpy.data.materials.new("Paint"); me.materials.append(mat)
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.3, 0.6, 1)
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-2])
weathering.apply_object(ob, bpy.context.scene, "painted_metal")
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
'''


def _git_v07(out_dir):
    dst = os.path.join(out_dir, "v07_src")
    if os.path.isdir(os.path.join(dst, "realworn")):
        return dst
    os.makedirs(dst, exist_ok=True)
    tar = os.path.join(out_dir, "v07.tar")
    r = subprocess.run(["git", "-C", ROOT, "archive", "-o", tar, "v0.7.0", "realworn"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    import tarfile
    with tarfile.open(tar) as tf:
        tf.extractall(dst, filter="data")
    return dst


def test_v07_file_is_restored_and_set_up_again(empty_scene, out_dir):
    src = _git_v07(out_dir)
    if src is None:
        pytest.skip("git / tag v0.7.0 not available")
    clean, weathered = os.path.join(out_dir, "v07_clean.blend"), os.path.join(out_dir, "v07_weathered.blend")
    script = os.path.join(out_dir, "make_v07.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(V07_SCRIPT)
    r = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python", script, "--",
                        src, clean, weathered], capture_output=True, text=True, timeout=600)
    assert os.path.exists(weathered), r.stdout[-1500:] + r.stderr[-1500:]
    bpy.ops.wm.open_mainfile(filepath=clean)
    want = snapshot.dumps(snapshot.serialize(bpy.data.materials["Paint"].node_tree))
    bpy.ops.wm.open_mainfile(filepath=weathered)
    mat = bpy.data.materials["Paint"]
    found = migrate.find_v07()
    assert mat in found["materials"] and bpy.data.objects["Crate"] in found["objects"]
    assert "RW_Stack" in bpy.data.node_groups
    rep = migrate.remove_v07()
    assert not [r for r in rep if r[0] == "ERROR"], rep
    assert snapshot.dumps(snapshot.serialize(mat.node_tree)) == want  # exactly the pre-v0.7 tree
    ob = bpy.data.objects["Crate"]
    assert not ob.modifiers and "rw_paint" not in ob.data.color_attributes
    assert not [g for g in bpy.data.node_groups if g.name in migrate.V07_GROUPS]
    assert not migrate.find_v07()["materials"]
    ob.data.uv_layers.new(name="UVMap")
    setup.setup_object(ob)  # v3 from here
    assert mat.realworn.stack is not None and mat.realworn.schema_version == naming.SCHEMA


# --------------------------------------------- success criterion 3
def test_twenty_setup_paint_remove_cycles(empty_scene):
    sc = empty_scene
    obs = [uv_cube(sc, "P%d" % i, loc=(i * 1.5, 0, 0.5), material=GENERATED[g]())
           for i, g in enumerate(("principled_basic", "image_based", "procedural", "multi_principled"))]
    before = {o.name: state_of(o) for o in obs}
    images_before = set(bpy.data.images.keys())
    groups_before = set(bpy.data.node_groups.keys())
    kinds = ("VARIATION", "PAINT", "REVEAL", "DECALS", "EDGE_WEAR", "DIRT")
    for cycle in range(20):
        for i, o in enumerate(obs):
            setup.setup_object(o)
            mat = o.material_slots[0].material
            for k in range(1 + (cycle + i) % 3):
                ly = layers.add_layer(mat, kinds[(cycle + i + k) % len(kinds)])
                ly.mask_res, ly.decal_res = 64, "2048"
                if ly.kind in ("PAINT", "REVEAL", "DIRT"):
                    images.fill(images.ensure_mask(o, mat, ly), 1.0)
        for o in obs:
            assert setup.remove_object(o) == []
    for o in obs:
        assert state_of(o) == before[o.name], o.name
        assert not [m.name for m in o.modifiers]
    leftover_imgs = set(bpy.data.images.keys()) - images_before
    assert not [n for n in leftover_imgs if n.startswith("RW_")], leftover_imgs
    leftover_groups = {g for g in set(bpy.data.node_groups.keys()) - groups_before
                       if g.startswith(naming.STACK_PREFIX)}
    assert not leftover_groups
    for m in bpy.data.materials:
        if m.node_tree is not None:
            assert not nodeutil.owned_nodes(m.node_tree), m.name

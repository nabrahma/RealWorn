"""P8 acceptance: Bake Material + Restore Live Stack (BAK-2), Flatten (BAK-1), Export Textures with
engine presets (BAK-3), Geometry damage handled explicitly (BAK-4), v0.7 files cleaned
(migration path), and success criterion 3: 20 x Setup / paint / Remove without leftovers."""

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
from realworn.core import bake, damage, images, layers, migrate, naming, nodeutil, setup, snapshot
from test_p1_setup import state_of, uv_cube

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def painted_cube(sc, name="Prop"):
    ob = uv_cube(sc, name, size=1.0, cuts=8, material=ms.principled(name + "Mat", (0.05, 0.2, 0.5), roughness=0.4))
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    me = ob.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[naming.UV_PAINT].data.foreach_get("uv", uv)
    for kind, half in (("DIRT", 0), ("WEAR", 1), ("WATER", 2)):
        ly = layers.add_layer(mat, kind)
        ly.mask_res = 256
        if kind == "WEAR":
            ly.lock_source = "NONE"
        img = images.ensure_mask(ob, mat, ly)
        px = np.zeros((256, 256, 4), np.float32)
        px[:, half * 85:(half + 1) * 85] = 1.0  # three vertical bands of the RW_Paint layout
        img.pixels.foreach_set(px.ravel())
        img.update()
    return ob, mat


def _camera(sc, res=(128, 128), samples=16):
    ms.camera_light(sc, cam_loc=(2.2, -2.4, 1.8), target=(0, 0, 0.45))
    ru.setup(sc, samples=samples, res=res)


# ------------------------------------------------------------- BAK-2
def test_bake_material_swap_restore_remove(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = painted_cube(sc)
    before_tree = snapshot.dumps(snapshot.serialize(mat.node_tree))
    _camera(sc)
    live = ru.render(sc, os.path.join(out_dir, "p8_live.png"))
    imgs = bake.bake_material(ob, mat, sc, resolution=256, folder=os.path.join(out_dir, "p8_bake"))
    assert set(imgs) == {"base_color", "roughness", "metallic", "height", "coat_weight", "coat_roughness", "normal"}
    for img in imgs.values():
        assert os.path.exists(bpy.path.abspath(img.filepath_raw)), img.name
    p = mat.node_tree.nodes["Principled BSDF"]
    assert p.inputs["Base Color"].links[0].from_node.name == "RW::baked.base_color"
    assert p.inputs["Normal"].links[0].from_node.name == "RW::baked.nmap" and mat.realworn.baked
    assert mat.node_tree.nodes["RW::baked.uv"].uv_map == naming.UV_PAINT
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


def test_bake_geometry_damage_is_explicit(empty_scene, out_dir):
    sc = empty_scene
    ob = ms.sharp_cube(sc, name="Block", size=1.0, cuts=8, location=(0, 0, 0.5), material=ms.principled("B"))
    ob.data.uv_layers.new(name="UVMap")
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    ly = layers.add_layer(mat, "DAMAGE")
    images.fill(images.ensure_mask(ob, mat, ly), 1.0)
    ly.damage.depth_mode = "GEOMETRY"
    ly.damage.density = 30.0
    mod = damage.damage_modifier(ob)
    assert mod is not None
    with pytest.raises(bake.BakeError, match="Geometry-mode damage"):
        bake.bake_material(ob, mat, sc, resolution=32, folder=os.path.join(out_dir, "p8_dmg"))
    bake.bake_material(ob, mat, sc, resolution=32, folder=os.path.join(out_dir, "p8_dmg"), geometry_damage="EXCLUDE")
    assert mod.show_render and mod.show_viewport  # put back after the bake


# ------------------------------------------------------------- BAK-1
def test_flatten_two_layers(empty_scene, out_dir):
    sc = empty_scene
    ob, mat = painted_cube(sc)
    _camera(sc)
    for ly in mat.realworn.layers:  # flatten the two bottom ones; hide Water so only they show
        ly.visible = ly.type != "WATER"
    before = ru.render(sc, os.path.join(out_dir, "p8_flat_before.png"))
    n = len(mat.realworn.layers)
    merged = bake.flatten(ob, mat, 0, 1, sc, resolution=256)
    assert len(mat.realworn.layers) == n - 1 and merged.type == "PAINT"
    assert merged.content_image is not None and merged.roughness.image is not None
    assert mat.realworn.stack.nodes[naming.layer_node(merged.id, "roughness.img")].inputs["Vector"].links[0] \
        .from_node.uv_map == naming.UV_PAINT
    after = ru.render(sc, os.path.join(out_dir, "p8_flat_after.png"))
    d = ru.mad(before, after)
    print("\n[flatten] before vs after MAD {:.4f}".format(d))
    assert d < 0.03


# ------------------------------------------------------------- BAK-3
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
    r = subprocess.run(["git", "-C", ROOT, "archive", "-o", tar, "v0.7", "realworn"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    import tarfile
    with tarfile.open(tar) as tf:
        tf.extractall(dst, filter="data")
    return dst


def test_v07_file_is_restored_and_set_up_again(empty_scene, out_dir):
    src = _git_v07(out_dir)
    if src is None:
        pytest.skip("git / tag v0.7 not available")
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
    setup.setup_object(ob)  # v2 from here
    assert mat.realworn.stack is not None and mat.realworn.schema_version == naming.SCHEMA


# --------------------------------------------- success criterion 3
def test_twenty_setup_paint_remove_cycles(empty_scene):
    sc = empty_scene
    obs = [uv_cube(sc, "P%d" % i, loc=(i * 1.5, 0, 0.5), material=GENERATED[g]())
           for i, g in enumerate(("principled_basic", "image_based", "procedural", "multi_principled"))]
    before = {o.name: state_of(o) for o in obs}
    images_before = set(bpy.data.images.keys())
    groups_before = set(bpy.data.node_groups.keys())
    kinds = ("DIRT", "WEAR", "RUST", "WATER", "DAMAGE", "PAINT", "CUSTOM")
    for cycle in range(20):
        for i, o in enumerate(obs):
            setup.setup_object(o)
            mat = o.material_slots[0].material
            for k in range(1 + (cycle + i) % 3):
                ly = layers.add_layer(mat, kinds[(cycle + i + k) % len(kinds)])
                ly.mask_res = 64
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

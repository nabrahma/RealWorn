"""R5 Migration (PRD v3 "Other required suites"): a file painted with RealWorn v2.1 (made by the real
v2.1 code, from git tag v2.1-q4, in a separate Blender) converts layer by layer where there is a
clear match, keeps the painted masks, reports the rest, and still Removes exactly."""

import os
import subprocess
import tarfile

import bpy
import numpy as np
import pytest

from realworn.core import images, migrate, naming, setup, snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

V21_SCRIPT = r'''
import sys, bpy, numpy as np
sys.path.insert(0, sys.argv[-3])
import realworn
realworn.register()
from realworn.core import setup, layers, images
bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
import bmesh
me = bpy.data.meshes.new("C")
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bm.to_mesh(me)
ob = bpy.data.objects.new("Crate", me); bpy.context.scene.collection.objects.link(ob)
mat = bpy.data.materials.new("Paint"); me.materials.append(mat)
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.3, 0.6, 1)
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-2])
setup.setup_object(ob)
for kind in ("DIRT", "WEAR", "DAMAGE", "WATER", "CUSTOM"):
    ly = layers.add_layer(mat, kind, index=len(mat.realworn.layers))
    ly.mask_res = 256
    img = images.ensure_mask(ob, mat, ly)
    px = np.zeros((256, 256, 4), np.float32)
    px[:, :128] = 1.0  # the left half painted (v2 masks: white, alpha 1)
    img.pixels.foreach_set(px.ravel()); img.update()
mat.realworn.layers[0].color.color = (0.2, 0.15, 0.1)
mat.realworn.layers[2].damage.depth_mm = 4.0
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
'''


def _git(tag, out_dir):
    dst = os.path.join(out_dir, tag + "_src")
    if os.path.isdir(os.path.join(dst, "realworn")):
        return dst
    os.makedirs(dst, exist_ok=True)
    tar = os.path.join(out_dir, tag + ".tar")
    r = subprocess.run(["git", "-C", ROOT, "archive", "-o", tar, tag, "realworn"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    with tarfile.open(tar) as tf:
        tf.extractall(dst, filter="data")
    return dst


@pytest.fixture
def v21_file(out_dir):
    src = _git("v2.1-q4", out_dir)
    if src is None:
        pytest.skip("git / tag v2.1-q4 not available")
    clean, painted = os.path.join(out_dir, "v21_clean.blend"), os.path.join(out_dir, "v21_painted.blend")
    script = os.path.join(out_dir, "make_v21.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(V21_SCRIPT)
    if not os.path.exists(painted):
        r = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python", script, "--",
                            src, clean, painted], capture_output=True, text=True, timeout=900)
        assert os.path.exists(painted), r.stdout[-1500:] + r.stderr[-1500:]
    return clean, painted


def test_v21_file_converts_and_keeps_masks(v21_file):
    clean, painted = v21_file
    bpy.ops.wm.open_mainfile(filepath=clean)
    want = snapshot.dumps(snapshot.serialize(bpy.data.materials["Paint"].node_tree))
    bpy.ops.wm.open_mainfile(filepath=painted)
    mat = bpy.data.materials["Paint"]
    assert migrate.find_v2() == [mat] and not migrate.find_v07()["materials"]
    masks_before = {ly.name: images.pixels(ly.mask_image)[..., 0].copy() for ly in mat.realworn.layers}
    rep = migrate.convert_v2(mat)
    print("\n[migrate] " + "\n[migrate] ".join(m for _, m in rep))
    assert not [r for r in rep if r[0] == "ERROR"], rep
    st = mat.realworn
    assert st.schema_version == naming.SCHEMA and st.applied and st.stack is not None
    assert [(ly.name, ly.kind) for ly in st.layers] == [("Dirt", "PAINT"), ("Wear", "REVEAL"), ("Damage", "REVEAL"),
                                                        ("Custom", "PAINT")]
    assert any("Water" in m and "not converted" in m for _, m in rep)
    dirt, wear, damage, custom = st.layers
    assert tuple(dirt.color) == pytest.approx((0.2, 0.15, 0.1)) and dirt.content == "COLOR"
    assert damage.depth_mm == pytest.approx(4.0) and wear.depth_mm == 0.0
    for ly in st.layers:  # painted masks kept, pixel for pixel
        assert np.array_equal(images.pixels(ly.mask_image)[..., 0], masks_before[ly.name]), ly.name
        assert ly.mask_image.get(naming.IMG_MASK) == "Crate/" + ly.id
    ob = bpy.data.objects["Crate"]
    assert not [m for m in ob.modifiers if m.name in migrate.V2_MODIFIERS]
    assert not [k for k in st.keys() if k in ("v21", "base_height_kind", "detail_split")]
    assert not [g for g in bpy.data.node_groups if g.name.startswith("RW_P_")]  # v2 groups gone
    assert setup.remove_object(ob) == []  # and Remove is still exact
    assert snapshot.dumps(snapshot.serialize(mat.node_tree)) == want


def test_v21_file_shows_the_convert_banner(v21_file):
    clean, painted = v21_file
    bpy.ops.wm.open_mainfile(filepath=painted)
    assert bpy.ops.realworn.convert_v2(material="Paint") == {"FINISHED"}
    assert bpy.data.materials["Paint"].realworn.schema_version == naming.SCHEMA

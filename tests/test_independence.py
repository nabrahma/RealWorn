"""PRD suite 5: a weathered file opens and renders identically with the add-on NOT installed."""

import os
import subprocess

import bpy

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import damage, decals, masks, weathering

RENDER_EXPR = (
    "import bpy, sys; sc = bpy.context.scene; "
    "assert not hasattr(bpy.types.Scene, 'realworn'), 'add-on must not be loaded'; "
    "sc.render.filepath = sys.argv[-1]; bpy.ops.render.render(write_still=True)"
)


def test_renders_without_addon(empty_scene, out_dir):
    sc = empty_scene
    floor, obs = ms.demo_props(sc)
    for o in [floor] + obs:
        weathering.apply_object(o, sc)
    masks.mark_ground(floor)
    decals.place(sc, "poster_01.png", (0.3, 0.09, 0.6), (0, -1, 0), size=0.5)
    damage.add_damage(bpy.data.objects["BevelCube"], sc, {"Strength": 0.6})
    sc.frame_set(7)
    ru.setup(sc, samples=16, res=(200, 112))
    path = os.path.join(out_dir, "indep.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    with_addon = ru.render(sc, os.path.join(out_dir, "indep_with.png"))
    out_png = os.path.join(out_dir, "indep_without.png")
    if os.path.exists(out_png):
        os.remove(out_png)
    r = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", path,
                        "--python-expr", RENDER_EXPR, "--", out_png], capture_output=True, text=True, timeout=600)
    assert os.path.exists(out_png), r.stdout[-2000:] + r.stderr[-2000:]
    without = ru.load(out_png)
    d = ru.mad(with_addon, without)
    print("\n[independence] with vs without add-on MAD {:.5f}".format(d))
    assert d < 0.002

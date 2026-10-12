"""Render a fixture demo scene weathered in Cycles and EEVEE (headless).

    $BLENDER_BIN --background --factory-startup --python scripts/render_demo.py -- \
        --scene props --out tests/_out/m2 [--res 640] [--samples 32] [--set wetness=0.8 ...] [--clean]
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="props", choices=("props", "alley"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=int, default=640)
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--engines", default="CYCLES,BLENDER_EEVEE")
    ap.add_argument("--set", nargs="*", default=[])
    ap.add_argument("--clean", action="store_true", help="render without RealWorn")
    ap.add_argument("--cam", default="", help="x,y,z camera location override")
    ap.add_argument("--target", default="", help="x,y,z look-at point for --cam")
    ap.add_argument("--lens", type=float, default=0.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    import realworn
    realworn.register()
    from realworn.core import assets
    if assets.asset_stale():
        assets.build_asset_file()
    from fixtures import make_scenes as ms
    from realworn.core import weather, weathering
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    scene = bpy.context.scene
    if a.scene == "props":
        floor, obs = ms.demo_props(scene)
        grounds = [floor]
    else:
        d = ms.demo_alley(scene)
        floor, obs = d["floor"], [d["kerb"]] + d["walls"] + [d["roof"]] + d["crates"]
        grounds = [floor]
    timings = {}
    if not a.clean:
        t = time.perf_counter()
        for o in [floor] + obs:
            weathering.apply_object(o, scene)
        for g in grounds:
            weather.mark_ground(g, scene)
        if a.scene == "alley":
            weather.mark_occluder(d["roof"])
        timings["apply_s"] = time.perf_counter() - t
        for kv in a.set:
            k, v = kv.split("=")
            setattr(scene.realworn, k, type(getattr(scene.realworn, k))(float(v) if v not in ("True", "False") else v == "True"))
    if a.cam:
        from mathutils import Vector
        cam = scene.camera
        cam.location = [float(v) for v in a.cam.split(",")]
        tgt = Vector([float(v) for v in a.target.split(",")]) if a.target else Vector((0, 0, 0))
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        if a.lens:
            cam.data.lens = a.lens
    scene.render.resolution_x = a.res
    scene.render.resolution_y = int(a.res * 0.5625)
    scene.render.image_settings.file_format = "PNG"
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    for eng in a.engines.split(","):
        scene.render.engine = eng
        if eng == "CYCLES":
            scene.cycles.samples = a.samples
            scene.cycles.use_denoising = True
            scene.cycles.device = "CPU"
        else:
            scene.eevee.taa_render_samples = a.samples
        scene.render.filepath = os.path.join(a.out, "{}{}_{}{}.png".format(a.scene, a.tag, eng.lower(), "_clean" if a.clean else ""))
        t = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        timings[eng] = time.perf_counter() - t
    print("[RealWorn] render timings", {k: round(v, 2) for k, v in timings.items()})


main()

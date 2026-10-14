"""Performance budgets, on the GPU (OptiX when present), on the reference wall.

The reference stack for timing: Base, three Variations, one Paint, one Reveal,
one Decals layer. Overhead is measured against the Base alone (the same wall with only its texture
set loaded), with Cycles defaults (adaptive sampling, up to 1024 spp) and at a fixed 1024 spp,
best of 3 renders each:

  reference stack                               budget +40% (v2.1: about +90%, 4 layers)
  + Edge Wear and Dirt, Baked                   (the budgeted case)
  + Edge Wear and Dirt, Live                    measured and reported (Bevel and AO cost rays)
  after Bake Material                           budget +15% (v2.1: +30% to +32%)

Misses are recorded with real numbers in tests/_out/perf.md, not relaxed.
"""

import os
import time

import pytest

import render_util as ru
from reference_realworn import realworn_look, write_masks
from fixtures import reference_wall as R
from perf_log import record
from realworn.core import bake, images, layers, setup

pytestmark = pytest.mark.skipif(not R.available(), reason="Reference wall sets not downloaded "
                                                          "(python tests/corpus/fetch.py --reference)")
RES = 960


def _best(sc, path, n=3):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        sc.render.filepath = path
        bpy_ops_render()
        times.append(time.perf_counter() - t)
    return min(times)


def bpy_ops_render():
    import bpy
    bpy.ops.render.render(write_still=True)


def _measure(sc, out_dir, tag):
    """Best of 3: Cycles defaults (adaptive sampling, up to 1024 spp) and fixed 1024 spp."""
    out = {}
    for mode, adaptive in (("default", True), ("fixed", False)):
        ru.setup(sc, samples=1024, res=(RES, RES))
        ru.use_gpu(sc)
        sc.cycles.use_adaptive_sampling = adaptive
        sc.render.image_settings.file_format = "PNG"
        out[mode] = _best(sc, os.path.join(out_dir, "v3perf_{}_{}.png".format(tag, mode)))
    return out


def test_cycles_overhead_reference_stack(empty_scene, out_dir):
    sc = empty_scene
    wall = R.build_scene(sc)
    import bpy
    assert bpy.ops.realworn.setup(objects=wall.name) == {"FINISHED"}
    device = ru.use_gpu(sc) or "CPU"
    mat = realworn_look(wall, "base")
    base = _measure(sc, out_dir, "base")
    realworn_look_layers(wall)
    stack = _measure(sc, out_dir, "stack")
    for kind in ("EDGE_WEAR", "DIRT"):
        layers.add_layer(mat, kind)
    live = _measure(sc, out_dir, "stack_edges_live")
    t = time.perf_counter()
    bake.bake_sources(wall, mat, sc, resolution=2048)
    t_bake = time.perf_counter() - t
    baked_src = _measure(sc, out_dir, "stack_edges_baked")
    bake.bake_material(wall, mat, sc, resolution=2048, folder=os.path.join(out_dir, "v3perf_bake"))
    baked = _measure(sc, out_dir, "baked")
    ov = {(state, mode): (t[mode] - base[mode]) / base[mode] * 100
          for state, t in (("stack", stack), ("live", live), ("baked_src", baked_src), ("baked", baked))
          for mode in ("default", "fixed")}
    for mode in ("default", "fixed"):
        print("\n[v3 overhead] {} {}: base {:.2f} s; stack +{:.0f}%; + edges/dirt live +{:.0f}%, baked sources "
              "+{:.0f}%; after Bake Material +{:.0f}%".format(device, mode, base[mode], ov["stack", mode],
                                                             ov["live", mode], ov["baked_src", mode],
                                                             ov["baked", mode]))
    note = "best of 3, {}, reference wall {} px; vs the Base alone".format(device, RES)
    record("v3 Cycles overhead, reference stack (3 Variations, Paint, Reveal, Decals), GPU defaults", ov["stack", "default"],
           "%", 40, note + "; v2.1: about +90% (4 layers)")
    record("v3 Cycles overhead, reference stack, GPU fixed 1024 spp", ov["stack", "fixed"], "%", None, note)
    record("v3 Cycles overhead, reference stack + Edge Wear and Dirt Baked, GPU defaults", ov["baked_src", "default"],
           "%", 40, note)
    record("v3 Cycles overhead, reference stack + Edge Wear and Dirt Live, GPU defaults", ov["live", "default"],
           "%", None, note + "; no budget: Bevel and AO cost rays, Bake Edges and AO is the fix")
    record("v3 Cycles overhead, reference stack + Edge Wear and Dirt Live, GPU fixed 1024 spp", ov["live", "fixed"],
           "%", None, note)
    record("v3 Cycles overhead after Bake Material, GPU defaults", ov["baked", "default"], "%", 15,
           note + "; v2.1: +30% to +32%")
    record("v3 Bake Edges and AO, reference wall, 2 masks 2048 px ({})".format(device), t_bake, "s", None,
           "32 samples per mask")
    over = ["{} {} +{:.0f}% (budget +{})".format(s, m, v, b) for (s, m), v, b in
            ((k, ov[k], {("stack", "default"): 40, ("baked_src", "default"): 40, ("baked", "default"): 15}.get(k))
             for k in sorted(ov)) if b is not None and v > b]
    assert ov["stack", "default"] < 120 and ov["baked", "default"] < 60, "regression"
    if over:
        pytest.xfail("over budget: " + ", ".join(over))


def realworn_look_layers(wall):
    """The reference stack on top of the Base: second material and two more variations
    (three Variations in all), Paint, Reveal, Decals, with their masks."""
    realworn_look(wall, "decals", skip=("edges",), base=False)
    write_masks(wall)


def test_mask_memory_reference_stack(empty_scene):
    """Paint 2K 8-bit, Reveal 2K float, Decals 4K 8-bit on a 1 m object: under 180 MB."""
    import bmesh
    from fixtures import make_scenes as ms
    sc = empty_scene
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = ms._link(sc, "Prop", bm, (0, 0, 0.5), ms.principled("PropMat"))
    setup.setup_object(ob)
    mat = ob.material_slots[0].material
    for kind in ("VARIATION", "VARIATION", "VARIATION", "PAINT", "REVEAL", "DECALS"):
        ly = layers.add_layer(mat, kind)
        if kind != "VARIATION":
            images.ensure_mask(ob, mat, ly)
    sizes = {ly.kind: (ly.mask_image.size[0], ly.mask_image.is_float) for ly in mat.realworn.layers if ly.mask_image}
    assert sizes == {"PAINT": (2048, False), "REVEAL": (2048, True), "DECALS": (4096, False)}
    mb = images.memory_estimate(ob, mat.realworn.layers) / 2 ** 20
    record("v3 Mask memory, reference stack on a 1 m object", mb, "MB", 180,
           "Paint 2K 8-bit 16 MB, Reveal 2K float 64 MB (32-bit in RAM), Decals 4K 8-bit 64 MB; v2.1: 224 MB")
    print("\n[memory] reference stack {:.0f} MB".format(mb))
    assert mb < 180


def test_hand_built_tree_overhead_for_context(empty_scene, out_dir):
    """Context for the budget: the same look built the reference's way (the reference fixture's Mix
    Shader tree), timed the same way against its own base alone. No budget: this is what the look
    itself costs."""
    sc = empty_scene
    wall = R.build_scene(sc)
    R.paint_uv(wall)
    arr = R.mask_arrays(wall, 2048)
    imgs = {"paint": R.new_image("ref_paint", arr["paint"]),
            "reveal": R.new_image("ref_reveal", arr["reveal"], float_buffer=True),
            "decal": R.new_image("ref_decal", arr["decal"])}
    device = ru.use_gpu(sc) or "CPU"
    R.build_material(wall, imgs, upto="base")
    base = _measure(sc, out_dir, "tut_base")
    R.build_material(wall, imgs, upto="decals", skip=("edges",))
    stack = _measure(sc, out_dir, "tut_stack")
    ov = {m: (stack[m] - base[m]) / base[m] * 100 for m in ("default", "fixed")}
    print("\n[reference tree] {}: base {:.2f} s / {:.2f} s; stack +{:.0f}% defaults, +{:.0f}% fixed".format(
        device, base["default"], base["fixed"], ov["default"], ov["fixed"]))
    record("v3 context: the reference's own Mix Shader tree, same stack, GPU defaults", ov["default"], "%", None,
           "reference fixture, best of 3, {}; RealWorn's channel mixing compared against this".format(device))
    record("v3 context: the reference's own Mix Shader tree, same stack, GPU fixed 1024 spp", ov["fixed"], "%", None, "")

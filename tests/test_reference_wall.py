"""The reference wall test, one stage per workflow step.

REF-1 tests/fixtures/reference_wall.py builds the reference's wall material with plain nodes.
REF-2 the same look is built here with RealWorn only: Setup, Load Texture, add layers, set
      sliders, and NumPy-written mask and decal images in RealWorn's own images.
REF-3 both render in Cycles (CPU, seed 0, 128 samples, denoise off, 512 px, same camera and
      light). Pass: mean absolute difference under 0.02 and no 32 px block over 0.06. The
      side-by-side and the diff go to tests/_out/reference/<step>/.

The two materials sample the same paint UV layout (the RealWorn object's RW_Paint, copied with the
mesh): Pack Islands may place equal islands in different slots depending on context
(test_core_setup.test_cube_projection_matches_the_reference_fixture), and the masks are defined on
the layout.
"""

import os

import bpy
import numpy as np
import pytest

from reference_realworn import build_pair, realworn_look, write_masks
from fixtures import reference_wall as R
from perf_log import record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "_out", "reference")
MAD_MAX, BLOCK_MAX = 0.02, 0.06

pytestmark = pytest.mark.skipif(not R.available(), reason="Reference wall sets not downloaded "
                                                          "(python tests/corpus/fetch.py --reference)")


def _save_target(px, folder, name):
    os.makedirs(folder, exist_ok=True)
    return R.save_rgb(px, os.path.join(folder, name))


# ------------------------------------------------------------------ target
def test_reference_target(empty_scene, out_dir):
    """REF-4: the reference alone, before any v3 code, defines the target image."""
    sc = empty_scene
    wall = R.build_scene(sc)
    R.paint_uv(wall)
    arr = R.mask_arrays(wall, 2048)
    imgs = {"paint": R.new_image("ref_paint", arr["paint"]),
            "reveal": R.new_image("ref_reveal", arr["reveal"], float_buffer=True),
            "decal": R.new_image("ref_decal", arr["decal"])}
    mat = R.build_material(wall, imgs)
    px = R.render(sc, os.path.join(out_dir, "reference_wall.png"))
    _save_target(px, os.path.join(OUT, "target"), "reference_wall.png")
    # every step of the reference is in the tree
    kinds = {n.bl_idname for n in mat.node_tree.nodes}
    assert {"ShaderNodeBevel", "ShaderNodeAmbientOcclusion", "ShaderNodeHueSaturation", "ShaderNodeValToRGB",
            "ShaderNodeMixShader", "ShaderNodeDisplacement", "ShaderNodeMapRange"} <= kinds
    boxes = [n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.projection == "BOX"]
    assert boxes and all(n.projection_blend == pytest.approx(R.BOX_BLEND) for n in boxes)
    assert mat.displacement_method == "BUMP"
    # and every mask shows somewhere
    for key, a in arr.items():
        cov = float((a[..., 3] if a.ndim == 3 else a).mean())
        print("\n[ref] {} coverage of the layout {:.3f}".format(key, cov))
        assert cov > 0.0005, key  # the drips are thin streaks: 0.1 % of the layout
    assert 0.05 < float(px.mean()) < 0.9


def compare_stage(sc, out_dir, upto, skip=()):
    """REF-3: render both walls, compare, save the side-by-side and the diff to tests/_out/reference."""
    wall, ref, arr = build_pair(sc, upto, skip=skip)
    realworn_look(wall, upto, skip=skip)
    write_masks(wall)
    folder = os.path.join(OUT, upto)
    os.makedirs(folder, exist_ok=True)
    wall.hide_render, ref.hide_render = True, False
    a = R.render(sc, os.path.join(out_dir, "ref_{}.png".format(upto)))
    wall.hide_render, ref.hide_render = False, True
    b = R.render(sc, os.path.join(out_dir, "rw_{}.png".format(upto)))
    mad, block = R.compare(a, b)
    R.save_rgb(np.concatenate([a, b], axis=1), os.path.join(folder, "reference_vs_realworn_{}.png".format(upto)))
    R.save_rgb(R.diff_image(a, b), os.path.join(folder, "diff_{}_x5.png".format(upto)))
    record("Reference wall up to {}: mean abs difference".format(upto), mad, "", MAD_MAX,
           "Cycles CPU 128 spp 512 px; reference Mix Shader tree vs RealWorn")
    record("Reference wall up to {}: worst 32 px block".format(upto), block, "", BLOCK_MAX, "")
    print("\n[REF-3] up to {}: MAD {:.4f} (max {}), worst 32 px block {:.4f} (max {})".format(
        upto, mad, MAD_MAX, block, BLOCK_MAX))
    return mad, block, wall


# ------------------------------------------------------------------ base and variations
def test_base_and_variations(empty_scene, out_dir):
    mad, block, wall = compare_stage(empty_scene, out_dir, "variations")
    mat = wall.material_slots[0].material
    assert [ly.kind for ly in mat.realworn.layers] == ["VARIATION"] * 4
    assert mad < MAD_MAX and block < BLOCK_MAX


# ------------------------------------------------------------------ up to the damage
def test_up_to_damage(empty_scene, out_dir):
    """Reference comparison up to the damage step: base, second material, variations, paint, reveal
    (edge wear comes later)."""
    mad, block, wall = compare_stage(empty_scene, out_dir, "reveal", skip=("edges",))
    mat = wall.material_slots[0].material
    assert [ly.kind for ly in mat.realworn.layers][-2:] == ["PAINT", "REVEAL"]
    assert mad < MAD_MAX and block < BLOCK_MAX


# ------------------------------------------------------------------ up to the decals
def test_up_to_decals(empty_scene, out_dir):
    """Reference comparison up to the decal step (edge wear comes later)."""
    mad, block, wall = compare_stage(empty_scene, out_dir, "decals", skip=("edges",))
    mat = wall.material_slots[0].material
    assert [ly.kind for ly in mat.realworn.layers][-1] == "DECALS"
    assert mad < MAD_MAX and block < BLOCK_MAX


# ------------------------------------------------------------------ the full wall
def test_full_reference(empty_scene, out_dir):
    """The full reference wall: every step of the reference (REF-3 on the whole reference)."""
    mad, block, wall = compare_stage(empty_scene, out_dir, "dirt")
    mat = wall.material_slots[0].material
    assert [ly.kind for ly in mat.realworn.layers] == ["VARIATION"] * 4 + ["PAINT", "EDGE_WEAR", "REVEAL", "DECALS", "DIRT"]
    assert mad < MAD_MAX and block < BLOCK_MAX

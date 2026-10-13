"""The reference wall test (PRD v3 REF-1..REF-4), one stage per milestone.

REF-1 tests/fixtures/reference_wall.py builds the tutorial's wall material with plain nodes.
REF-2 the same look is built here with RealWorn only: Setup, Load Texture, add layers, set
      sliders, and NumPy-written mask and decal images in RealWorn's own images.
REF-3 both render in Cycles (CPU, seed 0, 128 samples, denoise off, 512 px, same camera and
      light). Pass: mean absolute difference under 0.02 and no 32 px block over 0.06. The
      side-by-side and the diff go to docs/milestones/R<n>/.

The two materials sample the same paint UV layout (the RealWorn object's RW_Paint, copied with the
mesh): Pack Islands may place equal islands in different slots depending on context
(test_core_setup.test_cube_projection_matches_the_tutorial_fixture), and the masks are defined on
the layout.
"""

import os

import bpy
import numpy as np
import pytest

from fixtures import reference_wall as R
from perf_log import record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MILESTONES = os.path.join(ROOT, "docs", "milestones")
MAD_MAX, BLOCK_MAX = 0.02, 0.06

pytestmark = pytest.mark.skipif(not R.available(), reason="Reference wall sets not downloaded "
                                                          "(python tests/corpus/fetch.py --reference)")


def _save_target(px, folder, name):
    os.makedirs(folder, exist_ok=True)
    return R.save_rgb(px, os.path.join(folder, name))


# ------------------------------------------------------------------ R0
def test_r0_reference_target(empty_scene, out_dir):
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
    _save_target(px, os.path.join(MILESTONES, "R0"), "reference_wall.png")
    # every step of the tutorial is in the tree
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

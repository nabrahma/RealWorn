"""PRD suite 6: every mask previews the same in Cycles and EEVEE (per-pixel correlation > 0.9)."""

import os

import numpy as np
import pytest

import render_util as ru
from test_m4_weather import yard  # noqa: F401  (fixture)

VIEWS = {
    "oblique": ((6.0, -6.0, 5.0), (0.0, 0.5, 0.5), 9.0),
    "top": ((0.0, 0.0, 8.0), (0.0, 0.0, 0.0), 8.0),
    "under_roof": ((-2.0, -6.0, 1.2), (-2.0, -2.0, 0.0), 5.0),
}
CASES = [("EDGE", "oblique", 0.0), ("CAVITY", "oblique", 0.0), ("CONTACT", "oblique", 0.0),
         ("SHELTER", "under_roof", 0.0), ("PUDDLE", "top", 0.85), ("WETNESS", "under_roof", 0.6),
         ("DUST", "oblique", 0.0), ("GRIME", "oblique", 0.0), ("STREAK", "oblique", 0.0)]


@pytest.mark.parametrize("mode,view,wetness", CASES)
def test_mask_parity(yard, out_dir, mode, view, wetness):  # noqa: F811
    sc = yard["scene"]
    if mode == "CAVITY":  # the yard has no inside corners; add an L-block
        from fixtures import make_scenes as ms
        from realworn.core import weathering
        lb = ms.l_block(sc, location=(0.5, -1.0, 0.0), material=ms.principled("LMat"))
        weathering.apply_object(lb, sc, "concrete")
    sc.realworn.wetness = wetness
    imgs = {}
    for eng in ("CYCLES", "BLENDER_EEVEE"):
        v, cov = ru.preview(sc, mode, os.path.join(out_dir, "parity_{}_{}".format(mode, eng)), *VIEWS[view],
                            res=(128, 128), engine=eng, samples=8)
        imgs[eng] = (v, cov)
    (a, ca), (b, cb) = imgs["CYCLES"], imgs["BLENDER_EEVEE"]
    both = ca & cb
    assert both.mean() > 0.2
    assert a[both].std() > 0.01, "mask is flat in this view, parity would be meaningless"
    c = ru.corr(a[both], b[both])
    print("\n[parity] {:8s} correlation {:.4f}".format(mode, c))
    assert c > 0.9

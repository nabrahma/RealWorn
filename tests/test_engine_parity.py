"""PRD suite 6: every mask previews the same in Cycles and EEVEE (per-pixel correlation > 0.9)."""

import os

import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import masks, weathering

VIEWS = {
    "oblique": ((6.0, -6.0, 5.0), (0.0, 0.5, 0.5), 9.0),
}
CASES = [("EDGE", "oblique"), ("CAVITY", "oblique"), ("CONTACT", "oblique"), ("DUST", "oblique"),
         ("GRIME", "oblique"), ("STREAK", "oblique")]


@pytest.fixture
def yard(empty_scene):
    """Ground slab, a box on it, a tall wall, an L-block (inside corners), a camera."""
    import bmesh
    sc = empty_scene
    ground = ms.street(sc, size=(8.0, 8.0), tiles=8, material=ms.principled("GroundMat", (0.3, 0.3, 0.3)))
    obs = [ground]
    for name, size, loc in (("Box", (1.0, 1.0, 1.0), (-2.0, 0.0, 0.5)), ("Wall", (3.0, 0.3, 3.0), (2.0, 3.0, 1.5))):
        bm = bmesh.new()
        ms._box(bm, size)
        ms._subdivide(bm, 8)
        obs.append(ms._link(sc, name, bm, loc, ms.principled(name + "Mat", (0.5, 0.5, 0.5), roughness=0.8)))
    obs.append(ms.l_block(sc, location=(0.5, -1.0, 0.0), material=ms.principled("LMat")))
    ms.camera_light(sc)
    for o in obs:
        weathering.apply_object(o, sc, "concrete")
    masks.mark_ground(ground)
    sc["rw_dirt"], sc["rw_dust"], sc["rw_age"] = 0.8, 0.8, 0.6
    return sc


@pytest.mark.parametrize("mode,view", CASES)
def test_mask_parity(yard, out_dir, mode, view):
    sc = yard
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

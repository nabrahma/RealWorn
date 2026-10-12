"""PRD suite 7: render snapshots of fixed scenes compared to tests/snapshots/ references.

Cycles, 16 samples, denoise off, 256 px, fixed seed. Run with `-- --update-snapshots` to
regenerate references (the owner reviews changed PNGs before committing them).
"""

import os

import pytest

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import masks, weathering

SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
THRESHOLD = 0.01


def _props(sc):
    floor, obs = ms.demo_props(sc)
    for o in [floor] + obs:
        weathering.apply_object(o, sc)
    masks.mark_ground(floor)
    sc["rw_age"], sc["rw_dirt"] = 0.7, 0.6


@pytest.mark.parametrize("name,build", [("props_dry", _props)])
def test_snapshot(empty_scene, out_dir, name, build):
    build(empty_scene)
    ru.setup(empty_scene, samples=16, res=(256, 144))
    img = ru.render(empty_scene, os.path.join(out_dir, "snap_{}.png".format(name)))
    ref_path = os.path.join(SNAP, name + ".png")
    if os.environ.get("RW_UPDATE_SNAPSHOTS") or not os.path.exists(ref_path):
        os.makedirs(SNAP, exist_ok=True)
        import shutil
        shutil.copyfile(os.path.join(out_dir, "snap_{}.png".format(name)), ref_path)
        pytest.skip("reference written: " + ref_path)
    d = ru.mad(img, ru.load(ref_path))
    print("\n[snapshot] {} MAD vs reference {:.5f}".format(name, d))
    assert d < THRESHOLD

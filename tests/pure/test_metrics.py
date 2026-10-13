"""Unit tests of the edge width metric on synthetic images (PRD v2.1 Q0)."""

import math

import numpy as np
import pytest

from realworn.core import metrics as M


def test_hard_disk_is_sharp():
    assert M.edge_width(M.disk(256, 80)) < 1.5


def test_antialiased_disk_is_sharp():
    w = M.edge_width(M.disk(256, 80, supersample=8))
    assert 0.3 < w < 1.5


def test_boundary_length_of_disk_matches_circumference():
    r = 90
    assert M.boundary_length(M.disk(256, r)) == pytest.approx(2 * math.pi * r, rel=0.05)


@pytest.mark.parametrize("sigma", [1.5, 3.0, 6.0])
def test_gaussian_blurred_disk_matches_analytical_width(sigma):
    img = M.gaussian_blur(M.disk(320, 110, supersample=4), sigma)
    assert M.edge_width(img) == pytest.approx(M.GAUSSIAN_W_PER_SIGMA * sigma, rel=0.08)


def test_width_does_not_depend_on_shape_or_orientation():
    yy, xx = np.mgrid[0:320, 0:320] - 160.0
    a = math.radians(30)
    u, v = xx * math.cos(a) + yy * math.sin(a), -xx * math.sin(a) + yy * math.cos(a)
    square = ((np.abs(u) < 90) & (np.abs(v) < 90)).astype(float)
    w_sq = M.edge_width(M.gaussian_blur(square, 4.0))
    w_disk = M.edge_width(M.gaussian_blur(M.disk(320, 100), 4.0))
    assert w_sq == pytest.approx(w_disk, rel=0.1)


def test_halving_resolution_doubles_width_of_magnified_mask():
    """The effect T1 relies on: a mask magnified 2x more on screen has a 2x wider soft band."""
    small = M.gaussian_blur(M.disk(128, 40), 1.0)
    big = np.kron(small, np.ones((4, 4)))       # 4x magnification (nearest), then blur like bilinear
    big2 = np.kron(M.gaussian_blur(M.disk(256, 80), 1.0), np.ones((2, 2)))
    assert M.edge_width(big) / M.edge_width(big2) == pytest.approx(2.0, rel=0.15)


def test_empty_and_full_images_have_no_width():
    assert M.edge_width(np.zeros((32, 32))) is None
    assert M.edge_width(np.ones((32, 32))) is None


def test_edge_report_fields():
    r = M.edge_report(M.disk(128, 40))
    assert set(r) == {"W", "A", "L", "coverage"}
    assert r["coverage"] == pytest.approx(math.pi * 40 ** 2 / 128 ** 2, rel=0.03)

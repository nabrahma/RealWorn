"""Decals for the Decals layer's Stencil brush (PRD v3 DEC-3, DEC-7). Original CC0 work.

RGBA images (straight alpha, transparent background) in category folders, the way a user's own
decal library is laid out:

  Drips/     drips_01 (grime under a ledge), drips_02 (rust)
  Dirt/      dirt_01 (ground splash), dirt_02 (grime patch)
  Graffiti/  graffiti_01, graffiti_02 (sprayed tags with overspray)
  Stickers/  sticker_01 (a torn paper notice)
  Mold/      mold_01 (green-black growth)
  Cracks/    cracks_01 (dark hairline cracks)

make_all(n) is pure NumPy (tests use it); generate(out_dir) writes 8-bit PNGs through Blender.

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_decals.py
"""

import numpy as np

from .gen_alphas import _polyline, cracks as _crack_shape
from .gen_grunges import value_noise

SIZE = 1024


def _grid(n):
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    return (xs + 0.5) / n, 1.0 - (ys + 0.5) / n  # x right, v up; row 0 is the top of the image


def _rgba(color, alpha, tint=None):
    a = np.clip(alpha, 0.0, 1.0).astype(np.float32)
    out = np.empty(a.shape + (4,), np.float32)
    out[..., :3] = np.asarray(color, np.float32)
    if tint is not None:
        out[..., :3] *= tint[..., None]
    out[..., 3] = a
    return out


def _edges(n, width=0.03):
    x, v = _grid(n)
    d = np.minimum(np.minimum(x, 1 - x), np.minimum(v, 1 - v))
    return np.clip(d / width, 0.0, 1.0)


def drips(rng, n, color, base_band=0.08, count=30):
    x, v = _grid(n)
    top = 1.0 - v  # 0 at the top edge, where the ledge is
    a = base_band * 4 * np.clip(1 - top / base_band, 0, 1) ** 1.5 * 0.6
    cols = np.sort(rng.uniform(0.05, 0.95, count))
    for c in cols:
        length = rng.uniform(0.15, 0.95) ** 1.6
        w = rng.uniform(0.003, 0.012)
        wiggle = 0.004 * np.sin(top * rng.uniform(20, 40) + rng.uniform(0, 6))
        across = np.clip(1 - np.abs(x - c - wiggle) / (w * (1.0 - 0.6 * np.clip(top / length, 0, 1))), 0, 1)
        along = np.clip(1 - top / length, 0, 1) ** 0.5 * (top < length)
        bead = np.exp(-((top - length * 0.97) / 0.012) ** 2) * np.clip(1 - np.abs(x - c) / (w * 1.8), 0, 1)
        a = np.maximum(a, np.maximum(across * along, bead) * rng.uniform(0.6, 0.95))
    tint = 0.8 + 0.4 * value_noise(rng, n, 16, 3)
    return _rgba(color, a * _edges(n, 0.01), tint)


def dirt_splash(rng, n):
    x, v = _grid(n)
    base = np.clip(1 - v / 0.45, 0, 1) ** 1.4  # heaviest at the bottom, where the ground is
    noise = value_noise(rng, n, 10, 5)
    speck = (value_noise(rng, n, 64, 2) > 0.62) * np.clip(1 - v / 0.7, 0, 1)
    a = np.clip(base * (0.4 + 0.9 * noise) + speck * 0.6, 0, 1) * 0.85
    return _rgba((0.16, 0.12, 0.08), a * _edges(n, 0.08), 0.75 + 0.5 * noise)


def grime_patch(rng, n):
    x, v = _grid(n)
    r = np.hypot(x - 0.5, v - 0.5) * 2
    noise = value_noise(rng, n, 6, 6)
    a = np.clip((1 - r) * 1.6 + (noise - 0.5) * 1.4, 0, 1) ** 1.3 * 0.75
    return _rgba((0.09, 0.08, 0.06), a * _edges(n, 0.1), 0.8 + 0.4 * value_noise(rng, n, 24, 3))


def graffiti(rng, n, color):
    a = np.zeros((n, n), np.float32)
    halo = np.zeros((n, n), np.float32)
    x0 = -0.38
    for k in range(5):  # a tag: five letter-like loops and strokes, left to right
        t = np.linspace(0, 1, 18)
        cx = x0 + k * 0.17
        pts = [(cx + 0.06 * np.sin(6.28 * tt * rng.uniform(0.8, 1.6)) + 0.08 * tt,
                0.15 * np.cos(6.28 * tt * rng.uniform(0.6, 1.2)) + rng.uniform(-0.03, 0.03)) for tt in t]
        _polyline(a, pts, [0.012] * (len(pts) - 1), n)
        _polyline(halo, pts, [0.03] * (len(pts) - 1), n)
    underline = [(-0.42 + 0.84 * tt, -0.22 + 0.02 * np.sin(tt * 9)) for tt in np.linspace(0, 1, 12)]
    _polyline(a, underline, [0.008] * 11, n)
    a = np.flipud(a)
    halo = np.flipud(halo)
    spray = value_noise(rng, n, 96, 1)
    out = np.maximum(a * (0.85 + 0.15 * spray), halo * 0.25 * spray)
    return _rgba(color, out, 0.9 + 0.2 * value_noise(rng, n, 8, 2))


def sticker(rng, n):
    x, v = _grid(n)
    img = np.empty((n, n, 4), np.float32)
    img[..., :3] = (0.86, 0.82, 0.7)
    band = (v > 0.72) & (v < 0.86)
    img[band, :3] = (0.7, 0.15, 0.1)
    for i, row in enumerate(np.linspace(0.62, 0.22, 7)):
        width = 0.35 + 0.3 * rng.random()
        line = (np.abs(v - row) < 0.012) & (x > 0.2) & (x < 0.2 + width)
        img[line, :3] = (0.25, 0.22, 0.2)
    tear = value_noise(rng, n, 9, 5)
    inside = np.minimum(np.minimum(x - 0.12, 0.88 - x), np.minimum(v - 0.08, 0.92 - v)) / 0.05
    img[..., 3] = np.clip(inside + (tear - 0.5) * 2.2, 0, 1)
    img[..., :3] *= (0.75 + 0.3 * tear)[..., None]
    return img


def mold(rng, n):
    x, v = _grid(n)
    r = np.hypot(x - 0.5, (v - 0.4) * 1.3) * 2
    cluster = np.clip(1 - r, 0, 1) ** 0.8
    spots = value_noise(rng, n, 48, 3)
    a = np.clip((spots - 0.55 + cluster * 0.45) * 4.0, 0, 1) * cluster
    dark = value_noise(rng, n, 20, 3)
    col = np.dstack([0.05 + 0.08 * dark, 0.08 + 0.12 * dark, 0.04 + 0.04 * dark])
    out = np.empty((n, n, 4), np.float32)
    out[..., :3] = col
    out[..., 3] = a * 0.9
    return out


def cracks(rng, n):
    a = np.flipud(_crack_shape(rng, n))
    return _rgba((0.06, 0.055, 0.05), a * 0.9)


RECIPES = {
    "Drips/drips_01": (lambda rng, n: drips(rng, n, (0.09, 0.07, 0.05)), 21),
    "Drips/drips_02": (lambda rng, n: drips(rng, n, (0.32, 0.12, 0.04), base_band=0.05, count=18), 22),
    "Dirt/dirt_01": (dirt_splash, 23),
    "Dirt/dirt_02": (grime_patch, 24),
    "Graffiti/graffiti_01": (lambda rng, n: graffiti(rng, n, (0.85, 0.12, 0.35)), 25),
    "Graffiti/graffiti_02": (lambda rng, n: graffiti(rng, n, (0.95, 0.85, 0.15)), 26),
    "Stickers/sticker_01": (sticker, 27),
    "Mold/mold_01": (mold, 28),
    "Cracks/cracks_01": (cracks, 29),
}


def make_all(n=SIZE):
    """{"Category/name": (n, n, 4) float32 RGBA, row 0 = top of the image}."""
    return {k: np.clip(fn(np.random.default_rng(seed), n), 0.0, 1.0).astype(np.float32)
            for k, (fn, seed) in RECIPES.items()}


def generate(out_dir, n=SIZE):
    """Write every decal as an 8-bit RGBA PNG in its category folder (needs Blender)."""
    import os

    import bpy
    names = []
    for key, rgba in make_all(n).items():
        path = os.path.join(out_dir, *key.split("/")) + ".png"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = bpy.data.images.new("rw_decal", n, n, alpha=True)
        img.pixels.foreach_set(np.flipud(rgba).ravel())  # Blender rows are bottom-up
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        names.append(key + ".png")
    return names

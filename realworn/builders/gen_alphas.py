"""Damage brush alphas for RW Damage (PRD v3 REV-3, PNT-5). Original CC0 work.

Each alpha is a white-on-black stamp, centred, black at the border (a Texture Mask in View Plane
mapping must not show a square), with near-crisp edges like a hand-made damage alpha:

  chips        one broken-off chip with a ragged outline and a few small satellites
  chips_small  a scatter of small chips (edge wear touch-ups)
  cracks       branching hairline cracks from a point
  scratches    thin near-parallel scratches along X (Rake turns them along the stroke)
  gouges       an elongated gouge along X with a rough rim
  impact       a dent-like crater with short radial cracks

make_all(n) is pure NumPy (tests use it); generate(out_dir) writes 8-bit PNGs through Blender.

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_alphas.py
"""

import numpy as np

from .gen_grunges import value_noise

SIZE = 512


def _grid(n):
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    return (xs + 0.5) / n - 0.5, (ys + 0.5) / n - 0.5


def _soft_step(x, edge, width):
    return np.clip((x - (edge - width)) / (2 * width), 0.0, 1.0)


def _border(n):
    """1 inside, 0 within 4 % of the image border: no square edge on the brush."""
    x, y = _grid(n)
    r = np.maximum(np.abs(x), np.abs(y))
    return 1.0 - _soft_step(r, 0.47, 0.02)


def _blob(x, y, cx, cy, radius, rng, rough=0.25, aa=0.004, aspect=1.0):
    """A ragged blob: a circle whose radius varies with angle (smooth noise on the angle)."""
    dx, dy = (x - cx) / aspect, y - cy
    th = np.arctan2(dy, dx)
    r = np.hypot(dx, dy)
    k = rng.integers(3, 6)
    wobble = sum(rng.uniform(0.3, 1.0) / (i + 1) * np.sin((i + 2) * th + rng.uniform(0, 6.28)) for i in range(k))
    jag = sum(rng.uniform(0.5, 1.0) * np.sin(f * th + rng.uniform(0, 6.28)) / f for f in (11, 17, 23, 31))
    edge = radius * (1.0 + rough * wobble / k * 2.0 + rough * 0.9 * jag)
    return 1.0 - _soft_step(r, edge, aa)


def chips(rng, n):
    x, y = _grid(n)
    a = _blob(x, y, 0.0, 0.0, 0.26, rng, rough=0.35)
    for _ in range(4):
        ang, dist = rng.uniform(0, 6.28), rng.uniform(0.3, 0.4)
        a = np.maximum(a, _blob(x, y, np.cos(ang) * dist, np.sin(ang) * dist, rng.uniform(0.03, 0.06), rng))
    detail = value_noise(rng, n, 24, octaves=3)
    return a * (0.8 + 0.2 * detail)


def chips_small(rng, n):
    x, y = _grid(n)
    a = np.zeros((n, n), np.float32)
    for _ in range(28):
        ang, dist = rng.uniform(0, 6.28), 0.38 * np.sqrt(rng.uniform(0, 1))
        a = np.maximum(a, _blob(x, y, np.cos(ang) * dist, np.sin(ang) * dist, rng.uniform(0.012, 0.035), rng,
                                rough=0.4, aa=0.003))
    return a


def _polyline(a, pts, width, n):
    """Draw an anti-aliased polyline into `a` (coordinates in -0.5..0.5)."""
    x, y = _grid(n)
    for (x0, y0), (x1, y1), w in zip(pts[:-1], pts[1:], width):
        dx, dy = x1 - x0, y1 - y0
        L2 = max(dx * dx + dy * dy, 1e-9)
        t = np.clip(((x - x0) * dx + (y - y0) * dy) / L2, 0, 1)
        d = np.hypot(x - (x0 + t * dx), y - (y0 + t * dy))
        np.maximum(a, 1.0 - _soft_step(d, w, 0.0015), out=a)
    return a


def cracks(rng, n):
    a = np.zeros((n, n), np.float32)

    def walk(x0, y0, ang, length, w, depth):
        pts, widths = [(x0, y0)], []
        steps = 14
        for i in range(steps):
            ang += rng.normal(0, 0.35)
            x0 += np.cos(ang) * length / steps
            y0 += np.sin(ang) * length / steps
            pts.append((x0, y0))
            widths.append(w * (1 - i / steps * 0.7))
            if depth < 2 and rng.random() < 0.18:
                walk(x0, y0, ang + rng.choice((-1, 1)) * rng.uniform(0.5, 1.1), length * 0.5, w * 0.6, depth + 1)
        _polyline(a, pts, widths, n)

    for k in range(4):
        walk(0.0, 0.0, k * 1.57 + rng.uniform(-0.4, 0.4), 0.4, 0.006, 0)
    return a


def scratches(rng, n):
    a = np.zeros((n, n), np.float32)
    for _ in range(22):
        yc = rng.uniform(-0.3, 0.3)
        x0, x1 = rng.uniform(-0.42, -0.1), rng.uniform(0.1, 0.42)
        tilt = rng.normal(0, 0.03)
        pts = [(x0 + (x1 - x0) * t, yc + tilt * (t - 0.5) + rng.normal(0, 0.002)) for t in np.linspace(0, 1, 8)]
        w = rng.uniform(0.0015, 0.0045)
        _polyline(a, pts, [w * (0.5 + 0.5 * np.sin(np.pi * t)) + 0.0008 for t in np.linspace(0, 1, 7)], n)
    return a * (0.6 + 0.4 * value_noise(rng, n, 8, octaves=2))


def gouges(rng, n):
    x, y = _grid(n)
    core = _blob(x, y, 0.0, 0.0, 0.095, rng, rough=0.3, aspect=3.0)
    rim = _blob(x, y, 0.0, 0.0, 0.11, rng, rough=0.45, aspect=3.2)
    return np.maximum(core, rim * 0.55) * (0.75 + 0.25 * value_noise(rng, n, 20, octaves=3))


def impact(rng, n):
    x, y = _grid(n)
    a = _blob(x, y, 0.0, 0.0, 0.16, rng, rough=0.2) * 0.9
    for k in range(9):
        ang = k * 6.28 / 9 + rng.uniform(-0.2, 0.2)
        r1 = rng.uniform(0.25, 0.4)
        pts = [(np.cos(ang + rng.normal(0, 0.05)) * r, np.sin(ang + rng.normal(0, 0.05)) * r)
               for r in np.linspace(0.12, r1, 6)]
        _polyline(a, pts, [0.004 * (1 - i / 6) + 0.001 for i in range(5)], n)
    return a


RECIPES = {"chips": (chips, 11), "chips_small": (chips_small, 12), "cracks": (cracks, 13),
           "scratches": (scratches, 14), "gouges": (gouges, 15), "impact": (impact, 16)}


def make_all(n=SIZE):
    out = {}
    border = _border(n)
    for name, (fn, seed) in RECIPES.items():
        a = fn(np.random.default_rng(seed), n).astype(np.float32)
        out[name] = np.clip(a * border, 0.0, 1.0)
    return out


def generate(out_dir, n=SIZE):
    """Write every alpha as an 8-bit greyscale PNG (needs Blender). Returns the file names."""
    import os

    import bpy
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.data.scenes.new("rw_alpha_save")
    st = scene.render.image_settings
    st.file_format, st.color_mode, st.color_depth, st.compression = "PNG", "BW", "8", 90
    names = []
    for name, arr in make_all(n).items():
        img = bpy.data.images.new("rw_" + name, n, n, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        rgba = np.repeat(arr[..., None], 4, axis=2)
        rgba[..., 3] = 1.0
        img.pixels.foreach_set(np.flipud(rgba).ravel())
        img.save_render(os.path.join(out_dir, name + ".png"), scene=scene)
        bpy.data.images.remove(img)
        names.append(name + ".png")
    bpy.data.scenes.remove(scene)
    return names

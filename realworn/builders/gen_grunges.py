"""Procedural grunge images for the bundled library (GRN-1). Original CC0 work.

Every image is tileable (periodic noise, toroidal distances, wrapped strokes) and greyscale,
white = grunge. generate(out_dir) writes 2048 px 8-bit greyscale PNGs through Blender (v2.1:
4x the v2.0 512 px, same look: pixel-sized parameters scale with the size);
make_all() returns {name: float32 array} and is pure numpy (used by tests).

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_grunges.py
"""

import numpy as np

SIZE = 2048
REF = 512  # the size the recipes were tuned at; pixel-sized parameters scale by SIZE / REF

# SRC-7: suggested real-world size of one tile, in metres (chips are centimetres, stains and
# leaks tens of centimetres). Written next to the images as grunges.json.
SUGGESTED_SIZE = {
    "breakup_fine": 0.12, "breakup_rust": 0.25, "chips_large": 0.4, "chips_small": 0.2, "concrete_pores": 0.3,
    "cracks": 0.6, "dust": 0.5, "edge_scuffs": 0.3, "grime_clouds": 0.6, "leaks": 1.0, "rust_spots": 0.4,
    "scratches_fine": 0.3, "scratches_heavy": 0.5, "smudge": 0.6, "speckle_coarse": 0.3, "speckle_fine": 0.15,
    "spots_fine": 0.2, "spots_large": 0.8, "spots_medium": 0.4, "stain_rings": 0.5, "streaks_drips": 0.8,
    "streaks_vertical": 1.0,
}


# ------------------------------------------------------------------ noises
def value_noise(rng, n, cells, octaves=4, persistence=0.5):
    """Periodic value noise (fBm) on an n x n grid; tiles seamlessly."""
    out = np.zeros((n, n), np.float32)
    amp, total = 1.0, 0.0
    t = np.arange(n, dtype=np.float32) / n
    for o in range(octaves):
        c = cells * 2 ** o
        g = rng.random((c, c)).astype(np.float32)
        p = t * c
        i0 = p.astype(int)
        f = p - i0
        f = f * f * (3 - 2 * f)
        i1 = (i0 + 1) % c
        a, b = g[i0][:, i0], g[i0][:, i1]
        cc, d = g[i1][:, i0], g[i1][:, i1]
        fy, fx = f[:, None], f[None, :]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (cc * (1 - fx) + d * fx) * fy)
        total += amp
        amp *= persistence
    return out / total


def worley(rng, n, count, second=False, warp=None):
    """Toroidal cellular noise: F1 (or F2 - F1 edges) distance, normalised to 0..1. `warp` is an
    optional (dx, dy) pair of periodic offset fields (domain warp for organic shapes)."""
    pts = rng.random((count, 2)).astype(np.float32)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32) / n
    if warp is not None:
        xs = (xs + warp[0]) % 1.0
        ys = (ys + warp[1]) % 1.0
    d1 = np.full((n, n), 9.0, np.float32)
    d2 = np.full((n, n), 9.0, np.float32)
    for px, py in pts:
        dx = np.abs(xs - px)
        dy = np.abs(ys - py)
        dx = np.minimum(dx, 1 - dx)
        dy = np.minimum(dy, 1 - dy)
        d = np.sqrt(dx * dx + dy * dy)
        d2 = np.where(d < d1, d1, np.minimum(d2, d))
        d1 = np.minimum(d1, d)
    out = (d2 - d1) if second else d1
    return out / max(float(out.max()), 1e-6)


def smooth(x, a, b):
    t = np.clip((x - a) / max(b - a, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def blur(img, r=1):
    """Periodic box blur (cheap, wraps)."""
    out = img.copy()
    for _ in range(r):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def strokes(rng, n, count, length, width, angle=None, angle_jitter=np.pi, intensity=(0.6, 1.0)):
    """Wrapped straight strokes (scratches, scuffs, streaks)."""
    img = np.zeros((n, n), np.float32)
    for _ in range(count):
        x0, y0 = rng.random(2) * n
        a = (angle if angle is not None else rng.random() * np.pi) + (rng.random() - 0.5) * angle_jitter
        ln = length * (0.4 + rng.random() * 0.6) * n
        k = max(int(ln), 2)
        t = np.linspace(0, 1, k)
        xs = (x0 + np.cos(a) * ln * t).astype(int) % n
        ys = (y0 + np.sin(a) * ln * t).astype(int) % n
        v = rng.uniform(*intensity)
        for dw in range(-int(width), int(width) + 1):
            img[(ys + dw) % n, xs] = np.maximum(img[(ys + dw) % n, xs], v * (1 - abs(dw) / (width + 1)))
    return img


def dots(rng, n, count, rmin, rmax, soft=0.5):
    """Soft round dots, stamped locally (wrapping), so large sizes stay fast."""
    img = np.zeros((n, n), np.float32)
    for _ in range(count):
        cx, cy = rng.random(2) * n
        r = rng.uniform(rmin, rmax)
        k = int(np.ceil(r)) + 1
        xs = np.arange(int(cx) - k, int(cx) + k + 1)
        ys = np.arange(int(cy) - k, int(cy) + k + 1)
        d = np.sqrt((xs[None, :] + 0.0 - cx) ** 2 + (ys[:, None] + 0.0 - cy) ** 2).astype(np.float32)
        v = 1 - smooth(d, r * (1 - soft), r)
        iy, ix = np.ix_(ys % n, xs % n)
        img[iy, ix] = np.maximum(img[iy, ix], v)
    return img


# --------------------------------------------------------------- grunges
def _spots(rng, n, cells, thr):
    v = value_noise(rng, n, cells, 5)
    return smooth(v, thr, thr + 0.08)


def make_all(n=SIZE, seed=2026):
    rng = np.random.default_rng(seed)
    px = n / float(REF)  # pixel-sized parameters (radii, widths, blur) keep their size per tile
    bl = max(1, int(round(px * px)))  # box-blur passes: variance grows linearly with passes
    g = {}
    g["spots_fine"] = _spots(rng, n, 16, 0.58)
    g["spots_medium"] = _spots(rng, n, 8, 0.6)
    g["spots_large"] = _spots(rng, n, 4, 0.52)
    cell = worley(rng, n, 60)
    g["rust_spots"] = np.clip(smooth(1 - cell, 0.55, 0.85) * smooth(value_noise(rng, n, 6, 4), 0.4, 0.65) * 1.3, 0, 1)
    g["speckle_fine"] = dots(rng, n, 1400, 0.6 * px, 1.6 * px, 0.3)
    g["speckle_coarse"] = dots(rng, n, 260, 1.5 * px, 4.0 * px, 0.4)
    vs = value_noise(rng, n, 4, 4)
    stretch = np.repeat(value_noise(rng, n, 32, 3)[:1], n, 0)  # columns vary, rows constant
    g["streaks_vertical"] = np.clip(smooth(stretch, 0.45, 0.75) * (0.4 + 0.6 * vs), 0, 1)
    drips = np.zeros((n, n), np.float32)
    for _ in range(70):
        x = int(rng.random() * n)
        y0, ln = int(rng.random() * n), int(rng.uniform(0.15, 0.6) * n)
        w = rng.uniform(1.0, 3.5) * px
        ys = (y0 + np.arange(ln)) % n
        fade = np.linspace(1, 0.15, ln)
        for dx in range(-int(w), int(w) + 1):
            drips[ys, (x + dx) % n] = np.maximum(drips[ys, (x + dx) % n], fade * (1 - abs(dx) / (w + 1)))
    g["streaks_drips"] = blur(drips, bl)
    leak_cols = smooth(np.repeat(value_noise(rng, n, 12, 2)[:1], n, 0), 0.5, 0.7)
    yy = np.linspace(0, 1, n)[:, None]
    g["leaks"] = np.clip(leak_cols * (0.5 + 0.5 * np.cos(2 * np.pi * yy)) * (0.6 + 0.4 * value_noise(rng, n, 8, 3)), 0, 1)
    g["scratches_fine"] = strokes(rng, n, 160, 0.25, round(0.5 * (px - 1)), intensity=(0.4, 0.9))
    g["scratches_heavy"] = blur(strokes(rng, n, 40, 0.45, px, angle=0.3, angle_jitter=0.8), bl)
    chip_cell = worley(rng, n, 120)
    chip_mask = smooth(value_noise(rng, n, 8, 4), 0.55, 0.62)
    g["chips_small"] = ((chip_cell < 0.45) * chip_mask).astype(np.float32)
    big_cell = worley(rng, n, 30)
    g["chips_large"] = ((big_cell < 0.5) * smooth(value_noise(rng, n, 4, 5), 0.52, 0.58)).astype(np.float32)
    warp = ((value_noise(rng, n, 6, 4) - 0.5) * 0.06, (value_noise(rng, n, 6, 4) - 0.5) * 0.06)
    edges = worley(rng, n, 40, second=True, warp=warp)
    g["cracks"] = np.clip(1 - smooth(edges, 0.0, 0.03), 0, 1) * smooth(value_noise(rng, n, 4, 3), 0.25, 0.45)
    g["dust"] = np.clip(0.25 + 0.75 * smooth(value_noise(rng, n, 6, 6, 0.6), 0.35, 0.8), 0, 1) * \
        (0.7 + 0.3 * dots(rng, n, 900, 0.5 * px, 1.2 * px, 0.2))
    g["smudge"] = smooth(blur(value_noise(rng, n, 3, 3), 3 * bl), 0.45, 0.7)
    rings = np.zeros((n, n), np.float32)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    for _ in range(14):
        cx, cy = rng.random(2) * n
        r = rng.uniform(0.04, 0.14) * n
        dx = np.abs(xs - cx)
        dy = np.abs(ys - cy)
        d = np.sqrt(np.minimum(dx, n - dx) ** 2 + np.minimum(dy, n - dy) ** 2)
        rings = np.maximum(rings, np.exp(-((d - r) / (2.2 * px)) ** 2) * 0.9 + (d < r) * 0.25)
    g["stain_rings"] = np.clip(rings * (0.7 + 0.3 * value_noise(rng, n, 8, 3)), 0, 1)
    g["edge_scuffs"] = blur(strokes(rng, n, 220, 0.06, px, angle=0.0, angle_jitter=0.25), bl)
    g["concrete_pores"] = dots(rng, n, 700, 0.8 * px, 2.5 * px, 0.25) * 0.9
    g["grime_clouds"] = smooth(value_noise(rng, n, 5, 6, 0.55), 0.42, 0.68)
    # v2.1 breakup maps for Edge Detail: about half white, boundaries at every scale (Erode keeps
    # where the map is light, so a sparse stamp grunge would erase most of a stroke)
    pits = 1.0 - worley(rng, n, 220)
    g["breakup_rust"] = _stretch(0.55 * value_noise(rng, n, 10, 6, 0.6) + 0.45 * smooth(pits, 0.35, 0.95))
    g["breakup_fine"] = _stretch(value_noise(rng, n, 24, 5, 0.55))
    return {k: np.clip(v, 0, 1).astype(np.float32) for k, v in g.items()}


def _stretch(v, lo=2.0, hi=98.0):
    a, b = np.percentile(v, (lo, hi))
    return np.clip((v - a) / max(b - a, 1e-6), 0, 1)


def generate(out_dir, n=SIZE):
    """Write every grunge as an 8-bit greyscale PNG (needs Blender). Returns the file names."""
    import os

    import bpy
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.data.scenes.new("rw_grunge_save")
    st = scene.render.image_settings
    st.file_format = "PNG"
    st.color_mode = "BW"
    st.color_depth = "8"
    st.compression = 90
    names = []
    for name, arr in make_all(n).items():
        img = bpy.data.images.new("rw_" + name, n, n, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        rgba = np.repeat(arr[..., None], 4, axis=2)
        rgba[..., 3] = 1.0
        img.pixels.foreach_set(np.flipud(rgba).ravel())
        path = os.path.join(out_dir, name + ".png")
        img.save_render(path, scene=scene)
        bpy.data.images.remove(img)
        names.append(name + ".png")
    bpy.data.scenes.remove(scene)
    import json
    with open(os.path.join(out_dir, "grunges.json"), "w", encoding="utf-8") as fh:
        json.dump({k + ".png": {"size_m": v} for k, v in sorted(SUGGESTED_SIZE.items())}, fh, indent=1)
    return names

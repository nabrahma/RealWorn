"""Generate the bundled test decals (procedural, so they are original CC0 work).

    $BLENDER_BIN --background --factory-startup --python scripts/make_decals.py

Writes realworn/assets/decals/*.png: colour + alpha, plus one *_nrm.png normal map.
"""

import os

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "realworn", "assets", "decals")
RNG = np.random.default_rng(7)


def value_noise(h, w, cells, octaves=4):
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        c = cells * 2 ** o
        g = RNG.random((c + 1, c + 1)).astype(np.float32)
        ys, xs = np.linspace(0, c, h, endpoint=False), np.linspace(0, c, w, endpoint=False)
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        a, b = g[y0][:, x0], g[y0][:, x0 + 1]
        c_, d = g[y0 + 1][:, x0], g[y0 + 1][:, x0 + 1]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (c_ * (1 - fx) + d * fx) * fy)
        total += amp
        amp *= 0.5
    return out / total


def save(name, rgba, non_color=False):
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())  # Blender rows are bottom-up
    img.filepath_raw = os.path.join(OUT, name + ".png")
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def rgba(color, alpha):
    h, w = alpha.shape
    out = np.empty((h, w, 4), np.float32)
    out[..., :3] = np.asarray(color, np.float32)
    out[..., 3] = np.clip(alpha, 0, 1)
    return out


def leak():
    h, w = 512, 256
    cols = value_noise(1, w, 24, 3)[0]
    length = 0.35 + 0.65 * value_noise(1, w, 9, 2)[0]
    v = np.linspace(0, 1, h)[:, None]  # 0 = top row
    fade = np.clip(1 - v / length[None, :], 0, 1) ** 0.9
    a = np.clip((cols[None, :] - 0.22) * 2.6, 0, 1) * fade
    a = np.maximum(a, 0.55 * np.clip(1 - v / 0.12, 0, 1))  # soaked band right under the edge
    a *= 0.75 + 0.25 * value_noise(h, w, 6, 4)
    edge = np.clip(np.minimum(np.linspace(0, 1, w), np.linspace(1, 0, w)) * 8, 0, 1)
    save("leak_01", rgba((0.10, 0.08, 0.06), a * edge[None, :]))


def stain():
    n = 512
    y, x = np.mgrid[-1:1:n * 1j, -1:1:n * 1j]
    r = np.sqrt(x * x + y * y) + 0.25 * (value_noise(n, n, 4, 3) - 0.5)
    ring = np.exp(-((r - 0.72) / 0.05) ** 2)
    fill = np.clip(1 - r / 0.75, 0, 1) * 0.35
    save("stain_01", rgba((0.18, 0.15, 0.11), np.clip(ring * 0.9 + fill, 0, 1) * (r < 0.85)))


def soot():
    n = 512
    y, x = np.mgrid[-1:1:n * 1j, -1:1:n * 1j]
    r = np.sqrt(x * x + (y * 1.3) ** 2)
    a = np.clip(1 - r, 0, 1) ** 1.2 * (0.5 + 0.7 * value_noise(n, n, 5, 5))
    save("soot_01", rgba((0.02, 0.02, 0.02), a))


def scrape():
    h, w = 256, 512
    a = np.zeros((h, w), np.float32)
    for _ in range(14):
        row = RNG.integers(20, h - 20)
        x0, x1 = sorted(RNG.integers(0, w, 2))
        thick = RNG.uniform(1.0, 3.5)
        yy = np.arange(h)[:, None]
        a[:, x0:x1] = np.maximum(a[:, x0:x1], np.exp(-((yy - row) / thick) ** 2))
    a *= 0.6 + 0.4 * value_noise(h, w, 16, 3)
    save("scrape_01", rgba((0.6, 0.6, 0.6), a))


def bullet():
    n = 256
    y, x = np.mgrid[-1:1:n * 1j, -1:1:n * 1j]
    r = np.sqrt(x * x + y * y)
    ang = np.arctan2(y, x)
    cracks = np.clip(np.cos(ang * 7 + 3 * value_noise(n, n, 3, 2)) ** 40, 0, 1) * np.clip(1 - r, 0, 1)
    hole = (r < 0.18).astype(np.float32)
    rim = np.exp(-((r - 0.25) / 0.08) ** 2)
    save("bullet_01", rgba((0.05, 0.05, 0.05), np.clip(hole + rim * 0.8 + cracks * 0.7, 0, 1)))
    # normal map of a shallow crater (OpenGL convention, tangent space)
    height = np.exp(-(r / 0.35) ** 2)
    gy, gx = np.gradient(height)
    nrm = np.dstack([-gx * 12, -gy * 12, np.ones_like(gx)])
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    out = np.empty((n, n, 4), np.float32)
    out[..., :3] = nrm * 0.5 + 0.5
    out[..., 3] = 1.0
    save("bullet_01_nrm", out, non_color=True)


def poster():
    h, w = 512, 360
    img = np.empty((h, w, 4), np.float32)
    img[..., :3] = (0.75, 0.18, 0.12)
    img[40:120, 30:w - 30, :3] = (0.95, 0.9, 0.75)
    for i, row in enumerate(range(170, 440, 34)):
        img[row:row + 16, 40:40 + int((w - 80) * (0.5 + 0.5 * RNG.random())), :3] = (0.95, 0.92, 0.85)
    tear = value_noise(h, w, 8, 4)
    yy, xx = np.mgrid[0:h, 0:w]
    border = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy)) / 24.0
    img[..., 3] = np.clip(border + (tear - 0.5) * 1.6, 0, 1)
    img[..., :3] *= (0.8 + 0.2 * tear)[..., None]
    save("poster_01", img)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in (leak, stain, soot, scrape, bullet, poster):
        f()
    print("[RealWorn] decals:", sorted(os.listdir(OUT)))

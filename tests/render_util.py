"""Small helpers for render-based tests: deterministic renders and image comparison."""

import os

import bpy
import numpy as np


def setup(scene, engine="CYCLES", samples=16, res=(128, 128), denoise=False):
    scene.render.engine = engine
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    if engine == "CYCLES":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        scene.cycles.device = "CPU"
        scene.cycles.seed = 0
        scene.cycles.use_animated_seed = False
    else:
        scene.eevee.taa_render_samples = samples


def render(scene, path):
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    return load(path)


def load(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[:, :, :3]


def mad(a, b):
    return float(np.abs(a - b).mean())


def corr(a, b):
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 1.0


def look_at(cam, loc, target, ortho_scale=None):
    from mathutils import Vector
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    if ortho_scale:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho_scale


def save_sheet(images, path, cols=None):
    """Tile equally sized RGB arrays (top-left origin rows) into one PNG."""
    cols = cols or len(images)
    rows = (len(images) + cols - 1) // cols
    h, w = images[0].shape[:2]
    sheet = np.ones((rows * h, cols * w, 4), dtype=np.float32)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        y0 = (rows - 1 - r) * h  # Blender images are bottom-up
        sheet[y0:y0 + h, c * w:(c + 1) * w, :3] = im
    out = bpy.data.images.new("rw_sheet", cols * w, rows * h)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = os.path.abspath(path)
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)


def load_rgba(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)

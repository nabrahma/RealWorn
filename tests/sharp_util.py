"""Scenes, synthetic strokes and Mask View renders for the v2.1 sharpness tests (PRD v2.1 Testing).

The close-up of S1/T2: a 30 cm crate, camera 30 cm from its front face, 1920 px wide. Strokes are
written straight into a layer's mask through RW_Paint (painting level 1), as a disk in UV space,
so the same stroke can be rasterised at any mask resolution. Mask View renders to a 32-bit EXR,
so the edge width metric sees linear mask values.
"""

import glob
import math
import os

import bpy
import numpy as np
from mathutils import Vector, interpolate
from mathutils.bvhtree import BVHTree

import render_util as ru
from fixtures import make_scenes as ms
from realworn.core import images, injector, naming, setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "tests", "corpus")


def corpus_material(asset):
    """First material of a Poly Haven corpus .blend, or None when the corpus is missing."""
    paths = glob.glob(os.path.join(CORPUS, asset, "*.blend"))
    if not paths:
        return None
    with bpy.data.libraries.load(paths[0], link=False) as (src, dst):
        dst.materials = list(src.materials)
    return next((m for m in dst.materials if m is not None and m.node_tree is not None), None)


def crate(sc, size=0.3, material=None, cuts=6, name="Crate"):
    """A cube of `size` metres standing on the origin, set up for painting."""
    mat = material or ms.principled(name + "Mat", (0.08, 0.2, 0.38), roughness=0.45)
    ob = ms.sharp_cube(sc, name=name, size=size, cuts=cuts, location=(0, 0, size / 2), material=mat)
    ob.data.uv_layers.new(name="UVMap")
    setup.setup_object(ob)
    return ob, ob.material_slots[0].material


def wall(sc, width=1.0, height=0.6, material=None, name="Wall", cuts=8):
    """A thin wall facing -Y (front at y = 0), set up for painting with its own UV (brick tiling)."""
    import bmesh
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=0.5)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "X"),
                     verts=bm.verts[:])
    bmesh.ops.scale(bm, vec=(width, 1.0, height), verts=bm.verts[:])
    for f in bm.faces:
        for lp in f.loops:
            co = lp.vert.co
            lp[uv].uv = (co.x + 0.5 * width, co.z + 0.5 * height)  # 1 UV unit = 1 m
    ob = ms._link(sc, name, bm, (0, 0, height / 2), material)
    setup.setup_object(ob, use_existing_uv=True)
    return ob, ob.material_slots[0].material


def closeup_camera(sc, target=(0, -0.15, 0.15), dist=0.3, res=(1920, 1080), lens=50.0):
    """Camera `dist` metres in front of `target` (looking along +Y), plus a dark world."""
    cam_data = bpy.data.cameras.new("CloseCam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("CloseCam", cam_data)
    sc.collection.objects.link(cam)
    cam.location = (target[0], target[1] - dist, target[2])
    cam.rotation_euler = (math.pi / 2, 0, 0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    sc.world.color = (0, 0, 0)
    return cam


def metres_per_pixel(sc, dist=0.3):
    cam = sc.camera.data
    return dist * cam.sensor_width / cam.lens / sc.render.resolution_x


# ------------------------------------------------------------------ UV and strokes
def uv_at(obj, world_pt):
    """RW_Paint UV of the surface point nearest `world_pt`."""
    me = obj.data
    bvh = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
    local = obj.matrix_world.inverted() @ Vector(world_pt)
    loc, _, fi, _ = bvh.find_nearest(local)
    poly = me.polygons[fi]
    w = interpolate.poly_3d_calc([me.vertices[v].co for v in poly.vertices], loc)
    uvl = me.uv_layers[naming.UV_PAINT].data
    return sum((Vector(uvl[li].uv) * wi for li, wi in zip(poly.loop_indices, w)), Vector((0, 0)))


def uv_per_metre(obj, point, axis=(1, 0, 0), step=0.02):
    a = uv_at(obj, point)
    b = uv_at(obj, Vector(point) + Vector(axis) * step)
    return (b - a).length / step


def soft_disk(res, center_uv, radius_uv, falloff_uv):
    """Mask values of a disk: 1 inside radius - falloff, smoothstep down to 0 at radius."""
    t = (np.arange(res, dtype=np.float64) + 0.5) / res
    u, v = np.meshgrid(t, t)
    d = np.hypot(u - center_uv[0], v - center_uv[1])
    x = np.clip((radius_uv - d) / max(falloff_uv, 1e-9), 0.0, 1.0)
    return x * x * (3 - 2 * x)


def write_mask(img, values):
    """Paint `values` (res x res, 0..1, rows bottom-up like Blender) into a mask: alpha marks
    'painted', the value channel is white (PNT channel packing: mask = lerp(P, R, A) = A)."""
    res = img.size[0]
    px = np.zeros((res, res, 4), np.float32)
    px[..., 0] = px[..., 1] = px[..., 2] = 1.0
    px[..., 3] = values
    img.pixels.foreach_set(px.ravel())
    img.update()


def paint_layer(obj, mat, layer, values_fn, res=None):
    """Create/resize the layer's mask at `res` (None: texel density) and fill it from
    values_fn(res) -> res x res array."""
    if res is not None:
        layer.mask_res = res
    img = images.ensure_mask(obj, mat, layer)
    if res is not None and tuple(img.size) != (res, res):
        images.resize(img, res)
    write_mask(img, values_fn(img.size[0]))
    return img


# ------------------------------------------------------------------ render
def setup_render(sc, engine="BLENDER_EEVEE", samples=16):
    sc.render.engine = engine
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    if engine == "CYCLES":
        sc.cycles.samples = samples
        sc.cycles.use_denoising = False
        sc.cycles.device = "CPU"
    else:
        sc.eevee.taa_render_samples = samples


def render_mask_view(sc, mat, layer_index, path):
    """Render the layer's Mask View; returns the greyscale float image (rows top-down)."""
    st = mat.realworn
    st.active_layer_index = layer_index
    st.mask_view = True
    injector.set_mask_view(mat, True)
    try:
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = ru.load(path if path.endswith(".exr") else path + ".exr")
    finally:
        st.mask_view = False
        injector.set_mask_view(mat, False)
    return np.flipud(img[..., 0])


def crop(img, frac=0.8):
    h, w = img.shape
    dy, dx = int(h * (1 - frac) / 2), int(w * (1 - frac) / 2)
    return img[dy:h - dy, dx:w - dx]

"""The reference road for the Puddle layer: a night street to judge wet ground on.

  asphalt   the road, 2.4 m wide, with a kerb (vertical faces) and a dashed centre marking
  cobble    a cobblestone strip on the left
  tiles     a raised tiled pavement on the right, at kerb height

Emissive signs at the far end and a street lamp give the water something to reflect; the sky is
a dim night blue. Three framings: WIDE looks along the street from standing height, LOW sits a
hand above the ground for the close-up, and WINDOW looks down at the tiled pavement at about 45
degrees, with a lit shop window standing at the pavement's edge and a small red light on the
right (both shown only in that framing, like a wet sidewalk outside a storefront at night). Texture sets are CC0 Poly Haven sets in the test corpus
(python tests/corpus/fetch.py --road). No RealWorn code is imported here.
"""

import os

import bpy
import mathutils
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "tests", "corpus")

SETS = {"asphalt": "aerial_asphalt_01", "cobble": "cobblestone_floor_04", "tiles": "interior_tiles"}
SET_SCALE = {"asphalt": 2.0, "cobble": 1.5, "tiles": 1.2}  # metres per texture tile
BUMP = 0.02            # metres of height over a height map's 0..1 (midlevel 0.5)
KERB = 0.14            # kerb and pavement height, metres
LENGTH = (-1.0, 10.0)  # the street runs along +Y

FRAMES = {
    "WIDE": dict(location=(0.15, -1.6, 1.55), target=(-0.1, 7.0, 0.0), lens=28.0),
    "LOW": dict(location=(0.35, 0.6, 0.16), target=(-0.15, 5.0, 0.02), lens=22.0),
    "WINDOW": dict(location=(0.0, 4.0, 2.6), target=(2.4, 4.8, KERB), lens=24.0),
}
WINDOW_PROPS = ("Shop_Window", "Red_Light", "Red_Lamp")  # rendered only in the WINDOW framing


def available():
    return all(os.path.isdir(set_folder(k)) for k in SETS)


def set_folder(key):
    return os.path.join(CORPUS, SETS[key], "textures")


def set_maps(key):
    """{color, roughness, height} files of a road set."""
    folder = set_folder(key)
    out = {}
    for f in sorted(os.listdir(folder)):
        low = f.lower()
        if "_diff_" in low:
            out["color"] = os.path.join(folder, f)
        elif "_rough_" in low:
            out["roughness"] = os.path.join(folder, f)
        elif "_disp_" in low:
            out["height"] = os.path.join(folder, f)
    return out


# ------------------------------------------------------------------ geometry
def _grid(name, x0, x1, y0, y1, z, nx, ny):
    """A flat grid mesh (enough vertices for True Depth's adaptive subdivision to start from)."""
    verts, faces = [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append((x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny, z))
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    return verts, faces


def _mesh_object(scene, name, parts):
    verts, faces = [], []
    for pv, pf in parts:
        off = len(verts)
        verts += pv
        faces += [tuple(i + off for i in f) for f in pf]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.data.materials.append(bpy.data.materials.new(name + "_Mat"))
    return ob


def _kerb(x0, x1, y0, y1, h):
    """The kerb: a top and the two vertical faces (road side and pavement side are covered)."""
    verts = [(x0, y0, 0.0), (x0, y1, 0.0), (x0, y0, h), (x0, y1, h), (x1, y0, h), (x1, y1, h)]
    faces = [(0, 2, 3, 1), (2, 4, 5, 3)]  # road-side face (vertical, facing the road), top (facing up)
    return verts, faces


def _emitter(scene, name, verts, color, strength):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    m = bpy.data.materials.new(name + "_Mat")
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1.0)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    me.materials.append(m)
    return ob


def build_scene(scene):
    """Builds the street. Returns {'asphalt': obj, 'cobble': obj, 'tiles': obj}."""
    y0, y1 = LENGTH
    asphalt = _mesh_object(scene, "Road_Asphalt", [_grid("a", -1.2, 1.2, y0, y1, 0.0, 12, 44),
                                                   _kerb(1.2, 1.45, y0, y1, KERB)])
    cobble = _mesh_object(scene, "Road_Cobble", [_grid("c", -3.6, -1.2, y0, y1, 0.0, 12, 44)])
    tiles = _mesh_object(scene, "Road_Tiles", [_grid("t", 1.45, 3.6, y0, y1, KERB, 10, 44)])
    # signs and a lamp to reflect
    for name, x, z, col in (("Sign_Pink", -1.6, 2.4, (1.0, 0.08, 0.5)), ("Sign_Cyan", 1.4, 3.0, (0.05, 0.7, 1.0)),
                            ("Sign_Amber", 3.0, 1.8, (1.0, 0.45, 0.05))):
        me = bpy.data.meshes.new(name)
        me.from_pydata([(-0.7, 0, -0.25), (0.7, 0, -0.25), (0.7, 0, 0.25), (-0.7, 0, 0.25)], [], [(0, 1, 2, 3)])
        ob = bpy.data.objects.new(name, me)
        scene.collection.objects.link(ob)
        ob.location = (x, y1 + 0.5, z)
        m = bpy.data.materials.new(name + "_Mat")
        nt = m.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*col, 1.0)
        em.inputs["Strength"].default_value = 12.0
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        me.materials.append(m)
    lamp_d = bpy.data.lights.new("Street_Lamp", "POINT")
    lamp_d.energy = 450.0
    lamp_d.color = (1.0, 0.78, 0.55)
    lamp_d.shadow_soft_size = 0.15
    lamp = bpy.data.objects.new("Street_Lamp", lamp_d)
    scene.collection.objects.link(lamp)
    lamp.location = (2.2, 4.5, 3.6)
    # the storefront for the WINDOW framing: a lit window at the pavement's edge, a red light
    x = 3.6
    _emitter(scene, "Shop_Window", [(x, 4.0, KERB + 0.05), (x, 7.0, KERB + 0.05), (x, 7.0, 2.3), (x, 4.0, 2.3)],
             (1.0, 0.86, 0.68), 6.0)
    _emitter(scene, "Red_Light", [(x - 0.02, 3.0, 0.35), (x - 0.02, 3.4, 0.35), (x - 0.02, 3.4, 0.75),
                                  (x - 0.02, 3.0, 0.75)], (1.0, 0.04, 0.03), 20.0)
    red = bpy.data.lights.new("Red_Lamp", "POINT")
    red.energy, red.color, red.shadow_soft_size = 25.0, (1.0, 0.05, 0.03), 0.1
    red_ob = bpy.data.objects.new("Red_Lamp", red)
    scene.collection.objects.link(red_ob)
    red_ob.location = (3.3, 3.2, 0.6)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Night")
    if scene.world.node_tree is None:
        scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.03, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    cam = bpy.data.objects.new("Road_Cam", bpy.data.cameras.new("Road_Cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    frame(scene, "WIDE")
    return {"asphalt": asphalt, "cobble": cobble, "tiles": tiles}


def frame(scene, which):
    f = FRAMES[which]
    for name in WINDOW_PROPS:
        ob = scene.objects.get(name)
        if ob is not None:
            ob.hide_render = which != "WINDOW"
    cam = scene.camera
    cam.data.lens = f["lens"]
    cam.data.clip_start = 0.01
    cam.location = f["location"]
    cam.rotation_euler = (mathutils.Vector(f["target"]) - cam.location).to_track_quat("-Z", "Y").to_euler()


# ------------------------------------------------------------------ marking
def marking_rgba(pos):
    """The dashed centre line (white, alpha 1) at surface positions `pos` (n, 3); transparent
    elsewhere."""
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    line = (np.abs(x) < 0.06) & (np.mod(y + 0.3, 3.0) < 1.6) & (z < 0.01)
    rgba = np.zeros((len(pos), 4), np.float32)
    rgba[line] = (0.85, 0.85, 0.8, 1.0)
    return rgba


def height_range(path, step=4):
    """The 2nd / 98th percentiles of a height map's values (every `step`-th pixel), as the puddle
    normalises the ground."""
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    v = px.reshape(h, w, 4)[::step, ::step, 0]
    lo, hi = np.percentile(v.ravel(), [2.0, 98.0])
    return float(lo), float(hi)


def render(scene, path, samples=64, res=(640, 360), device="CPU", seed=0):
    """Cycles, fixed seed, no denoising. Returns display pixels (h, w, 3) of the saved PNG."""
    r = scene.render
    r.engine = "CYCLES"
    scene.cycles.device = device
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.seed = seed
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_depth = "16"
    scene.view_settings.view_transform = "AgX"
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[..., :3]

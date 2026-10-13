"""The reference wall: a weathered building wall material built by hand with plain Blender nodes. No RealWorn code is imported here.

This file defines what "correct" means for RealWorn v3: never change it to
make RealWorn pass. RealWorn rebuilds the same look with its own operators and sliders
(tests/test_v3_reference.py) and the two renders are compared.

The tree, step by step (the tutorial's pipeline in the PRD's default stack order):

  base       Red Plaster Weathered: Object coordinates, Mapping (scale in metres), Image Texture
             with Box projection, Blend 0.3; Displacement node, material set to Bump
  second     Beige Wall over it through a grunge and Color Ramp; Mix Shader, displacement mixed
  variations three copies of the base mixed in by grunge + Color Ramp: washed out (Hue/Saturation
             saturation 0.7), dark patches (value 0.75), and a plain brown BSDF (dirt patches)
  paint      a copy of the base with a hue shift (blue paint), mask = painted image minus a
             grunge (Mix Subtract), then a Color Ramp
  edges      Bevel normal . Geometry normal, Color Ramp; a grunge through Map Range drives the
             Bevel radius; a lighter, less saturated copy of the base shows on worn edges
  reveal     Plaster Gray 04 under a painted damage mask through a Color Ramp; the hole's height is
             the plaster's own height minus 2 mm
  decals     one RGBA image painted with drips: its colour into a Principled, alpha into a Mix
             Shader
  dirt       Ambient Occlusion, Color Ramp, Less Than a grunge through Map Range; plain dark BSDF

Cycles note: a Mix Shader tree of 10 Principled BSDFs reserves 120 closures (12 each), over Cycles'
limit of 64, and Cycles warns. At render time zero-weight branches are skipped, so only points
where many layer edges overlap can lose closures (checked in R0: a fully opaque decal over all
other steps renders). This is the tutorial's method and its known cost; RealWorn mixes channels
into one Principled instead.

Masks and the decal image are written with NumPy as functions of the surface position, through a
paint UV made the tutorial's way (Cube Projection, then Pack Islands).
"""

import os

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "tests", "corpus")
GRUNGES = os.path.join(ROOT, "realworn", "assets", "grunges")
PAINT_UV = "RW_Paint"

STEPS = ("base", "second", "variations", "paint", "edges", "reveal", "decals", "dirt")
SETS = {"base": "red_plaster_weathered", "second": "beige_wall_001", "under": "plaster_grey_04"}
SET_SCALE = 2.0      # metres per texture tile (the tutorial's Value node)
BUMP = 0.02          # Displacement node Scale in metres (height maps are 0..1, midlevel 0.5)
BOX_BLEND = 0.3
CUBE_SIZE = 1.0      # Cube Projection
PACK_MARGIN = 0.004  # Pack Islands

# Every look value is set by hand, as the tutorial does with its sliders and Color Ramps.
# Grunge Color Ramps: white stop at `white`, black stop at `black` (factor 1 where the grunge is dark).
SECOND = dict(grunge="smudge.png", size=1.5, offset=0.0, white=0.03, black=0.13)
VARIATIONS = (
    dict(name="washed_out", grunge="breakup_fine.png", size=0.9, offset=3.1, white=0.18, black=0.32,
         hsv=(0.5, 0.7, 1.0)),
    dict(name="dark_patches", grunge="breakup_rust.png", size=0.8, offset=5.3, white=0.10, black=0.26,
         hsv=(0.5, 1.0, 0.75)),
    dict(name="dirt_patches", grunge="dust.png", size=0.5, offset=7.9, white=0.16, black=0.21,
         color=(0.12, 0.09, 0.06), roughness=0.9),
)
PAINT = dict(hsv=(1.0, 1.1, 0.9), grunge="chips_large.png", size=0.6, offset=1.7, amount=1.0,
             black=0.4, white=0.6)                         # mask: (painted - grunge) through black..white
EDGES = dict(grunge="breakup_fine.png", size=0.3, offset=2.2, radius=(0.002, 0.006),
             white=0.935, black=0.965, hsv=(0.5, 0.8, 1.25))  # Color Ramp on Bevel . Normal
REVEAL = dict(depth=0.002, black=0.45, white=0.55)
DECAL = dict(roughness=0.6)
DIRT = dict(distance=0.2, ao_black=0.5, ao_white=0.95, grunge="dust.png", size=0.5, offset=4.4,
            map_to=(0.55, 0.25), color=(0.1, 0.075, 0.05), roughness=0.9)
AO_SAMPLES = 16
BEVEL_SAMPLES = 8


def available():
    """True when the three Poly Haven sets are in tests/corpus (python tests/corpus/fetch.py --reference)."""
    return all(os.path.isdir(set_folder(k)) for k in SETS)


def set_folder(key):
    return os.path.join(CORPUS, SETS[key], "textures")


def set_maps(key):
    """{color, roughness, height} files of a corpus set."""
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


# ------------------------------------------------------------------ scene
def _box(bm, lo, hi):
    import bmesh
    m = bmesh.ops.create_cube(bm, size=1.0)
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    s = [b - a for a, b in zip(lo, hi)]
    for v in m["verts"]:
        v.co = (v.co.x * s[0] + c[0], v.co.y * s[1] + c[1], v.co.z * s[2] + c[2])


def build_scene(scene, name="Wall"):
    """A building wall with a window sill and a pilaster (edges for wear, corners for dirt), a
    ground plane, a camera, a sun and a grey sky. Returns the wall object."""
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    _box(bm, (-1.5, -0.15, 0.0), (1.5, 0.15, 2.5))   # wall
    _box(bm, (-0.7, -0.27, 0.95), (0.7, -0.15, 1.03))  # sill
    _box(bm, (1.15, -0.23, 0.0), (1.45, -0.15, 2.5))   # pilaster
    bm.to_mesh(me)
    bm.free()
    wall = bpy.data.objects.new(name, me)
    scene.collection.objects.link(wall)
    gme = bpy.data.meshes.new(name + "_Ground")
    gme.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new(name + "_Ground", gme)
    scene.collection.objects.link(ground)
    gm = bpy.data.materials.new(name + "_GroundMat")
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.3, 0.3, 0.3, 1.0)
    gme.materials.append(gm)
    cam_d = bpy.data.cameras.new(name + "_Cam")
    cam_d.lens = 35
    cam = bpy.data.objects.new(name + "_Cam", cam_d)
    scene.collection.objects.link(cam)
    cam.location = (1.15, -3.05, 1.45)
    import mathutils
    cam.rotation_euler = (mathutils.Vector((0.1, 0.0, 1.2)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    sun_d = bpy.data.lights.new(name + "_Sun", "SUN")
    sun_d.energy = 3.0
    sun_d.angle = 0.05
    sun = bpy.data.objects.new(name + "_Sun", sun_d)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.95, 0.0, -0.6)
    if scene.world is None:
        scene.world = bpy.data.worlds.new(name + "_World")
    if scene.world.node_tree is None:
        scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.25, 0.27, 0.3, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    return wall


def _separate_projections(me, uv_name):
    """Faces of different Cube Projection directions share UVs along their common edges, which
    Pack Islands would keep as one overlapping island: move each direction (dominant normal axis
    and sign) apart before packing."""
    n = np.empty(len(me.polygons) * 3, np.float32)
    me.polygons.foreach_get("normal", n)
    n = n.reshape(-1, 3)
    axis = np.abs(n).argmax(axis=1)
    side = (n[np.arange(len(n)), axis] < 0).astype(np.int64)
    total = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", total)
    loop_group = np.repeat(axis * 2 + side, total)
    co = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[uv_name].data.foreach_get("uv", co)
    co = co.reshape(-1, 2)
    co[:, 0] += loop_group * 8.0
    me.uv_layers[uv_name].data.foreach_set("uv", co.ravel())


def paint_uv(obj, name=PAINT_UV):
    """The tutorial's paint UV: Cube Projection, then Pack Islands, into a new UV map (with the
    projection directions moved apart first, so packing never keeps an overlap)."""
    me = obj.data
    me.uv_layers.active = me.uv_layers.new(name=name)
    vl = bpy.context.view_layer
    prev = vl.objects.active
    vl.objects.active = obj
    obj.select_set(True)
    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj],
                                   selected_editable_objects=[obj]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.cube_project(cube_size=CUBE_SIZE, correct_aspect=True)
        bpy.ops.object.mode_set(mode="OBJECT")
        _separate_projections(me, name)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.pack_islands(margin=PACK_MARGIN)
        bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    vl.objects.active = prev
    return me.uv_layers[name]


# ------------------------------------------------------------------ masks
def texel_positions(obj, uv_name, res, dilate=6):
    """Object-space position and face normal of every texel of the UV layout (res x res), plus
    which texels lie inside an island. Positions are pushed `dilate` texels outward into the
    margins so linear filtering at island borders never reads empty texels."""
    me = obj.data
    uv = me.uv_layers[uv_name]
    co = np.empty(len(me.loops) * 2, np.float32)
    uv.data.foreach_get("uv", co)
    co = co.reshape(-1, 2) * res
    vco = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", vco)
    vco = vco.reshape(-1, 3)
    pos = np.zeros((res, res, 3), np.float32)
    nrm = np.zeros((res, res, 3), np.float32)
    cover = np.zeros((res, res), bool)
    for p in me.polygons:
        li = list(p.loop_indices)
        vi = [me.loops[i].vertex_index for i in li]
        n = np.asarray(p.normal, np.float32)
        for k in range(1, len(li) - 1):
            ia, ib, ic = 0, k, k + 1
            a, b, c = co[li[ia]], co[li[ib]], co[li[ic]]
            x0, x1 = int(max(np.floor(min(a[0], b[0], c[0])), 0)), int(min(np.ceil(max(a[0], b[0], c[0])) + 1, res))
            y0, y1 = int(max(np.floor(min(a[1], b[1], c[1])), 0)), int(min(np.ceil(max(a[1], b[1], c[1])) + 1, res))
            if x1 <= x0 or y1 <= y0:
                continue
            ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32) + 0.5
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
            l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
            l3 = 1.0 - l1 - l2
            inside = (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4)
            if not inside.any():
                continue
            P = (l1[..., None] * vco[vi[ia]] + l2[..., None] * vco[vi[ib]] + l3[..., None] * vco[vi[ic]])
            sub_pos = pos[y0:y1, x0:x1]
            sub_n = nrm[y0:y1, x0:x1]
            sub_c = cover[y0:y1, x0:x1]
            sub_pos[inside] = P[inside]
            sub_n[inside] = n
            sub_c[inside] = True
    filled = cover.copy()
    for _ in range(dilate):
        if filled.all():
            break
        acc_p = np.zeros_like(pos)
        acc_n = np.zeros_like(nrm)
        cnt = np.zeros((res, res), np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            f = np.roll(np.roll(filled, dy, 0), dx, 1)
            acc_p += np.roll(np.roll(pos, dy, 0), dx, 1) * f[..., None]
            acc_n += np.roll(np.roll(nrm, dy, 0), dx, 1) * f[..., None]
            cnt += f
        grow = (~filled) & (cnt > 0)
        pos[grow] = acc_p[grow] / cnt[grow][..., None]
        nrm[grow] = acc_n[grow] / cnt[grow][..., None]
        filled |= grow
    return pos, nrm, cover


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def paint_mask(pos, nrm):
    """Blue paint on the lower wall: a soft, slightly wavy top edge (a big soft brush)."""
    x, z = pos[..., 0], pos[..., 2]
    top = 1.25 + 0.05 * np.sin(2.1 * x) + 0.02 * np.sin(7.3 * x)
    return 1.0 - _smoothstep(top - 0.04, top + 0.04, z)


def reveal_mask(pos, nrm):
    """Damage patches on the front face, irregular outlines (a damage brush)."""
    x, z = pos[..., 0], pos[..., 2]
    front = nrm[..., 1] < -0.5
    out = np.zeros(x.shape, np.float32)
    for cx, cz, r in ((-0.9, 0.55, 0.18), (0.35, 1.6, 0.13), (0.85, 0.32, 0.22), (-0.2, 2.1, 0.1)):
        dx, dz = x - cx, z - cz
        th = np.arctan2(dz, dx)
        rr = r * (1.0 + 0.12 * np.sin(3 * th + cx * 3) + 0.08 * np.sin(5 * th + cz * 7)
                  + 0.05 * np.sin(11 * th + cx) + 0.03 * np.sin(19 * th + cz))
        out = np.maximum(out, 1.0 - _smoothstep(rr - 0.015, rr + 0.015, np.hypot(dx, dz)))
    return np.where(front, out, 0.0).astype(np.float32)


def decal_rgba(pos, nrm):
    """Drips under the sill on the wall face: dark streaks with soft ends (stencil-painted)."""
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    on_face = (nrm[..., 1] < -0.5) & (y > -0.16) & (np.abs(x) < 0.66) & (z < 0.95)
    step = 0.045
    col = np.floor((x + 0.7) / step)
    h = np.abs(np.modf(np.sin(col * 12.9898) * 43758.5453)[0])
    h2 = np.abs(np.modf(np.sin(col * 78.233) * 12345.678)[0])
    length = np.where(h > 0.35, 0.05 + 0.45 * h2 * h2, 0.0)
    centre = (col + 0.5) * step - 0.7 + (h2 - 0.5) * 0.02
    width = (0.003 + 0.006 * h) * (0.6 + 0.4 * _smoothstep(0.95 - length, 0.95, z))  # thinner towards the end
    across = 1.0 - _smoothstep(width * 0.5, width, np.abs(x - centre))
    along = _smoothstep(0.95 - length, 0.95 - length * 0.6, z)
    stain = 0.25 * (1.0 - _smoothstep(0.0, 0.05, 0.95 - z)) * (np.abs(x) < 0.62)  # a band right under the sill
    a = np.where(on_face, np.maximum(across * along * (0.55 + 0.35 * h2), stain), 0.0).astype(np.float32)
    rgba = np.zeros(x.shape + (4,), np.float32)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 0.09, 0.07, 0.05
    rgba[..., 3] = a
    return rgba


def mask_arrays(obj, res, uv_name=PAINT_UV):
    """{'paint', 'reveal', 'decal'} for a layout at `res` px."""
    pos, nrm, _ = texel_positions(obj, uv_name, res)
    return {"paint": paint_mask(pos, nrm), "reveal": reveal_mask(pos, nrm), "decal": decal_rgba(pos, nrm)}


def write_image(img, arr):
    """A (res, res) mask (grey, alpha 1) or (res, res, 4) RGBA array into an image's pixels."""
    if arr.ndim == 2:
        rgba = np.empty(arr.shape + (4,), np.float32)
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = arr
        rgba[..., 3] = 1.0
    else:
        rgba = arr
    img.pixels.foreach_set(np.ascontiguousarray(rgba, np.float32).ravel())
    img.update()
    return img


def new_image(name, arr, float_buffer=False):
    res = arr.shape[0]
    img = bpy.data.images.new(name, res, res, alpha=True, float_buffer=float_buffer)
    img.colorspace_settings.name = "Non-Color" if arr.ndim == 2 else "sRGB"
    img.alpha_mode = "CHANNEL_PACKED"
    return write_image(img, arr)


# ------------------------------------------------------------------ material
class _T:
    def __init__(self, tree):
        self.t = tree
        self.n = tree.nodes
        self.l = tree.links
        self.x = 0

    def node(self, idname, **inputs):
        nd = self.n.new(idname)
        nd.location = (self.x, -len(self.n) * 25)
        for k, v in inputs.items():
            self.set(nd.inputs[k.replace("_", " ")], v)
        return nd

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.l.new(v, sock)
        else:
            if sock.type == "RGBA" and len(v) == 3:
                v = (*v, 1.0)
            sock.default_value = v

    def ramp(self, value, stops):
        """Color Ramp with [(position, grey)] stops."""
        r = self.node("ShaderNodeValToRGB")
        els = r.color_ramp.elements
        (p0, g0), (p1, g1) = stops
        els[0].position, els[0].color = p0, (g0, g0, g0, 1.0)
        els[1].position, els[1].color = p1, (g1, g1, g1, 1.0)
        self.set(r.inputs["Fac"], value)
        return r.outputs["Color"]


def _box_vector(T, size, offset=0.0):
    tc = T.node("ShaderNodeTexCoord")
    mp = T.node("ShaderNodeMapping")
    s = 1.0 / size
    mp.inputs["Scale"].default_value = (s, s, s)
    mp.inputs["Location"].default_value = (offset, offset * 0.7, offset * 0.3)
    T.l.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _image(T, path, vector, non_color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    n = T.node("ShaderNodeTexImage")
    n.image = img
    n.projection = "BOX"
    n.projection_blend = BOX_BLEND
    T.l.new(vector, n.inputs["Vector"])
    return n


def _texture_set(T, key):
    """A box-mapped set: {'color', 'roughness', 'height'} sockets."""
    maps = set_maps(key)
    vec = _box_vector(T, SET_SCALE)
    return {"color": _image(T, maps["color"], vec, False).outputs["Color"],
            "roughness": _image(T, maps["roughness"], vec, True).outputs["Color"],
            "height": _image(T, maps["height"], vec, True).outputs["Color"]}


def _grunge(T, name, size, offset):
    return _image(T, os.path.join(GRUNGES, name), _box_vector(T, size, offset), True).outputs["Color"]


def _hsv(T, color, hsv):
    n = T.node("ShaderNodeHueSaturation", Hue=hsv[0], Saturation=hsv[1], Value=hsv[2], Color=color)
    return n.outputs["Color"]


def _bsdf(T, color, roughness):
    return T.node("ShaderNodeBsdfPrincipled", Base_Color=color, Roughness=roughness).outputs["BSDF"]


def _mix(T, fac, a, b):
    n = T.n.new("ShaderNodeMixShader")
    T.set(n.inputs[0], fac)
    T.l.new(a, n.inputs[1])
    T.l.new(b, n.inputs[2])
    return n.outputs[0]


def _mix_float(T, fac, a, b):
    n = T.n.new("ShaderNodeMix")
    n.data_type = "FLOAT"
    T.set(n.inputs["Factor"], fac)
    ins = {s.identifier: s for s in n.inputs}
    T.set(ins["A_Float"], a)
    T.set(ins["B_Float"], b)
    return next(s for s in n.outputs if s.identifier == "Result_Float")


def build_material(obj, images=None, upto="dirt"):
    """The reference material on `obj`, built up to and including step `upto` (STEPS).
    `images`: {'paint', 'reveal', 'decal'} bpy images (sampled through the paint UV)."""
    last = STEPS.index(upto)
    on = lambda step: STEPS.index(step) <= last  # noqa: E731
    mat = bpy.data.materials.new("Reference_Wall")
    mat.displacement_method = "BUMP"
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    T = _T(nt)
    out = T.node("ShaderNodeOutputMaterial")
    base = _texture_set(T, "base")
    shader = _bsdf(T, base["color"], base["roughness"])
    height = base["height"]
    uv = None
    if images:
        uvn = T.node("ShaderNodeUVMap")
        uvn.uv_map = PAINT_UV
        uv = uvn.outputs["UV"]

    def painted(key):
        n = T.node("ShaderNodeTexImage")
        n.image = images[key]
        T.l.new(uv, n.inputs["Vector"])
        return n

    if on("second"):
        sec = _texture_set(T, "second")
        g = _grunge(T, SECOND["grunge"], SECOND["size"], SECOND["offset"])
        f = T.ramp(g, ((SECOND["white"], 1.0), (SECOND["black"], 0.0)))
        shader = _mix(T, f, shader, _bsdf(T, sec["color"], sec["roughness"]))
        height = _mix_float(T, f, height, sec["height"])
    if on("variations"):
        for v in VARIATIONS:
            g = _grunge(T, v["grunge"], v["size"], v["offset"])
            f = T.ramp(g, ((v["white"], 1.0), (v["black"], 0.0)))
            if "hsv" in v:
                b = _bsdf(T, _hsv(T, base["color"], v["hsv"]), base["roughness"])
            else:
                b = _bsdf(T, v["color"], v["roughness"])
            shader = _mix(T, f, shader, b)
    if on("paint"):
        g = _grunge(T, PAINT["grunge"], PAINT["size"], PAINT["offset"])
        sub = T.n.new("ShaderNodeMix")
        sub.data_type, sub.blend_type, sub.clamp_result = "RGBA", "SUBTRACT", False
        ins = {s.identifier: s for s in sub.inputs}
        T.set(ins["Factor_Float"], PAINT["amount"])
        T.l.new(painted("paint").outputs["Color"], ins["A_Color"])
        T.l.new(g, ins["B_Color"])
        res = next(s for s in sub.outputs if s.identifier == "Result_Color")
        f = T.ramp(res, ((PAINT["black"], 0.0), (PAINT["white"], 1.0)))
        shader = _mix(T, f, shader, _bsdf(T, _hsv(T, base["color"], PAINT["hsv"]), base["roughness"]))
    if on("edges"):
        g = _grunge(T, EDGES["grunge"], EDGES["size"], EDGES["offset"])
        lo, hi = EDGES["radius"]
        radius = T.node("ShaderNodeMapRange", Value=g)
        radius.inputs[3].default_value, radius.inputs[4].default_value = lo, hi
        bevel = T.node("ShaderNodeBevel", Radius=radius.outputs["Result"])
        bevel.samples = BEVEL_SAMPLES
        geo = T.node("ShaderNodeNewGeometry")
        dot = T.n.new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        T.l.new(bevel.outputs["Normal"], dot.inputs[0])
        T.l.new(geo.outputs["Normal"], dot.inputs[1])
        f = T.ramp(dot.outputs["Value"], ((EDGES["white"], 1.0), (EDGES["black"], 0.0)))
        shader = _mix(T, f, shader, _bsdf(T, _hsv(T, base["color"], EDGES["hsv"]), base["roughness"]))
    if on("reveal"):
        under = _texture_set(T, "under")
        f = T.ramp(painted("reveal").outputs["Color"], ((REVEAL["black"], 0.0), (REVEAL["white"], 1.0)))
        shader = _mix(T, f, shader, _bsdf(T, under["color"], under["roughness"]))
        hole = T.n.new("ShaderNodeMath")
        hole.operation = "SUBTRACT"
        T.l.new(under["height"], hole.inputs[0])
        hole.inputs[1].default_value = REVEAL["depth"] / BUMP
        height = _mix_float(T, f, height, hole.outputs[0])
    if on("decals"):
        img = painted("decal")
        shader = _mix(T, img.outputs["Alpha"], shader, _bsdf(T, img.outputs["Color"], DECAL["roughness"]))
    if on("dirt"):
        ao = T.node("ShaderNodeAmbientOcclusion", Distance=DIRT["distance"])
        ao.samples = AO_SAMPLES
        x = T.ramp(ao.outputs["AO"], ((DIRT["ao_black"], 0.0), (DIRT["ao_white"], 1.0)))
        g = _grunge(T, DIRT["grunge"], DIRT["size"], DIRT["offset"])
        mr = T.node("ShaderNodeMapRange", Value=g)
        mr.inputs[3].default_value, mr.inputs[4].default_value = DIRT["map_to"]
        sep = T.node("ShaderNodeSeparateColor", Color=x)
        less = T.n.new("ShaderNodeMath")
        less.operation = "LESS_THAN"
        T.l.new(sep.outputs[0], less.inputs[0])
        T.l.new(mr.outputs["Result"], less.inputs[1])
        shader = _mix(T, less.outputs[0], shader, _bsdf(T, DIRT["color"], DIRT["roughness"]))
    disp = T.node("ShaderNodeDisplacement", Height=height, Midlevel=0.5, Scale=BUMP)
    T.l.new(shader, out.inputs["Surface"])
    T.l.new(disp.outputs[0], out.inputs["Displacement"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat


# ------------------------------------------------------------------ render
def render(scene, path, samples=128, res=512, device="CPU"):
    """REF-3: Cycles, fixed seed, `samples`, denoise off, `res` px square. Returns linear-display
    pixels (h, w, 3) of the saved 16-bit PNG."""
    r = scene.render
    r.engine = "CYCLES"
    scene.cycles.device = device
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.seed = 0
    r.resolution_x = r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_depth = "16"
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[..., :3]


def compare(a, b, block=32):
    """REF-3 numbers: mean absolute difference, and the worst 32 x 32 px block's mean difference."""
    d = np.abs(a.astype(np.float32) - b.astype(np.float32)).mean(axis=2)
    h, w = d.shape
    blocks = d[:h - h % block, :w - w % block].reshape(h // block, block, w // block, block).mean(axis=(1, 3))
    return float(d.mean()), float(blocks.max())


def diff_image(a, b, gain=5.0):
    """A visual of |a - b| x gain (grey)."""
    d = np.clip(np.abs(a - b).mean(axis=2) * gain, 0.0, 1.0)
    return np.dstack([d, d, d])


def save_rgb(arr, path):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("rw_tmp_save", w, h, alpha=False)
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = arr
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path

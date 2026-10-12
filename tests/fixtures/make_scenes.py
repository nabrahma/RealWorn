"""Builds every test fixture from code (PRD Testing > Test fixtures).

Functions return objects linked into the given scene. Running this file saves the
demo scenes to tests/fixtures/scenes/*.blend:

    $BLENDER_BIN --background --factory-startup --python tests/fixtures/make_scenes.py
"""

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = os.path.join(HERE, "scenes")


# --------------------------------------------------------------------- helpers
def _link(scene, name, bm, location=(0, 0, 0), material=None):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    scene.collection.objects.link(ob)
    if material is not None:
        me.materials.append(material)
    return ob


def _box(bm, size, center=(0, 0, 0)):
    geom = bmesh.ops.create_cube(bm, size=1.0)
    verts = geom["verts"]
    bmesh.ops.scale(bm, vec=size, verts=verts)
    bmesh.ops.translate(bm, vec=center, verts=verts)
    return verts


def _subdivide(bm, cuts):
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)


def principled(name, color=(0.6, 0.6, 0.6), metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


# -------------------------------------------------------------------- meshes
def lowpoly_cube(scene, name="LowPolyCube", size=2.0, location=(0, 0, 1), material=None):
    """6 faces, 8 vertices: needs pre-subdivide to hold an edge band."""
    bm = bmesh.new()
    _box(bm, (size, size, size))
    return _link(scene, name, bm, location, material)


def sharp_cube(scene, name="SharpCube", size=2.0, cuts=15, location=(0, 0, 1), material=None):
    """Dense cube with sharp 90 degree edges."""
    bm = bmesh.new()
    _box(bm, (size, size, size))
    _subdivide(bm, cuts)
    return _link(scene, name, bm, location, material)


def bevel_cube(scene, name="BevelCube", size=2.0, bevel=0.04, segments=3, cuts=12, location=(0, 0, 1), material=None):
    """Cube with rounded edges, the common production case."""
    bm = bmesh.new()
    _box(bm, (size, size, size))
    _subdivide(bm, cuts)
    bmesh.ops.bevel(bm, geom=[e for e in bm.edges if not e.is_contiguous or e.calc_face_angle(0) > 1.0],
                    offset=bevel, segments=segments, profile=0.5, affect="EDGES")
    return _link(scene, name, bm, location, material)


def l_block(scene, name="LBlock", cuts=12, location=(0, 0, 0), material=None):
    """L-shaped prism: one concave (inside corner) edge plus convex edges."""
    bm = bmesh.new()
    # profile built from three quads (no n-gon caps; see M1 notes on n-gons)
    grid = {(x, z): bm.verts.new((x, 0.0, z)) for x in (0, 1, 2) for z in (0, 1, 2) if not (x == 2 and z == 2)}
    quads = [((0, 0), (1, 0), (1, 1), (0, 1)), ((1, 0), (2, 0), (2, 1), (1, 1)), ((0, 1), (1, 1), (1, 2), (0, 2))]
    faces = [bm.faces.new([grid[k] for k in q]) for q in quads]
    ext = bmesh.ops.extrude_face_region(bm, geom=faces)
    bmesh.ops.translate(bm, vec=(0, 2, 0), verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    # triangulate-free grid density on the long faces
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    return _link(scene, name, bm, location, material)


def crate(scene, name="Crate", size=1.0, location=(0, 0, 0.5), material=None):
    """Bevelled box with recessed panels (convex rim, concave grooves)."""
    bm = bmesh.new()
    _box(bm, (size, size, size))
    _subdivide(bm, 2)
    faces = [f for f in bm.faces]
    res = bmesh.ops.inset_individual(bm, faces=[f for f in faces if abs(f.normal.z) < 0.5 or f.normal.z > 0.5],
                                     thickness=0.06 * size, depth=-0.02 * size)
    bmesh.ops.bevel(bm, geom=[e for e in bm.edges if e.calc_face_angle(0) > 1.2], offset=0.008 * size,
                    segments=2, affect="EDGES")
    _subdivide(bm, 1)
    return _link(scene, name, bm, location, material)


def pipe(scene, name="Pipe", radius=0.15, length=2.0, location=(0, 0, 0.3), material=None):
    """Horizontal pipe with two flanges."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=radius, radius2=radius, depth=length)
    for x in (-length * 0.35, length * 0.35):
        g = bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=radius * 1.5, radius2=radius * 1.5,
                                  depth=0.06)
        bmesh.ops.translate(bm, vec=(0, 0, x), verts=g["verts"])
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"), verts=bm.verts[:])
    return _link(scene, name, bm, location, material)


def wall_with_window(scene, name="Wall", width=4.0, height=3.0, thick=0.25, location=(0, 0, 0), material=None):
    """Wall with a window opening and a protruding sill (overhang for leaks)."""
    bm = bmesh.new()
    wx0, wx1, wz0, wz1 = -0.6, 0.6, 1.0, 2.2
    hw = width / 2
    for (x0, x1, z0, z1) in ((-hw, wx0, 0, height), (wx1, hw, 0, height), (wx0, wx1, 0, wz0), (wx0, wx1, wz1, height)):
        _box(bm, (x1 - x0, thick, z1 - z0), ((x0 + x1) / 2, 0, (z0 + z1) / 2))
    _box(bm, (wx1 - wx0 + 0.3, thick + 0.18, 0.08), (0, -0.09, wz0 - 0.04))  # sill
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
    _subdivide(bm, 4)
    return _link(scene, name, bm, location, material)


def street(scene, name="Street", size=(6.0, 4.0), tiles=8, location=(0, 0, 0), material=None):
    """Flat ground slab with shallow grout grooves between tiles."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=tiles * 4, y_segments=int(tiles * 4 * size[1] / size[0]), size=0.5)
    bmesh.ops.scale(bm, vec=(size[0], size[1], 1), verts=bm.verts[:])
    step_x = size[0] / tiles
    for v in bm.verts:
        gx = abs(((v.co.x + size[0] / 2) / step_x) % 1.0 - 0.5)
        gy = abs(((v.co.y + size[1] / 2) / step_x) % 1.0 - 0.5)
        if gx > 0.45 or gy > 0.45:
            v.co.z -= 0.01
    ob = _link(scene, name, bm, location, material)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def kerb(scene, name="Kerb", length=6.0, location=(0, 1.8, 0.075), material=None):
    bm = bmesh.new()
    _box(bm, (length, 0.3, 0.15))
    _subdivide(bm, 6)
    return _link(scene, name, bm, location, material)


def roof(scene, name="Roof", size=(3.0, 2.0, 0.15), location=(0, 0, 3.0), material=None):
    bm = bmesh.new()
    _box(bm, size)
    return _link(scene, name, bm, location, material)


def dense_sphere(scene, name="DenseSphere", verts_target=100_000, location=(0, 0, 1)):
    """UV sphere with about `verts_target` vertices for the performance budget."""
    seg = int(math.sqrt(verts_target * 2))
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=seg // 2, radius=1.0)
    return _link(scene, name, bm, location)


def camera_light(scene, cam_loc=(5.5, -6.0, 3.2), target=(0, 0, 0.8), lens=35):
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = lens
    cam.location = cam_loc
    direction = Vector(target) - Vector(cam_loc)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("World") if scene.world is None else scene.world
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.25, 0.28, 0.32, 1.0)
        bg.inputs["Strength"].default_value = 0.8
    return cam


# --------------------------------------------------------------------- scenes
def demo_props(scene):
    """M1-M3 demo: crate, painted cube, pipe, L-block on a floor, with camera."""
    floor = street(scene, material=principled("Floor_Concrete", (0.42, 0.41, 0.4), roughness=0.8))
    obs = [
        crate(scene, material=principled("Crate_Paint", (0.12, 0.3, 0.16), roughness=0.45), location=(-1.4, 0.3, 0.5)),
        bevel_cube(scene, size=1.0, bevel=0.03, cuts=8, location=(0.3, 0.6, 0.5),
                   material=principled("Steel_Blue", (0.08, 0.16, 0.35), roughness=0.35)),
        pipe(scene, location=(0.6, -1.0, 0.25), material=principled("Pipe_Metal", (0.6, 0.6, 0.62), metallic=1.0, roughness=0.3)),
        l_block(scene, location=(1.6, 0.0, 0.0), material=principled("Block_Concrete", (0.55, 0.53, 0.5), roughness=0.85)),
    ]
    camera_light(scene, cam_loc=(4.5, -5.2, 3.0), target=(0.2, 0.0, 0.4))
    return floor, obs


def demo_alley(scene):
    """M4+ demo: street, kerb, two walls with windows, a roof overhang, crates."""
    floor = street(scene, size=(8.0, 6.0), tiles=10, material=principled("Asphalt", (0.09, 0.09, 0.09), roughness=0.75))
    k = kerb(scene, length=8.0, location=(0, 1.3, 0.075), material=principled("Kerb_Concrete", (0.5, 0.5, 0.48), roughness=0.85))
    w1 = wall_with_window(scene, name="WallBack", width=8.0, location=(0, 2.6, 0),
                          material=principled("Brick_Plaster", (0.55, 0.38, 0.3), roughness=0.85))
    w2 = wall_with_window(scene, name="WallSide", width=6.0, location=(-3.9, 0, 0),
                          material=principled("Plaster_Grey", (0.6, 0.6, 0.58), roughness=0.9))
    w2.rotation_euler = (0, 0, math.pi / 2)
    rf = roof(scene, name="Awning", size=(2.4, 1.4, 0.1), location=(2.2, 1.9, 2.6),
              material=principled("Awning_Metal", (0.3, 0.05, 0.05), metallic=0.6, roughness=0.4))
    crates = [crate(scene, name="Crate.%d" % i, location=(1.2 + i * 1.1, 1.9, 0.5),
                    material=principled("Crate_Wood_%d" % i, (0.35, 0.22, 0.12), roughness=0.7)) for i in range(2)]
    camera_light(scene, cam_loc=(3.5, -5.0, 1.6), target=(0.0, 1.5, 0.9), lens=28)
    return dict(floor=floor, kerb=k, walls=[w1, w2], roof=rf, crates=crates)


def save_demo(builder, filename):
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    scene = bpy.context.scene
    builder(scene)
    os.makedirs(SCENES, exist_ok=True)
    path = os.path.join(SCENES, filename)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path


if __name__ == "__main__":
    for b, f in ((demo_props, "demo_props.blend"), (demo_alley, "demo_alley.blend")):
        print("[RealWorn] saved", save_demo(b, f))

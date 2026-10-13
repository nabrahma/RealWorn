"""Test fixtures built from code: meshes, materials, a camera and lights.

Functions return objects linked into the given scene; nothing is saved to disk.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


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
    """Mixed props on a floor (crate, bevelled cube, pipe, L-block), with camera and lights."""
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

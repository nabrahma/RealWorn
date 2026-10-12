"""Projector decals (DEC-1..DEC-10) and Auto Leaks (DEC-8).

A decal is an Empty (cube display) named RW_Decal_<image>. Every material of every object
inside its box gets an RW_L_Decal layer that projects through Texture Coordinate > Object of
that Empty. Each material keeps the list of its decals (`material.realworn.decals`, JSON) and
its decal chain is rebuilt from that list, so the order is stable and removal is exact.
"""

import json
import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import assets, injector, naming, nodeutil, weathering

DECAL_DIR = os.path.join(assets.ASSET_DIR, "decals")
MODES = {"FULL": 0.0, "GRIME": 1.0, "DAMAGE": 2.0}
_ACC_TO_STACK = (("Color", "Decal Color"), ("Alpha", "Decal Alpha"), ("Roughness", "Decal Roughness"),
                 ("Rough Alpha", "Decal Rough Alpha"), ("Darken", "Decal Darken"), ("Damage", "Decal Damage"),
                 ("Height", "Decal Height"), ("Normal", "Decal Normal"), ("Normal Alpha", "Decal Normal Alpha"))
_ACC_NAMES = [a for a, _ in _ACC_TO_STACK]


class DecalError(Exception):
    pass


# ---------------------------------------------------------------- library
def _user_folder():
    try:
        from ..props import prefs
        p = prefs()
        return bpy.path.abspath(p.decal_folder) if p and p.decal_folder else ""
    except Exception:
        return ""


def library():
    """[(file name, absolute path)] of decal images; *_nrm.png are normal maps, not decals."""
    out = []
    for folder in (DECAL_DIR, _user_folder()):
        if folder and os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")) and \
                        not os.path.splitext(f)[0].endswith("_nrm"):
                    out.append((f, os.path.join(folder, f)))
    return out


_previews = None
_enum_items = []  # keep strings alive for Blender's enum callback


def library_enum_items():
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    for i, (name, path) in enumerate(library()):
        icon = 0
        if _previews is not None:
            if name not in _previews:
                _previews.load(name, path, "IMAGE")
            icon = _previews[name].icon_id
        _enum_items.append((name, os.path.splitext(name)[0].replace("_", " ").title(), path, icon, i))
    if not _enum_items:
        _enum_items.append(("NONE", "No decals found", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None


def _path_for(name):
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for n, p in library():
        if n == name or os.path.splitext(n)[0] == name:
            return p
    raise DecalError("decal image '{}' not found in the library".format(name))


def load_image(name, non_color=False):
    path = _path_for(name)
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(path):
            return img
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def _normal_map_for(path):
    stem, ext = os.path.splitext(path)
    p = stem + "_nrm" + ext
    return p if os.path.exists(p) else None


# ------------------------------------------------------------ decal objects
def is_decal(ob):
    return ob is not None and ob.type == "EMPTY" and bool(ob.get("rw_decal"))


def decal_objects():
    return [o for o in bpy.data.objects if is_decal(o)]


def ensure_collection(scene):
    coll = bpy.data.collections.get(naming.COLL_DECALS)
    if coll is None:
        coll = bpy.data.collections.new(naming.COLL_DECALS)
    if scene is not None and coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def projection_normal(empty):
    return (empty.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()


def _corners(empty):
    mw = empty.matrix_world
    return [mw @ Vector((x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]


def _aabb(points):
    xs, ys, zs = zip(*points)
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def intersecting_objects(empty, scene):
    """Meshes whose world bounds overlap the decal box (DEC-9 lists these)."""
    lo, hi = _aabb(_corners(empty))
    out = []
    for ob in scene.objects:
        if ob.type != "MESH" or is_decal(ob):
            continue
        blo, bhi = _aabb([ob.matrix_world @ Vector(c) for c in ob.bound_box])
        if all(blo[i] <= hi[i] and bhi[i] >= lo[i] for i in range(3)):
            out.append(ob)
    return out


def orientation(normal, rotation=0.0, up=(0.0, 0.0, 1.0)):
    """3x3 basis: Z = surface normal, Y = world up projected on the surface (image stays upright)."""
    z = Vector(normal).normalized()
    upv = Vector(up)
    y = upv - z * z.dot(upv)
    if y.length < 1e-4:  # floor or ceiling: keep image Y along world Y
        y = Vector((0, 1, 0)) - z * z.dot(Vector((0, 1, 0)))
    y.normalize()
    x = y.cross(z).normalized()
    m = Matrix((x, y, z)).transposed()
    return m @ Matrix.Rotation(rotation, 3, "Z")


def place(scene, image, location, normal, size=0.6, mode="FULL", rotation=0.0, height=None, depth=None,
          opacity=1.0, targets=None):
    """Create a projector decal at a surface point. Returns (empty, report list)."""
    if mode not in MODES:
        raise DecalError("mode must be one of {}".format(sorted(MODES)))
    img = load_image(image)
    w, h = img.size
    height = height if height is not None else size * (h / w if w else 1.0)
    depth = depth if depth is not None else max(0.1, min(size, height) * 0.5)
    empty = bpy.data.objects.new(naming.decal_name(img.name), None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 1.0
    rot = orientation(normal, rotation)
    empty.matrix_world = Matrix.Translation(Vector(location)) @ (rot @ Matrix.Diagonal(
        (size / 2.0, height / 2.0, depth / 2.0))).to_4x4()
    ensure_collection(scene).objects.link(empty)
    empty["rw_decal"] = True
    empty["rw_decal_image"] = img.name
    empty["rw_decal_mode"] = mode
    empty["rw_opacity"] = float(opacity)
    nrm = _normal_map_for(_path_for(image))
    if nrm:
        empty["rw_decal_normal"] = load_image(nrm, non_color=True).name
    bpy.context.view_layer.update() if bpy.context.view_layer else None
    rep = []
    targets = targets if targets is not None else intersecting_objects(empty, scene)
    names = []
    for ob in targets:
        if not ob.realworn.applied:
            rep += weathering.apply_object(ob, scene, scene.realworn.preset)
        for mat in weathering.materials_of(ob):
            if not injector.is_applied(mat):
                continue
            if add_to_material(mat, empty):
                names.append(mat.name)
            else:
                rep.append(("WARNING", "{}: {} decals already; bake it to add more".format(
                    mat.name, naming.MAX_DECALS_PER_MATERIAL)))
    empty["rw_targets"] = sorted(set(names))
    shared = sorted({o.name for m in names for o in weathering.users_of(bpy.data.materials[m])} -
                    {o.name for o in targets})
    if shared:
        rep.append(("INFO", "Shared material: also used by {} (unaffected outside the decal box)".format(
            ", ".join(shared[:5]))))
    if not names:
        rep.append(("WARNING", "Decal placed but it touches no weathered material"))
    return empty, rep


# -------------------------------------------------------- material chains
def material_decals(mat):
    try:
        return list(json.loads(mat.realworn.decals or "[]"))
    except ValueError:
        return []


def _set_list(mat, names):
    mat.realworn.decals = json.dumps(names)


def add_to_material(mat, empty):
    names = material_decals(mat)
    if empty.name in names:
        return True
    if len(names) >= naming.MAX_DECALS_PER_MATERIAL:
        return False
    names.append(empty.name)
    _set_list(mat, names)
    rebuild_material(mat)
    return True


def remove_from_material(mat, name):
    names = material_decals(mat)
    if name in names:
        names.remove(name)
        _set_list(mat, names)
        rebuild_material(mat)


def _decal_nodes(tree):
    return [n for n in tree.nodes if nodeutil.is_owned(n) and n.name.startswith(naming.node_name("decal"))]


def rebuild_material(mat):
    """Rebuild the decal chain of one material from its decal list (dropping deleted Empties)."""
    tree = mat.node_tree
    for n in _decal_nodes(tree):
        tree.nodes.remove(n)
    stacks = injector.stacks(tree)
    names = [n for n in material_decals(mat) if is_decal(bpy.data.objects.get(n))]
    _set_list(mat, names)
    if not stacks or not names:
        return 0
    assets.ensure_groups((naming.SH_DECAL, naming.SH_DECAL_PROJECT))
    frame = nodeutil.ensure_frame(tree)
    sx, sy = injector._abs(stacks[0])
    prev = None
    for k, name in enumerate(names):
        e = bpy.data.objects[name]
        x, y = sx - 1100 + 0 * k, sy - 500 - 260 * k
        tc = nodeutil.new(tree, "ShaderNodeTexCoord", "decal_tc.{}".format(k), frame=frame)
        tc.object = e
        pj = nodeutil.new(tree, "ShaderNodeGroup", "decal_proj.{}".format(k), frame=frame)
        pj.node_tree = bpy.data.node_groups[naming.SH_DECAL_PROJECT]
        im = nodeutil.new(tree, "ShaderNodeTexImage", "decal_img.{}".format(k), frame=frame)
        im.image = bpy.data.images.get(e.get("rw_decal_image", ""))
        im.extension = "CLIP"
        ly = nodeutil.new(tree, "ShaderNodeGroup", "decal.{}".format(k), frame=frame)
        ly.node_tree = bpy.data.node_groups[naming.SH_DECAL]
        ly["rw_decal"] = name
        for node, dx in ((tc, 0), (pj, 200), (im, 400), (ly, 700)):
            node.hide = node is not ly
            injector._place(node, x + dx, y)
        tree.links.new(tc.outputs["Object"], pj.inputs["Vector"])
        tree.links.new(pj.outputs["UV"], im.inputs["Vector"])
        tree.links.new(im.outputs["Color"], ly.inputs["Image Color"])
        tree.links.new(im.outputs["Alpha"], ly.inputs["Image Alpha"])
        tree.links.new(pj.outputs["Box"], ly.inputs["Box"])
        ly.inputs["Projection Normal"].default_value = projection_normal(e)
        ly.inputs["Mode"].default_value = MODES.get(e.get("rw_decal_mode", "FULL"), 0.0)
        ly.inputs["Opacity"].default_value = float(e.get("rw_opacity", 1.0))
        nimg = bpy.data.images.get(e.get("rw_decal_normal", ""))
        if nimg is not None:
            nm = nodeutil.new(tree, "ShaderNodeTexImage", "decal_nrm.{}".format(k), frame=frame)
            nm.image = nimg
            nm.extension = "CLIP"
            nm.hide = True
            injector._place(nm, x + 400, y - 60)
            tree.links.new(pj.outputs["UV"], nm.inputs["Vector"])
            tree.links.new(nm.outputs["Color"], ly.inputs["Normal Map"])
            ly.inputs["Has Normal"].default_value = 1.0
        if prev is not None:
            for a in _ACC_NAMES:
                tree.links.new(prev.outputs[a], ly.inputs[a])
        prev = ly
    for st in stacks:
        for a, s in _ACC_TO_STACK:
            tree.links.new(prev.outputs[a], st.inputs[s])
    return len(names)


def update_projection(empty):
    """Keep the facing fade aligned when a decal Empty is rotated (DEC-3)."""
    n = projection_normal(empty)
    for mat in bpy.data.materials:
        if mat.node_tree is None or empty.name not in material_decals(mat):
            continue
        for node in _decal_nodes(mat.node_tree):
            if node.get("rw_decal") == empty.name:
                cur = Vector(node.inputs["Projection Normal"].default_value)
                if (cur - n).length > 1e-5:
                    node.inputs["Projection Normal"].default_value = n


def cleanup(scene=None, retarget=False):
    """Clean Up Decals (DEC-10): drop layers of deleted Empties; optionally re-target moved ones."""
    changed = 0
    for mat in bpy.data.materials:
        if mat.node_tree is None or not injector.is_applied(mat):
            continue
        names = material_decals(mat)
        alive = [n for n in names if is_decal(bpy.data.objects.get(n))]
        if alive != names or len(_decal_nodes(mat.node_tree)) != _expected_nodes(mat, alive):
            _set_list(mat, alive)
            rebuild_material(mat)
            changed += 1
    if retarget and scene is not None:
        for vl in scene.view_layers:  # moved Empties: refresh matrix_world before testing bounds
            vl.update()
        for e in decal_objects():
            want = {m.name for o in intersecting_objects(e, scene) for m in weathering.materials_of(o)
                    if injector.is_applied(m)}
            for mat in bpy.data.materials:
                has = e.name in material_decals(mat)
                if has and mat.name not in want:
                    remove_from_material(mat, e.name)
                    changed += 1
                elif not has and mat.name in want:
                    changed += add_to_material(mat, e)
            e["rw_targets"] = sorted(want)
    return changed


def _expected_nodes(mat, names):
    n = 0
    for name in names:
        e = bpy.data.objects.get(name)
        n += 4 + (1 if e is not None and bpy.data.images.get(e.get("rw_decal_normal", "")) else 0)
    return n


def delete_decal(empty):
    name = empty.name
    bpy.data.objects.remove(empty)
    for mat in bpy.data.materials:
        if mat.node_tree is not None and name in material_decals(mat):
            remove_from_material(mat, name)


def remove_all_decals():
    n = 0
    for e in decal_objects():
        bpy.data.objects.remove(e)
        n += 1
    for mat in bpy.data.materials:
        if mat.node_tree is not None and material_decals(mat):
            _set_list(mat, [])
            rebuild_material(mat)
    coll = bpy.data.collections.get(naming.COLL_DECALS)
    if coll is not None:
        bpy.data.collections.remove(coll)
    return n


# ------------------------------------------------------- depsgraph upkeep
_state = {"objects": -1}


def on_depsgraph_update(scene, depsgraph):
    """DEC-10 and DEC-3 upkeep: cheap unless an Empty moved or objects were deleted."""
    n = len(bpy.data.objects)
    if n < _state["objects"]:
        cleanup()
    _state["objects"] = n
    for upd in depsgraph.updates:
        idb = upd.id
        if isinstance(idb, bpy.types.Object) and upd.is_updated_transform and idb.get("rw_decal"):
            ob = bpy.data.objects.get(idb.name)
            if ob is not None:
                update_projection(ob)


# ------------------------------------------------------------- auto leaks
def _overhang_edges(ob):
    """(world midpoint, outward side normal, height above base, protrusion) for edges where a top face
    meets a side face that continues downward (DEC-8), plus drip edges of downward faces."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    bm.normal_update()
    base_z = min((v.co.z for v in bm.verts), default=0.0)
    # main plane offset per horizontal facing direction (area-weighted median), so protruding
    # ledges (sills, cornices) can be ranked above plain wall tops
    planes = {}
    for f in bm.faces:
        if abs(f.normal.z) < 0.3:
            key = (round(f.normal.x, 1), round(f.normal.y, 1))
            planes.setdefault(key, []).append((f.calc_center_median().dot(f.normal), f.calc_area()))
    main = {}
    for key, vals in planes.items():
        vals.sort()
        half, acc = sum(a for _, a in vals) / 2.0, 0.0
        for off, a in vals:
            acc += a
            if acc >= half:
                main[key] = off
                break
    out = []
    for e in bm.edges:
        if len(e.link_faces) != 2 or not e.is_convex:
            continue
        f1, f2 = e.link_faces
        lo_z = min(v.co.z for v in e.verts)
        for top, side in ((f1, f2), (f2, f1)):
            if abs(side.normal.z) >= 0.3:
                continue
            side_below = side.calc_center_median().z < lo_z + 1e-4
            drip = top.normal.z < -0.7 and not side_below and lo_z > base_z + 0.25  # an overhang, not a base
            if (top.normal.z > 0.7 and side_below) or drip:
                mid = (e.verts[0].co + e.verts[1].co) / 2.0
                d = (e.verts[1].co - e.verts[0].co).normalized()
                n = Vector((side.normal.x, side.normal.y, 0.0)).normalized()
                key = (round(side.normal.x, 1), round(side.normal.y, 1))
                protrude = side.calc_center_median().dot(side.normal) - main.get(key, 0.0)
                out.append((mid.copy(), n, mid.z - base_z, protrude))
                break
    bm.free()
    return out


def auto_leaks(scene, objects, seed=0, spacing=1.5, image="leak_01.png", max_per_object=6):
    """Spawn Grime-mode leak decals below overhangs, sills and parapets. Returns (empties, report)."""
    rng = random.Random(seed)
    made, rep, skipped = [], [], 0
    for ob in objects:
        cands = _overhang_edges(ob)
        rng.shuffle(cands)
        cands.sort(key=lambda c: c[3] <= 0.02)  # protruding ledges first, then the rest (stable)
        accepted = []
        for p, n, room, _protrude in cands:
            if room < 0.2:  # too close to the object's base for a visible run
                continue
            gap = spacing * (0.6 + 0.8 * rng.random())
            if all((p - q).length > gap or n.dot(m) < 0.9 for q, m, _ in accepted):
                accepted.append((p, n, room))
            if len(accepted) >= max_per_object:
                break
        for p, n, room in accepted:
            run = min(rng.uniform(0.3, 1.5), room)  # never runs below the object's base
            width = rng.uniform(0.25, 0.55) * min(spacing, 1.0)
            loc = p - Vector((0, 0, run / 2.0))
            empty, r = place(scene, image, loc, n, size=width, mode="GRIME", height=run, depth=0.6,
                             opacity=rng.uniform(0.6, 1.0))
            if not empty["rw_targets"]:
                skipped += 1
                delete_decal(empty)
                continue
            rep += [x for x in r if x[0] != "INFO"]
            made.append(empty)
    if skipped:
        rep.append(("WARNING", "{} leak(s) skipped (decal limit or nothing weathered)".format(skipped)))
    return made, rep

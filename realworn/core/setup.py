"""One-click Setup and Remove per object (SET-1..SET-7, G6).

Setup: validate the mesh; give an object without a material RW_<object> (a neutral grey Base);
make materials used by other objects unique to this object (<name>.RW); add the RW_Paint UV map
the tutorial's way (Cube Projection, then Pack Islands; Smart UV or a copy of the existing UV as
options) without touching the user's UV maps; wrap every material (injector.inject) with an empty,
invisible stack. Unapplied object scale is reported (SET-5): the operator offers to apply it,
since Object texture coordinates follow the object's scale.

Remove restores each slot's original material (deleting the .RW copies and default materials
RealWorn made), the original node trees, the UV state and the slot links, and deletes RW_Paint,
the stack groups and RealWorn modifiers. Painted images are deleted only when asked.

Everything Setup changes on the object is recorded in obj["rw_setup"] (JSON). Applying scale is
a separate, confirmed user action and is not undone by Remove.
"""

import json
import math

import bpy

from . import ctx, injector, naming

CUBE_SIZE = 1.0       # SET-2: Cube Projection (the tutorial's settings)
PACK_MARGIN = 0.004   # Pack Islands margin (about 8 px at 2048)
SCALE_TOL = 1e-4


class SetupError(Exception):
    pass


# ----------------------------------------------------------------- queries
def is_supported(obj):
    return obj is not None and obj.type == "MESH" and obj.library is None


def materials_of(obj):
    seen = []
    for slot in obj.material_slots:
        m = slot.material
        if m is not None and m not in seen:
            seen.append(m)
    return seen


def objects_using(mat):
    return [o for o in bpy.data.objects if o.type == "MESH" and any(s.material == mat for s in o.material_slots)]


def is_setup(obj):
    return obj is not None and naming.OB_SETUP in obj


def record(obj):
    try:
        return json.loads(obj.get(naming.OB_SETUP, "{}"))
    except ValueError:
        return {}


def layered_materials(obj):
    return [m for m in materials_of(obj) if injector.is_setup(m)]


def needs_scale_apply(obj):
    """SET-5: True when the object's scale is not (1, 1, 1)."""
    return obj is not None and any(abs(s - 1.0) > SCALE_TOL for s in obj.scale)


def apply_scale(obj):
    """Apply the object's scale to its mesh (a single-user mesh only). Returns True when applied."""
    if not needs_scale_apply(obj):
        return False
    if obj.data.users > 1:
        return False
    with bpy.context.temp_override(**ctx.override(obj)):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return True


# ---------------------------------------------------------------- RW_Paint
def _restore_uv_state(me, active, render):
    if active and active in me.uv_layers:
        me.uv_layers.active = me.uv_layers[active]
    if render and render in me.uv_layers:
        me.uv_layers[render].active_render = True


def ensure_paint_uv(obj, method="CUBE"):
    """SET-2: add RW_Paint (non-overlapping islands) without changing the user's UV maps or which
    one renders. CUBE: Cube Projection then Pack Islands; SMART: Smart UV Project; EXISTING: a copy
    of the active UV map. Returns True if created."""
    me = obj.data
    if naming.UV_PAINT in me.uv_layers:
        return False
    active = me.uv_layers.active.name if me.uv_layers.active else None
    render = next((u.name for u in me.uv_layers if u.active_render), None)
    src = me.uv_layers.active if method == "EXISTING" and me.uv_layers.active else None
    uv = me.uv_layers.new(name=naming.UV_PAINT, do_init=False)
    if src is not None:
        n = len(me.loops)
        buf = [0.0] * (n * 2)
        src.data.foreach_get("uv", buf)
        uv.data.foreach_set("uv", buf)
    elif me.polygons:
        _unwrap(obj, uv.name, method)
    _restore_uv_state(me, active, render)
    return True


def separate_projections(me, uv_name):
    """Cube Projection gives faces that meet at an edge the same UVs along it, so Pack Islands
    would treat two projection directions as one overlapping island. Move each direction's faces
    (dominant normal axis and sign) apart first; Pack Islands then lays them out without overlap."""
    import numpy as np
    n = np.empty(len(me.polygons) * 3, np.float32)
    me.polygons.foreach_get("normal", n)
    n = n.reshape(-1, 3)
    axis = np.abs(n).argmax(axis=1)
    side = (n[np.arange(len(n)), axis] < 0).astype(np.int64)
    group = axis * 2 + side
    total = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", total)
    loop_group = np.repeat(group, total)
    uv = me.uv_layers[uv_name]
    co = np.empty(len(me.loops) * 2, np.float32)
    uv.data.foreach_get("uv", co)
    co = co.reshape(-1, 2)
    co[:, 0] += loop_group * 8.0
    me.uv_layers[uv_name].data.foreach_set("uv", co.ravel())


def _unwrap(obj, uv_name, method):
    """Unwrap one object into `uv_name`, restoring mode, selection and active object."""
    me = obj.data
    vl = bpy.context.view_layer
    prev_active = vl.objects.active
    prev_sel = [o for o in vl.objects if o.select_get()]
    prev_mode = obj.mode
    linked = obj.name in vl.objects
    if not linked:
        bpy.context.scene.collection.objects.link(obj)
    for o in prev_sel:
        o.select_set(False)
    obj.select_set(True)
    vl.objects.active = obj
    me.uv_layers.active = me.uv_layers[uv_name]
    hidden = obj.hide_get()
    obj.hide_set(False)
    try:
        with bpy.context.temp_override(**ctx.override(obj)):
            if obj.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action="SELECT")
            if method == "SMART":
                bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=PACK_MARGIN,
                                         area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
            else:
                bpy.ops.uv.cube_project(cube_size=CUBE_SIZE, correct_aspect=True)
                bpy.ops.object.mode_set(mode="OBJECT")
                separate_projections(me, uv_name)
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.uv.select_all(action="SELECT")
                bpy.ops.uv.pack_islands(margin=PACK_MARGIN)
            bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        obj.hide_set(hidden)
        obj.select_set(False)
        for o in prev_sel:
            if o.name in vl.objects:
                o.select_set(True)
        vl.objects.active = prev_active
        if prev_mode not in ("OBJECT", "EDIT") and prev_active is obj:
            with bpy.context.temp_override(**ctx.override(obj)):
                bpy.ops.object.mode_set(mode=prev_mode)
        if not linked:
            bpy.context.scene.collection.objects.unlink(obj)


def uv_overlap_ratio(obj, uv_name=naming.UV_PAINT, res=256):
    """Fraction of rasterised UV area covered more than once (0 for a clean layout)."""
    import numpy as np
    me = obj.data
    uv = me.uv_layers.get(uv_name)
    if uv is None or not me.polygons:
        return 0.0
    co = np.empty(len(me.loops) * 2, np.float32)
    uv.data.foreach_get("uv", co)
    co = co.reshape(-1, 2) * res
    cover = np.zeros((res, res), np.int32)
    ys, xs = np.mgrid[0:res, 0:res] + 0.5
    for p in me.polygons:
        idx = list(p.loop_indices)
        for k in range(1, len(idx) - 1):  # triangle fan
            a, b, c = co[idx[0]], co[idx[k]], co[idx[k + 1]]
            x0, x1 = int(max(min(a[0], b[0], c[0]), 0)), int(min(max(a[0], b[0], c[0]) + 1, res))
            y0, y1 = int(max(min(a[1], b[1], c[1]), 0)), int(min(max(a[1], b[1], c[1]) + 1, res))
            if x1 <= x0 or y1 <= y0:
                continue
            px, py = xs[y0:y1, x0:x1], ys[y0:y1, x0:x1]
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
            l2 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
            inside = (l1 > 1e-3) & (l2 > 1e-3) & (l1 + l2 < 1 - 1e-3)
            cover[y0:y1, x0:x1] += inside
    used = (cover > 0).sum()
    return float((cover > 1).sum()) / float(used) if used else 0.0


# ------------------------------------------------------------------ setup
def _default_material(obj):
    """SET-1: RW_<object>, a neutral grey Principled."""
    mat = bpy.data.materials.new(naming.default_material_name(obj.name))
    p = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if p is not None:
        p.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    mat["rw_created"] = True
    return mat


def setup_object(obj, uv_method="CUBE"):
    """Set the object up for painting. Returns report tuples [(level, message)]."""
    rep = []
    if not is_supported(obj):
        raise SetupError("{}: not a local mesh object".format(obj.name if obj else None))
    if is_setup(obj):
        for m in materials_of(obj):  # a material added after Setup gets wrapped too
            if not injector.is_setup(m):
                _wrap(obj, m, rep)
        return rep
    rec = {"slots": [], "uv_created": False, "uv_active": None, "uv_render": None}
    me = obj.data
    rec["uv_active"] = me.uv_layers.active.name if me.uv_layers.active else None
    rec["uv_render"] = next((u.name for u in me.uv_layers if u.active_render), None)
    if not obj.material_slots:
        obj.data.materials.append(None)
        rec["added_slot"] = True
    for i, slot in enumerate(obj.material_slots):
        orig = slot.material
        rec["slots"].append({"index": i, "material": orig.name if orig else None, "link": slot.link})
        if orig is None:
            slot.material = _default_material(obj)
            continue
        if orig.library is not None and orig.override_library is None:
            rep.append(("WARNING", "{}: linked from a library, skipped".format(orig.name)))
            continue
        others = [o for o in objects_using(orig) if o is not obj]
        shared_mesh = me.users > 1 and slot.link == "DATA"
        if others or shared_mesh:
            if shared_mesh:  # changing a DATA slot would change every object sharing this mesh
                slot.link = "OBJECT"
            dup = orig.copy()
            dup.name = naming.unique_material_name(orig.name)
            dup.realworn.source_material = orig.name
            slot.material = dup
            rep.append(("INFO", "{}: made unique to {} (was shared)".format(dup.name, obj.name)))
    obj[naming.OB_SETUP] = json.dumps(rec)
    rec["uv_created"] = ensure_paint_uv(obj, uv_method)
    obj[naming.OB_SETUP] = json.dumps(rec)
    if rec["uv_created"] and uv_method != "EXISTING":
        ov = uv_overlap_ratio(obj)
        if ov > 0.02:
            rep.append(("WARNING", "{}: RW_Paint islands overlap {:.0%}".format(obj.name, ov)))
    if needs_scale_apply(obj):
        rep.append(("WARNING", "{}: scale is not applied; box-mapped textures follow the object's scale "
                               "(Setup can apply it)".format(obj.name)))
    for m in materials_of(obj):
        _wrap(obj, m, rep)
    return rep


def _wrap(obj, mat, rep):
    try:
        injector.inject(mat)
        mat.realworn.owner = obj.name
    except injector.InjectError as ex:
        rep.append(("WARNING", str(ex)))


# ------------------------------------------------------------------ remove
def mask_images(obj):
    out = []
    for m in materials_of(obj):
        for ly in m.realworn.layers:
            for img in (ly.mask_image, ly.baked_image):
                if img is not None and img not in out:
                    out.append(img)
    return out


def remove_object(obj, delete_images=True):
    """Undo Setup on one object. Returns report tuples."""
    from . import reveal
    rep = []
    rec = record(obj)
    reveal.remove_subdiv(obj)
    images = mask_images(obj) if delete_images else []
    for m in materials_of(obj):
        if injector.is_setup(m):
            diffs = injector.restore(m)
            if diffs:
                rep.append(("ERROR", "{}: restore mismatch ({} diffs), snapshot kept: {}".format(
                    m.name, len(diffs), diffs[0])))
            else:
                m.realworn.layers.clear()
                m.realworn.owner = ""
                from . import pbrset
                pbrset.clear(m.realworn.base)
    for s in rec.get("slots", []):
        i = s["index"]
        if i >= len(obj.material_slots):
            continue
        slot = obj.material_slots[i]
        cur = slot.material
        want = bpy.data.materials.get(s["material"]) if s["material"] else None
        if slot.link != s["link"]:
            slot.link = s["link"]
        if obj.material_slots[i].material != want:
            obj.material_slots[i].material = want
        if cur is not None and cur is not want and (cur.get("rw_created") or cur.realworn.source_material):
            if cur.users == 0:
                bpy.data.materials.remove(cur)
    if rec.get("added_slot") and len(obj.material_slots) == 1 and obj.material_slots[0].material is None:
        # materials.pop() leaves the object's slot count behind; the operator removes the slot
        obj.active_material_index = 0
        with bpy.context.temp_override(**ctx.override(obj)):
            bpy.ops.object.material_slot_remove()
    me = obj.data
    if rec.get("uv_created") and naming.UV_PAINT in me.uv_layers:
        still = [o for o in bpy.data.objects if o is not obj and o.data is me and is_setup(o)]
        if not still:
            me.uv_layers.remove(me.uv_layers[naming.UV_PAINT])
    _restore_uv_state(me, rec.get("uv_active"), rec.get("uv_render"))
    for img in images:
        if img.users == 0 or (img.users == 1 and img.use_fake_user):
            bpy.data.images.remove(img)
    if naming.OB_SETUP in obj:
        del obj[naming.OB_SETUP]
    return rep


def remove_all():
    rep = []
    for o in list(bpy.data.objects):
        if o.type == "MESH" and is_setup(o):
            rep += remove_object(o)
    for m in list(bpy.data.materials):
        if injector.is_setup(m):
            if injector.restore(m):
                rep.append(("ERROR", "{}: restore mismatch, snapshot kept".format(m.name)))
    from . import assets
    assets.remove_unused_groups()
    return rep

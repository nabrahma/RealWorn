"""Scene weather: mirror slider values into rw_* custom properties (G4, no drivers).

Shaders read scene values through Attribute (View Layer) and object values through
Attribute (Object), which look up custom properties.
"""

import zlib

import bpy
from mathutils import Vector

from . import masks, naming


def _put(idblock, key, value):
    if idblock.get(key) != value:
        idblock[key] = value
        return True
    return False


def sync_scene(scene):
    p = scene.realworn
    vals = {
        naming.SC_AGE: float(p.age),
        naming.SC_DIRT: float(p.dirt),
        naming.SC_DUST: float(p.dust),
        naming.SC_WETNESS: float(p.wetness),
        naming.SC_RAIN: 1.0 if p.rain else 0.0,
        naming.SC_SPLASH: float(p.splash_height),
        naming.SC_GROUND_Z: float(p.ground_z),
    }
    changed = False
    for k, v in vals.items():
        changed |= _put(scene, k, v)
    if naming.SC_PREVIEW not in scene:
        scene[naming.SC_PREVIEW] = 0.0
    changed |= sync_wet_variant()
    if changed:
        _refresh(scene)
    return changed


def wet_needed():
    return any(s.realworn.wetness > 0.0 or s.realworn.rain for s in bpy.data.scenes)


def sync_wet_variant():
    """Point RW_Stack at the full wetness group only while some scene is wet or raining.

    One edit of the shared group updates every material; files opened without the add-on
    keep whichever variant matched their sliders when saved.
    """
    stack = bpy.data.node_groups.get(naming.SH_STACK)
    if stack is None:
        return False
    node = stack.nodes.get(naming.STACK_WET_NODE)
    if node is None:
        return False
    target = naming.SH_L_WET if wet_needed() else naming.SH_L_WET_DRY
    if node.node_tree is not None and node.node_tree.name == target:
        return False
    from . import assets
    assets.ensure_groups((target,))
    node.node_tree = bpy.data.node_groups[target]
    return True


def _refresh(scene):
    """Custom property edits do not tag the depsgraph by themselves; nudge shading."""
    scene.update_tag()
    for vl in scene.view_layers:
        vl.update_tag() if hasattr(vl, "update_tag") else None
    wm = bpy.context.window_manager if bpy.context else None
    for win in (wm.windows if wm else []):
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def stable_seed(name):
    """Seed from a stable hash of the object name (independent of Python's hash salt)."""
    return float(zlib.crc32(name.encode("utf-8")) % 10007) / 10.0


def sync_object(obj):
    p = obj.realworn
    changed = False
    changed |= _put(obj, naming.OB_SEED, float(p.seed))
    changed |= _put(obj, naming.OB_WEAR, float(p.wear))
    changed |= _put(obj, naming.OB_DIRT, float(p.dirt))
    changed |= _put(obj, naming.OB_GROUND, 1.0 if p.is_ground else 0.0)
    if changed:
        obj.update_tag()
    return changed


def clear_object(obj):
    for k in naming.OBJECT_PROPS:
        if k in obj:
            del obj[k]


def ground_objects(scene):
    coll = bpy.data.collections.get(naming.COLL_GROUND)
    if coll is None:
        return []
    names = set(scene.objects.keys())
    return [o for o in coll.objects if o.name in names]


def update_ground_z(scene):
    """Auto Ground Z: the lowest world-space bound of the scene's ground objects."""
    p = scene.realworn
    if not p.ground_z_auto:
        return p.ground_z
    zs = []
    for o in ground_objects(scene):
        mw = o.matrix_world
        zs.extend((mw @ Vector(c)).z for c in o.bound_box)
    z = min(zs) if zs else 0.0
    if abs(p.ground_z - z) > 1e-6:
        p.ground_z = z  # triggers sync_scene through the update callback
    _put(scene, naming.SC_GROUND_Z, float(z))
    return z


def mark_ground(obj, scene, state=True):
    """WX-13: flag as ground, link into RW_Ground (without unlinking elsewhere)."""
    coll = masks.ensure_collection(naming.COLL_GROUND)
    if state and obj.name not in coll.objects:
        coll.objects.link(obj)
    elif not state and obj.name in coll.objects:
        coll.objects.unlink(obj)
    obj.realworn.is_ground = state
    sync_object(obj)
    masks.sync_collections(obj)
    update_ground_z(scene)
    sync_scene(scene)


def mark_occluder(obj, state=True):
    """WX-14: roofs, awnings and balconies cast shelter (rw_shelter) on objects below."""
    coll = masks.ensure_collection(naming.COLL_OCCLUDERS)
    if state and obj.name not in coll.objects:
        coll.objects.link(obj)
    elif not state and obj.name in coll.objects:
        coll.objects.unlink(obj)
    obj.realworn.is_occluder = state
    masks.sync_collections(obj)


def resync_all():
    """Load handler: make custom properties agree with the PropertyGroups again."""
    for scene in bpy.data.scenes:
        sync_scene(scene)
    for obj in bpy.data.objects:
        if obj.get(naming.OB_SEED) is not None or obj.realworn.applied:
            sync_object(obj)

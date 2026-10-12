"""Add, update and remove the RW_Masks modifier (MASK-1..MASK-5, MASK-9)."""

import bpy

from . import assets, naming

MASK_DEFAULTS = {
    "Edge Angle Threshold": 0.4363323,
    "Edge Width": 0.015,
    "Cavity Width": 0.03,
    "Contact Width": 0.15,
    "Blur Iterations": 2,
    "Pre-Subdivide": -1,
}


# ------------------------------------------------------------- collections
def ensure_collection(name):
    """RW_Ground / RW_Occluders / RW_Decals: kept alive by a fake user, not linked to scenes."""
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        coll.use_fake_user = True
    return coll


# ---------------------------------------------------------- modifier inputs
def _identifier(group, name):
    for item in group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            return item.identifier
    raise KeyError(name)


def _input_item(mod, name):
    # Blender 5.x: modifier inputs live at mod.properties.inputs.<identifier>.value
    return getattr(mod.properties.inputs, _identifier(mod.node_group, name))


def set_input(mod, name, value):
    item = _input_item(mod, name)
    if item.value != value:
        item.value = value
        mod.id_data.update_tag()  # setting .value does not tag the object by itself
        return True
    return False


def get_input(mod, name):
    return _input_item(mod, name).value


def input_names(mod):
    return [i.name for i in mod.node_group.interface.items_tree
            if i.item_type == "SOCKET" and i.in_out == "INPUT" and i.socket_type != "NodeSocketGeometry"]


# ---------------------------------------------------------------- modifier
def is_supported(obj):
    return obj is not None and obj.type == "MESH" and obj.library is None


def masks_modifier(obj):
    m = obj.modifiers.get(naming.MOD_MASKS)
    return m if m is not None and m.type == "NODES" else None


def _target_index(obj, name):
    """Index for an RW modifier: after everything except a trailing Subdivision Surface.

    RW_Damage sits directly before RW_Masks (DMG-1) so chips get edge wear too.
    """
    mods = [m for m in obj.modifiers if m.name != name]
    idx = len(mods)
    if mods and mods[-1].type == "SUBSURF":
        idx -= 1
    if name == naming.MOD_DAMAGE:
        for i, m in enumerate(mods):
            if m.name == naming.MOD_MASKS:
                idx = min(idx, i)
    return idx


def place_modifier(obj, mod):
    idx = _target_index(obj, mod.name)
    cur = list(obj.modifiers).index(mod)
    if cur != idx:
        obj.modifiers.move(cur, idx)


def ensure_paint_attribute(mesh):
    """Create the rw_paint corner byte-color attribute filled black; True if created."""
    if naming.ATTR_PAINT in mesh.color_attributes:
        return False
    active = mesh.color_attributes.active_color_name
    attr = mesh.color_attributes.new(naming.ATTR_PAINT, "BYTE_COLOR", "CORNER")
    attr.data.foreach_set("color", [0.0, 0.0, 0.0, 1.0] * len(attr.data))
    if active:  # do not steal the user's active/render color attribute
        mesh.color_attributes.active_color_name = active
    return True


def ensure_masks(obj, settings=None):
    """Add (or update) the RW_Masks modifier on a mesh object and return it."""
    if not is_supported(obj):
        raise TypeError("{} is not a local mesh object".format(obj.name if obj else None))
    assets.ensure_groups((naming.GN_MASKS,))
    group = bpy.data.node_groups[naming.GN_MASKS]
    mod = masks_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(naming.MOD_MASKS, "NODES")
        mod.node_group = group
        for k, v in MASK_DEFAULTS.items():
            set_input(mod, k, v)
        mod.show_expanded = False
    elif mod.node_group is not group:
        mod.node_group = group
    place_modifier(obj, mod)
    for k, v in (settings or {}).items():
        set_input(mod, k, v)
    sync_collections(obj, mod)
    if obj.data.users == 1 or naming.ATTR_PAINT not in obj.data.color_attributes:
        if ensure_paint_attribute(obj.data):
            obj.data["rw_created_paint"] = True
    return mod


def sync_collections(obj, mod=None):
    """Point the modifier at RW_Ground / RW_Occluders and disable contact on ground objects."""
    mod = mod or masks_modifier(obj)
    if mod is None:
        return
    ground = ensure_collection(naming.COLL_GROUND)
    occ = ensure_collection(naming.COLL_OCCLUDERS)
    # An object must never read a collection that contains itself: that is a depsgraph cycle,
    # and Blender then evaluates the ground before its own modifiers are done, so other objects
    # see stale geometry. Ground objects skip contact, occluders skip self-shelter.
    is_ground = obj.name in ground.objects
    is_occ = obj.name in occ.objects
    set_input(mod, "Ground", None if is_ground else ground)
    set_input(mod, "Occluders", None if is_occ else occ)
    set_input(mod, "Use Contact", not is_ground)
    set_input(mod, "Use Shelter", not is_occ)
    obj.update_tag()


def remove_masks(obj):
    mod = masks_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)
    me = obj.data
    if me is not None and me.get("rw_created_paint"):
        attr = me.color_attributes.get(naming.ATTR_PAINT)
        if attr is not None:
            me.color_attributes.remove(attr)
        del me["rw_created_paint"]


def large_ngon_count(mesh, limit=8):
    """Faces with more than `limit` corners: vertex masks interpolate across them."""
    import numpy as np
    n = len(mesh.polygons)
    if n == 0:
        return 0
    sizes = np.empty(n, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", sizes)
    return int((sizes > limit).sum())


def has_nonuniform_scale(obj, tol=1e-3):
    s = [abs(v) for v in obj.scale]
    return max(s) - min(s) > tol * max(max(s), 1e-9)


def read_masks(obj, depsgraph):
    """Evaluated point positions (world) and mask values; for tests and debugging."""
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        mw = obj.matrix_world
        co = [mw @ v.co for v in me.vertices]
        out = {"co": co}
        for name in naming.MASK_ATTRS:
            a = me.attributes.get(name)
            out[name] = [d.value for d in a.data] if a is not None else None
        return out
    finally:
        ev.to_mesh_clear()

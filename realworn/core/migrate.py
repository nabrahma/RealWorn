"""v0.7 files (PRD v2 "Schema version bump"): the clean Remove path.

v0.7 weathered materials still carry their snapshot (same format) under the same property names
(applied, snapshot, schema_version 1), so the original tree is restored exactly. Everything else
v0.7 left is removed too: its RW_Masks / RW_Damage modifiers, the rw_paint colour attribute,
object and scene rw_* custom properties, v0.7 decal Empties and node groups. Afterwards the
objects are clean and can be Set Up for painting.
"""

import bpy

from . import naming, nodeutil, snapshot

V07_MODIFIERS = ("RW_Masks", "RW_Damage")
V07_INNER_PREFIX = "RW_Inner_"
V07_GROUPS = ("RW_Stack", "RW_Breakup", "RW_ShadingMasks", "RW_L_EdgeWear", "RW_L_Rust", "RW_L_DecalApply",
              "RW_L_CavityDirt", "RW_L_Grime", "RW_L_Dust", "RW_L_Wetness", "RW_L_WetnessDry", "RW_L_WetnessRain",
              "RW_L_Decal", "RW_BevelEdge", "RW_RayCavity")
V07_SCENE_PROPS = ("rw_age", "rw_dirt", "rw_dust", "rw_wetness", "rw_rain", "rw_ground_z", "rw_splash_height",
                   "rw_preview")
V07_OBJECT_PROPS = ("rw_seed", "rw_wear", "rw_dirt_amt", "rw_is_ground")


def is_v07_material(mat):
    st = getattr(mat, "realworn", None)
    if st is None or mat.node_tree is None or not st.applied:
        return False
    if st.schema_version >= 2 and st.stack is not None:
        return False  # a v2.x or v3 stack
    return any(n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None and n.node_tree.name == "RW_Stack"
               for n in mat.node_tree.nodes) or st.schema_version < 2


def find_v07():
    """{'materials': [...], 'objects': [...]} still carrying v0.7 weathering."""
    mats = [m for m in bpy.data.materials if is_v07_material(m)]
    obs = [o for o in bpy.data.objects if o.type == "MESH" and naming.OB_SETUP not in o and (
        any(k in o for k in V07_OBJECT_PROPS) or "rw_paint" in o.data.color_attributes)]
    return {"materials": mats, "objects": obs}


def remove_v07():
    """Restore every v0.7 material exactly and clear v0.7 data. Returns report tuples."""
    rep = []
    found = find_v07()
    for m in found["materials"]:
        try:
            snap = snapshot.loads(m.realworn.snapshot)
        except ValueError:
            rep.append(("ERROR", "{}: v0.7 snapshot unreadable".format(m.name)))
            continue
        diffs = snapshot.restore(m.node_tree, snap)
        for n in [n for n in m.node_tree.nodes if nodeutil.is_owned(n)]:
            m.node_tree.nodes.remove(n)
        if diffs:
            rep.append(("WARNING", "{}: restored with {} difference(s): {}".format(m.name, len(diffs), diffs[0])))
        st = m.realworn
        st.applied = False
        st.snapshot = ""
        st.mode = ""
        st.schema_version = 0
        for k in ("preset", "decals"):
            if k in st:
                del st[k]
    for o in found["objects"]:
        for mod in [md for md in o.modifiers if md.name in V07_MODIFIERS]:
            o.modifiers.remove(mod)
        me = o.data
        if "rw_paint" in me.color_attributes and me.get("rw_created_paint", True):
            me.color_attributes.remove(me.color_attributes["rw_paint"])
        if "rw_created_paint" in me:
            del me["rw_created_paint"]
        for k in V07_OBJECT_PROPS:
            if k in o:
                del o[k]
    for sc in bpy.data.scenes:
        for k in V07_SCENE_PROPS:
            if k in sc:
                del sc[k]
    for e in [o for o in bpy.data.objects if o.type == "EMPTY" and o.get("rw_decal") and not _v2_decal(o)]:
        bpy.data.objects.remove(e)
    for name in V07_GROUPS:
        g = bpy.data.node_groups.get(name)
        if g is not None and g.users == 0:
            bpy.data.node_groups.remove(g)
    for m in [m for m in bpy.data.materials if m.name.startswith(V07_INNER_PREFIX) and m.users == 0]:
        bpy.data.materials.remove(m)
    rep.append(("INFO", "Removed v0.7 weathering from {} material(s) and {} object(s)".format(
        len(found["materials"]), len(found["objects"]))))
    return rep


def _v2_decal(empty):
    """A v2.x decal projector (handled by the v2 conversion, not by the v0.7 cleanup)."""
    return bool(empty.get("rw_v2_decal"))

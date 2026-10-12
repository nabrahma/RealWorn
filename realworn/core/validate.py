"""Validate Scene: report problems in RealWorn data (orphans, missing data, schema mismatches)."""

import bpy

from . import assets, decals, injector, masks, naming, nodeutil


def validate(scene=None):
    """Return a list of (level, message). Empty means everything checks out."""
    out = []
    build = assets.asset_build()
    for g in bpy.data.node_groups:
        if g.name.startswith("RW_") and "rw_schema" in g and g.name in naming.ALL_GROUPS:
            if g["rw_schema"] != naming.SCHEMA:
                out.append(("ERROR", "{}: schema {} (expected {}); reload the add-on to upgrade".format(
                    g.name, g["rw_schema"], naming.SCHEMA)))
            elif g.get("rw_build") != build:
                out.append(("WARNING", "{}: built from older builders; Rebuild Assets / reload upgrades it".format(
                    g.name)))
    for m in bpy.data.materials:
        if m.node_tree is None:
            continue
        owned = nodeutil.owned_nodes(m.node_tree)
        if owned and not m.realworn.applied:
            out.append(("ERROR", "{}: {} orphan RealWorn node(s) on an unweathered material".format(m.name, len(owned))))
        if m.realworn.applied:
            if not injector.stacks(m.node_tree):
                out.append(("ERROR", "{}: marked weathered but has no RW_Stack".format(m.name)))
            if not m.realworn.snapshot:
                out.append(("ERROR", "{}: weathered without a snapshot; Remove cannot restore it".format(m.name)))
            missing = [n for n in decals.material_decals(m) if not decals.is_decal(bpy.data.objects.get(n))]
            if missing:
                out.append(("WARNING", "{}: decal layers for deleted Empties {} (run Clean Up Decals)".format(
                    m.name, missing)))
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        mod = masks.masks_modifier(o)
        if o.realworn.applied and mod is None:
            out.append(("ERROR", "{}: weathered but the RW_Masks modifier is missing".format(o.name)))
        if mod is not None:
            if naming.ATTR_PAINT not in o.data.color_attributes:
                out.append(("WARNING", "{}: no rw_paint attribute (Paint Wear will create it)".format(o.name)))
            for coll, inp in ((naming.COLL_GROUND, "Ground"), (naming.COLL_OCCLUDERS, "Occluders")):
                c = bpy.data.collections.get(coll)
                if c is not None and o.name in c.objects and masks.get_input(mod, inp) is not None:
                    out.append(("ERROR", "{}: reads {} which contains itself (dependency cycle)".format(o.name, coll)))
            if masks.has_nonuniform_scale(o):
                out.append(("INFO", "{}: non-uniform scale; mask widths use the mean scale".format(o.name)))
            if masks.large_ngon_count(o.data):
                out.append(("INFO", "{}: large n-gons; masks smear across them".format(o.name)))
    for sc in ([scene] if scene is not None else bpy.data.scenes):
        p = sc.realworn
        for prop, key in (("age", naming.SC_AGE), ("dirt", naming.SC_DIRT), ("dust", naming.SC_DUST),
                          ("wetness", naming.SC_WETNESS)):
            if key in sc and abs(sc[key] - getattr(p, prop)) > 1e-6:
                out.append(("WARNING", "{}: {} out of sync ({} vs {})".format(sc.name, key, sc[key], getattr(p, prop))))
    return out

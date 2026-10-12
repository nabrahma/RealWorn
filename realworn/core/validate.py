"""Validate (realworn.validate): orphan nodes, missing images, unsaved masks, schema mismatches."""

import os

import bpy

from . import assets, injector, masks, naming, nodeutil


def validate(scene=None):
    """Return a list of (level, message). Empty means everything checks out."""
    out = []
    build = assets.asset_build()
    for g in bpy.data.node_groups:
        if g.name in naming.ALL_GROUPS and "rw_schema" in g:
            if g["rw_schema"] != naming.SCHEMA:
                out.append(("ERROR", "{}: schema {} (expected {}); reload the add-on to upgrade".format(
                    g.name, g["rw_schema"], naming.SCHEMA)))
            elif g.get("rw_build") != build:
                out.append(("WARNING", "{}: built from older builders; Rebuild Assets upgrades it".format(g.name)))
        if g.name.startswith(naming.STACK_PREFIX) and g.users == 0:
            out.append(("WARNING", "{}: stack group with no material".format(g.name)))
    for m in bpy.data.materials:
        if m.node_tree is None:
            continue
        owned = nodeutil.owned_nodes(m.node_tree)
        st = m.realworn
        if owned and not st.applied:
            out.append(("ERROR", "{}: {} orphan RealWorn node(s) on a material that is not set up".format(
                m.name, len(owned))))
        if not st.applied:
            continue
        if not injector.stacks(m.node_tree):
            out.append(("ERROR", "{}: set up but has no stack node".format(m.name)))
        if st.stack is None:
            out.append(("ERROR", "{}: set up but RW_Stack group is missing".format(m.name)))
        if not st.snapshot:
            out.append(("ERROR", "{}: no snapshot; Remove cannot restore it".format(m.name)))
        if st.schema_version != naming.SCHEMA:
            out.append(("WARNING", "{}: schema {} (current {})".format(m.name, st.schema_version, naming.SCHEMA)))
        ids = [ly.id for ly in st.layers]
        if len(set(ids)) != len(ids):
            out.append(("ERROR", "{}: duplicate layer ids".format(m.name)))
        below = set()
        for ly in st.layers:
            for ing in ly.ingredients:
                if ing.kind == "REFERENCE" and ing.ref_layer_id and ing.ref_layer_id not in below:
                    out.append(("ERROR", "{}: layer '{}' references a layer that is not below it".format(
                        m.name, ly.name)))
            below.add(ly.id)
            for attr in ("mask_image", "content_image"):
                img = getattr(ly, attr)
                if img is None:
                    continue
                if img.is_dirty and img.packed_file is None and not img.filepath:
                    out.append(("INFO", "{} / {}: {} has unsaved paint (packed on save)".format(
                        m.name, ly.name, img.name)))
                if img.source == "FILE" and img.packed_file is None and \
                        not os.path.exists(bpy.path.abspath(img.filepath)):
                    out.append(("WARNING", "{} / {}: image {} is missing".format(m.name, ly.name, img.name)))
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        mod = masks.masks_modifier(o)
        if mod is not None:
            c = bpy.data.collections.get(naming.COLL_GROUND)
            if c is not None and o.name in c.objects and masks.get_input(mod, "Ground") is not None:
                out.append(("ERROR", "{}: reads {} which contains itself (dependency cycle)".format(
                    o.name, naming.COLL_GROUND)))
            if masks.has_nonuniform_scale(o):
                out.append(("INFO", "{}: non-uniform scale; generator widths use the mean scale".format(o.name)))
        if naming.OB_SETUP in o and naming.UV_PAINT not in o.data.uv_layers:
            out.append(("ERROR", "{}: set up but the RW_Paint UV map is missing".format(o.name)))
    return out

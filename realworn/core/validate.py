"""Validate (realworn.validate): orphan nodes, missing images, unsaved masks, schema mismatches."""

import os

import bpy

from . import injector, naming, nodeutil


def validate(scene=None):
    """Return a list of (level, message). Empty means everything checks out."""
    out = []
    for g in bpy.data.node_groups:
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
            out.append(("WARNING", "{}: schema {} (current {}); convert it from the panel".format(
                m.name, st.schema_version, naming.SCHEMA)))
        ids = [ly.id for ly in st.layers]
        if len(set(ids)) != len(ids):
            out.append(("ERROR", "{}: duplicate layer ids".format(m.name)))
        for ly in st.layers:
            for img in (ly.mask_image, ly.baked_image):
                if img is None:
                    continue
                if img.is_dirty and img.packed_file is None and not img.filepath:
                    out.append(("INFO", "{} / {}: {} has unsaved paint (packed on save)".format(
                        m.name, ly.name, img.name)))
                if img.source == "FILE" and img.packed_file is None and \
                        not os.path.exists(bpy.path.abspath(img.filepath)):
                    out.append(("WARNING", "{} / {}: image {} is missing".format(m.name, ly.name, img.name)))
    for o in bpy.data.objects:
        if o.type == "MESH" and naming.OB_SETUP in o and naming.UV_PAINT not in o.data.uv_layers:
            out.append(("ERROR", "{}: set up but the RW_Paint UV map is missing".format(o.name)))
    return out

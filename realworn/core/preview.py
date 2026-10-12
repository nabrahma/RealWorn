"""Mask Preview (MASK-6): temporarily route one mask to the material output as emission.

The chosen mask is also written to the scene property rw_preview, which the RW_Stack
"Preview" output reads, so switching between masks needs no shader recompile.
Toggle back to NONE (or save the file) to restore every material exactly.
"""

import json

import bpy

from . import naming, nodeutil

PREVIEW_KEY = "rw_preview_src"
_ATTR_FOR_MODE = {
    "EDGE": naming.ATTR_EDGE,
    "CAVITY": naming.ATTR_CAVITY,
    "CONTACT": naming.ATTR_CONTACT,
    "SHELTER": naming.ATTR_SHELTER,
}


def weathered_objects(scene):
    return [o for o in scene.objects if o.type == "MESH" and o.modifiers.get(naming.MOD_MASKS)]


def _materials(objects):
    seen = []
    for o in objects:
        for slot in o.material_slots:
            m = slot.material
            if m is not None and m.node_tree is not None and m.library is None and m not in seen:
                seen.append(m)
    return seen


def enable(mat, mode):
    nt = mat.node_tree
    out = nodeutil.output_node(nt)
    if out is None:
        return False
    emis = nodeutil.find(nt, "preview")
    if emis is None:
        src = nodeutil.link_source(out.inputs["Surface"])
        mat[PREVIEW_KEY] = json.dumps(nodeutil.socket_ref(src) if src is not None else None)
        emis = nodeutil.new(nt, "ShaderNodeEmission", "preview", (out.location.x, out.location.y + 220))
        attr = nodeutil.new(nt, "ShaderNodeAttribute", "preview_attr", (out.location.x - 200, out.location.y + 220))
        nt.links.new(emis.outputs[0], out.inputs["Surface"])
    attr = nodeutil.find(nt, "preview_attr")
    stack = nodeutil.find(nt, "stack.0")
    if stack is not None and "Preview" in stack.outputs:
        nt.links.new(stack.outputs["Preview"], emis.inputs["Color"])
    else:
        attr.attribute_type = "GEOMETRY"
        attr.attribute_name = _ATTR_FOR_MODE.get(mode, "")
        nt.links.new(attr.outputs["Fac"], emis.inputs["Color"])
    return True


def disable(mat):
    if PREVIEW_KEY not in mat:
        return False
    nt = mat.node_tree
    ref = json.loads(mat[PREVIEW_KEY])
    for role in ("preview", "preview_attr"):
        n = nodeutil.find(nt, role)
        if n is not None:
            nt.nodes.remove(n)
    out = nodeutil.output_node(nt)
    src = nodeutil.resolve(nt, ref)
    if out is not None and src is not None:
        nt.links.new(src, out.inputs["Surface"])
    del mat[PREVIEW_KEY]
    return True


def set_preview(scene, mode, objects=None):
    """Switch every weathered material in the scene to `mode` ('NONE' restores)."""
    scene[naming.SC_PREVIEW] = float(naming.PREVIEW_CODES[mode])
    mats = _materials(objects if objects is not None else weathered_objects(scene))
    if mode == "NONE":
        restore_all()
        return len(mats)
    for m in mats:
        enable(m, mode)
    return len(mats)


def restore_all():
    n = 0
    for m in bpy.data.materials:
        if m.node_tree is not None and PREVIEW_KEY in m:
            n += disable(m)
    return n

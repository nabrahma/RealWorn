"""Material injector (SET-2, SET-5, SET-6, REM-1): wrap a material's base and restore it exactly.

Only this module touches a material's top-level node tree (the compiler owns the inside of
RW_Stack::<material>).

Setup: snapshot the tree; find the Principled BSDF(s) feeding the active output (through Mix /
Add Shader, reroutes and groups, which are never edited); per Principled insert one group node
RW::stack.<i> instancing RW_Stack::<material> between the captured channels and the Principled
inputs. Height is captured from a Displacement node, a Bump node, or an image named height /
disp / displacement. Materials without a Principled BSDF get a Principled overlay mixed in by the
stack's Coverage output (SHADER mode). Remove deletes every owned node and restores links,
defaults and layout from the snapshot, then checks the tree equals it.
"""

import json

import bpy

from . import naming, nodeutil, snapshot

STACK_ROLE = "stack"
_PASS_THROUGH = {"ShaderNodeMixShader", "ShaderNodeAddShader", "NodeReroute", "ShaderNodeGroup"}
_HEIGHT_WORDS = ("height", "disp", "displacement")


class InjectError(Exception):
    pass


# ------------------------------------------------------------------ queries
def find_principled(tree):
    """(output node, [Principled BSDF nodes reachable from its Surface input])."""
    out = nodeutil.output_node(tree)
    if out is None:
        return None, []
    found, seen = [], set()

    def walk(sock):
        for link in sock.links:
            if link.is_muted:
                continue
            n = link.from_node
            if n.name in seen:
                continue
            seen.add(n.name)
            if n.bl_idname == "ShaderNodeBsdfPrincipled":
                found.append(n)
            elif n.bl_idname in _PASS_THROUGH:
                for s in n.inputs:
                    if s.type == "SHADER" or n.bl_idname == "NodeReroute":
                        walk(s)

    walk(out.inputs["Surface"])
    found.sort(key=lambda n: n.name)
    return out, found


def stacks(tree):
    return [n for n in tree.nodes if nodeutil.is_owned(n) and n.name.startswith(naming.node_name(STACK_ROLE + "."))
            and n.bl_idname == "ShaderNodeGroup"]


def is_setup(mat):
    return bool(mat is not None and mat.node_tree is not None and mat.realworn.applied)


def can_edit(mat):
    if mat is None or mat.node_tree is None:
        return False, "no node tree"
    if mat.library is not None and mat.override_library is None:
        return False, "linked from a library (make a library override first)"
    return True, ""


# ------------------------------------------------------------------ helpers
def _place(node, x, y):
    if hasattr(node, "location_absolute"):
        node.location_absolute = (x, y)
    else:
        node.location = (x, y)


def _abs(node):
    loc = node.location_absolute if hasattr(node, "location_absolute") else node.location
    return loc.x, loc.y


def height_source(tree, principled, out):
    """SET-5: Displacement node height, else a Bump node's height, else an image named like a
    height map, else None (the stack then uses 0.5, i.e. flat)."""
    disp = nodeutil.link_source(out.inputs["Displacement"])
    if disp is not None and disp.node.bl_idname == "ShaderNodeDisplacement":
        h = nodeutil.link_source(disp.node.inputs["Height"])
        if h is not None:
            return h
    if principled is not None:
        n = nodeutil.link_source(principled.inputs["Normal"])
        if n is not None and n.node.bl_idname == "ShaderNodeBump":
            h = nodeutil.link_source(n.node.inputs["Height"])
            if h is not None:
                return h
    for n in tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image is not None and not nodeutil.is_owned(n):
            stem = n.image.name.lower()
            if any(w in stem for w in _HEIGHT_WORDS):
                return n.outputs["Color"]
    return None


def _new_stack(tree, mat, idx, frame, x, y):
    stack = nodeutil.new(tree, "ShaderNodeGroup", "{}.{}".format(STACK_ROLE, idx), frame=frame)
    stack.node_tree = mat.realworn.stack
    stack.label = "RealWorn Layers"
    stack.width = 240
    _place(stack, x, y)
    geom = nodeutil.new(tree, "ShaderNodeNewGeometry", "geom.{}".format(idx), frame=frame)
    geom.hide = True
    _place(geom, x - 200, y - 40)
    return stack, geom


def _inject_channel(tree, mat, principled, idx, frame, out):
    px, py = _abs(principled)
    stack, geom = _new_stack(tree, mat, idx, frame, px - 320, py)
    stack["rw_principled"] = principled.name  # Bake swaps and Restore Live Stack relink by this
    hs = height_source(tree, principled, out)  # before the Normal input is relinked to the stack
    for ch in naming.CHANNELS:
        pin, sin = principled.inputs[ch], stack.inputs[ch]
        src = nodeutil.link_source(pin)
        if src is not None:
            tree.links.new(src, sin)
        elif ch in naming.NORMAL_CHANNELS:
            tree.links.new(geom.outputs["Normal"], sin)
        else:
            sin.default_value = pin.default_value
        tree.links.new(stack.outputs[ch], pin)
    if hs is not None:
        tree.links.new(hs, stack.inputs["Height"])
    return stack


def _inject_shader(tree, mat, out, frame):
    """No Principled BSDF: mix the original shader with a layered Principled by coverage."""
    ox, oy = _abs(out)
    src = nodeutil.link_source(out.inputs["Surface"])
    stack, geom = _new_stack(tree, mat, 0, frame, ox - 700, oy - 260)
    bsdf = nodeutil.new(tree, "ShaderNodeBsdfPrincipled", "overlay_bsdf", frame=frame)
    stack["rw_principled"] = bsdf.name
    _place(bsdf, ox - 420, oy - 260)
    for ch in naming.CHANNELS:
        if ch in naming.NORMAL_CHANNELS:
            tree.links.new(geom.outputs["Normal"], stack.inputs[ch])
        else:
            stack.inputs[ch].default_value = bsdf.inputs[ch].default_value
        tree.links.new(stack.outputs[ch], bsdf.inputs[ch])
    stack.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    mix = nodeutil.new(tree, "ShaderNodeMixShader", "overlay_mix", frame=frame)
    _place(mix, ox - 180, oy)
    tree.links.new(stack.outputs["Coverage"], mix.inputs[0])
    if src is not None:
        tree.links.new(src, mix.inputs[1])
    tree.links.new(bsdf.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], out.inputs["Surface"])
    return stack


# -------------------------------------------------------------------- setup
def inject(mat):
    """Wrap `mat` with its stack group (empty: pass-through). Raises InjectError."""
    from . import compiler
    ok, why = can_edit(mat)
    if not ok:
        raise InjectError("{}: {}".format(mat.name if mat else "None", why))
    if is_setup(mat):
        return "already"
    tree = mat.node_tree
    out, princ = find_principled(tree)
    if out is None:
        raise InjectError("{}: no Material Output node".format(mat.name))
    snap = snapshot.serialize(tree)
    st = mat.realworn
    st.snapshot = snapshot.dumps(snap)
    st.schema_version = naming.SCHEMA
    try:
        compiler.ensure_group(mat)
        frame = nodeutil.ensure_frame(tree)
        if princ:
            for i, p in enumerate(princ):
                _inject_channel(tree, mat, p, i, frame, out)
            st.mode = "CHANNEL"
        else:
            _inject_shader(tree, mat, out, frame)
            st.mode = "SHADER"
        st.applied = True
        compiler.compile(mat)
    except Exception:
        snapshot.restore(tree, snap)
        _drop_group(mat)
        st.applied = False
        st.snapshot = ""
        raise
    return "setup"


def _drop_group(mat):
    g = mat.realworn.stack
    mat.realworn.stack = None
    if g is not None and g.users == 0:
        bpy.data.node_groups.remove(g)


def restore(mat):
    """Remove every RealWorn node and restore the original tree. Returns remaining diffs."""
    if not is_setup(mat):
        return []
    set_mask_view(mat, False)
    snap = snapshot.loads(mat.realworn.snapshot)
    diffs = snapshot.restore(mat.node_tree, snap)
    if not diffs:
        st = mat.realworn
        st.applied = False
        st.snapshot = ""
        st.mode = ""
        st.baked = False
        _drop_group(mat)
        if mat.get("rw_disp_method") is not None:
            mat.displacement_method = mat["rw_disp_method"]
            del mat["rw_disp_method"]
    return diffs  # on mismatch the snapshot is kept for a retry


# ------------------------------------------------- outputs outside the stack
def sync_outputs(mat):
    """Displacement-mode damage: stack Displacement (mm) -> owned Displacement node -> output
    (added to the user's own displacement if there is one). Removed when unused."""
    tree = mat.node_tree
    g = mat.realworn.stack
    if tree is None or g is None or not mat.realworn.applied:
        return
    used = any(ly.visible and ly.type == "DAMAGE" and ly.damage.depth_mode == "DISPLACEMENT"
               for ly in mat.realworn.layers)
    out = nodeutil.output_node(tree)
    disp = nodeutil.find(tree, "disp")
    st = stacks(tree)
    if not used or not st or out is None:
        if disp is not None:
            add = nodeutil.find(tree, "disp_add")
            orig = None
            if add is not None:
                orig = nodeutil.link_source(add.inputs[0])
                tree.nodes.remove(add)
            tree.nodes.remove(disp)
            if orig is not None:
                tree.links.new(orig, out.inputs["Displacement"])
            if mat.get("rw_disp_method") is not None:
                mat.displacement_method = mat["rw_disp_method"]
                del mat["rw_disp_method"]
        return
    if disp is None:
        frame = nodeutil.ensure_frame(tree)
        disp = nodeutil.new(tree, "ShaderNodeDisplacement", "disp", frame=frame)
        disp.inputs["Scale"].default_value = 0.001  # stack heights are millimetres
        disp.inputs["Midlevel"].default_value = 0.0
        x, y = _abs(out)
        _place(disp, x - 220, y - 300)
        orig = nodeutil.link_source(out.inputs["Displacement"])
        if orig is not None:
            add = nodeutil.new(tree, "ShaderNodeVectorMath", "disp_add", frame=frame)
            add.operation = "ADD"
            _place(add, x - 60, y - 300)
            tree.links.new(orig, add.inputs[0])
            tree.links.new(disp.outputs[0], add.inputs[1])
            tree.links.new(add.outputs[0], out.inputs["Displacement"])
        else:
            tree.links.new(disp.outputs[0], out.inputs["Displacement"])
        if mat.get("rw_disp_method") is None:
            mat["rw_disp_method"] = mat.displacement_method
        mat.displacement_method = "BOTH"
    tree.links.new(st[0].outputs["Displacement"], disp.inputs["Height"])


def set_mask_view(mat, state):
    """PNT-8: route the stack's Mask View output to the surface as greyscale emission."""
    tree = mat.node_tree
    if tree is None:
        return False
    out = nodeutil.output_node(tree)
    emis = nodeutil.find(tree, "maskview")
    if state:
        st = stacks(tree)
        if not st or out is None:
            return False
        if emis is None:
            src = nodeutil.link_source(out.inputs["Surface"])
            mat["rw_maskview_src"] = json.dumps(nodeutil.socket_ref(src) if src is not None else None)
            emis = nodeutil.new(tree, "ShaderNodeEmission", "maskview", frame=nodeutil.ensure_frame(tree))
            x, y = _abs(out)
            _place(emis, x, y + 200)
        tree.links.new(st[0].outputs["Mask View"], emis.inputs["Color"])
        tree.links.new(emis.outputs[0], out.inputs["Surface"])
        return True
    if emis is None:
        return False
    tree.nodes.remove(emis)
    ref = json.loads(mat.get("rw_maskview_src", "null"))
    src = nodeutil.resolve(tree, ref)
    if out is not None and src is not None:
        tree.links.new(src, out.inputs["Surface"])
    if "rw_maskview_src" in mat:
        del mat["rw_maskview_src"]
    return True

"""Material injector (SET-1, SET-4, SET-6, G6): wrap a material's base and restore it exactly.

Only this module touches a material's top-level node tree (the compiler owns the inside of
RW_Stack::<material>).

Setup: snapshot the tree; find the Principled BSDF(s) feeding the active output (through Mix /
Add Shader, reroutes and groups, which are never edited); per Principled insert one group node
RW::stack.<i> instancing RW_Stack::<material> between the captured channels (Base Color,
Roughness, Metallic, Normal) and the Principled inputs. Materials without a Principled BSDF get a
Principled overlay mixed in by the stack's Coverage output (SHADER mode).

Height (SET-4): the stack's one shared height (metres) feeds an owned Displacement node (Midlevel
0, Scale 1) on the Material Output, the classic Displacement node with the material on Bump.
It is added to the material's own displacement, or replaces it once a texture set is loaded onto
the Base (the set is then the base look).

Remove deletes every owned node and restores links, defaults and layout from the snapshot, then
checks the tree equals it.

Other add-ons (3.1, RealDust): nodes another add-on owns (an *_owned flag other than rw_owned)
are never edited or deleted. RealWorn always goes under a layer another add-on inserted at the
Principled boundary (channel_target), so dust stays on top whatever the order. While such nodes
exist, or existed when the material was set up, Remove is surgical: each channel is relinked from
the stack's input source to the stack's output targets and only RealWorn's nodes are deleted; the
whole tree is never restored from the snapshot.
"""

import json

import bpy

from . import naming, nodeutil, snapshot

STACK_ROLE = "stack"
_PASS_THROUGH = {"ShaderNodeMixShader", "ShaderNodeAddShader", "NodeReroute", "ShaderNodeGroup"}


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
                if not nodeutil.is_foreign(n):  # another add-on's overlay BSDF is not ours to wrap
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


def channel_target(tree, principled, ch):
    """The socket RealWorn feeds for channel `ch` of `principled`: the Principled input itself, or
    the matching input of another add-on's layer sitting on it (3.1), so RealWorn stays under it."""
    sock = principled.inputs[ch]
    seen = set()
    while True:
        src = nodeutil.link_source(sock)
        if src is None or not nodeutil.is_foreign(src.node) or src.node.name in seen:
            return sock
        seen.add(src.node.name)
        nxt = src.node.inputs.get(ch)
        if nxt is None:
            return sock
        sock = nxt


def _inject_channel(tree, mat, principled, idx, frame):
    px, py = _abs(principled)
    stack, geom = _new_stack(tree, mat, idx, frame, px - 320, py)
    stack["rw_principled"] = principled.name  # Bake swaps and Restore Live Stack relink by this
    for ch in naming.CHANNELS:
        pin, sin = channel_target(tree, principled, ch), stack.inputs[ch]
        src = nodeutil.link_source(pin)
        if src is not None and nodeutil.is_foreign(src.node):
            src = None  # another add-on's helper (its own normal source): treat as unlinked
        if src is not None:
            tree.links.new(src, sin)
        elif ch in naming.NORMAL_CHANNELS:
            tree.links.new(geom.outputs["Normal"], sin)
        else:
            sin.default_value = pin.default_value
        tree.links.new(stack.outputs[ch], pin)
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
    mat["rw_foreign"] = json.dumps(nodeutil.foreign_nodes(tree))
    st.schema_version = naming.SCHEMA
    mat["rw_orig_disp"] = json.dumps(_disp_ref(tree, out))
    try:
        compiler.ensure_group(mat)
        frame = nodeutil.ensure_frame(tree)
        if princ:
            for i, p in enumerate(princ):
                _inject_channel(tree, mat, p, i, frame)
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
    from . import reveal
    if not is_setup(mat):
        return []
    set_mask_view(mat, False)
    if nodeutil.foreign_nodes(mat.node_tree) or json.loads(mat.get("rw_foreign", "[]")):
        return _restore_surgical(mat)
    snap = snapshot.loads(mat.realworn.snapshot)
    diffs = snapshot.restore(mat.node_tree, snap)
    if not diffs:
        st = mat.realworn
        st.applied = False
        st.snapshot = ""
        st.mode = ""
        st.baked = False
        if "rw_orig_disp" in mat:
            del mat["rw_orig_disp"]
        if "rw_foreign" in mat:
            del mat["rw_foreign"]
        _drop_group(mat)
        reveal.restore(mat)
    return diffs  # on mismatch the snapshot is kept for a retry


def _relink_around(tree, node, in_name, out_name):
    """The input's source feeds every target of the output; RealWorn's own sources count as
    unlinked (the target then falls back to its own default value, which RealWorn never changed)."""
    sin, sout = node.inputs.get(in_name), node.outputs.get(out_name)
    if sin is None or sout is None:
        return
    src = nodeutil.link_source(sin)
    if src is not None and nodeutil.is_owned(src.node):
        src = None
    targets = [l.to_socket for l in sout.links if not nodeutil.is_owned(l.to_node)]
    for l in list(sout.links):
        tree.links.remove(l)
    if src is not None:
        for tgt in targets:
            tree.links.new(src, tgt)


def _restore_surgical(mat):
    """3.1: another add-on's nodes are (or were) in the tree. Relink around RealWorn's nodes and
    delete only those; the snapshot is not restored (it would undo the other add-on's work)."""
    from . import bake, reveal
    tree = mat.node_tree
    st = mat.realworn
    if st.baked:
        bake.restore_live(mat)
    for stack in stacks(tree):
        for ch in naming.CHANNELS:
            _relink_around(tree, stack, ch, ch)
    mix = nodeutil.find(tree, "overlay_mix")
    if mix is not None:
        src = nodeutil.link_source(mix.inputs[1])
        targets = [l.to_socket for l in mix.outputs[0].links]
        for l in list(mix.outputs[0].links):
            tree.links.remove(l)
        if src is not None:
            for tgt in targets:
                tree.links.new(src, tgt)
    unlink_displacement(mat)
    for n in [n for n in tree.nodes if nodeutil.is_owned(n) and n.bl_idname != "NodeFrame"]:
        tree.nodes.remove(n)
    for n in [n for n in tree.nodes if nodeutil.is_owned(n)]:
        tree.nodes.remove(n)
    st.applied = False
    st.snapshot = ""
    st.mode = ""
    st.baked = False
    for k in ("rw_orig_disp", "rw_foreign"):
        if k in mat:
            del mat[k]
    _drop_group(mat)
    reveal.restore(mat)
    return []


# ------------------------------------------------- outputs outside the stack
def _disp_ref(tree, out):
    src = nodeutil.link_source(out.inputs["Displacement"]) if out is not None else None
    return nodeutil.socket_ref(src) if src is not None else None


def sync_outputs(mat):
    """SET-4: stack Displacement (metres) -> owned Displacement node -> Material Output; added to
    the material's own displacement, or replacing it when a texture set is loaded onto the Base.
    Removed (and the original link restored) when nothing in the stack has height."""
    from . import compiler
    tree = mat.node_tree
    g = mat.realworn.stack
    if tree is None or g is None or not mat.realworn.applied or mat.realworn.baked:
        return
    out = nodeutil.output_node(tree)
    st = stacks(tree)
    used = bool(st) and out is not None and compiler.has_height(mat)
    replace = mat.realworn.base.loaded()
    orig = nodeutil.resolve(tree, json.loads(mat.get("rw_orig_disp", "null")))
    disp, add = nodeutil.find(tree, "disp"), nodeutil.find(tree, "disp_add")
    want_add = used and orig is not None and not replace
    if not used:
        for n in (add, disp):
            if n is not None:
                tree.nodes.remove(n)
        if out is not None and orig is not None and not out.inputs["Displacement"].is_linked:
            tree.links.new(orig, out.inputs["Displacement"])
        return
    frame = nodeutil.ensure_frame(tree)
    x, y = _abs(out)
    if disp is None:
        disp = nodeutil.new(tree, "ShaderNodeDisplacement", "disp", frame=frame)
        disp.inputs["Scale"].default_value = 1.0  # the stack's height is in metres
        disp.inputs["Midlevel"].default_value = 0.0
        _place(disp, x - 220, y - 300)
    tree.links.new(st[0].outputs["Displacement"], disp.inputs["Height"])
    if want_add:
        if add is None:
            add = nodeutil.new(tree, "ShaderNodeVectorMath", "disp_add", frame=frame)
            add.operation = "ADD"
            _place(add, x - 60, y - 300)
        tree.links.new(orig, add.inputs[0])
        tree.links.new(disp.outputs[0], add.inputs[1])
        tree.links.new(add.outputs[0], out.inputs["Displacement"])
    else:
        if add is not None:
            tree.nodes.remove(add)
        tree.links.new(disp.outputs[0], out.inputs["Displacement"])


def unlink_displacement(mat):
    """Bake: the baked normal map carries the relief, so the live height is unplugged."""
    tree = mat.node_tree
    out = nodeutil.output_node(tree)
    for role in ("disp_add", "disp"):
        n = nodeutil.find(tree, role)
        if n is not None:
            tree.nodes.remove(n)
    orig = nodeutil.resolve(tree, json.loads(mat.get("rw_orig_disp", "null")))
    if out is not None and orig is not None and not mat.realworn.base.loaded():
        tree.links.new(orig, out.inputs["Displacement"])


def set_mask_view(mat, state):
    """MSK-4: route the stack's Mask View output to the surface as greyscale emission."""
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

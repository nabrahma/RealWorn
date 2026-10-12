"""Material injector: rewire a material through RW_Stack, and remove it exactly.

Algorithm (PRD "Injection algorithm"):
1 snapshot the tree; 2 walk upstream from the active output's Surface through Mix/Add
Shader, reroutes and group nodes (groups are opaque, never edited) collecting Principled
BSDFs; 3 channel mode (one RW_Stack per Principled) or shader mode (Mix Shader overlay)
when there is none; 4-6 move each channel's incoming link (or copy its default) into the
stack and link the stack back out; 7 tag every inserted node (RW::<role>, rw_owned) in a
"RealWorn" frame; 8 Remove deletes owned nodes and restores links/defaults from the
snapshot, then asserts the tree equals the snapshot.
"""

import bpy

from . import assets, naming, nodeutil, presets, snapshot

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


def is_applied(mat):
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


def _height_source(tree, principled, out):
    """WX-3: the material's own height texture, if it has one (displacement or bump)."""
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
    return None


def _set(sock, value):
    if sock.type == "RGBA" and len(value) == 3:
        value = (*value, 1.0)
    sock.default_value = value


def _new_stack(tree, idx, frame, x, y):
    stack = nodeutil.new(tree, "ShaderNodeGroup", "{}.{}".format(STACK_ROLE, idx), frame=frame)
    stack.node_tree = bpy.data.node_groups[naming.SH_STACK]
    stack.label = "RealWorn Stack"
    stack.width = 240
    _place(stack, x, y)
    geom = nodeutil.new(tree, "ShaderNodeNewGeometry", "geom.{}".format(idx), frame=frame)
    geom.hide = True
    _place(geom, x - 200, y - 40)
    return stack, geom


def _inject_channel(tree, principled, idx, frame, out):
    px, py = _abs(principled)
    stack, geom = _new_stack(tree, idx, frame, px - 320, py)
    stack["rw_principled"] = principled.name  # Bake swaps and Restore Live Stack relink by this
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
    hs = _height_source(tree, principled, out)
    if hs is not None:
        tree.links.new(hs, stack.inputs["Surface Height"])
        stack.inputs["Has Surface Height"].default_value = 1.0
    return stack


def _inject_shader(tree, out, frame):
    """No Principled BSDF: mix the original shader with a weathered Principled by coverage."""
    ox, oy = _abs(out)
    src = nodeutil.link_source(out.inputs["Surface"])
    stack, geom = _new_stack(tree, 0, frame, ox - 700, oy - 260)
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


# ----------------------------------------------------------------- presets
def resolve_preset(mat, preset_id, obj_name=""):
    if preset_id and preset_id != "AUTO":
        return preset_id
    _, princ = find_principled(mat.node_tree)
    if princ:
        metal = princ[0].inputs["Metallic"].default_value
        rough = princ[0].inputs["Roughness"].default_value
    else:
        metal, rough = 0.0, 0.5
    return presets.choose_auto(metal, rough, "{} {}".format(obj_name, mat.name))


def set_preset_values(mat, preset_id):
    vals = presets.stack_inputs(presets.get(preset_id))
    for st in stacks(mat.node_tree):
        for k, v in vals.items():
            sock = st.inputs.get(k)
            if sock is not None:
                _set(sock, v)
    mat.realworn.preset = preset_id


# -------------------------------------------------------------------- apply
def apply(mat, preset_id="AUTO", obj_name=""):
    """Inject RW_Stack into `mat` (or update its preset if already weathered).

    Returns "applied" or "updated". Raises InjectError when the material cannot be used.
    """
    ok, why = can_edit(mat)
    if not ok:
        raise InjectError("{}: {}".format(mat.name if mat else "None", why))
    resolved = resolve_preset(mat, preset_id, obj_name)
    if is_applied(mat):
        assets.ensure_groups()
        set_preset_values(mat, resolved)
        return "updated"
    assets.ensure_groups()
    tree = mat.node_tree
    out, princ = find_principled(tree)
    if out is None:
        raise InjectError("{}: no Material Output node".format(mat.name))
    snap = snapshot.serialize(tree)
    mat.realworn.snapshot = snapshot.dumps(snap)
    mat.realworn.schema_version = naming.SCHEMA
    try:
        ox, oy = _abs(out)
        frame = nodeutil.ensure_frame(tree)
        if princ:
            for i, p in enumerate(princ):
                _inject_channel(tree, p, i, frame, out)
            mat.realworn.mode = "CHANNEL"
        else:
            _inject_shader(tree, out, frame)
            mat.realworn.mode = "SHADER"
        mat.realworn.applied = True
        set_preset_values(mat, resolved)
    except Exception:
        snapshot.restore(tree, snap)
        mat.realworn.applied = False
        mat.realworn.snapshot = ""
        raise
    return "applied"


def remove(mat):
    """Remove every RealWorn node and restore the original tree. Returns remaining diffs."""
    if not is_applied(mat):
        return []
    snap = snapshot.loads(mat.realworn.snapshot)
    diffs = snapshot.restore(mat.node_tree, snap)
    if not diffs:
        mat.realworn.applied = False
        mat.realworn.snapshot = ""
        mat.realworn.preset = ""
        mat.realworn.mode = ""
        mat.realworn.baked = False
        mat.realworn.decals = "[]"
    return diffs  # on mismatch the snapshot is kept for a retry


# ------------------------------------------------------- edge/cavity sources
def _ensure_source(tree, stack, role, group, out_name, in_name, frame):
    n = nodeutil.find(tree, role)
    if n is None:
        n = nodeutil.new(tree, "ShaderNodeGroup", role, frame=frame)
        n.node_tree = bpy.data.node_groups[group]
        n.hide = True
        x, y = _abs(stack)
        _place(n, x - 220, y - (120 if "bevel" in role else 160))
    tree.links.new(n.outputs[out_name], stack.inputs[in_name])
    return n


def _drop(tree, role):
    n = nodeutil.find(tree, role)
    if n is not None:
        tree.nodes.remove(n)


def _is_eevee(scene):
    return scene is not None and scene.render.engine.startswith("BLENDER_EEVEE")


def apply_sources(mat, edge_source, cavity_source, scene=None):
    """MASK-7 / Raycast cavity: insert source groups only when chosen (zero cost otherwise)."""
    tree = mat.node_tree
    frame = nodeutil.ensure_frame(tree)
    for st in stacks(tree):
        i = st.name.rsplit(".", 1)[-1]
        if edge_source == "ATTRIBUTE":
            _drop(tree, "bevel." + i)
            st.inputs["Attr Edge Weight"].default_value = 1.0
        else:
            _ensure_source(tree, st, "bevel." + i, naming.SH_BEVEL_EDGE, "Edge", "Extra Edge", frame)
            only_bevel = edge_source == "BEVEL" and not _is_eevee(scene)
            st.inputs["Attr Edge Weight"].default_value = 0.0 if only_bevel else 1.0
        st["rw_edge_source"] = edge_source
        if cavity_source == "ATTRIBUTE":
            _drop(tree, "raycav." + i)
            st.inputs["Attr Cavity Weight"].default_value = 1.0
        else:
            _ensure_source(tree, st, "raycav." + i, naming.SH_RAY_CAVITY, "Cavity", "Extra Cavity", frame)
            st.inputs["Attr Cavity Weight"].default_value = 0.0 if cavity_source == "RAYCAST" else 1.0
        st["rw_cavity_source"] = cavity_source


def update_sources(obj, scene=None):
    for slot in obj.material_slots:
        if is_applied(slot.material):
            apply_sources(slot.material, obj.realworn.edge_source, obj.realworn.cavity_source, scene)


def apply_engine_fallback(scene):
    """EEVEE has no Bevel node: Bevel-only edge source silently falls back to the attribute."""
    eevee = _is_eevee(scene)
    n = 0
    for mat in bpy.data.materials:
        if not is_applied(mat):
            continue
        for st in stacks(mat.node_tree):
            if st.get("rw_edge_source") == "BEVEL":
                st.inputs["Attr Edge Weight"].default_value = 1.0 if eevee else 0.0
                n += 1
    return n

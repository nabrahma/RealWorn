"""Helpers for nodes RealWorn inserts into user materials (name RW::<role>, rw_owned)."""

from . import naming


def tag(node, role, frame=None):
    node.name = naming.node_name(role)
    node[naming.OWNED_PROP] = True
    if frame is not None and node.bl_idname != "NodeFrame":
        node.parent = frame
    return node


def is_owned(node):
    return bool(node.get(naming.OWNED_PROP)) or naming.is_rw_name(node.name)


def owned_nodes(tree):
    return [n for n in tree.nodes if is_owned(n)]


def find(tree, role):
    n = tree.nodes.get(naming.node_name(role))
    return n if n is not None and is_owned(n) else None


def new(tree, idname, role, location=None, frame=None, label=None):
    n = tree.nodes.new(idname)
    tag(n, role, frame)
    if location is not None:
        n.location = location
    if label:
        n.label = label
    return n


def ensure_frame(tree, location=None):
    fr = find(tree, "frame")
    if fr is None:
        fr = new(tree, "NodeFrame", "frame", label=naming.FRAME_LABEL)
        fr.label = naming.FRAME_LABEL
        fr.use_custom_color = True
        fr.color = (0.35, 0.22, 0.12)
        fr.shrink = True
    if location is not None:
        fr.location = location
    return fr


def output_node(tree):
    """The active Material Output (ALL target first), or any output node."""
    out = None
    try:
        out = tree.get_output_node("ALL")
    except Exception:
        out = None
    if out is None:
        outs = [n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
        act = [n for n in outs if n.is_active_output]
        out = (act or outs or [None])[0]
    return out


def socket_ref(sock):
    """Stable reference to a socket: (node name, socket identifier, is_output)."""
    return [sock.node.name, sock.identifier, bool(sock.is_output)]


def resolve(tree, ref):
    if not ref:
        return None
    node = tree.nodes.get(ref[0])
    if node is None:
        return None
    socks = node.outputs if ref[2] else node.inputs
    for s in socks:
        if s.identifier == ref[1]:
            return s
    return None


def link_source(sock):
    """The socket feeding `sock`; None if unlinked or the link is muted (a muted link
    behaves as if it were not there)."""
    if sock.is_linked and sock.links and not sock.links[0].is_muted:
        return sock.links[0].from_socket
    return None

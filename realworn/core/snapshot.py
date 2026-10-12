"""Serialise a material node tree, diff two serialisations, and restore a tree exactly.

`serialize` reads Blender data but never imports bpy at module level; `diff` and the
helpers below it are pure Python and unit-tested outside Blender.
"""

import json

from . import naming

SCHEMA = 1
_ND = 6  # decimals kept for floats


# ------------------------------------------------------------------ helpers
def _round(v):
    if isinstance(v, float):
        r = round(v, _ND)
        return 0.0 if r == 0 else r
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    return v


def _value(v):
    """Socket/property value -> JSON-friendly value."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return _round(v)
    if hasattr(v, "name") and hasattr(v, "users"):  # an ID datablock
        return {"id": v.name}
    try:
        return _round([float(x) for x in v])
    except (TypeError, ValueError):
        return repr(type(v).__name__)


def _is_owned(node):
    return bool(node.get(naming.OWNED_PROP)) or naming.is_rw_name(node.name)


_SKIP_PROPS = {"rna_type", "name", "label", "location", "location_absolute", "width", "height", "parent", "mute", "hide",
               "select", "show_options", "show_preview", "show_texture", "dimensions", "inputs", "outputs",
               "internal_links", "use_custom_color", "color", "bl_idname", "bl_label", "bl_description",
               "bl_icon", "bl_static_type", "bl_width_default", "bl_width_min", "bl_width_max",
               "bl_height_default", "bl_height_min", "bl_height_max", "type", "is_active_output",
               "warning_propagation", "color_tag", "debug_zone_body_lazy_function_graph",
               "debug_zone_lazy_function_graph"}


def _node_props(node):
    out = {}
    for p in node.bl_rna.properties:
        ident = p.identifier
        if ident in _SKIP_PROPS or p.is_readonly and p.type != "POINTER":
            continue
        try:
            v = getattr(node, ident)
        except AttributeError:
            continue
        if p.type == "POINTER":
            if v is None:
                out[ident] = None
            elif hasattr(v, "users"):
                out[ident] = {"id": v.name}
            elif ident == "color_ramp":
                out[ident] = {"interp": v.interpolation, "mode": v.color_mode,
                              "el": [[_round(e.position), _round(list(e.color))] for e in v.elements]}
            elif ident == "mapping" and hasattr(v, "curves"):
                out[ident] = [[[_round(list(pt.location)), pt.handle_type] for pt in c.points] for c in v.curves]
            continue
        if p.type == "COLLECTION":
            continue
        out[ident] = _value(v)
    return out


def _sockets(socks):
    out = []
    for i, s in enumerate(socks):
        if hasattr(s, "default_value"):
            out.append([s.identifier, i, _value(s.default_value)])
    return out


# --------------------------------------------------------------- serialize
def serialize(tree, include_owned=False):
    nodes = {}
    for n in tree.nodes:
        if not include_owned and _is_owned(n):
            continue
        parent = n.parent.name if n.parent is not None else None
        nodes[n.name] = {
            "type": n.bl_idname,
            "label": n.label,
            "location": _round([n.location.x, n.location.y]),
            "width": _round(n.width),
            "parent": parent,
            "mute": n.mute,
            "hide": n.hide,
            "props": _node_props(n),
            "inputs": _sockets(n.inputs),
            "outputs": _sockets(n.outputs),
        }
    links = []
    for l in tree.links:
        if not include_owned and (_is_owned(l.from_node) or _is_owned(l.to_node)):
            continue
        links.append([l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier,
                      bool(l.is_muted)])
    links.sort()
    return {"schema": SCHEMA, "nodes": nodes, "links": links}


def dumps(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def loads(text):
    return json.loads(text)


# -------------------------------------------------------------------- diff
def diff(a, b):
    """Differences between two serialisations, as readable strings (empty == identical)."""
    out = []
    an, bn = a.get("nodes", {}), b.get("nodes", {})
    for name in sorted(set(an) - set(bn)):
        out.append("node removed: {}".format(name))
    for name in sorted(set(bn) - set(an)):
        out.append("node added: {}".format(name))
    for name in sorted(set(an) & set(bn)):
        x, y = an[name], bn[name]
        for k in sorted(set(x) | set(y)):
            if k in ("inputs", "outputs"):
                xs = {s[0]: s[2] for s in x.get(k, [])}
                ys = {s[0]: s[2] for s in y.get(k, [])}
                for sid in sorted(set(xs) | set(ys)):
                    if xs.get(sid) != ys.get(sid):
                        out.append("{}.{}[{}]: {!r} -> {!r}".format(name, k, sid, xs.get(sid), ys.get(sid)))
            elif k == "props":
                xp, yp = x.get(k, {}), y.get(k, {})
                for pk in sorted(set(xp) | set(yp)):
                    if xp.get(pk) != yp.get(pk):
                        out.append("{}.{}: {!r} -> {!r}".format(name, pk, xp.get(pk), yp.get(pk)))
            elif x.get(k) != y.get(k):
                out.append("{}.{}: {!r} -> {!r}".format(name, k, x.get(k), y.get(k)))
    al = {tuple(l) for l in a.get("links", [])}
    bl = {tuple(l) for l in b.get("links", [])}
    for l in sorted(al - bl):
        out.append("link removed: {}:{} -> {}:{}".format(*l[:4]))
    for l in sorted(bl - al):
        out.append("link added: {}:{} -> {}:{}".format(*l[:4]))
    return out


# ----------------------------------------------------------------- restore
def _sock(socks, identifier):
    for s in socks:
        if s.identifier == identifier:
            return s
    return None


def restore(tree, snap):
    """Delete RealWorn-owned nodes and put links, defaults and layout back from `snap`.

    Returns the remaining differences (empty when the tree matches the snapshot exactly).
    """
    for n in [n for n in tree.nodes if _is_owned(n)]:
        tree.nodes.remove(n)
    want = {tuple(l[:4]): l[4] for l in snap["links"]}
    for l in list(tree.links):
        key = (l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
        if key not in want:
            tree.links.remove(l)
    have = {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
            for l in tree.links}
    for key, muted in want.items():
        if key in have:
            continue
        fn, tn = tree.nodes.get(key[0]), tree.nodes.get(key[2])
        if fn is None or tn is None:
            continue
        fs, ts = _sock(fn.outputs, key[1]), _sock(tn.inputs, key[3])
        if fs is not None and ts is not None:
            link = tree.links.new(fs, ts)
            link.is_muted = muted
    for name, data in snap["nodes"].items():
        n = tree.nodes.get(name)
        if n is None:
            continue
        for kind, socks in (("inputs", n.inputs), ("outputs", n.outputs)):
            for sid, _idx, val in data[kind]:
                s = _sock(socks, sid)
                if s is None or not hasattr(s, "default_value"):
                    continue
                if _value(s.default_value) != val and not isinstance(val, (dict, str)):
                    try:
                        s.default_value = val
                    except (TypeError, ValueError, AttributeError):
                        pass
        if _round([n.location.x, n.location.y]) != data["location"]:
            n.location = data["location"]
        parent = data["parent"]
        if (n.parent.name if n.parent else None) != parent:
            n.parent = tree.nodes.get(parent) if parent else None
        if n.mute != data["mute"]:
            n.mute = data["mute"]
        if n.hide != data["hide"]:
            n.hide = data["hide"]
    return diff(snap, serialize(tree))

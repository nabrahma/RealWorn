"""Tiny DSL for building node groups from Python.

Builders are the source of truth for every RealWorn node group; this module keeps
them short. Values passed to helpers may be a constant or an output socket.
"""

import bpy

from ..core import naming

SOCKET_TYPES = {
    "FLOAT": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "BOOL": "NodeSocketBool",
    "COLOR": "NodeSocketColor",
    "VECTOR": "NodeSocketVector",
    "SHADER": "NodeSocketShader",
    "GEO": "NodeSocketGeometry",
    "COLLECTION": "NodeSocketCollection",
    "MATERIAL": "NodeSocketMaterial",
    "OBJECT": "NodeSocketObject",
}


def _first_out(node):
    for s in node.outputs:
        if s.enabled:
            return s
    return node.outputs[0]


def _is_socket(v):
    return isinstance(v, bpy.types.NodeSocket)


class Tree:
    """Wraps a node tree and offers short helpers for common nodes."""

    def __init__(self, tree):
        self.t = tree
        self.nodes = tree.nodes
        self.links = tree.links
        self.is_geo = tree.bl_idname == "GeometryNodeTree"
        self.gi = None
        self.go = None

    # ------------------------------------------------------------------ setup
    @classmethod
    def new_group(cls, name, kind):
        idname = {"SHADER": "ShaderNodeTree", "GEOMETRY": "GeometryNodeTree"}[kind]
        old = bpy.data.node_groups.get(name)
        if old is not None:
            old.name = name + ".old"
        ng = bpy.data.node_groups.new(name, idname)
        ng["rw_schema"] = naming.SCHEMA
        ng.use_fake_user = False
        t = cls(ng)
        t.gi = ng.nodes.new("NodeGroupInput")
        t.go = ng.nodes.new("NodeGroupOutput")
        if old is not None:
            old.user_remap(ng)
            bpy.data.node_groups.remove(old)
        return t

    def inp(self, name, stype, default=None, lo=None, hi=None, subtype=None, hide_value=False,
            description="", default_input=None, force_single=False):
        s = self.t.interface.new_socket(name, in_out="INPUT", socket_type=SOCKET_TYPES[stype])
        if subtype is not None:
            s.subtype = subtype
        if default is not None:
            if stype == "COLOR" and len(default) == 3:
                default = (*default, 1.0)
            s.default_value = default
        if lo is not None:
            s.min_value = lo
        if hi is not None:
            s.max_value = hi
        if hide_value:
            s.hide_value = True
        if description:
            s.description = description
        if default_input is not None:
            s.default_input = default_input
        if force_single:
            s.force_non_field = True
        return s

    def out(self, name, stype, description=""):
        s = self.t.interface.new_socket(name, in_out="OUTPUT", socket_type=SOCKET_TYPES[stype])
        if description:
            s.description = description
        return s

    def I(self, name):
        """Group input socket by name."""
        return self.gi.outputs[name]

    def O(self, name, value):
        """Link a value into the group output socket of the given name."""
        self.set(self.go.inputs[name], value)

    # ------------------------------------------------------------- primitives
    def set(self, sock, value):
        if value is None:
            return
        if isinstance(value, bpy.types.Node):
            value = _first_out(value)
        if _is_socket(value):
            self.links.new(value, sock)
            return
        if sock.type == "RGBA" and isinstance(value, (tuple, list)) and len(value) == 3:
            value = (*value, 1.0)
        if sock.type == "RGBA" and isinstance(value, (int, float)):
            value = (value, value, value, 1.0)
        if sock.type == "VECTOR" and isinstance(value, (int, float)):
            value = (value, value, value)
        sock.default_value = value

    def node(self, idname, *args, props=None, label=None, name=None, **kw):
        n = self.nodes.new(idname)
        for k, v in (props or {}).items():
            setattr(n, k, v)
        if label:
            n.label = label
        if name:
            n.name = name
        ins = [s for s in n.inputs if s.enabled and s.type != "CUSTOM"]
        for sock, v in zip(ins, args):
            self.set(sock, v)
        for k, v in kw.items():
            key = k.replace("_", " ")
            sock = None
            for s in n.inputs:
                if s.enabled and (s.identifier == k or s.name == key or s.name == k):
                    sock = s
                    break
            if sock is None:
                raise KeyError("{}: no input {!r}".format(idname, k))
            self.set(sock, v)
        return n

    def outp(self, node, name=None):
        if name is None:
            return _first_out(node)
        for s in node.outputs:
            if s.enabled and (s.name == name or s.identifier == name):
                return s
        raise KeyError("{}: no output {!r}".format(node.bl_idname, name))

    # ------------------------------------------------------------------- math
    def math(self, op, a, b=None, c=None, clamp=False, label=None):
        n = self.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        if label:
            n.label = label
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if c is not None:
            self.set(n.inputs[2], c)
        return n.outputs[0]

    def add(self, a, b, clamp=False):
        return self.math("ADD", a, b, clamp=clamp)

    def sub(self, a, b, clamp=False):
        return self.math("SUBTRACT", a, b, clamp=clamp)

    def mul(self, a, b, clamp=False):
        return self.math("MULTIPLY", a, b, clamp=clamp)

    def div(self, a, b, clamp=False):
        return self.math("DIVIDE", a, b, clamp=clamp)

    def mad(self, a, b, c, clamp=False):
        return self.math("MULTIPLY_ADD", a, b, c, clamp=clamp)

    def max(self, a, b):
        return self.math("MAXIMUM", a, b)

    def min(self, a, b):
        return self.math("MINIMUM", a, b)

    def pow(self, a, b):
        return self.math("POWER", a, b)

    def clamp(self, a):
        return self.math("ADD", a, 0.0, clamp=True)

    def inv(self, a, clamp=True):
        return self.math("SUBTRACT", 1.0, a, clamp=clamp)

    def mul_all(self, *vals, clamp=False):
        out = vals[0]
        for v in vals[1:]:
            out = self.mul(out, v)
        return self.clamp(out) if clamp else out

    def max_all(self, *vals):
        out = vals[0]
        for v in vals[1:]:
            out = self.max(out, v)
        return out

    def maprange(self, v, a, b, c=0.0, d=1.0, interp="LINEAR", clamp=True, label=None):
        n = self.nodes.new("ShaderNodeMapRange")
        n.interpolation_type = interp
        n.clamp = clamp
        if label:
            n.label = label
        self.set(n.inputs["Value"], v)
        self.set(n.inputs[1], a)
        self.set(n.inputs[2], b)
        self.set(n.inputs[3], c)
        self.set(n.inputs[4], d)
        return n.outputs["Result"]

    def smooth(self, v, a, b, label=None):
        return self.maprange(v, a, b, 0.0, 1.0, interp="SMOOTHSTEP", label=label)

    def mix(self, fac, a, b, dtype="RGBA", blend="MIX", clamp_factor=True, label=None):
        n = self.nodes.new("ShaderNodeMix")
        n.data_type = dtype
        if dtype == "RGBA":
            n.blend_type = blend
        n.clamp_factor = clamp_factor
        if label:
            n.label = label
        suffix = {"RGBA": "Color", "FLOAT": "Float", "VECTOR": "Vector"}[dtype]
        ins = {s.identifier: s for s in n.inputs}
        self.set(ins["Factor_Float"], fac)
        self.set(ins["A_" + suffix], a)
        self.set(ins["B_" + suffix], b)
        return next(s for s in n.outputs if s.identifier == "Result_" + suffix)

    def mixf(self, fac, a, b, label=None):
        return self.mix(fac, a, b, dtype="FLOAT", label=label)

    def mixv(self, fac, a, b, label=None):
        return self.mix(fac, a, b, dtype="VECTOR", label=label)

    def vmath(self, op, a, b=None, scale=None):
        n = self.nodes.new("ShaderNodeVectorMath")
        n.operation = op
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if scale is not None:
            self.set(n.inputs["Scale"], scale)
        if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE"):
            return n.outputs["Value"]
        return n.outputs["Vector"]

    def sep(self, v):
        n = self.nodes.new("ShaderNodeSeparateXYZ")
        self.set(n.inputs[0], v)
        return n.outputs["X"], n.outputs["Y"], n.outputs["Z"]

    def comb(self, x, y, z):
        n = self.nodes.new("ShaderNodeCombineXYZ")
        self.set(n.inputs[0], x)
        self.set(n.inputs[1], y)
        self.set(n.inputs[2], z)
        return n.outputs[0]

    def value(self, v, label=None, name=None):
        n = self.nodes.new("ShaderNodeValue")
        n.outputs[0].default_value = v
        if label:
            n.label = label
        if name:
            n.name = name
        return n.outputs[0]

    # ----------------------------------------------------------- shader only
    def attr(self, name, kind="GEOMETRY", out="Fac"):
        n = self.nodes.new("ShaderNodeAttribute")
        n.attribute_type = kind
        n.attribute_name = name
        n.label = name
        return n.outputs[out]

    def noise(self, vector, scale, detail=2.0, roughness=0.5, w=None, out="Fac", dims="3D", distortion=0.0):
        n = self.nodes.new("ShaderNodeTexNoise")
        n.noise_dimensions = dims
        self.set(n.inputs["Vector"], vector)
        self.set(n.inputs["Scale"], scale)
        self.set(n.inputs["Detail"], detail)
        self.set(n.inputs["Roughness"], roughness)
        self.set(n.inputs["Distortion"], distortion)
        if w is not None:
            self.set(n.inputs["W"], w)
        return n.outputs[out]

    def lum(self, color):
        n = self.nodes.new("ShaderNodeRGBToBW")
        self.set(n.inputs[0], color)
        return n.outputs[0]

    # ------------------------------------------------------------------ geo
    def compare(self, a, b, op="GREATER_THAN", dtype="FLOAT"):
        n = self.nodes.new("FunctionNodeCompare")
        n.data_type = dtype
        n.operation = op
        ins = [s for s in n.inputs if s.enabled]
        self.set(ins[0], a)
        self.set(ins[1], b)
        return n.outputs["Result"]

    def bool_op(self, op, a, b=None):
        n = self.nodes.new("FunctionNodeBooleanMath")
        n.operation = op
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        return n.outputs[0]

    def switch(self, cond, false, true, dtype="FLOAT"):
        n = self.nodes.new("GeometryNodeSwitch")
        n.input_type = dtype
        self.set(n.inputs["Switch"], cond)
        self.set(n.inputs["False"], false)
        self.set(n.inputs["True"], true)
        return n.outputs[0]

    # ---------------------------------------------------------------- layout
    def layout(self, dx=240, dy=190):
        """Arrange nodes in columns by their longest upstream path."""
        nodes = list(self.nodes)
        depth = {n.name: 0 for n in nodes}
        incoming = {n.name: [] for n in nodes}
        for l in self.links:
            incoming[l.to_node.name].append(l.from_node.name)
        changed = True
        guard = 0
        while changed and guard < 400:
            changed = False
            guard += 1
            for n in nodes:
                d = max((depth[f] + 1 for f in incoming[n.name]), default=0)
                if d != depth[n.name]:
                    depth[n.name] = d
                    changed = True
        if self.go is not None:
            depth[self.go.name] = max(depth.values()) + 1
        cols = {}
        for n in nodes:
            cols.setdefault(depth[n.name], []).append(n)
        for d, col in cols.items():
            for i, n in enumerate(col):
                n.location = (d * dx, -i * dy)

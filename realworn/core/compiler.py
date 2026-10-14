"""The layer compiler: material.realworn.layers -> RW_Stack::<material>.

Rules
- compile(mat) rebuilds the group's contents from scratch, Base first, then the layers bottom to
  top. Same data, same tree: nodes are named RW::<layer_id>::<role> and placed by code.
- The tree uses standard Blender nodes, labelled: box-mapped Image Textures (Object coordinates, Mapping,
  Box projection Blend 0.3), Hue/Saturation for Tint Below, and per layer the mask recipe as real
  Color Ramp and Mix (Subtract) nodes (MSK-1), framed and named after the layer.
- Channel mixing into one Principled BSDF: every layer blends Base Color, Roughness and Metallic by
  its mask, and the one shared height (metres) goes to the material's Displacement as bump.
- Lean: a hidden layer, or one with nothing to show (nothing painted, no decal image), has no
  nodes; Breakup at Amount 0, Edge Darkening at 0 and a missing height add no nodes.
- Value changes (on_value) write into the named node; only structural changes recompile, so
  EEVEE does not rebuild shaders while a slider is dragged.
- Only this module creates or deletes nodes inside RW_Stack::<material>.
"""

import contextlib
import re

import bpy

from . import kinds as K
from . import naming
from ..builders._dsl import SOCKET_TYPES, Tree

_suspended = set()
SOURCE_VIEW = {}  # material name -> layer id: Mask View shows that layer's raw source (Bake Edges and AO)
COMPILES = {"count": 0}  # tests read this to prove value edits do not recompile
BOX_BLEND = 0.3          # SET-3: the classic Box projection blend
_LAYER_PATH = re.compile(r"^realworn\.layers\[(\d+)\](?:\.(texture))?$")


# ---------------------------------------------------------------- batching
@contextlib.contextmanager
def batch(mat):
    """Suspend update callbacks for `mat` (many property writes, then one compile)."""
    key = mat.name_full
    nested = key in _suspended
    _suspended.add(key)
    try:
        yield
    finally:
        if not nested:
            _suspended.discard(key)


def suspended(mat):
    return mat.name_full in _suspended


# ------------------------------------------------------------------ group
def ensure_group(mat):
    """The material's RW_Stack::<material> group, created with the fixed interface."""
    st = mat.realworn
    g = st.stack
    if g is None:
        g = bpy.data.node_groups.new(naming.stack_group_name(mat.name), "ShaderNodeTree")
        g["rw_stack_for"] = mat.name
        g[naming.OWNED_PROP] = True
        st.stack = g
    have = {(i.name, i.in_out) for i in g.interface.items_tree if i.item_type == "SOCKET"}
    for name, stype, default in naming.STACK_INPUTS:
        if (name, "INPUT") not in have:
            s = g.interface.new_socket(name, in_out="INPUT", socket_type=SOCKET_TYPES[stype])
            if default is None:
                s.hide_value = True
            else:
                s.default_value = default
    for name, stype in naming.STACK_OUTPUTS:
        if (name, "OUTPUT") not in have:
            g.interface.new_socket(name, in_out="OUTPUT", socket_type=SOCKET_TYPES[stype])
    return g


def _group_io(g):
    gi = next((n for n in g.nodes if n.bl_idname == "NodeGroupInput"), None) or g.nodes.new("NodeGroupInput")
    go = next((n for n in g.nodes if n.bl_idname == "NodeGroupOutput"), None) or g.nodes.new("NodeGroupOutput")
    gi.name, go.name = "RW::in", "RW::out"
    return gi, go


def layer_by_id(mat, layer_id):
    for ly in mat.realworn.layers:
        if ly.id == layer_id:
            return ly
    return None


def objects_using(mat):
    return [o for o in bpy.data.objects if o.type == "MESH" and any(s.material == mat for s in o.material_slots)]


# ---------------------------------------------------------------- builder
class _B(Tree):
    """Tree DSL plus deterministic naming and a labelled frame per layer block."""

    def __init__(self, tree, gi, go):
        super().__init__(tree)
        self.gi, self.go = gi, go
        self.lid = "stack"
        self.n = 0
        self._mark = 0
        self.base_channels = {}
        self.source_view = None

    def begin(self, lid):
        self.lid = lid
        self.n = 0
        self._mark = len(self.nodes)

    def end(self, x, label=None):
        """Name every anonymous node made since begin(), lay the block out in a column and frame it."""
        new = [n for n in list(self.nodes)[self._mark:] if n.bl_idname != "NodeFrame"]
        for i, node in enumerate(new):
            if not node.name.startswith(naming.NODE_PREFIX):
                node.name = naming.layer_node(self.lid, "n{}".format(self.n))
                self.n += 1
            node.location = (x + (i % 3) * 190, -(i // 3) * 170)
            node.width = 160
        if label and new:
            frame = self.nodes.new("NodeFrame")
            frame.name = naming.layer_node(self.lid, "frame")
            frame.label = label
            frame.label_size = 16
            for node in new:
                node.parent = frame

    def named(self, idname, role, **kw):
        props = kw.pop("props", None)
        n = self.node(idname, props=props, **kw)
        n.name = naming.layer_node(self.lid, role)
        n.label = role
        return n

    def value_node(self, role, v):
        n = self.named("ShaderNodeValue", role)
        n.outputs[0].default_value = v
        return n.outputs[0]

    def rgb_node(self, role, rgb):
        n = self.named("ShaderNodeRGB", role)
        n.outputs[0].default_value = (*rgb[:3], 1.0)
        return n.outputs[0]

    def ramp(self, role, value, stops):
        """A Color Ramp with two grey stops [(position, grey), (position, grey)] (Linear)."""
        n = self.named("ShaderNodeValToRGB", role)
        set_stops(n, stops)
        self.set(n.inputs["Fac"], value)
        return n.outputs["Color"]

    def shared(self, idname, role):
        """A node made once per stack (RW::stack::<role>), reused by every layer."""
        name = naming.layer_node("stack", role)
        n = self.nodes.get(name)
        if n is None:
            n = self.nodes.new(idname)
            n.name = name
            n.label = role
            n.location = (-400, 400 + 160 * len([x for x in self.nodes if x.name.startswith("RW::stack::")]))
        return n


def set_stops(ramp_node, stops):
    els = ramp_node.color_ramp.elements
    (p0, g0), (p1, g1) = stops
    if p1 < p0:  # Color Ramp sorts its stops; keep element 0 first
        (p0, g0), (p1, g1) = (p1, g1), (p0, g0)
    els[0].position, els[0].color = min(max(p0, 0.0), 1.0), (g0, g0, g0, 1.0)
    els[1].position, els[1].color = min(max(p1, 0.0), 1.0), (g1, g1, g1, 1.0)


def _paint_uv(b):
    n = b.shared("ShaderNodeUVMap", "uv")
    n.uv_map = naming.UV_PAINT
    return n.outputs[0]


def _geometry_normal(b):
    return b.shared("ShaderNodeNewGeometry", "geometry").outputs["Normal"]


def _image(b, role, image, vector, non_color=True, box=True):
    n = b.named("ShaderNodeTexImage", role)
    n.image = image
    n.interpolation = "Linear"
    if box:
        n.projection = "BOX"
        n.projection_blend = BOX_BLEND
    b.links.new(vector, n.inputs["Vector"])
    if image is not None and non_color and image.colorspace_settings.name != "Non-Color" and (
            image.get(naming.IMG_MASK) or image.get(naming.IMG_BAKED_SOURCE)):
        image.colorspace_settings.name = "Non-Color"
    return n


def _box_vector(b, role, scale, offset=0.0):
    """SET-3: Object coordinates -> Mapping with Scale in metres (and an offset)."""
    tc = b.shared("ShaderNodeTexCoord", "texcoord")
    mp = b.named("ShaderNodeMapping", role)
    s = 1.0 / max(scale, 1e-4)
    mp.inputs["Scale"].default_value = (s, s, s)
    mp.inputs["Location"].default_value = (offset, offset * 0.7, offset * 0.3)
    b.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _hsv(b, role, color, hue, sat, val):
    h, s, v = K.hsv_inputs(hue, sat, val)
    n = b.named("ShaderNodeHueSaturation", role, Hue=h, Saturation=s, Value=v)
    b.set(n.inputs["Color"], color)
    return n.outputs["Color"]


# ---------------------------------------------------------------- texture sets
def texture_set(b, ts, role="tex"):
    """LT-1..LT-3: a loaded set, box mapped. {'color', 'roughness', 'metallic', 'height'}; a channel
    the set does not have is None. Height is in metres: (map - 0.5) x Bump Strength."""
    vec = _box_vector(b, role + ".map", ts.scale)
    out = {"color": None, "roughness": None, "metallic": None, "height": None}
    if ts.color is not None:
        out["color"] = _image(b, role + ".color", ts.color, vec, non_color=False).outputs["Color"]
    rough = None
    if ts.packed is not None:  # ARM / ORM: R ambient occlusion, G roughness, B metallic
        sep = b.named("ShaderNodeSeparateColor", role + ".split")
        b.links.new(_image(b, role + ".packed", ts.packed, vec).outputs["Color"], sep.inputs["Color"])
        rough, out["metallic"] = sep.outputs["Green"], sep.outputs["Blue"]
    if ts.roughness is not None:
        rough = _image(b, role + ".rough", ts.roughness, vec).outputs["Color"]
        if ts.gloss:
            rough = b.sub(1.0, rough)
    if rough is not None:
        roff = b.named("ShaderNodeMath", role + ".roff", props={"operation": "ADD", "use_clamp": True})
        b.links.new(rough, roff.inputs[0])
        roff.inputs[1].default_value = ts.roughness_offset
        out["roughness"] = roff.outputs[0]
    if ts.metallic is not None:
        out["metallic"] = _image(b, role + ".metal", ts.metallic, vec).outputs["Color"]
    if ts.height is not None:
        h = _image(b, role + ".height", ts.height, vec).outputs["Color"]
        bump = b.named("ShaderNodeMath", role + ".bump", props={"operation": "MULTIPLY"})
        b.links.new(b.sub(h, 0.5), bump.inputs[0])
        bump.inputs[1].default_value = ts.bump
        out["height"] = bump.outputs[0]
    return out


# ---------------------------------------------------------------- masks
def _painted(b, layer, channel="Color"):
    """The layer's painted image through RW_Paint (one lookup: a Decals layer reads its colour from
    the same node)."""
    if layer.mask_image is None:
        return None
    node = b.nodes.get(naming.layer_node(b.lid, "mask"))
    if node is None:
        node = _image(b, "mask", layer.mask_image, _paint_uv(b), non_color=layer.kind != "DECALS", box=False)
    return node.outputs[channel]


def _grunge(b, layer, role="breakup"):
    vec = _box_vector(b, role + ".map", layer.breakup_scale, layer.breakup_offset)
    return _image(b, role + ".img", layer.breakup_grunge, vec).outputs["Color"]


def _edge_source(b, layer):
    """EDW-1: Bevel normal . geometry normal, (1 - dot) x 10; the grunge through a Map Range into
    the Bevel radius makes the worn band irregular."""
    w = layer.width_mm / 1000.0
    if layer.breakup_amount > 0 and layer.breakup_grunge is not None:
        mr = b.named("ShaderNodeMapRange", "edge.radius")
        b.links.new(_grunge(b, layer), mr.inputs["Value"])
        mr.inputs[3].default_value = w * (1.0 - layer.breakup_amount)
        mr.inputs[4].default_value = w
        radius = mr.outputs["Result"]
    else:
        radius = b.value_node("edge.radius", w)
    bevel = b.named("ShaderNodeBevel", "bevel", props={"samples": layer.bevel_samples})
    b.links.new(radius, bevel.inputs["Radius"])
    dot = b.vmath("DOT_PRODUCT", bevel.outputs["Normal"], _geometry_normal(b))
    return b.math("MULTIPLY_ADD", dot, -K.EDGE_GAIN, K.EDGE_GAIN, label="edge (1 - dot) x 10")


def _ao_source(b, layer):
    """DRT-1: Ambient Occlusion, Color Ramp (white in corners)."""
    ao = b.named("ShaderNodeAmbientOcclusion", "ao", props={"samples": K.AO_SAMPLES, "only_local": layer.only_local},
                 Distance=layer.distance_cm / 100.0)
    lo, hi = K.AO_RAMP
    return b.ramp("ao.ramp", ao.outputs["AO"], ((lo, 1.0), (hi, 0.0)))




def source(b, layer):
    """(S, raw): the layer's mask source S, and S without Edge Wear / Dirt touch-up paint (what Bake
    Edges and AO bakes). (None, None) when nothing can show."""
    kind = layer.kind
    if kind == "VARIATION":
        return (1.0, 1.0, 1.0, 1.0), None
    if kind in ("PAINT", "REVEAL"):
        s = _painted(b, layer)
        return s, s
    if kind == "DECALS":
        s = _painted(b, layer, "Alpha")
        return s, s
    if layer.edge_source == "BAKED" and layer.baked_image is not None:
        raw = _image(b, "baked", layer.baked_image, _paint_uv(b), box=False).outputs["Color"]
    elif kind == "EDGE_WEAR":
        raw = _edge_source(b, layer)
    else:
        raw = _ao_source(b, layer)
    touch = _painted(b, layer)
    return (b.max(raw, touch) if touch is not None else raw), raw  # EDW-3 / DRT-3: touch-ups on top


def build_mask(b, layer):
    """MSK-1: M = ramp_{t,w}(S - a ramp_g(G)) x opacity, as real Mix (Subtract) and Color Ramp
    nodes. None when the layer has nothing to show."""
    S, raw = source(b, layer)
    if S is None:
        return None
    if raw is not None and SOURCE_VIEW.get(layer.id_data.name) == layer.id:
        b.source_view = b.math("ADD", raw, 0.0, clamp=True)  # Bake Edges and AO reads this
    if layer.breakup_amount > 0 and layer.breakup_grunge is not None and layer.kind != "EDGE_WEAR":
        g = b.ramp("breakup.ramp", _grunge(b, layer), ((K.breakup_stops(layer.breakup_contrast)[0], 0.0),
                                                      (K.breakup_stops(layer.breakup_contrast)[1], 1.0)))
        sub = b.named("ShaderNodeMix", "breakup.sub", props={"data_type": "RGBA", "blend_type": "SUBTRACT",
                                                             "clamp_result": False})
        ins = {s.identifier: s for s in sub.inputs}
        ins["Factor_Float"].default_value = layer.breakup_amount
        b.set(ins["A_Color"], S)
        b.set(ins["B_Color"], g)
        S = next(s for s in sub.outputs if s.identifier == "Result_Color")
    lo, hi = K.ramp_stops(layer.threshold, layer.sharpness)
    m = b.ramp("ramp", S, ((lo, 0.0), (hi, 1.0)))
    op = b.named("ShaderNodeMath", "opacity", props={"operation": "MULTIPLY"})
    b.links.new(m, op.inputs[0])
    op.inputs[1].default_value = layer.opacity
    return op.outputs[0]


# ---------------------------------------------------------------- content
def content(b, layer, cur):
    """{'color', 'roughness', 'metallic', 'height'} the layer lays down; None keeps what is below."""
    out = {"color": None, "roughness": None, "metallic": None, "height": None}
    kind, c = layer.kind, layer.content
    if kind == "DECALS":
        out["color"] = _hsv(b, "hsv", _painted(b, layer, "Color"), layer.hue, layer.saturation, layer.value)
        out["roughness"] = b.value_node("rough", layer.roughness)
        return out
    if c == "TEXTURE" and layer.texture.loaded():
        ts = texture_set(b, layer.texture)
        out.update(ts)
        base = ts["color"] if ts["color"] is not None else b.rgb_node("color", layer.color)
        out["color"] = _hsv(b, "hsv", base, layer.hue, layer.saturation, layer.value)
        if out["roughness"] is None:
            out["roughness"] = b.value_node("rough", layer.roughness)
        if out["metallic"] is None:
            out["metallic"] = 0.0
        return out
    if c == "TINT_BELOW":
        # the classic trick: a copy of the Base material, recoloured with Hue/Saturation (its
        # roughness and metallic come along); layers in between do not show through
        base = b.base_channels
        out["color"] = _hsv(b, "hsv", base["Base Color"], layer.hue, layer.saturation, layer.value)
        out["roughness"], out["metallic"] = base["Roughness"], base["Metallic"]
        return out
    # COLOR (and TEXTURE with nothing loaded yet): the classic plain BSDF
    out["color"] = _hsv(b, "hsv", b.rgb_node("color", layer.color), layer.hue, layer.saturation, layer.value)
    out["roughness"] = b.value_node("rough", layer.roughness)
    out["metallic"] = 0.0
    return out


def blend(b, layer, mask, lay, cur, ctx):
    """Mix the layer's channels over the stack by its mask, in place."""
    if layer.kind == "DECALS" and layer.decal_blend == "DARKEN":
        cur["Base Color"] = b.mix(mask, cur["Base Color"], lay["color"], blend="MULTIPLY")
    else:
        cur["Base Color"] = b.mix(mask, cur["Base Color"], lay["color"])
    if layer.kind == "REVEAL" and layer.edge_dark > 0:
        # REV-6: a thin darker band where the hole meets the surface: 4 M (1 - M) x Edge Darkening
        band = b.mul(b.mul(mask, b.inv(mask, clamp=False)), 4.0)
        k = b.named("ShaderNodeMath", "edgedark", props={"operation": "MULTIPLY"})
        b.links.new(band, k.inputs[0])
        k.inputs[1].default_value = layer.edge_dark
        dark = b.mix(1.0, cur["Base Color"], (0.25, 0.25, 0.25, 1.0), blend="MULTIPLY")
        cur["Base Color"] = b.mix(k.outputs[0], cur["Base Color"], dark)
    for key, ch in (("roughness", "Roughness"), ("metallic", "Metallic")):
        if lay[key] is not None:
            cur[ch] = b.mixf(mask, cur[ch], lay[key])
    if layer.kind == "REVEAL":
        # REV-2: under the mask the height is the under-material's own height minus Depth
        under = lay["height"] if lay["height"] is not None else 0.0
        depth = b.named("ShaderNodeMath", "depth", props={"operation": "SUBTRACT"})
        b.set(depth.inputs[0], under)
        depth.inputs[1].default_value = layer.depth_mm / 1000.0
        ctx["height"] = b.mixf(mask, ctx["height"] if ctx["height"] is not None else 0.0, depth.outputs[0])
    elif lay["height"] is not None and layer.kind != "DECALS":
        ctx["height"] = b.mixf(mask, ctx["height"] if ctx["height"] is not None else 0.0, lay["height"])


# ---------------------------------------------------------------- compile
def _base(b, mat, cur, ctx):
    """The Base: the wrapped material, or a texture set loaded onto it (then it replaces the
    material's look, box mapped, and its height starts the shared height)."""
    st = mat.realworn
    if not st.base.loaded():
        return
    ts = texture_set(b, st.base)
    col = ts["color"] if ts["color"] is not None else cur["Base Color"]
    cur["Base Color"] = _hsv(b, "hsv", col, st.base_hue, st.base_saturation, st.base_value)
    if ts["roughness"] is not None:
        cur["Roughness"] = ts["roughness"]
    cur["Metallic"] = ts["metallic"] if ts["metallic"] is not None else 0.0
    cur["Normal"] = _geometry_normal(b)
    ctx["height"] = ts["height"]


def compile(mat):
    """Rebuild RW_Stack::<material> from the layer list. Returns the group."""
    COMPILES["count"] += 1
    g = ensure_group(mat)
    for n in list(g.nodes):
        g.nodes.remove(n)
    gi, go = _group_io(g)
    gi.location, go.location = (-700, 0), (300, 0)
    b = _B(g, gi, go)
    st = mat.realworn
    cur = {name: gi.outputs[name] for name, _, _ in naming.STACK_INPUTS}
    ctx = {"height": None, "coverage": None, "mask_view": None}
    b.begin("base")
    _base(b, mat, cur, ctx)
    b.base_channels = dict(cur)  # Tint Below recolours a copy of the Base
    b.end(0, "Base: " + (st.base.name or "texture set") if st.base.loaded() else None)
    active = st.active_layer_index
    for idx, layer in enumerate(st.layers):
        if not layer.visible:
            continue
        b.begin(layer.id)
        b.source_view = None
        mask = build_mask(b, layer)
        if b.source_view is not None:
            ctx["mask_view"] = b.source_view
        if mask is not None:
            lay = content(b, layer, cur)
            blend(b, layer, mask, lay, cur, ctx)
            ctx["coverage"] = mask if ctx["coverage"] is None else b.max(ctx["coverage"], mask)
            if st.mask_view and idx == active and not st.base_active and b.source_view is None:
                ctx["mask_view"] = mask
        b.end(600 * (idx + 1), "{}: {}".format(K.label(layer.kind), layer.name))
    b.begin("stack")
    for name in naming.CHANNELS:
        b.set(go.inputs[name], cur[name])
    for name, key in (("Displacement", "height"), ("Coverage", "coverage"), ("Mask View", "mask_view")):
        if ctx[key] is not None:
            b.set(go.inputs[name], ctx[key])
    go.location = (600 * (len(st.layers) + 1) + 400, 0)
    after_compile(mat)
    return g


def after_compile(mat):
    """Keep what lives outside the group in step: the owned Displacement node, True depth."""
    from . import injector, reveal
    injector.sync_outputs(mat)
    reveal.sync(mat)


def has_height(mat):
    g = mat.realworn.stack
    out = next((n for n in g.nodes if n.bl_idname == "NodeGroupOutput"), None) if g is not None else None
    return out is not None and out.inputs["Displacement"].is_linked


# ---------------------------------------------------------------- callbacks
def _set_socket(node, socket, value):
    s = node.outputs[0] if socket is None else node.inputs[socket]
    if s.type == "RGBA" and len(value) == 3:
        value = (*value, 1.0)
    s.default_value = value


def _hsv_targets(lid, role, hue, sat, val):
    h, s, v = K.hsv_inputs(hue, sat, val)
    return [(lid, role, "Hue", h), (lid, role, "Saturation", s), (lid, role, "Value", v)]


def _texture_targets(lid, ts, prop):
    if prop == "scale":
        s = 1.0 / max(ts.scale, 1e-4)
        return [(lid, "tex.map", "Scale", (s, s, s))]
    if prop == "roughness_offset":
        return [(lid, "tex.roff", 1, ts.roughness_offset)]
    if prop == "bump":
        return [(lid, "tex.bump", 1, ts.bump)]
    return None


def _layer_targets(g, layer, prop):
    """[(lid, role, socket, value)] for a value property of a layer; None means recompile."""
    lid = layer.id
    has = lambda role: g.nodes.get(naming.layer_node(lid, role)) is not None  # noqa: E731
    if prop == "opacity":
        return [(lid, "opacity", 1, layer.opacity)]
    if prop == "color":
        return [(lid, "color", None, tuple(layer.color))]
    if prop == "roughness":
        return [(lid, "rough", None, layer.roughness)]
    if prop in ("hue", "saturation", "value"):
        return _hsv_targets(lid, "hsv", layer.hue, layer.saturation, layer.value)
    if prop in ("threshold", "sharpness"):
        return [(lid, "ramp", "stops", ((K.ramp_stops(layer.threshold, layer.sharpness)[0], 0.0),
                                        (K.ramp_stops(layer.threshold, layer.sharpness)[1], 1.0)))]
    if prop == "breakup_contrast":
        lo, hi = K.breakup_stops(layer.breakup_contrast)
        return [(lid, "breakup.ramp", "stops", ((lo, 0.0), (hi, 1.0)))]
    if prop in ("breakup_scale", "breakup_offset"):
        s, o = 1.0 / max(layer.breakup_scale, 1e-4), layer.breakup_offset
        return [(lid, "breakup.map", "Scale", (s, s, s)), (lid, "breakup.map", "Location", (o, o * 0.7, o * 0.3))]
    if prop == "breakup_amount":
        if layer.kind == "EDGE_WEAR":
            return _edge_radius(g, layer)
        if layer.breakup_amount <= 0 or not has("breakup.sub"):
            return None  # crossing 0 adds or removes the subtract (lean)
        return [(lid, "breakup.sub", 0, layer.breakup_amount)]
    if prop == "width_mm":
        return _edge_radius(g, layer)
    if prop == "depth_mm":
        return [(lid, "depth", 1, layer.depth_mm / 1000.0)]
    if prop == "edge_dark":
        if layer.edge_dark <= 0 or not has("edgedark"):
            return None
        return [(lid, "edgedark", 1, layer.edge_dark)]
    if prop == "distance_cm":
        return [(lid, "ao", "Distance", layer.distance_cm / 100.0)]
    if prop == "only_local":
        return [(lid, "ao", "prop:only_local", layer.only_local)]
    if prop == "bevel_samples":
        return [(lid, "bevel", "prop:samples", layer.bevel_samples)]
    return None


def _edge_radius(g, layer):
    """The Bevel radius: a Map Range from the grunge with Breakup, a Value node without; switching
    between the two recompiles."""
    w = layer.width_mm / 1000.0
    node = g.nodes.get(naming.layer_node(layer.id, "edge.radius"))
    varied = layer.breakup_amount > 0 and layer.breakup_grunge is not None
    if node is None:
        return []
    if varied != (node.bl_idname == "ShaderNodeMapRange"):
        return None
    if varied:
        return [(layer.id, "edge.radius", 3, w * (1.0 - layer.breakup_amount)), (layer.id, "edge.radius", 4, w)]
    return [(layer.id, "edge.radius", None, w)]


def _targets(g, mat, owner_path, prop):
    st = mat.realworn
    if owner_path == "realworn":
        if prop in ("base_hue", "base_saturation", "base_value"):
            return _hsv_targets("base", "hsv", st.base_hue, st.base_saturation, st.base_value)
        return None
    if owner_path == "realworn.base":
        return _texture_targets("base", st.base, prop)
    m = _LAYER_PATH.match(owner_path)
    if m is None or int(m.group(1)) >= len(st.layers):
        return None
    layer = st.layers[int(m.group(1))]
    if not layer.visible:
        return []  # hidden layers have no nodes; the value is used at the next compile
    if m.group(2) == "texture":
        return _texture_targets(layer.id, layer.texture, prop)
    return _layer_targets(g, layer, prop)


def set_value(mat, owner_path, prop):
    """Write one value property into its node(s). False means recompile."""
    g = mat.realworn.stack
    if g is None:
        return False
    targets = _targets(g, mat, owner_path, prop)
    if targets is None:
        return False
    for lid, role, sock, value in targets:
        node = g.nodes.get(naming.layer_node(lid, role))
        if node is None:
            # compile() is a pure function of the layer data and every structural property
            # recompiles, so a missing node means the value is not in use (nothing painted yet...)
            continue
        try:
            if sock == "stops":
                set_stops(node, value)
            elif isinstance(sock, str) and sock.startswith("prop:"):
                setattr(node, sock[5:], value)
            else:
                _set_socket(node, sock, value)
        except (KeyError, TypeError, IndexError):
            return False
    return True


def on_value(pg, prop):
    mat = pg.id_data
    if not isinstance(mat, bpy.types.Material) or suspended(mat) or not mat.realworn.applied:
        return
    if not set_value(mat, pg.path_from_id(), prop):
        compile(mat)


def on_active_layer(pg):
    """Active layer changed: Mask View follows it; painting switches canvas."""
    mat = pg.id_data
    if not isinstance(mat, bpy.types.Material) or suspended(mat) or not mat.realworn.applied:
        return
    if mat.realworn.mask_view:
        compile(mat)
    from . import paint
    for obj in objects_using(mat):
        if paint.painting(obj):
            paint.switch_layer(obj, mat)


def on_struct(pg):
    mat = pg.id_data
    if not isinstance(mat, bpy.types.Material) or suspended(mat) or not mat.realworn.applied:
        return
    compile(mat)
    if pg.path_from_id() == "realworn":  # material-level property (Mask View)
        from . import injector
        injector.set_mask_view(mat, mat.realworn.mask_view)

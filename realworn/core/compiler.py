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
- Puddle (core/puddle.py) is the one kind without the mask recipe: its water stands where a water
  level is above the ground, as depth d per point. While a material has a Puddle layer the stack
  also carries the Principled Coat channels (the water is a clear coat at IOR 1.33), and the
  relief becomes a Bump node whose Strength fades with water depth; without one, neither exists.
- Value changes (on_value) write into the named node; only structural changes recompile, so
  EEVEE does not rebuild shaders while a slider is dragged.
- Only this module creates or deletes nodes inside RW_Stack::<material>.
"""

import contextlib
import re

import bpy

from . import kinds as K
from . import naming
from . import puddle as PD
from ..builders._dsl import SOCKET_TYPES, Tree

_suspended = set()
SOURCE_VIEW = {}  # material name -> layer id: Mask View shows that layer's raw source (Bake Edges and AO)
PUDDLE_PROBE = {}  # material name -> "water" | "deep" | "edge" | "halo" | "wet" | "depth" (d / 40 + 0.5) |
#                    "relief" | "gate" | "color" | "roughness" | "coat" | "film" | "film_relief": tests read
#                    one quantity through Mask View
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
    _coat_sockets(mat, g, wants_coat(mat))
    return g


def wants_coat(mat):
    """The Coat channels go through the stack only while the material has a Puddle layer."""
    return any(ly.kind == "PUDDLE" for ly in mat.realworn.layers)


def has_coat(g):
    return g is not None and any(i.item_type == "SOCKET" and i.in_out == "INPUT" and i.name == "Coat Weight"
                                 for i in g.interface.items_tree)


def _coat_sockets(mat, g, want):
    if want == has_coat(g):
        return
    if want:
        for name, stype, default in naming.COAT_INPUTS:
            s = g.interface.new_socket(name, in_out="INPUT", socket_type=SOCKET_TYPES[stype])
            if default is None:
                s.hide_value = True
            else:
                s.default_value = default
        for name, stype, _ in naming.COAT_INPUTS:
            g.interface.new_socket(name, in_out="OUTPUT", socket_type=SOCKET_TYPES[stype])
        return
    from . import injector
    injector.unroute_coat(mat)  # put the Principled's own coat sources back before the sockets go
    for item in [i for i in g.interface.items_tree if i.item_type == "SOCKET" and i.name in naming.COAT_CHANNELS]:
        g.interface.remove(item)


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
        self.base_v = None       # the Base's height map value (0..1), for Puddle
        self.base_h = None       # the Base's height in metres

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


# ---------------------------------------------------------------- puddle
PUDDLE_VALUES = ("water_level_mm", "height_scale_mm", "paint_depth_mm", "dip_depth_mm", "depth_look_mm", "halo",
                 "edge_width_mm", "halo_width_mm", "deep_threshold_mm", "darkening", "flat_threshold",
                 "wind_ripple", "tide_mark", "debris_settle", "wet_film", "film_relief", "dry_patches",
                 "film_gloss")
PUDDLE_LEAN = ("wind_ripple", "tide_mark", "debris_settle", "wet_film")  # nodes only above 0: crossing 0 recompiles


def _pv(b, layer, prop):
    """The Value node that carries one Puddle property (value edits write into it)."""
    return b.value_node("pud." + prop, getattr(layer, prop))


def _height_range(ts):
    """(lo, hi): the base height map's 2nd and 98th percentiles, measured once per image."""
    if ts.height is None:
        return 0.0, 1.0
    if ts.height_measured != ts.height.name:
        try:
            from . import pbrset
            pbrset.measure_height(ts)
        except (AttributeError, RuntimeError, ValueError):
            return 0.0, 1.0  # cannot write here (a draw or depsgraph context); measured on the next compile
    return ts.height_lo, ts.height_hi


def _smooth(b, d, lo, hi, role):
    n = b.named("ShaderNodeMapRange", role, props={"interpolation_type": "SMOOTHSTEP", "clamp": True})
    b.set(n.inputs["Value"], d)
    b.set(n.inputs[1], lo)
    b.set(n.inputs[2], hi)
    n.inputs[3].default_value, n.inputs[4].default_value = 0.0, 1.0
    return n.outputs["Result"]


def _puddle_ground(b, mat, layer, ctx):
    """H in millimetres (Height Source), or None for a flat ground."""
    st = mat.realworn
    if layer.height_source == "NONE":
        return None
    H = None
    if b.base_v is not None:
        lo, hi = _height_range(st.base)
        span = max(hi - lo, 0.02)
        bn = b.math("MULTIPLY_ADD", b.base_v, 1.0 / span, -(lo + hi) / 2.0 / span, label="base height -0.5..0.5")
        H = b.mul(bn, _pv(b, layer, "height_scale_mm"))
    if layer.height_source == "STACK" and ctx["height"] is not None:
        extra = ctx["height"] if b.base_h is None else b.sub(ctx["height"], b.base_h)
        extra = b.mul(extra, 1000.0)
        H = extra if H is None else b.add(H, extra)
    return H


def _film_breakup(b, layer, n):
    """One sample of the Film Breakup texture (0..1): Noise, normalised, or a library grunge, box
    mapped at Film Scale; the second sample (n = 2) is offset so it does not line up."""
    suffix = "" if n == 1 else str(n)
    mp = b.named("ShaderNodeMapping", "pud.film_map" + suffix)
    sc = 1.0 / max(layer.film_scale_m, 1e-3)
    mp.inputs["Scale"].default_value = (sc, sc, sc)
    if n != 1:
        mp.inputs["Location"].default_value = PD.FILM_OFFSET
    b.links.new(b.shared("ShaderNodeTexCoord", "texcoord").outputs["Object"], mp.inputs["Vector"])
    if layer.film_grunge is not None:
        return _image(b, "pud.film_img" + suffix, layer.film_grunge, mp.outputs["Vector"]).outputs["Color"]
    nz = b.named("ShaderNodeTexNoise", "pud.film_noise" + suffix, Scale=1.0, Detail=3.0, Roughness=0.5)
    b.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
    return b.smooth(nz.outputs["Fac"], *PD.FILM_NOISE_RANGE, label="film breakup")


def _film(b, layer, gate, D, op):
    """F (film weight, opacity included) and R (relief through the film) of core/puddle.py."""
    dry = b.mul(_pv(b, layer, "dry_patches"), b.smooth(_film_breakup(b, layer, 1), *PD.FILM_RAMP, label="dry"))
    F = b.mul_all(_pv(b, layer, "wet_film"), gate, b.inv(dry), op)
    b2 = b.math("MULTIPLY_ADD", _film_breakup(b, layer, 2), 1.0 - PD.FILM_RELIEF_MIN, PD.FILM_RELIEF_MIN,
                label="relief: calm .. scattered patches")
    R = b.mul_all(_pv(b, layer, "film_relief"), b2, b.inv(D))
    return F, R


def puddle(b, mat, layer, cur, ctx, view=False):
    """Water where the water level is above the ground: depth d = L - H' per point (core/puddle.py),
    then porosity darkening, absorption with depth, a clear coat at IOR 1.33 and a relief fade."""
    st = mat.realworn
    painted = layer.puddle_source != "AUTO" and layer.mask_image is not None
    unpainted = layer.puddle_source == "PAINT" and not painted
    if unpainted and layer.wet_film <= 0:
        return  # Paint only, nothing painted yet: no water anywhere (lean)
    op = b.named("ShaderNodeMath", "opacity", props={"operation": "MULTIPLY"})
    op.inputs[0].default_value, op.inputs[1].default_value = 1.0, layer.opacity
    op = op.outputs[0]
    # ground the water sees: H' = H - dips - paint
    H = _puddle_ground(b, mat, layer, ctx)
    Hp = H if H is not None else 0.0
    if layer.broad_dips or (b.base_v is None and layer.height_source != "NONE"):
        mp = b.named("ShaderNodeMapping", "pud.dip_map")
        sc = 1.0 / max(layer.dip_scale_m, 1e-3)
        mp.inputs["Scale"].default_value = (sc, sc, sc)
        b.links.new(b.shared("ShaderNodeTexCoord", "texcoord").outputs["Object"], mp.inputs["Vector"])
        nz = b.named("ShaderNodeTexNoise", "pud.dip_noise", Scale=1.0, Detail=1.0, Roughness=0.5)
        b.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        dips = b.smooth(nz.outputs["Fac"], 0.35, 0.65, label="broad dips")
        Hp = b.sub(Hp, b.mul(dips, _pv(b, layer, "dip_depth_mm")))
    if painted:
        P = b.math("MULTIPLY_ADD", _painted(b, layer), 2.0, -1.0, label="paint: -1 raise .. 1 lower")
        P = b.math("MAXIMUM", b.math("MINIMUM", P, 1.0), -1.0)
        pdep = _pv(b, layer, "paint_depth_mm")
        Hp = b.sub(Hp, b.mul(P, pdep))
        if layer.puddle_source == "PAINT":
            lift = b.mul(b.inv(P), b.add(pdep, PD.PAINT_LIFT))
            Hp = b.add(Hp, lift)
    elif unpainted:  # the film shows; the water waits for paint
        Hp = b.add(Hp, b.add(_pv(b, layer, "paint_depth_mm"), PD.PAINT_LIFT))
    L = _pv(b, layer, "water_level_mm")
    d = b.sub(L, Hp)
    # flat faces only
    thr = _pv(b, layer, "flat_threshold")
    _, _, nzc = b.sep(_geometry_normal(b))
    gate = _smooth(b, nzc, b.sub(thr, PD.FLAT_SOFT[0]), b.add(thr, PD.FLAT_SOFT[1]), "pud.flat")
    d = b.mixf(gate, PD.DRY_DEPTH, d, label="d (mm), dry on walls")
    # zones
    edge_w, halo_w = _pv(b, layer, "edge_width_mm"), _pv(b, layer, "halo_width_mm")
    W = _smooth(b, d, -PD.WATERLINE, PD.WATERLINE, "pud.water")
    D = _smooth(b, d, 0.0, _pv(b, layer, "deep_threshold_mm"), "pud.deep")
    neg_e = b.mul(edge_w, -1.0)
    E = _smooth(b, d, neg_e, 0.0, "pud.edge")
    outer = b.sub(neg_e, b.mul(halo_w, _pv(b, layer, "halo")))
    Hh = _smooth(b, d, outer, neg_e, "pud.halo")
    wet = b.max(b.mul(Hh, PD.HALO_WETNESS), E)
    Wo, Do, Eo, Ho, weto = b.mul(W, op), b.mul(D, op), b.mul(E, op), b.mul(Hh, op), b.mul(wet, op)
    F = R = None
    if layer.wet_film > 0:  # a thin skin of water over every flat face (lean: no nodes at 0)
        F, R = _film(b, layer, gate, D, op)
    # colour: porosity darkening, then the ground seen through the water
    por = b.maprange(cur["Roughness"], 0.5, 0.9, label="porosity")
    k = b.mul_all(b.inv(cur["Metallic"]), por, weto if F is None else b.max(weto, F), _pv(b, layer, "darkening"))
    keep = b.math("MULTIPLY_ADD", k, -(1.0 - PD.DARKEST), 1.0, label="wet: keep")
    c_wet = b.mix(1.0, cur["Base Color"], keep, blend="MULTIPLY")
    look = _pv(b, layer, "depth_look_mm")
    if layer.water_tint == "MUDDY":
        look = b.mul(look, PD.MUDDY_ABSORPTION)
    a = b.math("EXPONENT", b.div(b.mul(b.max(d, 0.0), -1.0), b.max(look, 1e-3)), label="absorption")
    tint = tuple(layer.tint_color) if layer.water_tint == "CUSTOM" else PD.TINTS[layer.water_tint]
    c_under = b.mix(a, b.rgb_node("pud.tint", tint), c_wet)
    col = b.mix(Wo, c_wet, c_under)
    if layer.debris_settle > 0:
        dk = b.math("MULTIPLY_ADD", b.mul(Do, _pv(b, layer, "debris_settle")), -PD.DEBRIS, 1.0)
        col = b.mix(1.0, col, dk, blend="MULTIPLY")
    if layer.tide_mark > 0:
        band = b.mul_all(Ho, b.inv(Ho, clamp=False), 4.0, _pv(b, layer, "tide_mark"))
        col = b.mix(1.0, col, b.math("MULTIPLY_ADD", band, -PD.TIDE, 1.0), blend="MULTIPLY")
    cur["Base Color"] = col
    # roughness
    r = b.mul(cur["Roughness"], b.math("MULTIPLY_ADD", Ho, -(1.0 - PD.HALO_ROUGHNESS), 1.0))
    r = b.mul(r, b.math("MULTIPLY_ADD", Eo, -(1.0 - PD.EDGE_ROUGHNESS / PD.HALO_ROUGHNESS), 1.0))
    if F is not None:
        r = b.mul(r, b.math("MULTIPLY_ADD", F, -PD.FILM_ROUGHNESS, 1.0))
    cur["Roughness"] = b.mixf(Wo, r, PD.WATER_ROUGHNESS)
    # the water is a clear coat
    if "Coat Weight" in cur:
        if F is None:
            cur["Coat Weight"] = b.max(cur["Coat Weight"], Eo)
            cr = b.mixf(D, b.mixf(W, PD.COAT_ROUGHNESS[0], PD.COAT_ROUGHNESS[1]), PD.COAT_ROUGHNESS[2])
            cur["Coat Roughness"] = b.mixf(Eo, cur["Coat Roughness"], cr)
            cur["Coat IOR"] = b.mixf(Eo, cur["Coat IOR"], PD.COAT_IOR)
        else:  # the film's coat on flat faces outside the water; the water's coat inside it
            present = b.mul(gate, op)
            cur["Coat Weight"] = b.max(b.max(cur["Coat Weight"], Eo), F)
            cr = b.mixf(D, b.mixf(W, PD.COAT_ROUGHNESS[0], PD.COAT_ROUGHNESS[1]), PD.COAT_ROUGHNESS[2])
            film_r = b.mixf(F, PD.FILM_COAT_ROUGHNESS, _pv(b, layer, "film_gloss"), label="film gloss")
            film_r = b.mixf(present, cur["Coat Roughness"], film_r)
            cur["Coat Roughness"] = b.mixf(Eo, film_r, cr)
            cur["Coat IOR"] = b.mixf(b.max(Eo, present), cur["Coat IOR"], PD.COAT_IOR)
        flat = cur["Coat Normal"]
        if layer.wind_ripple > 0:
            rip = b.named("ShaderNodeTexNoise", "pud.ripple", Scale=PD.RIPPLE_SCALE, Detail=3.0, Roughness=0.6)
            b.links.new(b.shared("ShaderNodeTexCoord", "texcoord").outputs["Object"], rip.inputs["Vector"])
            bump = b.named("ShaderNodeBump", "pud.ripple_bump", Distance=0.0004)
            b.set(bump.inputs["Strength"], b.mul(Do, _pv(b, layer, "wind_ripple")))
            b.links.new(rip.outputs["Fac"], bump.inputs["Height"])
            b.set(bump.inputs["Normal"], flat)
            flat = bump.outputs["Normal"]
        if not layer.true_depth:
            ctx["coat_flat"].append((Wo, flat, R))
        else:
            cur["Coat Normal"] = flat
        if layer.water_tint == "OILY":
            nz = b.named("ShaderNodeTexNoise", "pud.oil", Scale=PD.OILY_SCALE, Detail=2.0, Roughness=0.5)
            b.links.new(b.shared("ShaderNodeTexCoord", "texcoord").outputs["Object"], nz.inputs["Vector"])
            film = b.mul_all(b.smooth(nz.outputs["Fac"], 0.45, 0.6), Wo, PD.OILY_FILM_NM)
            cur["Thin Film Thickness"] = b.max(cur["Thin Film Thickness"], film)
    # relief: shading only fades the bump by depth (built after the last layer); True Depth
    # displaces the ground and holds the water flat at the level
    if layer.true_depth:
        held = b.mixf(gate, Hp, b.max(Hp, L), label="water held flat at the level (flat faces)")
        ctx["height"] = b.mul(held, 0.001)
    else:
        fade = b.mul(a, b.inv(D))
        s = b.inv(b.mul(op, b.inv(fade)))
        ctx["relief"] = s if ctx["relief"] is None else b.mul(ctx["relief"], s)
    ctx["coverage"] = weto if ctx["coverage"] is None else b.max(ctx["coverage"], weto)
    probe = PUDDLE_PROBE.get(mat.name)
    if probe is not None or view:
        if probe is not None:
            ctx["mask_view"] = {"water": Wo, "deep": Do, "edge": Eo, "halo": Ho, "wet": weto,
                                "depth": b.math("MULTIPLY_ADD", d, 1.0 / 40.0, 0.5, clamp=True),
                                "relief": ctx["relief"] if ctx["relief"] is not None else 1.0,
                                "gate": gate, "color": cur["Base Color"], "roughness": cur["Roughness"],
                                "coat": cur.get("Coat Weight", 0.0), "film": F if F is not None else 0.0,
                                "film_relief": R if R is not None else 0.0}[probe]
        else:
            ctx["mask_view"] = Wo
        v = PD.VIEW_COLORS
        c = b.mix(Ho, v["dry"], v["halo"])
        c = b.mix(Eo, c, v["edge"])
        c = b.mix(Wo, c, v["shallow"])
        ctx["mask_color"] = b.mix(Do, c, v["deep"]) if probe is None else ctx["mask_view"]


def _relief(b, cur, ctx):
    """With a Puddle layer the stack's height becomes a Bump node whose Strength fades under the
    water (Displacement is then left unplugged); the water's coat normal is flat. A wet film's coat
    follows its own Bump of the same height, at the film's relief strength."""
    if ctx["relief"] is None:
        return
    pre, height = cur["Normal"], ctx["height"]
    if ctx["height"] is not None:
        bump = b.named("ShaderNodeBump", "relief", Distance=1.0)
        b.set(bump.inputs["Strength"], ctx["relief"])
        b.set(bump.inputs["Height"], ctx["height"])
        b.set(bump.inputs["Normal"], cur["Normal"])
        cur["Normal"] = bump.outputs["Normal"]
        ctx["height"] = None
    if "Coat Normal" in cur:
        for i, (w, flat, R) in enumerate(ctx["coat_flat"]):
            ground = cur["Normal"]
            if R is not None and height is not None:
                fb = b.named("ShaderNodeBump", "film_relief.{}".format(i), Distance=1.0)
                b.set(fb.inputs["Strength"], R)
                b.set(fb.inputs["Height"], height)
                b.set(fb.inputs["Normal"], pre)
                ground = fb.outputs["Normal"]
            cur["Coat Normal"] = b.vmath("NORMALIZE", b.mixv(w, ground, flat))


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
    hnode = b.nodes.get(naming.layer_node("base", "tex.height"))
    if hnode is not None:
        b.base_v, b.base_h = hnode.outputs["Color"], ts["height"]


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
    coat = has_coat(g)
    cur = {name: gi.outputs[name] for name, _, _ in naming.STACK_INPUTS}
    if coat:
        cur.update({name: gi.outputs[name] for name in naming.COAT_CHANNELS})
    ctx = {"height": None, "coverage": None, "mask_view": None, "mask_color": None, "relief": None,
           "coat_flat": []}
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
        if layer.kind == "PUDDLE":
            view = st.mask_view and idx == active and not st.base_active
            puddle(b, mat, layer, cur, ctx, view)
            b.end(600 * (idx + 1), "{}: {}".format(K.label(layer.kind), layer.name))
            continue
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
    _relief(b, cur, ctx)
    for name in naming.CHANNELS + (naming.COAT_CHANNELS if coat else ()):
        b.set(go.inputs[name], cur[name])
    if ctx["mask_color"] is None and ctx["mask_view"] is not None:
        ctx["mask_color"] = ctx["mask_view"]
    for name, key in (("Displacement", "height"), ("Coverage", "coverage"), ("Mask View", "mask_view"),
                      ("Mask Color", "mask_color")):
        if ctx[key] is not None:
            b.set(go.inputs[name], ctx[key])
    go.location = (600 * (len(st.layers) + 1) + 400, 0)
    after_compile(mat)
    return g


def after_compile(mat):
    """Keep what lives outside the group in step: the owned Displacement node, True depth."""
    from . import injector, reveal
    injector.sync_outputs(mat)
    injector.sync_coat(mat)
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


def _puddle_targets(g, layer, prop):
    lid = layer.id
    if prop in PUDDLE_VALUES:
        if prop in PUDDLE_LEAN and (getattr(layer, prop) <= 0) != (g.nodes.get(naming.layer_node(lid, "pud." + prop))
                                                                  is None):
            return None
        return [(lid, "pud." + prop, None, getattr(layer, prop))]
    if prop == "dip_scale_m":
        sc = 1.0 / max(layer.dip_scale_m, 1e-3)
        return [(lid, "pud.dip_map", "Scale", (sc, sc, sc))]
    if prop == "film_scale_m":
        sc = 1.0 / max(layer.film_scale_m, 1e-3)
        return [(lid, role, "Scale", (sc, sc, sc)) for role in ("pud.film_map", "pud.film_map2")]
    if prop == "tint_color":
        return [(lid, "pud.tint", None, tuple(layer.tint_color))] if layer.water_tint == "CUSTOM" else []
    if prop == "opacity":
        return [(lid, "opacity", 1, layer.opacity)]
    return None


def _layer_targets(g, layer, prop):
    """[(lid, role, socket, value)] for a value property of a layer; None means recompile."""
    lid = layer.id
    has = lambda role: g.nodes.get(naming.layer_node(lid, role)) is not None  # noqa: E731
    if layer.kind == "PUDDLE":
        return _puddle_targets(g, layer, prop)
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

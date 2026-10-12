"""The layer compiler (CMP-1..CMP-5): material.realworn.layers -> RW_Stack::<material>.

Rules
- compile(mat) rebuilds the group's contents from scratch, bottom layer first. Same data,
  same tree: nodes are named RW::<layer_id>::<role> and placed by code (CMP-3).
- Lean (CMP-2): a layer only gets the nodes it uses. A hidden layer or a layer with nothing
  painted and no ingredient has no nodes at all; an empty stack is a pass-through.
- Value changes (on_value) write into the named node input; only structural changes (on_struct)
  recompile, so EEVEE does not rebuild shaders while a slider is dragged (CMP-4).
- Only this module creates or deletes nodes inside RW_Stack::<material>.

Units: height channels and the Displacement output are millimetres; the final Bump uses
Distance 0.001 so 1 unit of height is 1 mm.
"""

import contextlib
import re

import bpy

from . import assets, naming
from ..builders._dsl import SOCKET_TYPES, Tree

_suspended = set()
_PATH = re.compile(r"realworn\.layers\[(\d+)\](?:\.(\w+)(?:\[(\d+)\])?)?\.(\w+)$")
COMPILES = {"count": 0}  # tests read this to prove value edits do not recompile


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
    for name, stype, default in naming.STACK_INPUTS:  # also upgrades stacks from older versions
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
    """Tree DSL plus deterministic naming for one layer block."""

    def __init__(self, tree, gi, go):
        super().__init__(tree)
        self.gi, self.go = gi, go
        self.lid = "stack"
        self.n = 0

    def begin(self, lid):
        self.lid = lid
        self.n = 0
        self._mark = len(self.nodes)

    def end(self, x):
        """Name every anonymous node made since begin() and lay the block out in a column."""
        new = list(self.nodes)[self._mark:]
        for i, node in enumerate(new):
            if not node.name.startswith(naming.NODE_PREFIX):
                node.name = naming.layer_node(self.lid, "n{}".format(self.n))
                self.n += 1
            node.location = (x + (i % 4) * 180, -(i // 4) * 160)
            node.width = 150

    def named(self, idname, role, **kw):
        props = kw.pop("props", None)
        n = self.node(idname, props=props, **kw)
        n.name = naming.layer_node(self.lid, role)
        return n

    def value_node(self, role, v):
        n = self.named("ShaderNodeValue", role)
        n.outputs[0].default_value = v
        return n.outputs[0]

    def rgb_node(self, role, rgb):
        n = self.named("ShaderNodeRGB", role)
        n.outputs[0].default_value = (*rgb[:3], 1.0)
        return n.outputs[0]

    def group(self, name, role, **inputs):
        assets.ensure_groups((name,))
        return self.named("ShaderNodeGroup", role, props={"node_tree": bpy.data.node_groups[name]}, **inputs)


def _paint_uv(b):
    """One shared UV Map node (RW_Paint) per stack: masks are sampled through it only."""
    n = b.nodes.get(naming.layer_node("stack", "uv"))
    if n is None:
        n = b.nodes.new("ShaderNodeUVMap")
        n.name = naming.layer_node("stack", "uv")
        n.uv_map = naming.UV_PAINT
        n.location = (-300, 300)
    return n.outputs[0]


def _image_node(b, role, image, vector, non_color=True, box=False):
    n = b.named("ShaderNodeTexImage", role)
    n.image = image
    n.interpolation = "Linear"
    if box:
        n.projection = "BOX"
        n.projection_blend = 0.2
    b.links.new(vector, n.inputs["Vector"])
    if image is not None and non_color and image.colorspace_settings.name != "Non-Color" and image.get(naming.IMG_MASK):
        image.colorspace_settings.name = "Non-Color"
    return n


def _box_vector(b, role, scale, rotation=0.0, offset=0.0):
    tc = b.named("ShaderNodeTexCoord", role + ".tc")
    mp = b.named("ShaderNodeMapping", role + ".map")
    s = 1.0 / max(scale, 1e-4)
    mp.inputs["Scale"].default_value = (s, s, s)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rotation)
    mp.inputs["Location"].default_value = (offset, offset * 0.7, offset * 0.3)
    b.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


# ---------------------------------------------------------------- masks
def _generator(b, kind, role, angle=0.7853982):
    if kind == "UP":
        return b.outp(b.group(naming.SH_UP, role, Angle=angle), "Up")
    attr = {"EDGE": naming.ATTR_EDGE, "CAVITY": naming.ATTR_CAVITY, "CONTACT": naming.ATTR_CONTACT}[kind]
    n = b.named("ShaderNodeAttribute", role, props={"attribute_type": "GEOMETRY", "attribute_name": attr})
    return n.outputs["Fac"]


def _ingredient(b, layer, i, ing, masks):
    role = "ing{}".format(i)
    if ing.kind == "GRUNGE":
        if ing.image is None:
            return None
        vec = _box_vector(b, role, ing.scale, ing.rotation, ing.seed)
        src = b.outp(_image_node(b, role + ".img", ing.image, vec, box=True), "Color")
    elif ing.kind == "REFERENCE":
        src = masks.get(ing.ref_layer_id)
        if src is None:
            return None
    else:
        src = _generator(b, ing.kind, role + ".gen", ing.angle)
    c = b.group(naming.SH_CONTRAST, role + ".contrast", Value=src, Contrast=ing.contrast,
                Invert=1.0 if ing.invert else 0.0)
    return b.mul(b.outp(c), b.value_node(role + ".amount", ing.amount))


def _vertex_mask(b, layer):
    n = b.named("ShaderNodeVertexColor", "vmask", props={"layer_name": naming.ATTR_VMASK + layer.id})
    return n.outputs["Color"], n.outputs["Alpha"]


def build_mask(b, layer, masks, base_height, decal_alpha=None):
    """The layer's final mask socket, or None when nothing can show (PRD mask formula)."""
    P = None
    for i, ing in enumerate(layer.ingredients):
        term = _ingredient(b, layer, i, ing, masks)
        if term is not None:
            P = term if P is None else b.add(P, term)
    if decal_alpha is not None:  # decals: the projected image is the procedural part
        P = decal_alpha if P is None else b.max(P, decal_alpha)
    if P is not None:
        P = b.clamp(P)
    if layer.use_vertex_mask:
        col, alpha = _vertex_mask(b, layer)
        P = b.outp(b.group(naming.SH_PAINT_OVER, "paint", Procedural=P if P is not None else 0.0, Paint=col,
                           Alpha=alpha))
    elif layer.mask_image is not None:
        tex = _image_node(b, "mask", layer.mask_image, _paint_uv(b))
        P = b.outp(b.group(naming.SH_PAINT_OVER, "paint", Procedural=P if P is not None else 0.0,
                           Paint=tex.outputs["Color"], Alpha=tex.outputs["Alpha"]))
    if P is None:
        return None
    if layer.lock_source != "NONE":
        lock = _generator(b, layer.lock_source, "lock.gen")
        P = b.outp(b.group(naming.SH_EDGE_LOCK, "lock", Mask=P, Lock=lock, Strength=layer.lock_strength))
    if layer.use_height_blend:
        P = b.outp(b.group(naming.SH_HEIGHT_BLEND, "hblend", Mask=P, Height=base_height, Amount=layer.height_blend))
    b.raw_mask = P  # before Levels: damage dents use the soft falloff for their bowl shape
    P = b.outp(b.group(naming.SH_LEVELS, "levels", Mask=P, Threshold=layer.threshold, Softness=layer.softness))
    return b.mul(P, b.value_node("opacity", layer.opacity))


# ---------------------------------------------------------------- content
def _channel_source(b, layer, name, ch, scalar):
    """The B value of one channel: flat value, image, PBR set map or tinted grunge."""
    role = name
    if ch.source in ("IMAGE", "PBRSET") and ch.image is not None:
        baked = bool(ch.image.get("rw_baked"))  # Flatten output: painted space, sampled through RW_Paint
        if baked:
            vec = _paint_uv(b)
        elif ch.use_uv:
            vec = b.outp(b.named("ShaderNodeUVMap", role + ".uv"))
        else:
            vec = _box_vector(b, role, ch.scale)
        img = _image_node(b, role + ".img", ch.image, vec, non_color=scalar, box=not (ch.use_uv or baked))
        out = img.outputs["Color"]
        if name == "height":  # image height (0..1) scaled by the channel value in mm
            out = b.mul(out, b.value_node(role + ".value", ch.value))
        return out
    if scalar:
        return b.value_node(role + ".value", ch.value)
    col = b.rgb_node(role + ".value", ch.color)
    if ch.source == "TINTED_GRUNGE" and ch.grunge is not None:
        vec = _box_vector(b, role + ".tg", 1.0)
        g = b.outp(_image_node(b, role + ".grunge", ch.grunge, vec, box=True), "Color")
        var = b.value_node(role + ".variation", ch.variation)
        k = b.mixf(g, b.inv(var), 1.0)
        col = b.mix(1.0, col, b.comb(k, k, k), blend="MULTIPLY")
    return col


def _blend_scalar(b, mode, mask, cur, val):
    if mode == "MIN":
        val = b.min(cur, val)
    elif mode == "MAX":
        val = b.max(cur, val)
    return b.mixf(mask, cur, val)


def _blend_height(b, mode, mask, cur, val):
    if mode == "SUBTRACT":
        return b.sub(cur, b.mul(mask, val))
    if mode == "MAX":
        return b.max(cur, b.mul(mask, val))
    if mode == "REPLACE":
        return b.mixf(mask, cur, val)
    return b.add(cur, b.mul(mask, val))


def apply_content(b, layer, mask, cur, ctx):
    """Blend the layer's enabled channels over `cur` (dict of sockets), in place."""
    var = None
    if layer.use_variation:
        var = b.group(naming.SH_VARIATION, "variation", Amount=layer.variation, Scale=layer.variation_scale)
    if layer.color.enabled:
        val = _channel_source(b, layer, "color", layer.color, False)
        content = b.nodes.get(naming.layer_node(layer.id, "content"))
        if layer.type == "PAINT" and content is not None:
            val = b.mix(1.0, val, content.outputs["Color"], blend="MULTIPLY")
        if var is not None:
            b.links.new(val, var.inputs["Color"])
            val = b.outp(var, "Color")
        blend = layer.color.blend if layer.color.blend in ("MIX", "MULTIPLY", "OVERLAY", "ADD", "DARKEN") else "MIX"
        b.layer_color = val
        cur["Base Color"] = b.mix(mask, cur["Base Color"], val, blend=blend)
    for name, key in (("roughness", "Roughness"), ("metallic", "Metallic")):
        ch = getattr(layer, name)
        if ch.enabled:
            val = _channel_source(b, layer, name, ch, True)
            if name == "roughness" and var is not None:
                val = b.clamp(b.add(val, b.outp(var, "Roughness Offset")))
            mode = ch.blend if ch.blend in ("MIX", "MIN", "MAX") else "MIX"
            cur[key] = _blend_scalar(b, mode, mask, cur[key], val)
    if layer.normal_image is not None and any(getattr(layer, c).use_uv for c in ("color", "roughness", "height")):
        # tangent-space maps are only valid through a UV map (box projection has no tangents;
        # with box projection the PBR set's height map gives the relief instead)
        uvn = b.named("ShaderNodeUVMap", "normal.uv")
        img = _image_node(b, "normal.img", layer.normal_image, uvn.outputs[0], non_color=True)
        nm = b.named("ShaderNodeNormalMap", "normal.map", Strength=layer.normal_strength)
        b.links.new(img.outputs["Color"], nm.inputs["Color"])
        cur["Normal"] = b.mixv(mask, cur["Normal"], nm.outputs["Normal"])
    if layer.height.enabled:
        val = _channel_source(b, layer, "height", layer.height, True)
        mode = layer.height.blend if layer.height.blend in ("ADD", "SUBTRACT", "MAX", "REPLACE") else "ADD"
        cur["Height"] = _blend_height(b, mode, mask, cur["Height"], val)
        ctx["height_used"] = True


# ---------------------------------------------------------------- compile
def _special(b, layer, mask, cur, ctx):
    """Type-specific blocks (water, damage, decal) live in their own modules."""
    if layer.type == "WATER":
        from . import water
        water.apply(b, layer, mask, cur, ctx)
    elif layer.type == "DAMAGE":
        from . import damage
        damage.apply_shader(b, layer, mask, cur, ctx)


def compile(mat):
    """Rebuild RW_Stack::<material> from the layer list. Returns the group."""
    COMPILES["count"] += 1
    g = ensure_group(mat)
    for n in list(g.nodes):
        g.nodes.remove(n)
    gi, go = _group_io(g)
    gi.location, go.location = (-600, 0), (300, 0)
    b = _B(g, gi, go)
    cur = {name: gi.outputs[name] for name, _, _ in naming.STACK_INPUTS}
    base_height = cur["Height"]
    cur["Height"] = None  # layer height accumulator (mm); None until a layer adds height
    ctx = {"height_used": False, "flatten": None, "displacement": None, "coverage": None, "mask_view": None,
           "layer_color": None, "base_height": base_height, "geometry_normal": None}
    masks = {}
    active = mat.realworn.active_layer_index
    for idx, layer in enumerate(mat.realworn.layers):
        if not layer.visible:
            continue
        b.begin(layer.id)
        b.layer_color = None
        decal_alpha = None
        if layer.type == "DECAL":
            from . import decals
            decal_alpha = decals.build_projection(b, layer, cur, ctx)
        elif layer.type == "PAINT" and layer.content_image is not None:
            # PNT-10: a Paint layer shows where its colour image was painted (content alpha)
            content = _image_node(b, "content", layer.content_image, _paint_uv(b), non_color=False)
            decal_alpha = content.outputs["Alpha"]
        mask = build_mask(b, layer, masks, base_height, decal_alpha)
        if mask is not None:
            masks[layer.id] = mask
            if cur["Height"] is None and (layer.height.enabled or layer.type in ("DAMAGE", "WATER")):
                cur["Height"] = b.value_node("h0", 0.0)
            if layer.type == "DECAL":
                from . import decals
                decals.apply_content(b, layer, mask, cur, ctx)
            elif layer.type == "DAMAGE":
                from . import damage
                apply_content(b, layer, damage.content_mask(b, layer, mask, ctx), cur, ctx)
            else:
                apply_content(b, layer, mask, cur, ctx)
            _special(b, layer, mask, cur, ctx)
            ctx["coverage"] = mask if ctx["coverage"] is None else b.max(ctx["coverage"], mask)
            if mat.realworn.mask_view and idx == active:
                ctx["mask_view"] = mask
                if mat.realworn.view_channel == "COLOR":  # bake helpers read the layer's own colour
                    ctx["layer_color"] = getattr(b, "layer_color", None)
        b.end(300 * (idx + 1))
    b.begin("stack")
    normal = cur["Normal"]
    if ctx["height_used"] and cur["Height"] is not None:
        bump = b.named("ShaderNodeBump", "bump", Strength=1.0, Distance=0.001)
        b.links.new(cur["Height"], bump.inputs["Height"])
        b.links.new(normal, bump.inputs["Normal"])
        normal = bump.outputs["Normal"]
    if ctx["flatten"] is not None:  # standing water: base bump fades out (WAT-3)
        geo = b.named("ShaderNodeNewGeometry", "geo")
        normal = b.mixv(ctx["flatten"], normal, geo.outputs["Normal"])
    out = dict(cur)
    out["Normal"] = normal
    for name, _ in naming.STACK_OUTPUTS:
        if name in ("Displacement", "Coverage", "Mask View", "Layer Color", "Height"):
            continue
        b.links.new(out[name], go.inputs[name])
    ctx["height_out"] = cur["Height"]  # layer relief in mm (bake reads it)
    for name, key in (("Displacement", "displacement"), ("Coverage", "coverage"), ("Mask View", "mask_view"),
                      ("Layer Color", "layer_color"), ("Height", "height_out")):
        if ctx[key] is not None:
            b.links.new(ctx[key], go.inputs[name])
    b.end(300 * (len(mat.realworn.layers) + 1))
    go.location = (300 * (len(mat.realworn.layers) + 2) + 400, 0)
    after_compile(mat)
    return g


def after_compile(mat):
    """Keep things that live outside the group in step: generators (ING-1), displacement."""
    from . import damage, injector, setup
    setup.sync_generators(mat)
    injector.sync_outputs(mat)
    damage.sync(mat)


# ---------------------------------------------------------------- callbacks
_VALUE_ROLES = {
    # (sub, prop) -> (role, socket or None for outputs[0], transform)
    (None, "opacity"): ("opacity", None, None),
    (None, "threshold"): ("levels", "Threshold", None),
    (None, "softness"): ("levels", "Softness", None),
    (None, "lock_strength"): ("lock", "Strength", None),
    (None, "height_blend"): ("hblend", "Amount", None),
    (None, "variation"): ("variation", "Amount", None),
    (None, "variation_scale"): ("variation", "Scale", None),
    (None, "normal_strength"): ("normal.map", "Strength", None),
}


def _set_socket(node, socket, value):
    s = node.outputs[0] if socket is None else node.inputs[socket]
    if s.type == "RGBA" and len(value) == 3:
        value = (*value, 1.0)
    s.default_value = value


def on_value(pg, prop):
    mat = pg.id_data
    if not isinstance(mat, bpy.types.Material) or suspended(mat) or not mat.realworn.applied:
        return
    if not set_value(mat, pg.path_from_id() + "." + prop):
        compile(mat)


def set_value(mat, path):
    """Write one value property into its node; False when the node is not there (recompile)."""
    g = mat.realworn.stack
    m = _PATH.search(path)
    if g is None or m is None:
        return False
    idx, sub, sub_i, prop = int(m.group(1)), m.group(2), m.group(3), m.group(4)
    if idx >= len(mat.realworn.layers):
        return False
    layer = mat.realworn.layers[idx]
    if not layer.visible:
        return True  # hidden layers have no nodes; the value is used at the next compile
    lid = layer.id
    targets = []  # (role, socket, value)
    if sub is None:
        if prop in ("lock_width",):
            from . import setup
            setup.sync_widths(mat)
            return True
        r = _VALUE_ROLES.get((None, prop))
        if r is None:
            return False
        targets.append((r[0], r[1], getattr(layer, prop)))
    elif sub in ("color", "roughness", "metallic", "height"):
        ch = getattr(layer, sub)
        if prop == "color" or prop == "value":
            targets.append((sub + ".value", None, tuple(ch.color) if prop == "color" else ch.value))
        elif prop == "scale":
            s = 1.0 / max(ch.scale, 1e-4)
            targets.append((sub + ".map", "Scale", (s, s, s)))
        elif prop == "variation":
            targets.append((sub + ".variation", None, ch.variation))
        else:
            return False
    elif sub == "ingredients":
        i = int(sub_i)
        ing = layer.ingredients[i]
        role = "ing{}".format(i)
        if prop == "amount":
            targets.append((role + ".amount", None, ing.amount))
        elif prop in ("contrast", "invert"):
            targets.append((role + ".contrast", "Contrast" if prop == "contrast" else "Invert",
                            ing.contrast if prop == "contrast" else (1.0 if ing.invert else 0.0)))
        elif prop in ("scale", "rotation", "seed"):
            s = 1.0 / max(ing.scale, 1e-4)
            targets += [(role + ".map", "Scale", (s, s, s)), (role + ".map", "Rotation", (0.0, 0.0, ing.rotation)),
                        (role + ".map", "Location", (ing.seed, ing.seed * 0.7, ing.seed * 0.3))]
        elif prop == "angle":
            targets.append((role + ".gen", "Angle", ing.angle))
        elif prop == "width":
            from . import setup
            setup.sync_widths(mat)
            return True
        else:
            return False
    elif sub == "water":
        from . import water
        targets += water.value_targets(layer, prop)
    elif sub == "damage":
        from . import damage
        handled = damage.on_value(mat, layer, prop)
        if handled is not None:
            return handled
        targets += damage.value_targets(layer, prop)
    elif sub == "decal":
        targets.append(("decal", prop.title(), getattr(layer.decal, prop)))
    else:
        return False
    if not targets:
        return False
    for role, sock, value in targets:
        node = g.nodes.get(naming.layer_node(lid, role))
        if node is None:
            # compile() is a pure function of the layer data and every structural property
            # recompiles, so a missing node means this value is not used by the current tree
            # (disabled channel, nothing painted yet...): nothing to update.
            continue
        try:
            _set_socket(node, sock, value)
        except (KeyError, TypeError):
            return False
    return True


def on_active_layer(pg):
    """Active layer changed: Mask View follows it; painting switches canvas (PRD "While painting")."""
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
    if pg.path_from_id() == "realworn":  # material-level property (Mask View)
        from . import injector
        compile(mat)
        injector.set_mask_view(mat, mat.realworn.mask_view)
        return
    compile(mat)

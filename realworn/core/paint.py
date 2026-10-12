"""Paint mode (PNT-4..PNT-11): RealWorn drives Blender's own texture paint, it has no brush engine.

enter()  remembers the object's mode, active UV map, Image Paint mode / canvas, active brush and
         unified colours, then: RW_Paint becomes the active UV (never the render UV), Texture
         Paint mode in Single Image mode with the layer's mask (or content) image as canvas, the
         RealWorn brush, white primary and black secondary colour (Ctrl strokes erase).
set_mode PAINT (white, Mix), ERASE (black at full alpha: removes paint and the procedural
         fill under it), RESET (Erase Alpha: back to whatever the ingredients produce).
exit()   restores everything enter() changed and stores the image (packed or PNG).
Vertex-colour fallback (PNT-11): the mask is the corner colour attribute rw_vmask_<layer id>,
painted in Vertex Paint mode.
"""

import json

import bpy

from . import compiler, ctx, grunge, images, naming

STATE = "rw_paint_state"


def painting(obj):
    return obj is not None and STATE in obj


def _asset_ref(ip):
    ref = getattr(ip, "brush_asset_reference", None)
    if ref is None:
        return None
    return [ref.asset_library_type, ref.asset_library_identifier, ref.relative_asset_identifier]


def _activate_ref(ref):
    if not ref or not ref[2]:
        return False
    try:
        with bpy.context.temp_override(**ctx.override()):
            bpy.ops.brush.asset_activate(asset_library_type=ref[0], asset_library_identifier=ref[1],
                                         relative_asset_identifier=ref[2])
        return True
    except (RuntimeError, TypeError):
        return False


def _vertex_attr(obj, layer):
    me = obj.data
    name = naming.ATTR_VMASK + layer.id
    attr = me.color_attributes.get(name)
    if attr is None:
        active = me.color_attributes.active_color_name
        attr = me.color_attributes.new(name, "BYTE_COLOR", "CORNER")
        attr.data.foreach_set("color", [0.0, 0.0, 0.0, 0.0] * len(attr.data))
        if active:
            me.color_attributes.active_color_name = active
    return attr


def target_image(obj, mat, layer, target="MASK"):
    if target == "CONTENT":
        return images.ensure_content(obj, mat, layer)
    return images.ensure_mask(obj, mat, layer)


def enter(obj, mat, layer, target="MASK", mask_view=False):
    """PNT-4: switch to painting the layer's mask (or content image). Returns the canvas image
    (None for vertex-colour masks)."""
    ts = bpy.context.scene.tool_settings
    ip = ts.image_paint
    ups = ip.unified_paint_settings
    me = obj.data
    if not painting(obj):
        state = {
            "mode": obj.mode,
            "uv_active": me.uv_layers.active.name if me.uv_layers.active else None,
            "ip_mode": ip.mode,
            "canvas": ip.canvas.name if ip.canvas else None,
            "brush": _asset_ref(ip),
            "unified_color": ups.use_unified_color,
            "color": list(ups.color), "secondary": list(ups.secondary_color),
            "vp_brush": _asset_ref(ts.vertex_paint) if ts.vertex_paint else None,
            "color_attr": me.color_attributes.active_color_name,
            "material": mat.name, "mask_view": mat.realworn.mask_view,
        }
        obj[STATE] = json.dumps(state)
    state = json.loads(obj[STATE])
    state["layer"] = layer.id
    state["target"] = target
    obj[STATE] = json.dumps(state)
    idx = next(i for i, ly in enumerate(mat.realworn.layers) if ly.id == layer.id)
    if mat.realworn.active_layer_index != idx:
        with compiler.batch(mat):
            mat.realworn.active_layer_index = idx
    if layer.use_vertex_mask:
        attr = _vertex_attr(obj, layer)
        me.color_attributes.active_color_name = attr.name
        if obj.mode != "VERTEX_PAINT":
            with bpy.context.temp_override(**ctx.override(obj)):
                bpy.ops.object.mode_set(mode="VERTEX_PAINT")
        grunge.activate_brush(grunge.ensure_brush("RW Soft", mode="VERTEX_PAINT"))
        set_mode(obj, "PAINT")
        compiler.compile(mat)
        return None
    img = target_image(obj, mat, layer, target)
    me.uv_layers.active = me.uv_layers[naming.UV_PAINT]
    if obj.mode != "TEXTURE_PAINT":
        with bpy.context.temp_override(**ctx.override(obj)):
            bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    ip.mode = "IMAGE"
    ip.canvas = img
    grunge.activate_brush(grunge.ensure_brush(grunge.chosen_brush()))
    set_mode(obj, "PAINT")
    if mask_view and target == "MASK" and not mat.realworn.mask_view:
        mat.realworn.mask_view = True
    return img


def _brush(ts, obj):
    if obj is not None and obj.mode == "VERTEX_PAINT":
        return ts.vertex_paint.brush if ts.vertex_paint else None
    return ts.image_paint.brush


def set_mode(obj, mode):
    """PNT-5 / PNT-6: Paint (white), Erase (black, full alpha), Reset (Erase Alpha)."""
    ts = bpy.context.scene.tool_settings
    ups = ts.image_paint.unified_paint_settings
    ups.use_unified_color = True
    if mode == "ERASE":
        ups.color, ups.secondary_color = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    else:
        ups.color, ups.secondary_color = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    b = _brush(ts, obj)
    if b is not None and b.name.startswith("RW "):  # RealWorn only ever edits its own brushes
        b.blend = "ERASE_ALPHA" if mode == "RESET" else "MIX"
        b.color = ups.color
        b.secondary_color = ups.secondary_color
    if obj is not None and STATE in obj:
        st = json.loads(obj[STATE])
        st["paint_mode"] = mode
        obj[STATE] = json.dumps(st)
    return mode


def switch_layer(obj, mat):
    """Selecting another layer while painting switches the canvas immediately."""
    if not painting(obj):
        return None
    st = json.loads(obj[STATE])
    layer = mat.realworn.layers[mat.realworn.active_layer_index]
    if layer.id == st.get("layer"):
        return None
    return enter(obj, mat, layer, st.get("target", "MASK"))


def exit(obj):
    """PNT-9: back to the previous mode, UV, canvas, brush and colours; store the image."""
    if not painting(obj):
        return False
    st = json.loads(obj[STATE])
    ts = bpy.context.scene.tool_settings
    ip = ts.image_paint
    ups = ip.unified_paint_settings
    canvas = ip.canvas
    me = obj.data
    if obj.mode != st["mode"]:
        with bpy.context.temp_override(**ctx.override(obj)):
            bpy.ops.object.mode_set(mode=st["mode"] if st["mode"] in ("OBJECT", "EDIT", "SCULPT", "VERTEX_PAINT",
                                                                       "WEIGHT_PAINT", "TEXTURE_PAINT") else "OBJECT")
    if st["uv_active"] and st["uv_active"] in me.uv_layers:
        me.uv_layers.active = me.uv_layers[st["uv_active"]]
    ip.mode = st["ip_mode"]
    ip.canvas = bpy.data.images.get(st["canvas"]) if st["canvas"] else None
    _activate_ref(st.get("brush"))
    ups.use_unified_color = st["unified_color"]
    ups.color, ups.secondary_color = st["color"], st["secondary"]
    if st.get("color_attr") and st["color_attr"] in me.color_attributes:
        me.color_attributes.active_color_name = st["color_attr"]
    mat = bpy.data.materials.get(st.get("material", ""))
    if mat is not None and mat.realworn.mask_view != st.get("mask_view", False):
        mat.realworn.mask_view = st.get("mask_view", False)
    del obj[STATE]
    if canvas is not None and images.is_rw_image(canvas) and canvas.is_dirty:
        images.store(canvas)
    return True

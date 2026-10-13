"""Paint mode (PNT-1, PNT-2, PNT-4): RealWorn drives Blender's own texture paint; it has no brush
engine.

enter()  remembers the object's mode, active UV map, Image Paint mode / canvas, active brush and
         unified colours, then: RW_Paint becomes the active UV (never the render UV), Texture
         Paint mode in Single Image mode with the layer's image as canvas, the kind's brush
         (RW Soft, RW Damage with the damage alpha, RW Stencil with the decal), white primary and
         black secondary colour, so holding Ctrl paints black (erases a mask).
set_mode PAINT, or ERASE: masks paint black; a Decals image erases alpha (DEC-5, Erase Alpha).
exit()   restores everything enter() changed and stores the image (packed or PNG).
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


def enter(obj, mat, layer, mask_view=False):
    """PNT-1: switch to painting the layer's image. Returns the canvas image."""
    from . import kinds
    if not (kinds.paintable(layer.kind)):
        raise ValueError("{} layers are not painted".format(kinds.label(layer.kind)))
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
            "material": mat.name, "mask_view": mat.realworn.mask_view,
        }
        obj[STATE] = json.dumps(state)
    state = json.loads(obj[STATE])
    state["layer"] = layer.id
    obj[STATE] = json.dumps(state)
    idx = next(i for i, ly in enumerate(mat.realworn.layers) if ly.id == layer.id)
    if mat.realworn.active_layer_index != idx:
        with compiler.batch(mat):
            mat.realworn.active_layer_index = idx
    img = images.ensure_mask(obj, mat, layer)
    me.uv_layers.active = me.uv_layers[naming.UV_PAINT]
    if obj.mode != "TEXTURE_PAINT":
        with bpy.context.temp_override(**ctx.override(obj)):
            bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    ip.mode = "IMAGE"
    ip.canvas = img
    _, _, _, region = ctx.window_area()
    brush = grunge.prepare_brush(layer.kind, region=region)
    grunge.activate_brush(brush)
    set_mode(obj, "PAINT")
    if mask_view and layer.kind != "DECALS" and not mat.realworn.mask_view:
        mat.realworn.mask_view = True
    return img


def _layer_of(obj):
    if not painting(obj):
        return None, None
    st = json.loads(obj[STATE])
    mat = bpy.data.materials.get(st.get("material", ""))
    if mat is None:
        return None, None
    return mat, compiler.layer_by_id(mat, st.get("layer", ""))


def set_mode(obj, mode):
    """PAINT (white), or ERASE: black on masks, Erase Alpha on a Decals image (DEC-5)."""
    ts = bpy.context.scene.tool_settings
    ups = ts.image_paint.unified_paint_settings
    ups.use_unified_color = True
    _, layer = _layer_of(obj)
    decal = layer is not None and layer.kind == "DECALS"
    if mode == "ERASE" and not decal:
        ups.color, ups.secondary_color = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    else:
        ups.color, ups.secondary_color = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    b = ts.image_paint.brush
    if b is not None and b.get("rw_brush"):  # RealWorn only ever edits its own brushes
        b.blend = "ERASE_ALPHA" if (mode == "ERASE" and decal) else "MIX"
        b.color = ups.color
        b.secondary_color = ups.secondary_color
    if obj is not None and STATE in obj:
        st = json.loads(obj[STATE])
        st["paint_mode"] = mode
        obj[STATE] = json.dumps(st)
    return mode


def switch_layer(obj, mat):
    """Selecting another layer while painting switches the canvas immediately."""
    from . import kinds
    if not painting(obj):
        return None
    st = json.loads(obj[STATE])
    layer = mat.realworn.layers[mat.realworn.active_layer_index]
    if layer.id == st.get("layer") or not kinds.paintable(layer.kind):
        return None
    return enter(obj, mat, layer)


def exit(obj):
    """Back to the previous mode, UV, canvas, brush and colours; store the image."""
    if not painting(obj):
        return False
    st = json.loads(obj[STATE])
    ts = bpy.context.scene.tool_settings
    ip = ts.image_paint
    ups = ip.unified_paint_settings
    canvas = ip.canvas
    me = obj.data
    b = ip.brush
    if b is not None and b.get("rw_brush"):
        b.blend = "MIX"
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
    mat = bpy.data.materials.get(st.get("material", ""))
    if mat is not None and mat.realworn.mask_view != st.get("mask_view", False):
        mat.realworn.mask_view = st.get("mask_view", False)
    del obj[STATE]
    if canvas is not None and images.is_rw_image(canvas) and canvas.is_dirty:
        images.store(canvas)
    return True

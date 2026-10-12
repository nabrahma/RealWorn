"""While painting (PRD v2 "While painting"): a small viewport overlay and a pie menu.

Overlay: layer name, Paint / Erase / Reset, brush mode and a grunge thumbnail, drawn only while an
object is in RealWorn paint mode. Pie menu: Paint, Erase, Reset, Next Layer, Previous Layer, Mask
View, Exit. Its keymap item lives in the add-on keyconfig and is unassigned by default (key NONE)
so it never clashes; assign a key in Preferences > Keymap (search "RealWorn Paint"). Keymaps are
scoped to the add-on keyconfig, as Paint System does (docs/reference_notes.md).
"""

import json

import bpy
from bpy.props import EnumProperty, StringProperty

_draw_handle = None
_keymaps = []


def _painting_state(context):
    ob = context.active_object
    if ob is None or "rw_paint_state" not in ob:
        return None, None, None
    try:
        st = json.loads(ob["rw_paint_state"])
    except ValueError:
        return None, None, None
    mat = bpy.data.materials.get(st.get("material", ""))
    layer = None
    if mat is not None:
        layer = next((ly for ly in mat.realworn.layers if ly.id == st.get("layer")), None)
    return st, mat, layer


def _draw_overlay():
    context = bpy.context
    st, mat, layer = _painting_state(context)
    if st is None or layer is None or context.region is None:
        return
    import blf
    brush = context.tool_settings.image_paint.brush if context.tool_settings.image_paint else None
    mode = st.get("paint_mode", "PAINT").title()
    tex = brush.mask_texture if brush is not None and brush.name.startswith("RW ") else None
    mapping = brush.mask_texture_slot.mask_map_mode.title().replace("_", " ") if tex is not None else "Soft"
    lines = ["RealWorn  {}".format(layer.name), "{}  |  {}".format(mode, mapping)]
    font = 0
    blf.size(font, 13)
    x, y = 20, 60
    for i, text in enumerate(lines):
        blf.color(font, 1.0, 1.0, 1.0, 0.9 if i == 0 else 0.7)
        blf.position(font, x + (56 if tex is not None else 0), y - i * 18, 0)
        blf.draw(font, text)
    if tex is not None and tex.image is not None:
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader
            texture = gpu.texture.from_image(tex.image)
            shader = gpu.shader.from_builtin("IMAGE")
            s = 46
            batch = batch_for_shader(shader, "TRI_FAN", {"pos": ((x, y - 26), (x + s, y - 26), (x + s, y + 20),
                                                                 (x, y + 20)),
                                                         "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})
            shader.bind()
            shader.uniform_sampler("image", texture)
            batch.draw(shader)
        except Exception:
            pass  # the thumbnail is a nicety; never break drawing


class RW_OT_layer_step(bpy.types.Operator):
    """Select the next (up) or previous (down) layer; while painting the canvas follows"""
    bl_idname = "realworn.layer_step"
    bl_label = "Next / Previous Layer"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Next (up)", ""), ("DOWN", "Previous (down)", "")], default="UP")
    material: StringProperty(default="")

    def execute(self, context):
        ob = context.active_object
        mat = bpy.data.materials.get(self.material) if self.material else (ob.active_material if ob else None)
        if mat is None or not len(mat.realworn.layers):
            return {"CANCELLED"}
        st = mat.realworn
        st.active_layer_index = max(0, min(len(st.layers) - 1, st.active_layer_index + (1 if self.direction == "UP"
                                                                                       else -1)))
        return {"FINISHED"}


class RW_OT_mask_view_toggle(bpy.types.Operator):
    """Show the selected layer's final mask as greyscale (toggle)"""
    bl_idname = "realworn.mask_view_toggle"
    bl_label = "Mask View"
    bl_options = {"REGISTER", "UNDO"}

    material: StringProperty(default="")

    def execute(self, context):
        ob = context.active_object
        mat = bpy.data.materials.get(self.material) if self.material else (ob.active_material if ob else None)
        if mat is None or not mat.realworn.applied:
            return {"CANCELLED"}
        mat.realworn.mask_view = not mat.realworn.mask_view
        return {"FINISHED"}


class RW_MT_paint_pie(bpy.types.Menu):
    bl_idname = "RW_MT_paint_pie"
    bl_label = "RealWorn Paint"

    def draw(self, context):
        pie = self.layout.menu_pie()
        pie.operator("realworn.paint_mode", text="Erase", icon="REMOVE").mode = "ERASE"
        pie.operator("realworn.paint_mode", text="Paint", icon="ADD").mode = "PAINT"
        pie.operator("realworn.layer_step", text="Previous Layer", icon="TRIA_DOWN").direction = "DOWN"
        pie.operator("realworn.layer_step", text="Next Layer", icon="TRIA_UP").direction = "UP"
        pie.operator("realworn.paint_mode", text="Reset", icon="LOOP_BACK").mode = "RESET"
        pie.operator("realworn.mask_view_toggle", icon="MOD_MASK")
        pie.operator("realworn.paint_exit", icon="CHECKMARK")


_classes = (RW_OT_layer_step, RW_OT_mask_view_toggle, RW_MT_paint_pie)


def register():
    global _draw_handle
    for c in _classes:
        bpy.utils.register_class(c)
    if not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), "WINDOW", "POST_PIXEL")
    kc = bpy.context.window_manager.keyconfigs.addon if bpy.context.window_manager else None
    if kc is not None:
        for km_name in ("Image Paint", "Vertex Paint"):
            km = kc.keymaps.new(name=km_name, space_type="EMPTY")
            kmi = km.keymap_items.new("wm.call_menu_pie", type="NONE", value="PRESS")
            kmi.properties.name = RW_MT_paint_pie.bl_idname
            _keymaps.append((km, kmi))


def unregister():
    global _draw_handle
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

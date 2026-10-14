"""While painting: a small viewport overlay and a pie menu.

Overlay (UI-6): one line with the layer name, the brush and its shortcuts, drawn only while an
object is in RealWorn paint mode. Pie menu: Paint, Erase, Next Layer, Previous Layer, Mask View,
Exit. Its keymap item lives in the add-on keyconfig and is unassigned by default (key NONE)
so it never clashes; assign a key in Preferences > Keymap (search "RealWorn Paint"). Keymaps are
scoped to the add-on keyconfig, as Paint System does (THIRD_PARTY.md).
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


SHORTCUTS = {
    "RW Soft": "F size, Shift F strength, Ctrl erase",
    "RW Damage": "F size, Shift F strength, Ctrl erase; the alpha follows the stroke (Rake)",
    "RW Stencil": "Right-drag move, Ctrl right-drag rotate, Shift right-drag scale; Ctrl erases alpha",
}


def overlay_text(layer, brush_name):
    """UI-6: one line: layer name, brush, and the shortcuts for it (Blender's own, PNT-4)."""
    return "RealWorn  {}  |  {}  |  {}".format(layer.name, brush_name, SHORTCUTS.get(brush_name, "F size"))


def _draw_overlay():
    context = bpy.context
    st, mat, layer = _painting_state(context)
    if st is None or layer is None or context.region is None:
        return
    import blf
    brush = context.tool_settings.image_paint.brush if context.tool_settings.image_paint else None
    text = overlay_text(layer, brush.name if brush is not None else "")
    if st.get("paint_mode") == "ERASE":
        text += "  |  ERASING"
    font = 0
    scale = context.preferences.system.ui_scale
    blf.size(font, 13 * scale)
    # top left, in line with the view name: Blender 5's brush asset shelf covers the bottom
    tools = next((r.width for r in context.area.regions if r.type == "TOOLS"), 0) if context.area else 0
    x, y = int(tools + 20 * scale), int(context.region.height - 110 * scale)
    blf.color(font, 1.0, 1.0, 1.0, 0.9)
    blf.position(font, x, y, 0)
    blf.draw(font, text)


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


def _painting_decal(context):
    st, mat, layer = _painting_state(context)
    return layer is not None and layer.kind == "DECALS"


class RW_OT_decal_erase_stroke(bpy.types.Operator):
    """DEC-5: Ctrl + drag on a Decals layer erases alpha (Erase Alpha), so mistakes can be painted
    out without touching what is underneath. Only active while painting a Decals layer; elsewhere
    Ctrl + drag keeps Blender's own behaviour (the mask layers paint black)"""
    bl_idname = "realworn.decal_erase_stroke"
    bl_label = "Erase Decal"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "PAINT_TEXTURE" and _painting_decal(context)

    def invoke(self, context, event):
        brush = context.tool_settings.image_paint.brush
        if brush is None or not brush.get("rw_brush"):
            return {"PASS_THROUGH"}
        self._brush = brush.name
        brush.blend = "ERASE_ALPHA"
        bpy.ops.paint.image_paint("INVOKE_DEFAULT", mode="NORMAL")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if (event.type == "LEFTMOUSE" and event.value == "RELEASE") or event.type in ("ESC", "RIGHTMOUSE"):
            b = bpy.data.brushes.get(self._brush)
            if b is not None:
                b.blend = "MIX"
            return {"FINISHED", "PASS_THROUGH"}
        return {"PASS_THROUGH"}


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
        pie.operator("realworn.mask_view_toggle", icon="MOD_MASK")
        pie.operator("realworn.paint_exit", icon="CHECKMARK")


_classes = (RW_OT_layer_step, RW_OT_decal_erase_stroke, RW_OT_mask_view_toggle, RW_MT_paint_pie)


def register():
    global _draw_handle
    for c in _classes:
        bpy.utils.register_class(c)
    if not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), "WINDOW", "POST_PIXEL")
    kc = bpy.context.window_manager.keyconfigs.addon if bpy.context.window_manager else None
    if kc is not None:
        for km_name in ("Image Paint",):
            km = kc.keymaps.new(name=km_name, space_type="EMPTY")
            kmi = km.keymap_items.new("wm.call_menu_pie", type="NONE", value="PRESS")
            kmi.properties.name = RW_MT_paint_pie.bl_idname
            _keymaps.append((km, kmi))
            kmi = km.keymap_items.new(RW_OT_decal_erase_stroke.bl_idname, type="LEFTMOUSE", value="PRESS", ctrl=True)
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

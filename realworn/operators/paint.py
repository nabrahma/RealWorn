"""Paint Wear (W4): Vertex Paint on rw_paint with a preset brush colour."""

import bpy
from bpy.props import EnumProperty

from ..core import masks, naming, paint


class RW_OT_paint_wear(bpy.types.Operator):
    """Paint wear by hand: red adds wear, blue removes it (Ctrl clears)"""
    bl_idname = "realworn.paint_wear"
    bl_label = "Paint Wear"
    bl_options = {"REGISTER", "UNDO"}

    channel: EnumProperty(name="Brush", items=[
        ("ADD", "Add Wear", "Red: forces edge wear"),
        ("REMOVE", "Remove Wear", "Blue: removes wear, dirt, grime and dust"),
    ], default="ADD")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and masks.is_supported(context.active_object)

    def execute(self, context):
        ob = context.active_object
        paint.ensure(ob.data)
        ob.data.color_attributes.active_color_name = naming.ATTR_PAINT
        if ob.mode != "VERTEX_PAINT":
            bpy.ops.object.mode_set(mode="VERTEX_PAINT")
        paint.set_brush(context.tool_settings, self.channel)
        self.report({"INFO"}, "Painting rw_paint: {} (Ctrl paints black to clear)".format(self.channel.title()))
        return {"FINISHED"}


_classes = (RW_OT_paint_wear,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

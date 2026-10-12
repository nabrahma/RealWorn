"""3D Viewport sidebar tab "RealWorn"."""

import bpy


class RW_PT_main(bpy.types.Panel):
    bl_label = "RealWorn"
    bl_idname = "RW_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RealWorn"

    def draw(self, context):
        self.layout.label(text="RealWorn is loaded")


_classes = (RW_PT_main,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

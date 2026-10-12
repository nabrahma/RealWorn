"""3D Viewport sidebar tab "RealWorn": scene-wide first, then per-object, then tools."""

import bpy

from ..core import masks, naming


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RealWorn"


class RW_PT_scene(_Base, bpy.types.Panel):
    bl_label = "Scene Weather"
    bl_idname = "RW_PT_scene"

    def draw(self, context):
        p = context.scene.realworn
        col = self.layout.column(align=True)
        for prop in ("age", "dirt", "dust", "wetness"):
            col.prop(p, prop, slider=True)
        self.layout.prop(p, "rain")


class RW_PT_object(_Base, bpy.types.Panel):
    bl_label = "Object"
    bl_idname = "RW_PT_object"

    def draw(self, context):
        lay = self.layout
        ob = context.active_object
        if ob is None:
            lay.label(text="No active object")
            return
        if not masks.is_supported(ob):
            lay.label(text="{}: not a mesh".format(ob.name), icon="ERROR")
            return
        lay.operator("realworn.add_masks", icon="MOD_DATA_TRANSFER")
        if masks.has_nonuniform_scale(ob):
            lay.label(text="Non-uniform scale: widths use the mean scale", icon="ERROR")
        if masks.large_ngon_count(ob.data):
            lay.label(text="Large n-gons: masks smear across them", icon="ERROR")


class RW_PT_mask_settings(_Base, bpy.types.Panel):
    bl_label = "Mask Settings"
    bl_idname = "RW_PT_mask_settings"
    bl_parent_id = "RW_PT_object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "MESH" and masks.masks_modifier(ob) is not None

    def draw(self, context):
        mod = masks.masks_modifier(context.active_object)
        col = self.layout.column()
        for name in ("Edge Angle Threshold", "Edge Width", "Cavity Width", "Contact Width",
                     "Blur Iterations", "Pre-Subdivide"):
            item = masks._input_item(mod, name)
            col.prop(item, "value", text=name)


class RW_PT_debug(_Base, bpy.types.Panel):
    bl_label = "Debug"
    bl_idname = "RW_PT_debug"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        p = context.scene.realworn
        self.layout.prop(p, "mask_preview")


_classes = (RW_PT_scene, RW_PT_object, RW_PT_mask_settings, RW_PT_debug)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

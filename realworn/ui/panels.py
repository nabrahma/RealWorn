"""3D Viewport sidebar tab "RealWorn": scene-wide first, then per-object, then tools."""

import bpy

from ..core import masks, naming, weathering


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RealWorn"


class RW_PT_scene(_Base, bpy.types.Panel):
    bl_label = "Scene Weather"
    bl_idname = "RW_PT_scene"

    def draw(self, context):
        p = context.scene.realworn
        lay = self.layout
        col = lay.column(align=True)
        for prop in ("age", "dirt", "dust", "wetness"):
            col.prop(p, prop, slider=True)
        lay.prop(p, "rain", icon="MOD_FLUIDSIM")
        col = lay.column(align=True)
        col.prop(p, "splash_height")
        row = col.row(align=True)
        row.prop(p, "ground_z_auto", text="Auto Ground Z")
        sub = row.row(align=True)
        sub.enabled = not p.ground_z_auto
        sub.prop(p, "ground_z", text="")
        row = lay.row(align=True)
        row.operator("realworn.mark_ground", icon="VIEW_PERSPECTIVE").state = True
        row.operator("realworn.mark_ground", text="", icon="X").state = False
        row = lay.row(align=True)
        row.operator("realworn.mark_occluder", icon="MOD_SOLIDIFY").state = True
        row.operator("realworn.mark_occluder", text="", icon="X").state = False


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
        sp = context.scene.realworn
        p = ob.realworn
        lay.prop(sp, "preset")
        row = lay.row(align=True)
        row.scale_y = 1.3
        row.operator("realworn.apply", icon="BRUSH_DATA")
        row.operator("realworn.update", icon="FILE_REFRESH")
        row.operator("realworn.remove", icon="X")
        if not p.applied:
            return
        lay.label(text="Preset: {}".format(p.preset or "AUTO"))
        col = lay.column(align=True)
        col.prop(p, "wear", slider=True)
        col.prop(p, "dirt", slider=True)
        row = lay.row(align=True)
        row.prop(p, "seed")
        row.operator("realworn.randomize_seed", text="", icon="FILE_REFRESH")
        lay.prop(p, "edge_source")
        if p.edge_source != "ATTRIBUTE" and context.scene.render.engine.startswith("BLENDER_EEVEE"):
            lay.label(text="EEVEE: Bevel source falls back to Attribute", icon="INFO")
        lay.prop(p, "cavity_source")
        row = lay.row(align=True)
        row.operator("realworn.paint_wear", text="Paint Wear", icon="BRUSH_DATA").channel = "ADD"
        row.operator("realworn.paint_wear", text="", icon="REMOVE").channel = "REMOVE"
        row.operator("realworn.paint_wear", text="", icon="MOD_FLUIDSIM").channel = "DRY"
        shared = [m for m in weathering.materials_of(ob) if m.users > 1]
        if shared:
            box = lay.box()
            box.label(text="{} shared material(s), {} users".format(len(shared), max(m.users for m in shared)),
                      icon="LINKED")
            box.operator("realworn.make_single_user")
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


class RW_PT_decals(_Base, bpy.types.Panel):
    bl_label = "Decals"
    bl_idname = "RW_PT_decals"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        p = context.scene.realworn
        lay = self.layout
        lay.template_icon_view(p, "decal_image", show_labels=True, scale=5.0)
        lay.prop(p, "decal_mode", expand=True)
        lay.prop(p, "decal_size")
        row = lay.row(align=True)
        op = row.operator("realworn.decal_place", text="Place", icon="RESTRICT_SELECT_OFF")
        op.mode, op.size = p.decal_mode, p.decal_size
        op = row.operator("realworn.decal_place", text="At Cursor", icon="PIVOT_CURSOR")
        op.use_cursor, op.mode, op.size = True, p.decal_mode, p.decal_size
        row = lay.row(align=True)
        row.operator("realworn.decal_auto_leaks", icon="MOD_OCEAN")
        row.prop(p, "leak_seed", text="Seed")
        lay.operator("realworn.decal_cleanup", icon="BRUSH_DATA")


class RW_PT_debug(_Base, bpy.types.Panel):
    bl_label = "Debug"
    bl_idname = "RW_PT_debug"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        p = context.scene.realworn
        lay = self.layout
        lay.prop(p, "mask_preview")
        lay.operator("realworn.add_masks", icon="MOD_DATA_TRANSFER")
        lay.operator("realworn.remove_all", icon="TRASH")


_classes = (RW_PT_scene, RW_PT_object, RW_PT_mask_settings, RW_PT_decals, RW_PT_debug)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

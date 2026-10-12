"""Bake (W9) and Restore Live Stack."""

import bpy
from bpy.props import BoolProperty, StringProperty

from ..core import bake, injector, weathering
from .common import OBJECTS_DESC, target_objects


def smart_uv(context, obj):
    """Create a UV map with Smart UV Project (an edit-mode operator, so it lives here, not in core)."""
    obj.data.uv_layers.new(name="UVMap")
    prev = context.view_layer.objects.active
    with context.temp_override(active_object=obj, object=obj, selected_objects=[obj],
                               selected_editable_objects=[obj]):
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.01)
        bpy.ops.object.mode_set(mode="OBJECT")
    context.view_layer.objects.active = prev


class RW_OT_bake(bpy.types.Operator):
    """Bake Base Color, Roughness, Metallic, Normal and the masks to images and use them instead of the live stack"""
    bl_idname = "realworn.bake"
    bl_label = "Bake Selected"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")
    auto_uv: BoolProperty(name="Create Missing UVs", default=True)
    single_user: BoolProperty(name="Make Shared Materials Single User", default=True)

    def execute(self, context):
        p = context.scene.realworn
        done = 0
        for o in target_objects(context, self.objects):
            if not o.realworn.applied:
                continue
            if not o.data.uv_layers and self.auto_uv:
                smart_uv(context, o)
            if self.single_user:
                for slot in o.material_slots:
                    m = slot.material
                    if m is not None and injector.is_applied(m) and len(weathering.users_of(m)) > 1:
                        slot.material = m.copy()
            try:
                imgs = bake.bake_object(o, context.scene, int(p.bake_resolution), p.bake_folder, masks=p.bake_masks)
                done += 1
                self.report({"INFO"}, "{}: baked {} images".format(o.name, len(imgs)))
            except bake.BakeError as ex:
                self.report({"WARNING"}, str(ex))
        return {"FINISHED"} if done else {"CANCELLED"}


class RW_OT_bake_restore(bpy.types.Operator):
    """Use the live RealWorn stack again instead of the baked images (images are kept)"""
    bl_idname = "realworn.bake_restore"
    bl_label = "Restore Live Stack"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        n = 0
        for o in target_objects(context, self.objects):
            for m in weathering.materials_of(o):
                if injector.is_applied(m) and m.realworn.baked:
                    n += bake.restore_live(m)
        self.report({"INFO"}, "Restored the live stack on {} material(s)".format(n))
        return {"FINISHED"}


_classes = (RW_OT_bake, RW_OT_bake_restore)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

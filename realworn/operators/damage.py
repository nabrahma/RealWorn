"""Damage operators (W7): Add Damage, Remove Damage, Show in Viewport."""

import bpy
from bpy.props import BoolProperty, StringProperty

from ..core import damage
from .common import OBJECTS_DESC, target_objects


class RW_OT_damage_add(bpy.types.Operator):
    """Cut chips and corner breaks into the selected closed meshes (non-destructive modifier)"""
    bl_idname = "realworn.damage_add"
    bl_label = "Add Damage"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        done = 0
        settings = damage.settings_from_scene(context.scene)
        for o in target_objects(context, self.objects):
            try:
                damage.add_damage(o, context.scene, settings)
                done += 1
            except damage.DamageError as ex:
                self.report({"WARNING"}, str(ex))
        self.report({"INFO"}, "Damage on {} object(s)".format(done))
        return {"FINISHED"} if done else {"CANCELLED"}


class RW_OT_damage_remove(bpy.types.Operator):
    """Remove the RW_Damage modifier from the selected objects"""
    bl_idname = "realworn.damage_remove"
    bl_label = "Remove Damage"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        n = sum(damage.remove_damage(o) for o in target_objects(context, self.objects))
        self.report({"INFO"}, "Removed damage from {} object(s)".format(n))
        return {"FINISHED"}


class RW_OT_damage_viewport(bpy.types.Operator):
    """Show or hide damage in the viewport; renders always include it"""
    bl_idname = "realworn.damage_viewport"
    bl_label = "Damage in Viewport"
    bl_options = {"REGISTER", "UNDO"}

    state: BoolProperty(name="Show", default=True)
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        for o in target_objects(context, self.objects):
            damage.set_show_viewport(o, self.state)
        return {"FINISHED"}


_classes = (RW_OT_damage_add, RW_OT_damage_remove, RW_OT_damage_viewport)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

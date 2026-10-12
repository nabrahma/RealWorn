"""Apply, Update, Remove, Remove All, Randomise (W1, W8)."""

import random

import bpy
from bpy.props import EnumProperty, StringProperty

from ..core import weathering
from ..props import PRESET_ITEMS
from .common import OBJECTS_DESC, target_objects


def _report(op, reps):
    worst = "INFO"
    for level, msg in reps:
        op.report({level}, msg)
        if level in ("WARNING", "ERROR"):
            worst = level
    return worst


class RW_OT_apply(bpy.types.Operator):
    """Weather the selected meshes: add the mask modifier and inject every material"""
    bl_idname = "realworn.apply"
    bl_label = "Apply"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Preset", items=PRESET_ITEMS, default="AUTO")
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def invoke(self, context, event):
        self.preset = context.scene.realworn.preset
        return self.execute(context)

    def execute(self, context):
        obs = target_objects(context, self.objects, meshes_only=False)
        if not obs:
            self.report({"WARNING"}, "Select at least one mesh")
            return {"CANCELLED"}
        reps, n = [], 0
        for o in obs:
            r = weathering.apply_object(o, context.scene, self.preset)
            reps += r
            n += o.realworn.applied
        _report(self, reps)
        self.report({"INFO"}, "RealWorn applied to {} object(s)".format(n))
        return {"FINISHED"}


class RW_OT_update(bpy.types.Operator):
    """Re-apply the chosen preset's values without re-injecting"""
    bl_idname = "realworn.update"
    bl_label = "Update"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Preset", items=PRESET_ITEMS, default="AUTO")
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def invoke(self, context, event):
        self.preset = context.scene.realworn.preset
        return self.execute(context)

    def execute(self, context):
        obs = [o for o in target_objects(context, self.objects) if o.realworn.applied]
        for o in obs:
            weathering.update_object(o, context.scene, self.preset)
        self.report({"INFO"}, "Updated {} object(s)".format(len(obs)))
        return {"FINISHED"}


class RW_OT_remove(bpy.types.Operator):
    """Remove RealWorn from the selected objects and restore their materials exactly"""
    bl_idname = "realworn.remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        obs = target_objects(context, self.objects)
        reps = []
        for o in obs:
            reps += weathering.remove_object(o, context.scene)
        worst = _report(self, reps)
        self.report({"INFO"}, "Removed RealWorn from {} object(s)".format(len(obs)))
        return {"FINISHED"} if worst != "ERROR" else {"CANCELLED"}


class RW_OT_remove_all(bpy.types.Operator):
    """Remove every RealWorn modifier, node, decal, collection and property from the file"""
    bl_idname = "realworn.remove_all"
    bl_label = "Remove All RealWorn Data"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        reps = weathering.remove_all()
        _report(self, reps)
        self.report({"INFO"}, "RealWorn removed from the file")
        return {"FINISHED"}


class RW_OT_randomize_seed(bpy.types.Operator):
    """Reroll the per-object seed so this object wears differently"""
    bl_idname = "realworn.randomize_seed"
    bl_label = "Randomise"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        for o in target_objects(context, self.objects):
            o.realworn.seed = round(random.uniform(0.0, 1000.0), 2)
            weathering.sync_object(o)
        return {"FINISHED"}


class RW_OT_make_single_user(bpy.types.Operator):
    """Give the active object its own copies of shared weathered materials (for a different preset)"""
    bl_idname = "realworn.make_single_user"
    bl_label = "Make Single User"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        n = 0
        for o in target_objects(context, self.objects):
            for slot in o.material_slots:
                m = slot.material
                if m is not None and m.users > 1:
                    slot.material = m.copy()
                    n += 1
        self.report({"INFO"}, "Made {} material(s) single user".format(n))
        return {"FINISHED"}


_classes = (RW_OT_make_single_user, RW_OT_apply, RW_OT_update, RW_OT_remove, RW_OT_remove_all, RW_OT_randomize_seed)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

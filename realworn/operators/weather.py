"""Scene weather tools: Mark as Ground (WX-13), Mark as Occluder (WX-14)."""

import bpy
from bpy.props import BoolProperty, StringProperty

from ..core import weather, weathering
from .common import OBJECTS_DESC, target_objects


class RW_OT_mark_ground(bpy.types.Operator):
    """Let the selected objects hold puddles and act as the ground for contact grime"""
    bl_idname = "realworn.mark_ground"
    bl_label = "Mark as Ground"
    bl_options = {"REGISTER", "UNDO"}

    state: BoolProperty(name="Ground", default=True, description="Off un-marks the objects")
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        obs = target_objects(context, self.objects)
        for o in obs:
            if self.state and not o.realworn.applied:
                weathering.apply_object(o, context.scene, context.scene.realworn.preset)
            weather.mark_ground(o, context.scene, self.state)
        self.report({"INFO"}, "{} {} object(s)".format("Marked" if self.state else "Unmarked", len(obs)))
        return {"FINISHED"}


class RW_OT_mark_occluder(bpy.types.Operator):
    """Roofs, awnings and balconies: objects below them stay dry and collect less dust"""
    bl_idname = "realworn.mark_occluder"
    bl_label = "Mark as Occluder"
    bl_options = {"REGISTER", "UNDO"}

    state: BoolProperty(name="Occluder", default=True)
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        obs = target_objects(context, self.objects, meshes_only=True)
        for o in obs:
            weather.mark_occluder(o, self.state)
        self.report({"INFO"}, "{} {} occluder(s)".format("Marked" if self.state else "Unmarked", len(obs)))
        return {"FINISHED"}


_classes = (RW_OT_mark_ground, RW_OT_mark_occluder)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

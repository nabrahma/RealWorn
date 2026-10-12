"""Mark as Ground: objects the Contact generator measures distance to (RW_Ground)."""

import bpy
from bpy.props import BoolProperty, StringProperty

from ..core import masks
from .common import OBJECTS_DESC, target_objects


class RW_OT_mark_ground(bpy.types.Operator):
    """Contact grime is measured against ground objects (floors, terrain)"""
    bl_idname = "realworn.mark_ground"
    bl_label = "Mark as Ground"
    bl_options = {"REGISTER", "UNDO"}

    state: BoolProperty(name="Ground", default=True, description="Off un-marks the objects")
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        obs = target_objects(context, self.objects, meshes_only=True)
        for o in obs:
            masks.mark_ground(o, self.state)
        self.report({"INFO"}, "{} {} object(s)".format("Marked" if self.state else "Unmarked", len(obs)))
        return {"FINISHED"}


_classes = (RW_OT_mark_ground,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

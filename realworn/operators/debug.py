"""Debug tools: Mask Preview, Validate Scene, Reload Add-on, Rebuild Assets."""

import bpy
from bpy.props import EnumProperty, StringProperty

from ..core import masks
from ..props import PREVIEW_ITEMS
from .common import OBJECTS_DESC, target_objects


class RW_OT_mask_preview(bpy.types.Operator):
    """Show one mask as greyscale on every weathered object (None restores)"""
    bl_idname = "realworn.mask_preview"
    bl_label = "Mask Preview"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="Mask", items=PREVIEW_ITEMS, default="EDGE")

    def execute(self, context):
        context.scene.realworn.mask_preview = self.mode  # update callback does the work
        return {"FINISHED"}


class RW_OT_add_masks(bpy.types.Operator):
    """Add the RW_Masks modifier to the selected meshes (Apply does this too)"""
    bl_idname = "realworn.add_masks"
    bl_label = "Add Masks"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def execute(self, context):
        obs = target_objects(context, self.objects, meshes_only=False)
        done = 0
        for o in obs:
            if not masks.is_supported(o):
                self.report({"WARNING"}, "{}: not a mesh, skipped (convert it first)".format(o.name))
                continue
            masks.ensure_masks(o)
            done += 1
        self.report({"INFO"}, "Masks on {} object(s)".format(done))
        return {"FINISHED"}


_classes = (RW_OT_mask_preview, RW_OT_add_masks)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

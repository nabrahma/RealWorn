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


class RW_OT_validate(bpy.types.Operator):
    """Report orphan nodes, missing attributes, schema mismatches and other RealWorn problems"""
    bl_idname = "realworn.validate"
    bl_label = "Validate Scene"

    def execute(self, context):
        from ..core import validate
        issues = validate.validate(context.scene)
        for level, msg in issues:
            self.report({level}, msg)
        self.report({"INFO"}, "Validate: {} issue(s)".format(len(issues)) if issues else "Validate: all good")
        return {"FINISHED"}


class RW_OT_rebuild_assets(bpy.types.Operator):
    """Developer: run the builders, rewrite the asset .blend and upgrade the open file"""
    bl_idname = "realworn.rebuild_assets"
    bl_label = "Rebuild Assets"

    def execute(self, context):
        from ..core import assets
        path, n = assets.build_asset_file()
        up = assets.upgrade_open_file()
        self.report({"INFO"}, "Rebuilt {} groups, upgraded {}".format(n, up))
        return {"FINISHED"}


def _reload_package():
    import importlib
    import sys
    import addon_utils
    pkg = __package__.rsplit(".", 1)[0]
    addon_utils.disable(pkg, default_set=False)
    for k in [k for k in sys.modules if k == pkg or k.startswith(pkg + ".")]:
        del sys.modules[k]
    importlib.invalidate_caches()
    addon_utils.enable(pkg, default_set=False)
    return None


class RW_OT_reload(bpy.types.Operator):
    """Developer: reload the add-on code without restarting Blender"""
    bl_idname = "realworn.reload"
    bl_label = "Reload Add-on"

    def execute(self, context):
        bpy.app.timers.register(_reload_package, first_interval=0.1)  # after this operator returns
        return {"FINISHED"}


_classes = (RW_OT_mask_preview, RW_OT_add_masks, RW_OT_validate, RW_OT_rebuild_assets, RW_OT_reload)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

"""Debug tools: Validate, Remove All, Reload Add-on."""

import bpy

from .common import report_all


class RW_OT_validate(bpy.types.Operator):
    """Report orphan nodes, missing images, unsaved masks, schema mismatches and other problems"""
    bl_idname = "realworn.validate"
    bl_label = "Validate"

    def execute(self, context):
        from ..core import validate
        issues = validate.validate(context.scene)
        for level, msg in issues:
            self.report({level}, msg)
        self.report({"INFO"}, "Validate: {} issue(s)".format(len(issues)) if issues else "Validate: all good")
        return {"FINISHED"}


class RW_OT_remove_all(bpy.types.Operator):
    """Remove every trace of RealWorn from the file (materials restored exactly)"""
    bl_idname = "realworn.remove_all"
    bl_label = "Remove All RealWorn Data"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from ..core import setup
        report_all(self, setup.remove_all())
        self.report({"INFO"}, "RealWorn removed from the file")
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


_classes = (RW_OT_validate, RW_OT_remove_all, RW_OT_reload)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

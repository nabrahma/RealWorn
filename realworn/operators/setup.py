"""Setup / Remove and layer list editing. Every operator also takes explicit object, material and
layer ids, so tests and scripts drive them without mouse context."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ..core import injector, layers, setup
from ..props import TYPE_ITEMS
from .common import OBJECTS_DESC, report_all, resolve_layer, resolve_material, target_objects


class RW_OT_setup(bpy.types.Operator):
    """Wrap the material as the Base layer, add the RW_Paint UV map and make the material unique
    to this object. Nothing about the look changes until you add and paint a layer"""
    bl_idname = "realworn.setup"
    bl_label = "Setup"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")
    use_existing_uv: BoolProperty(name="Use Existing UV", default=False,
                                  description="Copy the object's UV map into RW_Paint (clean 0 to 1 layouts)")

    def invoke(self, context, event):
        self.use_existing_uv = context.scene.realworn.use_existing_uv
        return self.execute(context)

    def execute(self, context):
        obs = target_objects(context, self.objects)
        if not obs:
            self.report({"WARNING"}, "Select a mesh object")
            return {"CANCELLED"}
        reps = []
        for o in obs:
            try:
                reps += setup.setup_object(o, self.use_existing_uv)
            except setup.SetupError as ex:
                reps.append(("WARNING", str(ex)))
        report_all(self, reps)
        self.report({"INFO"}, "Set up {} object(s)".format(len(obs)))
        return {"FINISHED"}


class RW_OT_remove(bpy.types.Operator):
    """Restore the original materials and remove every RealWorn node, UV map and modifier"""
    bl_idname = "realworn.remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")
    delete_masks: BoolProperty(name="Delete Painted Masks", default=True,
                               description="Painted masks are your work; export them first if you may want them")
    export_folder: StringProperty(name="Export Masks To", subtype="DIR_PATH", default="",
                                  description="Write every mask and content image as PNG here before removing")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Painted masks are your work. Export them first?", icon="ERROR")
        col.prop(self, "export_folder")
        col.prop(self, "delete_masks")

    def execute(self, context):
        from ..core import images
        obs = [o for o in target_objects(context, self.objects) if setup.is_setup(o)]
        reps = []
        for o in obs:
            if self.export_folder:
                paths = images.export_masks(o, bpy.path.abspath(self.export_folder))
                reps.append(("INFO", "{}: exported {} image(s)".format(o.name, len(paths))))
            reps += setup.remove_object(o, delete_images=self.delete_masks)
        report_all(self, reps)
        self.report({"INFO"}, "Removed RealWorn from {} object(s)".format(len(obs)))
        return {"FINISHED"}


class RW_OT_layer_add(bpy.types.Operator):
    """Add a layer above the selected one. It starts with an empty mask: nothing shows until you paint"""
    bl_idname = "realworn.layer_add"
    bl_label = "Add Layer"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(name="Type", items=TYPE_ITEMS, default="DIRT")
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")

    def execute(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if ob is not None and not setup.is_setup(ob):
            report_all(self, setup.setup_object(ob))
            ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat):
            self.report({"WARNING"}, "No material set up for layers (click Setup)")
            return {"CANCELLED"}
        if self.type == "DECAL":
            self.report({"INFO"}, "Use Place Decal to add a decal layer")
            return {"CANCELLED"}
        ly = layers.add_layer(mat, self.type)
        self.report({"INFO"}, "Added {} to {}".format(ly.name, mat.name))
        return {"FINISHED"}


class _LayerOp:
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="", description="Layer id; empty uses the selected layer")

    def _target(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat) or not len(mat.realworn.layers):
            return None, None
        return mat, resolve_layer(mat, self.layer)


class RW_OT_layer_remove(_LayerOp, bpy.types.Operator):
    """Delete the selected layer (and its painted mask)"""
    bl_idname = "realworn.layer_remove"
    bl_label = "Delete Layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat, idx = self._target(context)
        if mat is None:
            return {"CANCELLED"}
        layers.remove_layer(mat, idx)
        return {"FINISHED"}


class RW_OT_layer_move(_LayerOp, bpy.types.Operator):
    """Move the selected layer up or down the stack"""
    bl_idname = "realworn.layer_move"
    bl_label = "Move Layer"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(name="Direction", items=[("UP", "Up", ""), ("DOWN", "Down", "")], default="UP")

    def execute(self, context):
        mat, idx = self._target(context)
        if mat is None:
            return {"CANCELLED"}
        layers.move_layer(mat, idx, 1 if self.direction == "UP" else -1)
        return {"FINISHED"}


class RW_OT_layer_duplicate(_LayerOp, bpy.types.Operator):
    """Duplicate the selected layer, including a copy of its painted mask"""
    bl_idname = "realworn.layer_duplicate"
    bl_label = "Duplicate Layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat, idx = self._target(context)
        if mat is None:
            return {"CANCELLED"}
        layers.duplicate_layer(mat, idx)
        return {"FINISHED"}


class RW_OT_layer_select(_LayerOp, bpy.types.Operator):
    """Select a layer by index (used by the panel and by tests)"""
    bl_idname = "realworn.layer_select"
    bl_label = "Select Layer"

    index: IntProperty(name="Index", default=0, min=0)

    def execute(self, context):
        mat, _ = self._target(context)
        if mat is None:
            return {"CANCELLED"}
        mat.realworn.active_layer_index = min(self.index, len(mat.realworn.layers) - 1)
        return {"FINISHED"}


_classes = (RW_OT_setup, RW_OT_remove, RW_OT_layer_add, RW_OT_layer_remove, RW_OT_layer_move,
            RW_OT_layer_duplicate, RW_OT_layer_select)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

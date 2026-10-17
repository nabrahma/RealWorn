"""Setup / Remove and layer list editing. Every operator also takes explicit object, material and
layer ids, so tests and scripts drive them without mouse context."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ..core import injector, kinds, layers, setup
from ..props import KIND_ITEMS, UV_ITEMS
from .common import OBJECTS_DESC, report_all, resolve_layer, resolve_material, target_objects


class RW_OT_setup(bpy.types.Operator):
    """Wrap the material as the Base, add the RW_Paint UV map (Cube Projection and Pack Islands) and
    make the material unique to this object. Nothing about the look changes until you add a layer"""
    bl_idname = "realworn.setup"
    bl_label = "Setup"
    bl_options = {"REGISTER", "UNDO"}

    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")
    uv_method: EnumProperty(name="Paint UV", items=UV_ITEMS, default="CUBE")
    apply_scale: BoolProperty(name="Apply Scale", default=True,
                              description="Object coordinates follow the object's scale: apply it so box-mapped "
                                          "textures do not stretch")

    def invoke(self, context, event):
        self.uv_method = context.scene.realworn.uv_method
        if any(setup.needs_scale_apply(o) for o in target_objects(context, self.objects)):
            return context.window_manager.invoke_props_dialog(self, width=360)  # SET-5
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Scale is not applied: box-mapped textures would stretch.", icon="ERROR")
        col.prop(self, "apply_scale")
        col.prop(self, "uv_method")

    def execute(self, context):
        obs = target_objects(context, self.objects)
        if not obs:
            self.report({"WARNING"}, "Select a mesh object")
            return {"CANCELLED"}
        reps = []
        for o in obs:  # SET-7: each object gets its own paint images
            if self.apply_scale and setup.needs_scale_apply(o):
                if setup.apply_scale(o):
                    reps.append(("INFO", "{}: scale applied".format(o.name)))
                else:
                    reps.append(("WARNING", "{}: scale not applied (the mesh is shared)".format(o.name)))
            try:
                reps += setup.setup_object(o, self.uv_method)
            except setup.SetupError as ex:
                reps.append(("WARNING", str(ex)))
        report_all(self, [r for r in reps if r[0] != "INFO"])
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
                                  description="Write every painted image as PNG here before removing")

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
    """Add a layer of this kind at its usual place in the stack and select it"""
    bl_idname = "realworn.layer_add"
    bl_label = "Add Layer"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Kind", items=KIND_ITEMS, default="PAINT")
    preset: StringProperty(name="Preset", default="", description="Washed Out, Dark Patches, Dirt Patches, "
                                                                   "Second Material; Damage, Scratches; Graffiti, Grime; "
                                                                   "Damp, Wet, Puddles, Soaked")
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")

    @classmethod
    def description(cls, context, props):
        return "Add a {} layer".format(kinds.label(props.kind)) + (
            " ({})".format(props.preset.replace("_", " ").title()) if props.preset else "")

    def execute(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if ob is not None and not setup.is_setup(ob):
            report_all(self, setup.setup_object(ob, context.scene.realworn.uv_method))
            ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat):
            self.report({"WARNING"}, "No material set up for layers (click Setup)")
            return {"CANCELLED"}
        ly = layers.add_layer(mat, self.kind, self.preset or None)
        alpha = kinds.defaults(self.kind, self.preset or None).get("alpha")
        if alpha:  # REV-4: the Scratches preset switches the Damage brush to a scratch alpha
            from ..core import grunge
            grunge.set_damage_alpha(alpha)
        self.report({"INFO"}, "Added {} to {}".format(ly.name, mat.name))
        return {"FINISHED"}


class RW_MT_add_variation(bpy.types.Menu):
    """UI-1: Variation presets"""
    bl_idname = "RW_MT_add_variation"
    bl_label = "Add Variation"

    def draw(self, context):
        for key, name in kinds.preset_items("VARIATION"):
            op = self.layout.operator("realworn.layer_add", text=name)
            op.kind, op.preset = "VARIATION", key


class RW_MT_add_reveal(bpy.types.Menu):
    """UI-1: Reveal presets"""
    bl_idname = "RW_MT_add_reveal"
    bl_label = "Add Reveal"

    def draw(self, context):
        for key, name in kinds.preset_items("REVEAL"):
            op = self.layout.operator("realworn.layer_add", text=name)
            op.kind, op.preset = "REVEAL", key


class RW_MT_add_decals(bpy.types.Menu):
    bl_idname = "RW_MT_add_decals"
    bl_label = "Add Decals"

    def draw(self, context):
        for key, name in kinds.preset_items("DECALS"):
            op = self.layout.operator("realworn.layer_add", text=name)
            op.kind, op.preset = "DECALS", key


class RW_MT_add_puddle(bpy.types.Menu):
    """Puddle presets: how wet the ground is"""
    bl_idname = "RW_MT_add_puddle"
    bl_label = "Add Puddle"

    def draw(self, context):
        for key, name in kinds.preset_items("PUDDLE"):
            op = self.layout.operator("realworn.layer_add", text=name)
            op.kind, op.preset = "PUDDLE", key


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
    """Delete the selected layer (and its painted image)"""
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
    """Duplicate the selected layer, including a copy of its painted image"""
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
    """Select a layer (or the Base, index -1)"""
    bl_idname = "realworn.layer_select"
    bl_label = "Select Layer"

    index: IntProperty(name="Index", default=0, min=-1)

    def execute(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat):
            return {"CANCELLED"}
        st = mat.realworn
        if self.index < 0:
            st.base_active = True
            if st.mask_view:
                from ..core import compiler
                compiler.compile(mat)
            return {"FINISHED"}
        st.base_active = False
        st.active_layer_index = min(self.index, len(st.layers) - 1)
        return {"FINISHED"}


_classes = (RW_OT_setup, RW_OT_remove, RW_OT_layer_add, RW_MT_add_variation, RW_MT_add_reveal, RW_MT_add_decals,
            RW_MT_add_puddle,
            RW_OT_layer_remove, RW_OT_layer_move, RW_OT_layer_duplicate, RW_OT_layer_select)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

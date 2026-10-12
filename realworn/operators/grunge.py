"""Grunge and ingredient operators (GRN-1..GRN-7, mask ingredients)."""

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, StringProperty

from ..core import compiler, grunge, injector, layers
from ..props import GRUNGE_MODE_ITEMS, INGREDIENT_ITEMS
from .common import resolve_layer, resolve_material


class _Target:
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="")

    def _resolve(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if ob is None or mat is None or not injector.is_setup(mat) or not len(mat.realworn.layers):
            return None, None, None
        return ob, mat, mat.realworn.layers[resolve_layer(mat, self.layer)]


class RW_OT_grunge_select(_Target, bpy.types.Operator):
    """Use the chosen grunge: as a brush stamp, projected, as a stencil, or as this layer's fill"""
    bl_idname = "realworn.grunge_select"
    bl_label = "Use Grunge"
    bl_options = {"REGISTER", "UNDO"}

    grunge: StringProperty(name="Grunge", default="", description="Library file name; empty uses the panel")
    mode: EnumProperty(name="Mode", items=GRUNGE_MODE_ITEMS, default="STAMP")

    def invoke(self, context, event):
        self.mode = context.scene.realworn.grunge_mode
        return self.execute(context)

    def execute(self, context):
        sp = context.scene.realworn
        name = self.grunge or sp.grunge_image
        if not name or name == "NONE":
            self.report({"WARNING"}, "No grunge chosen")
            return {"CANCELLED"}
        ob, mat, layer = self._resolve(context)
        if self.mode == "FILL" and layer is None:
            self.report({"WARNING"}, "Fill needs a layer")
            return {"CANCELLED"}
        try:
            grunge.use(self.mode, name, ob, mat, layer, sp.grunge_contrast, sp.grunge_invert)
        except KeyError as ex:
            self.report({"WARNING"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, "{}: {}".format(self.mode.title(), name))
        return {"FINISHED"}


class RW_OT_ingredient_add(_Target, bpy.types.Operator):
    """Add a mask ingredient (starts at 0: the layer still shows only where painted)"""
    bl_idname = "realworn.ingredient_add"
    bl_label = "Add Ingredient"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Kind", items=INGREDIENT_ITEMS, default="GRUNGE")
    amount: FloatProperty(name="Amount", default=0.0, min=0.0, max=1.0)

    def execute(self, context):
        ob, mat, layer = self._resolve(context)
        if layer is None:
            return {"CANCELLED"}
        with compiler.batch(mat):
            ing = layer.ingredients.add()
            ing.kind = self.kind
            ing.amount = self.amount
            if self.kind == "GRUNGE":
                name = context.scene.realworn.grunge_image
                try:
                    ing.image = grunge.load(name if name and name != "NONE" else "grime_clouds")
                except KeyError:
                    pass
            elif self.kind == "REFERENCE":
                below = layers.layers_below(mat, layer)
                ing.ref_layer_id = below[-1].id if below else ""
            layer.active_ingredient = len(layer.ingredients) - 1
        compiler.compile(mat)
        return {"FINISHED"}


class RW_OT_ingredient_remove(_Target, bpy.types.Operator):
    """Remove this ingredient"""
    bl_idname = "realworn.ingredient_remove"
    bl_label = "Remove Ingredient"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index", default=0, min=0)

    def execute(self, context):
        ob, mat, layer = self._resolve(context)
        if layer is None or self.index >= len(layer.ingredients):
            return {"CANCELLED"}
        with compiler.batch(mat):
            layer.ingredients.remove(self.index)
        compiler.compile(mat)
        return {"FINISHED"}


_classes = (RW_OT_grunge_select, RW_OT_ingredient_add, RW_OT_ingredient_remove)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    grunge.free_previews()

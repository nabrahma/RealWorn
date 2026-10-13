"""Library pickers: the Breakup grunge of a layer, the damage alpha (RW Damage) and the decal (RW
Stencil). Picking from a library sets the brush's image instantly (PNT-5)."""

import bpy
from bpy.props import StringProperty

from ..core import compiler, grunge, injector
from .common import resolve_layer, resolve_material


class RW_OT_breakup_pick(bpy.types.Operator):
    """Use the grunge picked in the library as this layer's Breakup"""
    bl_idname = "realworn.breakup_pick"
    bl_label = "Use Grunge"
    bl_options = {"REGISTER", "UNDO"}

    grunge: StringProperty(name="Grunge", default="", description="Empty: the library choice")
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        self.layout.template_icon_view(context.scene.realworn, "grunge", show_labels=True, scale=6.0,
                                       scale_popup=5.0)

    def execute(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat) or not len(mat.realworn.layers):
            return {"CANCELLED"}
        layer = mat.realworn.layers[resolve_layer(mat, self.layer)]
        key = self.grunge or context.scene.realworn.grunge
        try:
            img = grunge.load("grunges", key)
        except KeyError:
            self.report({"WARNING"}, "Grunge '{}' not found".format(key))
            return {"CANCELLED"}
        with compiler.batch(mat):
            layer.breakup_grunge = img
            layer.breakup_scale = grunge.suggested_scale(img, layer.breakup_scale)
        compiler.compile(mat)
        return {"FINISHED"}


class _Popup:
    prop = ""

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=340)

    def draw(self, context):
        self.layout.template_icon_view(context.scene.realworn, self.prop, show_labels=True, scale=6.0,
                                       scale_popup=5.0)
        self.layout.prop(context.scene.realworn, self.prop, text="")

    def execute(self, context):
        return {"FINISHED"}


class RW_OT_damage_alpha_pick(_Popup, bpy.types.Operator):
    """REV-3: pick the damage alpha (chips, cracks, scratches, gouges); the Damage brush changes instantly"""
    bl_idname = "realworn.damage_alpha_pick"
    bl_label = "Damage Alpha"
    prop = "damage_alpha"


class RW_OT_decal_pick(_Popup, bpy.types.Operator):
    """DEC-3: pick a decal; the Stencil brush shows it (right-drag move, Ctrl right-drag rotate,
    Shift right-drag scale)"""
    bl_idname = "realworn.decal_pick"
    bl_label = "Decal"
    prop = "decal_image"


_classes = (RW_OT_breakup_pick, RW_OT_damage_alpha_pick, RW_OT_decal_pick)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

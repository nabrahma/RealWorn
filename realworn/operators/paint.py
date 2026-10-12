"""Paint operators (PNT-4..PNT-10): Paint, Exit, Paint / Erase / Reset, Fill, Clear, Resize."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ..core import images, injector, paint
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


class RW_OT_paint_enter(_Target, bpy.types.Operator):
    """Paint this layer's mask: white adds the layer, hold Ctrl to erase"""
    bl_idname = "realworn.paint_enter"
    bl_label = "Paint"
    bl_options = {"REGISTER", "UNDO"}

    target: EnumProperty(name="Target", items=[("MASK", "Mask", ""), ("CONTENT", "Colour", "")], default="MASK")
    mask_view: BoolProperty(name="Mask View", default=False)

    def execute(self, context):
        ob, mat, layer = self._resolve(context)
        if layer is None:
            self.report({"WARNING"}, "Set up the object and add a layer first")
            return {"CANCELLED"}
        if self.target == "CONTENT" and layer.type not in ("PAINT", "DECAL"):
            self.report({"WARNING"}, "Only Paint and Decal layers have a colour image")
            return {"CANCELLED"}
        context.view_layer.objects.active = ob
        img = paint.enter(ob, mat, layer, self.target, self.mask_view)
        what = img.name if img is not None else "vertex colours"
        self.report({"INFO"}, "Painting {} ({}). Ctrl erases".format(layer.name, what))
        return {"FINISHED"}


class RW_OT_paint_exit(bpy.types.Operator):
    """Leave painting: restores your brush, UV map and mode, and stores the painted image"""
    bl_idname = "realworn.paint_exit"
    bl_label = "Exit Painting"
    bl_options = {"REGISTER", "UNDO"}

    object: StringProperty(name="Object", default="")

    def execute(self, context):
        ob = bpy.data.objects.get(self.object) if self.object else context.active_object
        if not paint.exit(ob):
            return {"CANCELLED"}
        return {"FINISHED"}


class RW_OT_paint_mode(bpy.types.Operator):
    """Paint adds the layer, Erase removes it (and the procedural fill), Reset returns to the
    procedural result"""
    bl_idname = "realworn.paint_mode"
    bl_label = "Paint Mode"
    bl_options = {"REGISTER"}

    mode: EnumProperty(name="Mode", items=[("PAINT", "Paint", ""), ("ERASE", "Erase", ""),
                                           ("RESET", "Reset", "")], default="PAINT")
    object: StringProperty(name="Object", default="")

    def execute(self, context):
        ob = bpy.data.objects.get(self.object) if self.object else context.active_object
        paint.set_mode(ob, self.mode)
        return {"FINISHED"}


class RW_OT_mask_fill(_Target, bpy.types.Operator):
    """Fill: the layer shows everywhere (then erase where it should not). Clear: nothing painted"""
    bl_idname = "realworn.mask_fill"
    bl_label = "Fill"
    bl_options = {"REGISTER", "UNDO"}

    value: FloatProperty(name="Value", default=1.0, min=0.0, max=1.0)

    def execute(self, context):
        ob, mat, layer = self._resolve(context)
        if layer is None:
            return {"CANCELLED"}
        img = images.ensure_mask(ob, mat, layer)
        images.fill(img, self.value)
        return {"FINISHED"}


class RW_OT_mask_resize(_Target, bpy.types.Operator):
    """Change the mask resolution; existing paint is resampled, not lost"""
    bl_idname = "realworn.mask_resize"
    bl_label = "Resize Mask"
    bl_options = {"REGISTER", "UNDO"}

    resolution: IntProperty(name="Resolution", default=2048, min=64, max=8192)

    def execute(self, context):
        ob, mat, layer = self._resolve(context)
        if layer is None or layer.mask_image is None:
            return {"CANCELLED"}
        images.resize(layer.mask_image, self.resolution)
        layer.mask_res = self.resolution
        return {"FINISHED"}


_classes = (RW_OT_paint_enter, RW_OT_paint_exit, RW_OT_paint_mode, RW_OT_mask_fill, RW_OT_mask_resize)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

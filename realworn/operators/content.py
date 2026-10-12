"""Layer content operators: load a PBR Set (LAY-2)."""

import os

import bpy
from bpy.props import CollectionProperty, FloatProperty, StringProperty

from ..core import injector, pbrset
from .common import resolve_layer, resolve_material


class RW_OT_pbrset_load(bpy.types.Operator):
    """Use a folder (or a few files) of PBR maps as this layer's content; maps are detected by
    name: color/albedo/diffuse, rough, metal, normal, height/disp"""
    bl_idname = "realworn.pbrset_load"
    bl_label = "Load PBR Set"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    scale: FloatProperty(name="Scale (m)", default=1.0, min=0.01, soft_max=20.0)
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat) or not len(mat.realworn.layers):
            self.report({"WARNING"}, "Select a layer first")
            return {"CANCELLED"}
        layer = mat.realworn.layers[resolve_layer(mat, self.layer)]
        names = [f.name for f in self.files if f.name]
        src = [os.path.join(self.directory, n) for n in names] if names else self.directory
        done = pbrset.assign(mat, layer, src, self.scale)
        if not done:
            self.report({"WARNING"}, "No PBR maps recognised in {}".format(self.directory))
            return {"CANCELLED"}
        self.report({"INFO"}, "{}: {}".format(layer.name, ", ".join(done)))
        return {"FINISHED"}


_classes = (RW_OT_pbrset_load,)


class RW_OT_damage_apply(bpy.types.Operator):
    """Make Geometry-mode damage permanent: the Boolean result is applied to the mesh (for export)"""
    bl_idname = "realworn.damage_apply"
    bl_label = "Apply Damage"
    bl_options = {"REGISTER", "UNDO"}

    object: StringProperty(name="Object", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from ..core import damage
        ob = bpy.data.objects.get(self.object) if self.object else context.active_object
        if ob is None or not damage.apply_geometry(ob):
            self.report({"WARNING"}, "No Geometry-mode damage on this object")
            return {"CANCELLED"}
        self.report({"INFO"}, "Damage applied to {}".format(ob.name))
        return {"FINISHED"}


class RW_OT_damage_dirt(bpy.types.Operator):
    """Add a Dirt layer above this Damage layer that collects in the breaks"""
    bl_idname = "realworn.damage_dirt"
    bl_label = "Dirt in Damage"
    bl_options = {"REGISTER", "UNDO"}

    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="")

    def execute(self, context):
        from ..core import damage
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat) or not len(mat.realworn.layers):
            return {"CANCELLED"}
        ly = mat.realworn.layers[resolve_layer(mat, self.layer)]
        if ly.type != "DAMAGE":
            self.report({"WARNING"}, "Select a Damage layer")
            return {"CANCELLED"}
        damage.add_dirt_in_damage(mat, ly)
        return {"FINISHED"}


_classes = _classes + (RW_OT_damage_apply, RW_OT_damage_dirt)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

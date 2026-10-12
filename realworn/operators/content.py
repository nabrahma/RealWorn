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


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

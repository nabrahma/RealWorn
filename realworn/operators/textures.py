"""Load Texture (LT-1..LT-5): a folder (or files) into the Base or the selected layer, from a file
browser, the library popup or Recent."""

import os

import bpy
from bpy.props import CollectionProperty, FloatProperty, StringProperty

from ..core import injector, layers, pbrset
from .common import resolve_layer, resolve_material


class _TextureTarget:
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")
    layer: StringProperty(name="Layer ID", default="",
                          description="Layer id; 'BASE' loads into the Base; empty uses the selection")
    scale: FloatProperty(name="Scale", default=0.0, min=0.0, subtype="DISTANCE",
                         description="Metres per tile; 0: from the folder name, else 1 m (LT-2)")

    def _load(self, context, paths):
        ob, mat = resolve_material(context, self.object, self.material)
        if mat is None or not injector.is_setup(mat):
            self.report({"WARNING"}, "Click Setup first")
            return {"CANCELLED"}
        st = mat.realworn
        base = self.layer == "BASE" or (not self.layer and (st.base_active or not len(st.layers)))
        layer = None if base else st.layers[resolve_layer(mat, self.layer)]
        done = layers.load_texture(mat, paths, layer, self.scale or None)
        if not done:
            self.report({"WARNING"}, "No texture maps found in {}".format(paths if isinstance(paths, str) else
                                                                           os.path.dirname(paths[0])))
            return {"CANCELLED"}
        self.report({"INFO"}, "{}: {}".format("Base" if layer is None else layer.name, ", ".join(done)))
        return {"FINISHED"}


class RW_OT_load_texture(_TextureTarget, bpy.types.Operator):
    """Load a texture set (a Poly Haven or ambientCG folder): maps found by name, box mapped, displacement
    as bump. Loading over a texture keeps every other setting and the paint"""
    bl_idname = "realworn.load_texture"
    bl_label = "Load Texture"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            return {"CANCELLED"}
        names = [f.name for f in self.files if f.name]
        paths = [os.path.join(self.directory, n) for n in names] if names else self.directory
        return self._load(context, paths)


class RW_OT_use_texture(_TextureTarget, bpy.types.Operator):
    """Use the texture set picked in the library (same as Load Texture)"""
    bl_idname = "realworn.use_texture"
    bl_label = "Use Texture"
    bl_options = {"REGISTER", "UNDO"}

    path: StringProperty(name="Folder", default="", description="Empty: the library choice")

    def execute(self, context):
        path = self.path or context.scene.realworn.texture
        if not path or path == "NONE" or not os.path.isdir(bpy.path.abspath(path)):
            self.report({"WARNING"}, "Pick a texture set (set a Texture Library folder in Preferences)")
            return {"CANCELLED"}
        return self._load(context, path)


class RW_OT_texture_library(bpy.types.Operator):
    """LT-4: your texture library as thumbnails, Recent first"""
    bl_idname = "realworn.texture_library"
    bl_label = "Texture Library"
    bl_options = {"REGISTER", "UNDO"}

    layer: StringProperty(name="Layer ID", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column()
        col.template_icon_view(context.scene.realworn, "texture", show_labels=True, scale=8.0, scale_popup=6.0)
        col.prop(context.scene.realworn, "texture", text="")

    def execute(self, context):
        return bpy.ops.realworn.use_texture(layer=self.layer)


_classes = (RW_OT_load_texture, RW_OT_use_texture, RW_OT_texture_library)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

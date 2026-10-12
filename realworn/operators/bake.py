"""Bake family (BAK-1..BAK-4) and the v0.7 Remove path."""

import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ..core import bake, injector, migrate
from ..props import EXPORT_ITEMS
from .common import report_all, resolve_layer, resolve_material

DAMAGE_ITEMS = [("ERROR", "Refuse", "Stop if Geometry-mode damage is present"),
                ("EXCLUDE", "Exclude", "Bake without the cut geometry"),
                ("APPLY", "Apply", "Apply the damage to the mesh first")]


class _Mat:
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")

    def _resolve(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if ob is None or mat is None or not injector.is_setup(mat):
            return None, None
        return ob, mat


class RW_OT_flatten(_Mat, bpy.types.Operator):
    """Merge a run of layers into one Paint layer with baked colour, roughness, metallic and height"""
    bl_idname = "realworn.flatten"
    bl_label = "Flatten Layers"
    bl_options = {"REGISTER", "UNDO"}

    first: IntProperty(name="From", default=-1, description="-1: the layer below the selected one")
    last: IntProperty(name="To", default=-1, description="-1: the selected layer")

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None or len(mat.realworn.layers) < 1:
            return {"CANCELLED"}
        last = self.last if self.last >= 0 else resolve_layer(mat)
        first = self.first if self.first >= 0 else max(0, last - 1)
        try:
            ly = bake.flatten(ob, mat, first, last, context.scene)
        except (bake.BakeError, RuntimeError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, "Flattened into {}".format(ly.name))
        return {"FINISHED"}


class RW_OT_bake(_Mat, bpy.types.Operator):
    """Bake the whole layer stack to PBR textures on RW_Paint and use them (Restore Live Stack goes back)"""
    bl_idname = "realworn.bake"
    bl_label = "Bake Material"
    bl_options = {"REGISTER", "UNDO"}

    resolution: IntProperty(name="Resolution", default=0, description="0: the panel setting")
    geometry_damage: EnumProperty(name="Geometry Damage", items=DAMAGE_ITEMS, default="EXCLUDE")

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None:
            return {"CANCELLED"}
        p = context.scene.realworn
        res = self.resolution or int(p.bake_resolution)
        try:
            imgs = bake.bake_material(ob, mat, context.scene, res, p.bake_folder, geometry_damage=self.geometry_damage)
        except (bake.BakeError, RuntimeError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, "Baked {} maps for {}".format(len(imgs), mat.name))
        return {"FINISHED"}


class RW_OT_restore_live(_Mat, bpy.types.Operator):
    """Go back to the editable, live layer stack after a bake"""
    bl_idname = "realworn.restore_live"
    bl_label = "Restore Live Stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None or not mat.realworn.baked:
            return {"CANCELLED"}
        bake.restore_live(mat)
        return {"FINISHED"}


class RW_OT_export_textures(_Mat, bpy.types.Operator):
    """Write the baked textures with engine conventions (Unity URP / HDRP, Unreal ORM, glTF)"""
    bl_idname = "realworn.export_textures"
    bl_label = "Export Textures"

    preset: EnumProperty(name="Engine", items=EXPORT_ITEMS, default="UNREAL")
    folder: StringProperty(name="Folder", subtype="DIR_PATH", default="")

    def invoke(self, context, event):
        self.preset = context.scene.realworn.export_preset
        return self.execute(context)

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None:
            return {"CANCELLED"}
        folder = self.folder or os.path.join(bake.output_folder(context.scene.realworn.bake_folder), "export")
        folder = bpy.path.abspath(folder)
        try:
            paths = bake.export_textures(mat, folder, self.preset)
        except bake.BakeError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"}, "Exported {} files to {}".format(len(paths), folder))
        return {"FINISHED"}


class RW_OT_migrate_v07(bpy.types.Operator):
    """This file was weathered with RealWorn v0.7: restore its materials exactly and remove v0.7 data, so
    the objects can be set up for painting"""
    bl_idname = "realworn.migrate_v07"
    bl_label = "Remove v0.7 Weathering"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        report_all(self, migrate.remove_v07())
        return {"FINISHED"}


_classes = (RW_OT_flatten, RW_OT_bake, RW_OT_restore_live, RW_OT_export_textures, RW_OT_migrate_v07)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

"""Bake family (UI-5): Bake Material, Restore Live Stack, Export Textures, and the v0.7 Remove path."""

import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ..core import bake, injector, migrate
from ..props import EXPORT_ITEMS
from .common import report_all, resolve_material


class _Mat:
    object: StringProperty(name="Object", default="")
    material: StringProperty(name="Material", default="")

    def _resolve(self, context):
        ob, mat = resolve_material(context, self.object, self.material)
        if ob is None or mat is None or not injector.is_setup(mat):
            return None, None
        return ob, mat


class RW_OT_bake(_Mat, bpy.types.Operator):
    """Bake the whole layer stack to PBR textures on RW_Paint and use them (Restore Live Stack goes back)"""
    bl_idname = "realworn.bake"
    bl_label = "Bake Material"
    bl_options = {"REGISTER", "UNDO"}

    resolution: IntProperty(name="Resolution", default=0, description="0: the panel setting")

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None:
            return {"CANCELLED"}
        p = context.scene.realworn
        res = self.resolution or int(p.bake_resolution)
        try:
            imgs = bake.bake_material(ob, mat, context.scene, res, p.bake_folder)
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


class RW_OT_bake_sources(_Mat, bpy.types.Operator):
    """Bake the Edge Wear and Dirt masks (Bevel and AO) to images on RW_Paint and switch those layers
    to Baked: they then look the same in EEVEE and render faster. Re-bake after changing the mesh"""
    bl_idname = "realworn.bake_sources"
    bl_label = "Bake Edges and AO"
    bl_options = {"REGISTER", "UNDO"}

    layer: StringProperty(name="Layer ID", default="", description="Empty: every Edge Wear and Dirt layer")
    resolution: IntProperty(name="Resolution", default=0, description="0: the mask texel density")

    def execute(self, context):
        ob, mat = self._resolve(context)
        if mat is None:
            return {"CANCELLED"}
        ids = [self.layer] if self.layer else None
        try:
            done = bake.bake_sources(ob, mat, context.scene, ids, self.resolution or None)
        except (bake.BakeError, RuntimeError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        if not done:
            self.report({"WARNING"}, "No Edge Wear or Dirt layer to bake")
            return {"CANCELLED"}
        self.report({"INFO"}, "Baked {} mask(s)".format(len(done)))
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


class RW_OT_convert_v2(bpy.types.Operator):
    """This material was painted with RealWorn v2: convert it to v3. Paint, Dirt, Rust, Dust and Custom
    become Paint layers, Wear, Scratches and Damage become Reveal layers, each keeping its painted mask;
    Water and projector decals are reported (Remove and redo them)"""
    bl_idname = "realworn.convert_v2"
    bl_label = "Convert to v3"
    bl_options = {"REGISTER", "UNDO"}

    material: StringProperty(name="Material", default="", description="Empty: every v2.x material")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if self.material:
            mat = bpy.data.materials.get(self.material)
            rep = migrate.convert_v2(mat) if mat is not None else [("WARNING", "no material " + self.material)]
        else:
            rep = migrate.convert_all_v2()
        report_all(self, [r for r in rep if r[0] != "INFO"] or rep[-1:])
        return {"FINISHED"}


_classes = (RW_OT_bake, RW_OT_restore_live, RW_OT_export_textures, RW_OT_bake_sources, RW_OT_migrate_v07,
            RW_OT_convert_v2)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

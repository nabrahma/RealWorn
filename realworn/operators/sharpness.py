"""Sharpness tools (PRD v2.1): one-click fixes for the diagnostics DIA-1..DIA-3."""

import bpy


def _prefs_changed(context):
    context.preferences.is_dirty = True  # auto-save preferences keeps the fix


class RW_OT_fix_texture_limit(bpy.types.Operator):
    """Turn off Preferences > Viewport > Limit Size, which caps texture resolution in the viewport
    and in EEVEE renders"""
    bl_idname = "realworn.fix_texture_limit"
    bl_label = "Remove Texture Limit"

    def execute(self, context):
        context.preferences.system.gl_texture_limit = "CLAMP_OFF"
        _prefs_changed(context)
        self.report({"INFO"}, "Texture Limit Size: Off")
        return {"FINISHED"}


class RW_OT_fix_simplify_textures(bpy.types.Operator):
    """Stop Simplify from limiting or scaling Cycles textures (viewport and render)"""
    bl_idname = "realworn.fix_simplify_textures"
    bl_label = "Full-Resolution Textures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cy = context.scene.cycles
        cy.texture_limit = cy.texture_limit_render = "OFF"
        cy.texture_resolution = cy.texture_resolution_render = 1.0
        return {"FINISHED"}


class RW_OT_fix_anisotropic(bpy.types.Operator):
    """Set anisotropic filtering to 16x so textures on oblique surfaces stay sharp"""
    bl_idname = "realworn.fix_anisotropic"
    bl_label = "Anisotropic 16x"

    def execute(self, context):
        context.preferences.system.anisotropic_filter = "FILTER_16"
        _prefs_changed(context)
        return {"FINISHED"}


_classes = (RW_OT_fix_texture_limit, RW_OT_fix_simplify_textures, RW_OT_fix_anisotropic)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

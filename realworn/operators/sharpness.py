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


class RW_OT_apply_v21_defaults(bpy.types.Operator):
    """Give every layer of this material the v2.1 Edge Detail defaults for its type (and capture the
    base height). v2.0 files look exactly as before until this is clicked"""
    bl_idname = "realworn.apply_v21_defaults"
    bl_label = "Apply v2.1 Defaults"
    bl_options = {"REGISTER", "UNDO"}

    material: bpy.props.StringProperty(default="")

    def execute(self, context):
        from ..core import detail
        from .common import resolve_material
        _, mat = resolve_material(context, material_name=self.material)
        if mat is None or not mat.realworn.applied:
            self.report({"WARNING"}, "Select a set-up object")
            return {"CANCELLED"}
        n = detail.apply_v21_defaults(mat)
        self.report({"INFO"}, "{}: v2.1 defaults on {} layer(s), base height {}".format(
            mat.name, n, mat.realworn.base_height_kind.lower()))
        return {"FINISHED"}


class RW_OT_refresh_base(bpy.types.Operator):
    """Recapture the base material's height and AO maps and their normalisation (after swapping its
    textures). Layers and paint are not touched"""
    bl_idname = "realworn.refresh_base"
    bl_label = "Refresh Base"
    bl_options = {"REGISTER", "UNDO"}

    material: bpy.props.StringProperty(default="")

    def execute(self, context):
        from ..core import detail
        from .common import resolve_material
        _, mat = resolve_material(context, material_name=self.material)
        if mat is None or not mat.realworn.applied:
            self.report({"WARNING"}, "Select a set-up object")
            return {"CANCELLED"}
        h, ao = detail.refresh_base(mat)
        self.report({"INFO"}, "{}: base height {}, AO {}".format(mat.name, h.lower(), ao.lower()))
        return {"FINISHED"}


class RW_OT_pick_ao(bpy.types.Operator):
    """Pick the base material's ambient occlusion map (Base AO is available once one is set)"""
    bl_idname = "realworn.pick_ao"
    bl_label = "Pick AO Image"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    material: bpy.props.StringProperty(default="")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import os
        from ..core import compiler, detail
        from .common import resolve_material
        _, mat = resolve_material(context, material_name=self.material)
        if mat is None or not mat.realworn.applied or not os.path.isfile(self.filepath):
            self.report({"WARNING"}, "Pick an image file for a set-up material")
            return {"CANCELLED"}
        img = bpy.data.images.load(self.filepath, check_existing=True)
        detail.link_ao(mat, img)
        detail.capture_ao(mat)
        compiler.compile(mat)
        self.report({"INFO"}, "Base AO: {}".format(img.name))
        return {"FINISHED"}


class RW_OT_upgrade_masks(bpy.types.Operator):
    """Resample this object's masks to the current texel density (bicubic, paint kept) and give
    relief-driving layers 16-bit masks. Undoable"""
    bl_idname = "realworn.upgrade_masks"
    bl_label = "Upgrade Masks"
    bl_options = {"REGISTER", "UNDO"}

    object: bpy.props.StringProperty(default="")

    def execute(self, context):
        import time
        from ..core import images, setup
        ob = bpy.data.objects.get(self.object) if self.object else context.active_object
        if ob is None or not setup.is_setup(ob):
            self.report({"WARNING"}, "Select a set-up object")
            return {"CANCELLED"}
        t = time.perf_counter()
        n = 0
        for mat in setup.layered_materials(ob):
            for ly in mat.realworn.layers:
                before = ly.mask_image
                if before is None:
                    continue
                size, was_float = tuple(before.size), before.is_float
                new = images.upgrade(ob, ly)
                if tuple(new.size) != size or new.is_float != was_float:
                    n += 1
        self.report({"INFO"}, "Upgraded {} mask(s) to {} px in {:.2f} s".format(
            n, images.texel_resolution(ob), time.perf_counter() - t))
        return {"FINISHED"}


class RW_OT_hero_toggle(bpy.types.Operator):
    """Hero object: masks at 4096 px per metre for extreme close-ups. Shows the memory the masks
    will take before you confirm"""
    bl_idname = "realworn.hero_toggle"
    bl_label = "Hero Masks"
    bl_options = {"REGISTER", "UNDO"}

    object: bpy.props.StringProperty(default="")
    upgrade: bpy.props.BoolProperty(name="Upgrade existing masks now", default=True)

    def _obj(self, context):
        return bpy.data.objects.get(self.object) if self.object else context.active_object

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        from ..core import images, setup
        ob = self._obj(context)
        if ob is None:
            return
        lys = [ly for m in setup.layered_materials(ob) for ly in m.realworn.layers]
        target = not ob.realworn.hero
        b, res = images.memory_estimate(ob, lys, hero=target)
        col = self.layout.column()
        col.label(text="Hero {}: masks at {} px".format("on" if target else "off", res))
        col.label(text="{} layer(s): about {:.0f} MB of RAM".format(len(lys), b / 1024 / 1024))
        col.prop(self, "upgrade")

    def execute(self, context):
        ob = self._obj(context)
        if ob is None:
            return {"CANCELLED"}
        ob.realworn.hero = not ob.realworn.hero
        if self.upgrade:
            bpy.ops.realworn.upgrade_masks(object=ob.name)
        return {"FINISHED"}


_classes = (RW_OT_upgrade_masks, RW_OT_hero_toggle, RW_OT_fix_texture_limit, RW_OT_fix_simplify_textures, RW_OT_fix_anisotropic, RW_OT_apply_v21_defaults,
            RW_OT_refresh_base, RW_OT_pick_ao)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

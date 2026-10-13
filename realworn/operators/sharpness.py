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


class RW_OT_sharpness_report(bpy.types.Operator):
    """Render a 512 px close-up of each painted layer's Mask View, measure its edge width and say
    what limits it (DIA-5). Render settings and the camera are restored afterwards"""
    bl_idname = "realworn.sharpness_report"
    bl_label = "Sharpness Report"

    object: bpy.props.StringProperty(default="")
    resolution: bpy.props.IntProperty(default=512, min=64, max=4096)

    def execute(self, context):
        import json
        import math
        import os
        import tempfile
        import numpy as np
        from mathutils import Vector
        from ..core import diagnostics, injector, metrics, setup
        ob = bpy.data.objects.get(self.object) if self.object else context.active_object
        if ob is None or not setup.is_setup(ob):
            self.report({"WARNING"}, "Select a set-up object")
            return {"CANCELLED"}
        sc = context.scene
        r, vs = sc.render, sc.view_settings
        saved = (sc.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
                 r.image_settings.file_format, r.image_settings.color_depth, vs.view_transform, vs.look,
                 sc.eevee.taa_render_samples)
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        centre = sum(corners, Vector()) / 8
        size = max(ob.dimensions)
        cam = bpy.data.objects.new("RW_SharpnessCam", bpy.data.cameras.new("RW_SharpnessCam"))
        sc.collection.objects.link(cam)
        cam.data.lens = 50
        front = min(c.y for c in corners)
        cam.location = (centre.x, front - size * 1.2, centre.z)  # a close-up of the front
        cam.rotation_euler = (math.pi / 2, 0, 0)
        rows, layer_widths = [], []
        folder = tempfile.mkdtemp(prefix="rw_sharp_")
        try:
            sc.camera = cam
            r.engine = "BLENDER_EEVEE"
            r.resolution_x = r.resolution_y = self.resolution
            r.resolution_percentage = 100
            r.image_settings.file_format, r.image_settings.color_depth = "OPEN_EXR", "32"
            vs.view_transform, vs.look = "Standard", "None"
            sc.eevee.taa_render_samples = 8
            for mat in setup.layered_materials(ob):
                st = mat.realworn
                keep = (st.active_layer_index, st.mask_view)
                for i, ly in enumerate(st.layers):
                    if not ly.visible or (ly.mask_image is None and not ly.ingredients):
                        continue
                    st.active_layer_index, st.mask_view = i, True
                    injector.set_mask_view(mat, True)
                    r.filepath = os.path.join(folder, "{}_{}.exr".format(mat.name, i))
                    bpy.ops.render.render(write_still=True)
                    img = bpy.data.images.load(r.filepath, check_existing=False)
                    px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
                    img.pixels.foreach_get(px)
                    bpy.data.images.remove(img)
                    w = metrics.edge_width(px.reshape(self.resolution, self.resolution, 4)[..., 0])
                    layer_widths.append((ly, w))
                st.active_layer_index, st.mask_view = keep
                injector.set_mask_view(mat, st.mask_view)
            rows = diagnostics.report_rows(ob, layer_widths)
        finally:
            (sc.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
             r.image_settings.file_format, r.image_settings.color_depth, vs.view_transform, vs.look,
             sc.eevee.taa_render_samples) = saved
            bpy.data.objects.remove(cam)
        sc["rw_sharpness_report"] = json.dumps({"object": ob.name, "px": self.resolution, "rows": rows})
        for name, w, lim in rows:
            self.report({"INFO"}, "{}: {}, limited by {}".format(name, "{:.1f} px".format(w) if w else "no edge", lim))
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


_classes = (RW_OT_sharpness_report, RW_OT_upgrade_masks, RW_OT_hero_toggle, RW_OT_fix_texture_limit, RW_OT_fix_simplify_textures, RW_OT_fix_anisotropic, RW_OT_apply_v21_defaults,
            RW_OT_refresh_base, RW_OT_pick_ao)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

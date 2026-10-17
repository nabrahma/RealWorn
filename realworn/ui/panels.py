"""The RealWorn sidebar tab: one short panel.

  Setup / Remove
  + Add: Variation | Paint | Reveal | Decals | Edge Wear | Dirt | Puddle
  the layer rows (top of the list is the top layer; the Base pinned at the bottom)
  the selected layer: Content, its kind's control, Breakup, Sharpness, Brush, then > Advanced
  Bake Material, Export Textures, Bake Edges and AO

If a control is not here, it lives under the layer's Advanced fold or does not exist (UI-3). The
same panel shows in the Image Editor.
"""

import bpy

from ..core import images, injector, kinds as K, setup


def op(layout, idname, **kw):
    """layout.operator that tolerates an operator not being registered."""
    if not hasattr(bpy.types, "REALWORN_OT_" + idname.split(".", 1)[1]):
        r = layout.row()
        r.enabled = False
        r.label(text=kw.get("text") or idname.split(".", 1)[1].replace("_", " ").title(), icon=kw.get("icon", "NONE"))
        return _Null()
    return layout.operator(idname, **kw)


class _Null:
    def __setattr__(self, k, v):
        pass


def _context_material(context):
    ob = context.active_object
    if ob is None or ob.type != "MESH":
        return ob, None
    return ob, ob.active_material


def eevee_without_raytracing(context):
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None or not scene.render.engine.startswith("BLENDER_EEVEE"):
        return False
    return not getattr(scene.eevee, "use_raytracing", True)


def status(ob, layer, context=None):
    """UI-2: a short status note for a layer row, or ''."""
    if layer.kind == "PUDDLE":
        if layer.puddle_source == "PAINT" and layer.mask_image is None:
            return "not painted"
        if eevee_without_raytracing(context):
            return "EEVEE: enable ray tracing"
        return ""
    if layer.kind in ("EDGE_WEAR", "DIRT") and layer.edge_source == "LIVE":
        shading = getattr(getattr(context, "space_data", None), "shading", None) if context else None
        if shading is not None and shading.type == "MATERIAL":
            return "Live - Bake for EEVEE"  # ENG-3
        return "Live"
    if layer.kind in ("EDGE_WEAR", "DIRT"):
        return "Baked"
    if layer.content == "TEXTURE" and layer.kind != "DECALS" and not layer.texture.loaded():
        return "no texture loaded"
    if K.paintable(layer.kind) and layer.mask_image is None and not K.paint_optional(layer.kind):
        return "not painted"
    return ""


class RW_UL_layers(bpy.types.UIList):
    bl_idname = "RW_UL_layers"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        row.label(text="", icon=K.INFO[item.kind]["icon"])
        if not item.name.startswith(K.label(item.kind)):  # "Reveal: Damage"
            row.label(text=K.label(item.kind) + ":")
        row.prop(item, "name", text="", emboss=False)  # UI-2: double-click to rename
        note = status(context.active_object, item, context)
        if note:
            sub = row.row()
            sub.alert = note.startswith(("Live -", "EEVEE"))
            sub.label(text=note)
        sub = row.row(align=True)
        sub.scale_x = 0.8
        sub.prop(item, "opacity", text="", slider=True)
        if K.paintable(item.kind):
            o = op(row, "realworn.paint_enter", text="", icon="BRUSH_DATA", emboss=False)
            o.layer = item.id

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        n = len(items)
        order = list(range(n - 1, -1, -1))  # top layer first
        neworder = [0] * n
        for pos, idx in enumerate(order):
            neworder[idx] = pos
        return [self.bitflag_filter_item] * n, neworder


class _Base:
    bl_region_type = "UI"
    bl_category = "RealWorn"


def _banners(layout, mat):
    st = mat.realworn
    if st.applied and st.stack is None:
        box = layout.box()
        box.label(text="Weathered with RealWorn v0.7", icon="ERROR")
        op(box, "realworn.migrate_v07", icon="LOOP_BACK")
        return True
    if st.applied and st.schema_version == 2:
        box = layout.box()
        box.label(text="Painted with RealWorn v2", icon="ERROR")
        o = op(box, "realworn.convert_v2", icon="FILE_REFRESH")
        o.material = mat.name
        op(box, "realworn.remove", icon="X")
        return True
    return False


def _add_row(layout):
    col = layout.column(align=True)
    col.label(text="Add")
    row = col.row(align=True)
    row.menu("RW_MT_add_variation", text="Variation", icon=K.INFO["VARIATION"]["icon"])
    o = op(row, "realworn.layer_add", text="Paint", icon=K.INFO["PAINT"]["icon"])
    o.kind = "PAINT"
    row.menu("RW_MT_add_reveal", text="Reveal", icon=K.INFO["REVEAL"]["icon"])
    row = col.row(align=True)
    row.menu("RW_MT_add_decals", text="Decals", icon=K.INFO["DECALS"]["icon"])
    o = op(row, "realworn.layer_add", text="Edge Wear", icon=K.INFO["EDGE_WEAR"]["icon"])
    o.kind = "EDGE_WEAR"
    o = op(row, "realworn.layer_add", text="Dirt", icon=K.INFO["DIRT"]["icon"])
    o.kind = "DIRT"
    row.menu("RW_MT_add_puddle", text="Puddle", icon=K.INFO["PUDDLE"]["icon"])


def _hsv(layout, owner, prefix=""):
    row = layout.row(align=True)
    row.prop(owner, prefix + "hue", text="Hue", slider=True)
    row.prop(owner, prefix + "saturation", text="Sat", slider=True)
    row.prop(owner, prefix + "value", text="Val", slider=True)


def _texture_row(layout, ts, layer_id):
    row = layout.row(align=True)
    o = op(row, "realworn.load_texture", text="Load Texture", icon="FILEBROWSER")
    o.layer = layer_id
    o = op(row, "realworn.texture_library", text="", icon="ASSET_MANAGER")
    o.layer = layer_id
    row.label(text=ts.name or "none")
    if ts.loaded():
        layout.prop(ts, "scale")


def draw_base(layout, mat):
    st = mat.realworn
    box = layout.box()
    box.label(text="Base: " + (st.base.name or mat.name), icon="MATERIAL")
    _texture_row(box, st.base, "BASE")
    if st.base.loaded():
        _hsv(box, st, "base_")
        row = box.row(align=True)
        row.prop(st.base, "roughness_offset")
        row.prop(st.base, "bump")
    else:
        box.label(text="Your material, untouched. Load a texture to replace its look.", icon="INFO")


def _mask_rows(layout, layer):
    row = layout.row(align=True)
    o = op(row, "realworn.upgrade_mask", text="Upgrade Mask")
    o.layer = layer.id
    o = op(row, "realworn.mask_fill", text="Fill")
    o.layer, o.value = layer.id, 1.0
    o = op(row, "realworn.mask_fill", text="Clear")
    o.layer, o.value = layer.id, 0.0


def draw_puddle(layout, context, ob, mat, layer):
    """Puddle: Preset, Source, Water Level, Depth Look, Halo, Water Tint, Wet Film (Relief Through
    Film, Film Breakup and Scale), True Depth, Brush; the rest under Advanced."""
    box = layout.box()
    box.label(text="Selected: {}".format(layer.name), icon=K.INFO["PUDDLE"]["icon"])
    col = box.column(align=True)
    col.prop(layer, "puddle_preset")
    col.prop(layer, "puddle_source")
    col = box.column(align=True)
    row = col.row(align=True)
    row.prop(layer, "water_level_mm", text="Water Level (mm)", slider=True)
    row.prop(layer, "depth_look_mm", text="Depth Look (mm)")
    row = col.row(align=True)
    row.prop(layer, "halo", slider=True)
    row.prop(layer, "water_tint", text="")
    if layer.water_tint == "CUSTOM":
        col.prop(layer, "tint_color")
    col = box.column(align=True)
    col.prop(layer, "wet_film", slider=True)
    if layer.wet_film > 0:
        col.prop(layer, "film_relief", slider=True)
        row = col.row(align=True)
        row.label(text="Film Breakup")
        o = op(row, "realworn.breakup_pick", text=layer.film_grunge.name if layer.film_grunge else "Noise",
               icon="TEXTURE")
        o.layer, o.target = layer.id, "FILM"
        if layer.film_grunge is not None:
            o = op(row, "realworn.breakup_pick", text="", icon="X")
            o.layer, o.target, o.grunge = layer.id, "FILM", "NOISE"
        row.prop(layer, "film_scale_m", text="Scale")
    row = box.row(align=True)
    row.prop(layer, "true_depth")
    if layer.true_depth:
        from ..core import reveal
        warn = reveal.density_warning(ob)
        if warn:
            box.label(text=warn, icon="ERROR")
    if layer.puddle_source != "AUTO":
        row = box.row(align=True)
        brush = context.scene.get("rw_puddle_outline", "NONE")
        op(row, "realworn.puddle_outline_pick", text="Outline: " + ("Round" if brush in ("", "NONE") else
                                                                     brush.rsplit(".", 1)[0]), icon="BRUSH_DATA")
        o = op(row, "realworn.paint_enter", text="Paint", icon="BRUSH_DATA")
        o.layer = layer.id
    row = box.row(align=True)
    row.prop(mat.realworn, "mask_view", text="Mask View", toggle=True)
    if eevee_without_raytracing(context):
        box.label(text="EEVEE: turn on Ray Tracing (Render Properties) for sharp reflections", icon="ERROR")
    box.label(text=K.TIPS["PUDDLE"], icon="INFO")
    adv = box.column(align=True)
    adv.prop(layer, "show_advanced", icon="TRIA_DOWN" if layer.show_advanced else "TRIA_RIGHT", emboss=False)
    if layer.show_advanced:
        adv.prop(layer, "height_source")
        adv.prop(layer, "surface")
        adv.prop(layer, "height_scale_mm", text="Height Scale (mm)")
        adv.prop(layer, "paint_depth_mm", text="Paint Depth (mm)")
        row = adv.row(align=True)
        row.prop(layer, "broad_dips")
        if not mat.realworn.base.loaded() or mat.realworn.base.height is None:
            row.label(text="on: the Base has no height map", icon="INFO")
        row = adv.row(align=True)
        row.prop(layer, "dip_depth_mm", text="Dip Depth (mm)")
        row.prop(layer, "dip_scale_m")
        row = adv.row(align=True)
        row.prop(layer, "edge_width_mm", text="Wet Edge (mm)")
        row.prop(layer, "halo_width_mm", text="Halo (mm)")
        row.prop(layer, "deep_threshold_mm", text="Deep (mm)")
        adv.prop(layer, "darkening", slider=True)
        row = adv.row(align=True)
        row.prop(layer, "wind_ripple", slider=True)
        row.prop(layer, "tide_mark", slider=True)
        row.prop(layer, "debris_settle", slider=True)
        adv.prop(layer, "flat_threshold", slider=True)
        row = adv.row(align=True)
        row.prop(layer, "dry_patches", slider=True)
        row.prop(layer, "film_gloss", slider=True)
        if layer.puddle_source != "AUTO":
            adv.prop(layer, "mask_res")
            _mask_rows(adv, layer)


def draw_layer(layout, context, ob, mat, layer):
    """UI-3: Content, kind-specific, Breakup, Sharpness, Brush; Advanced folded."""
    if layer.kind == "PUDDLE":
        draw_puddle(layout, context, ob, mat, layer)
        return
    box = layout.box()
    box.label(text="Selected: {}".format(layer.name), icon=K.INFO[layer.kind]["icon"])
    # Content
    col = box.column(align=True)
    if layer.kind == "DECALS":
        col.label(text="Content: the painted decal image")
        _hsv(col, layer)
        col.prop(layer, "roughness")
    else:
        col.row().prop(layer, "content", expand=True)
        if layer.content == "TEXTURE":
            _texture_row(col, layer.texture, layer.id)
        elif layer.content == "COLOR":
            row = col.row(align=True)
            row.prop(layer, "color", text="")
            row.prop(layer, "roughness")
        _hsv(col, layer)
    # kind-specific
    col = box.column(align=True)
    if layer.kind == "REVEAL":
        row = col.row(align=True)
        row.prop(layer, "depth_mm", text="Depth (mm)")
        row.prop(layer, "true_depth")
        if layer.true_depth:
            from ..core import reveal
            warn = reveal.density_warning(ob)
            if warn:
                col.label(text=warn, icon="ERROR")
    elif layer.kind == "EDGE_WEAR":
        col.prop(layer, "width_mm", text="Width (mm)")
    elif layer.kind == "DIRT":
        row = col.row(align=True)
        row.prop(layer, "distance_cm", text="Distance (cm)")
        row.prop(layer, "only_local")
    elif layer.kind == "DECALS":
        col.prop(layer, "decal_res")
        dens = images.decal_density(ob, layer)
        col.label(text="{:.0f} px per metre".format(dens),
                  icon="ERROR" if dens < images.DECAL_MIN_DENSITY else "INFO")
        if dens < images.DECAL_MIN_DENSITY:
            col.label(text="Low for a large building: use 8K or split it into parts")
    if layer.kind in ("EDGE_WEAR", "DIRT"):
        col.row().prop(layer, "edge_source", expand=True)
        o = op(col, "realworn.bake_sources", text="Bake Edges and AO", icon="RENDER_STILL")
        o.layer = layer.id
        if layer.edge_source == "BAKED" and layer.baked_image is None:
            col.label(text="Not baked yet: showing the live mask", icon="INFO")
    # Breakup
    col = box.column(align=True)
    row = col.row(align=True)
    row.label(text="Breakup")
    o = op(row, "realworn.breakup_pick", text=(layer.breakup_grunge.name if layer.breakup_grunge else "pick"),
           icon="TEXTURE")
    o.layer = layer.id
    row.prop(layer, "breakup_amount", text="Amount", slider=True)
    # Sharpness
    row = box.row(align=True)
    row.prop(layer, "sharpness", slider=True)
    row.prop(layer, "threshold", slider=True)
    # Brush
    if K.paintable(layer.kind):
        row = box.row(align=True)
        brush = K.INFO[layer.kind]["paint"]
        if brush == "RW Damage":
            op(row, "realworn.damage_alpha_pick", text="Damage Alpha", icon="BRUSH_DATA")
        elif brush == "RW Stencil":
            op(row, "realworn.decal_pick", text="Decal", icon="IMAGE_DATA")
        o = op(row, "realworn.paint_enter", text="Paint", icon="BRUSH_DATA")
        o.layer = layer.id
        row.prop(mat.realworn, "mask_view", text="Mask View", toggle=True)
    elif layer.kind == "VARIATION":
        box.label(text=K.TIPS["VARIATION"], icon="INFO")
    if layer.kind == "DECALS":
        box.label(text=K.TIPS["DECALS"], icon="INFO")
    # Advanced (UI-4)
    adv = box.column(align=True)
    adv.prop(layer, "show_advanced", icon="TRIA_DOWN" if layer.show_advanced else "TRIA_RIGHT", emboss=False)
    if layer.show_advanced:
        adv.prop(layer, "breakup_contrast")
        adv.prop(layer, "breakup_scale")
        adv.prop(layer, "breakup_offset")
        if layer.content == "TEXTURE" and layer.texture.loaded():
            adv.prop(layer.texture, "roughness_offset")
            adv.prop(layer.texture, "bump")
        if layer.kind == "REVEAL":
            adv.prop(layer, "edge_dark")
        if layer.kind == "EDGE_WEAR":
            adv.prop(layer, "bevel_samples")
        if layer.kind == "DECALS":
            adv.prop(layer, "decal_blend")
        if K.paintable(layer.kind) and layer.kind != "DECALS":
            adv.prop(layer, "mask_res")
        _mask_rows(adv, layer)


def _bake_rows(layout, mat):
    col = layout.column(align=True)
    if mat.realworn.baked:
        op(col, "realworn.restore_live", icon="LOOP_BACK")
    row = col.row(align=True)
    op(row, "realworn.bake", text="Bake Material", icon="RENDER_STILL")
    op(row, "realworn.export_textures", text="Export Textures", icon="EXPORT")
    op(col, "realworn.bake_sources", text="Bake Edges and AO", icon="MOD_BEVEL")


def draw_updates(layout, full=False):
    """The update notice (the sidebar shows it only when there is news; the add-on preferences
    always show it, with Check for Updates)."""
    from ..core import update
    from ..operators import update as U
    status, info, message = U.STATE["status"], U.STATE["info"], U.STATE["message"]
    if not full and status not in {"AVAILABLE", "DOWNLOADING"}:
        return
    col = layout.column(align=True)
    if full:
        cur = U.current_version()
        row = col.row(align=True)
        row.label(text="RealWorn {}".format(update.version_text(cur) if cur else "?"), icon="PACKAGE")
        op(row, "realworn.update_check", text="Check for Updates", icon="FILE_REFRESH")
        if not bpy.app.online_access:
            col.label(text="Allow Online Access is off (Preferences > System > Network)", icon="INFO")
    new = update.version_text(info["version"]) if info else ""
    if status == "CHECKING":
        col.label(text="Checking GitHub...", icon="SORTTIME")
    elif status == "LATEST":
        col.label(text="Up to date", icon="CHECKMARK")
    elif status == "DOWNLOADING":
        col.label(text="Downloading RealWorn {}...".format(new), icon="IMPORT")
    elif status == "ERROR":
        col.label(text=message, icon="ERROR")
    elif status == "AVAILABLE":
        repo, why = U.target()
        if repo is None:
            col.label(text="RealWorn {} is available".format(new), icon="INFO")
            if full:
                col.label(text=why)
            col.operator("wm.url_open", text="Open the Release Page", icon="URL").url = info["page"]
        else:
            op(col, "realworn.update_install", text="Update to RealWorn {}".format(new), icon="IMPORT")


class _PanelBody:
    bl_label = "RealWorn"

    def draw(self, context):
        layout = self.layout
        draw_updates(layout)
        ob, mat = _context_material(context)
        if ob is None or ob.type != "MESH":
            layout.label(text="Select a mesh object", icon="INFO")
            return
        row = layout.row(align=True)
        if not setup.is_setup(ob):
            row.prop(context.scene.realworn, "uv_method", text="")
            op(row, "realworn.setup", text="Setup", icon="ADD")
            return
        op(row, "realworn.setup", text="Setup", icon="FILE_REFRESH")
        op(row, "realworn.remove", text="Remove", icon="X")
        if mat is None:
            layout.label(text="No material in the active slot", icon="INFO")
            return
        if _banners(layout, mat) or not injector.is_setup(mat):
            return
        st = mat.realworn
        _add_row(layout)
        row = layout.row()
        row.template_list("RW_UL_layers", "", st, "layers", st, "active_layer_index", rows=5)
        col = row.column(align=True)
        o = op(col, "realworn.layer_move", text="", icon="TRIA_UP")
        o.direction = "UP"
        o = op(col, "realworn.layer_move", text="", icon="TRIA_DOWN")
        o.direction = "DOWN"
        op(col, "realworn.layer_duplicate", text="", icon="DUPLICATE")
        op(col, "realworn.layer_remove", text="", icon="X")
        base = layout.row(align=True)
        o = op(base, "realworn.layer_select", text="Base   {}".format(st.base.name or mat.name),
               icon="MATERIAL", depress=st.base_active or not len(st.layers))
        o.index = -1
        if st.base_active or not len(st.layers):
            draw_base(layout, mat)
        else:
            draw_layer(layout, context, ob, mat, st.layers[st.active_layer_index])
        _bake_rows(layout, mat)


class RW_PT_main(_PanelBody, _Base, bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_idname = "RW_PT_main"


class RW_PT_image(_PanelBody, _Base, bpy.types.Panel):
    bl_space_type = "IMAGE_EDITOR"
    bl_idname = "RW_PT_image"


class RW_PT_debug(_Base, bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_idname = "RW_PT_debug"
    bl_label = "Debug"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        op(col, "realworn.validate", icon="CHECKMARK")
        op(col, "realworn.remove_all", icon="TRASH")
        from ..props import prefs
        p = prefs()
        if p is not None and p.developer_mode:
            op(col, "realworn.reload", icon="FILE_REFRESH")


_classes = (RW_UL_layers, RW_PT_main, RW_PT_image, RW_PT_debug)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

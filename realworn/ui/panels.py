"""The RealWorn sidebar tab, laid out like a texturing app: header (Setup / Remove, UV status), the
layer list (top of the list is the top layer, Base pinned at the bottom), then the selected
layer's Content / Mask / Brush tabs, then Bake. The same panels show in the Image Editor."""

import bpy

from ..core import injector, layer_types as LT, setup

CHANNELS = (("color", "Color"), ("roughness", "Roughness"), ("metallic", "Metallic"), ("height", "Height (mm)"))


def op(layout, idname, **kw):
    """layout.operator that tolerates operators from later milestones not being registered."""
    if not hasattr(bpy.types, "REALWORN_OT_" + idname.split(".", 1)[1]):  # registered name
        r = layout.row()
        r.enabled = False
        r.label(text=kw.get("text") or idname.split(".", 1)[1].replace("_", " ").title(), icon=kw.get("icon", "NONE"))
        return None
    return layout.operator(idname, **kw)


class _Null:
    def __setattr__(self, k, v):
        pass


def opx(layout, idname, **kw):
    o = op(layout, idname, **kw)
    return o if o is not None else _Null()


def _context_material(context):
    ob = context.active_object
    if ob is None or ob.type != "MESH":
        return ob, None
    return ob, ob.active_material


class RW_UL_layers(bpy.types.UIList):
    bl_idname = "RW_UL_layers"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        row.label(text="", icon=LT.TYPES.get(item.type, LT.TYPES["CUSTOM"])["icon"])
        row.prop(item, "name", text="", emboss=False)
        sub = row.row(align=True)
        sub.scale_x = 0.9
        sub.prop(item, "opacity", text="", slider=True)
        op = opx(row, "realworn.paint_enter", text="", icon="BRUSH_DATA", emboss=False)
        op.layer = item.id
        img = item.mask_image or item.content_image
        if img is not None:
            if img.preview is None:
                img.preview_ensure()
            row.label(text="", icon_value=img.preview.icon_id if img.preview else 0)
        else:
            row.label(text="", icon="BLANK1")

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


def _draw_header(layout, context, ob, mat):
    if mat is not None and mat.realworn.applied and mat.realworn.stack is None:
        box = layout.box()
        box.label(text="Weathered with RealWorn v0.7", icon="ERROR")
        box.operator("realworn.migrate_v07", icon="LOOP_BACK")
        return False
    if ob is None or ob.type != "MESH":
        layout.label(text="Select a mesh object", icon="INFO")
        return False
    box = layout.box()
    box.label(text=ob.name, icon="OBJECT_DATA")
    if mat is not None:
        box.label(text=mat.name, icon="MATERIAL")
    if not setup.is_setup(ob) or mat is None or not injector.is_setup(mat):
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("realworn.setup", icon="BRUSHES_ALL")
        layout.prop(context.scene.realworn, "use_existing_uv")
        if mat is not None and setup.is_setup(ob) and not injector.is_setup(mat):
            layout.label(text="This material was added after Setup: click Setup again", icon="INFO")
        return False
    res = max((ly.mask_image.size[0] for ly in mat.realworn.layers if ly.mask_image), default=0)
    box.label(text="Painting on RW_Paint" + (", {} px".format(res) if res else ""), icon="UV")
    if mat.realworn.source_material:
        box.label(text="Unique copy of {} (was shared)".format(mat.realworn.source_material), icon="LINKED")
    return True


def _draw_layers(layout, mat):
    st = mat.realworn
    row = layout.row()
    row.template_list("RW_UL_layers", "", st, "layers", st, "active_layer_index", rows=6)
    col = row.column(align=True)
    col.operator_menu_enum("realworn.layer_add", "type", text="", icon="ADD")
    col.operator("realworn.layer_remove", text="", icon="REMOVE")
    col.separator()
    col.operator("realworn.layer_move", text="", icon="TRIA_UP").direction = "UP"
    col.operator("realworn.layer_move", text="", icon="TRIA_DOWN").direction = "DOWN"
    col.separator()
    col.operator("realworn.layer_duplicate", text="", icon="DUPLICATE")
    base = layout.row()
    base.enabled = False
    base.label(text="Base: {}".format(st.source_material or mat.name), icon="MATERIAL_DATA")


def _channel(layout, layer, key, label):
    ch = getattr(layer, key)
    box = layout.box()
    row = box.row(align=True)
    row.prop(ch, "enabled", text="")
    row.label(text=label)
    if not ch.enabled:
        return
    sub = box.row(align=True)  # LAY-3: only the blend modes this channel supports
    for mode in LT.blends_for(key):
        sub.prop_enum(ch, "blend", mode)
    row = box.row(align=True)
    if key == "color" and ch.source in ("FLAT", "TINTED_GRUNGE"):
        row.prop(ch, "color", text="")
    elif key != "color" and ch.source == "FLAT":
        row.prop(ch, "value", text="Value" if key != "height" else "mm", slider=key != "height")
    row.prop(ch, "source", text="")
    if ch.source in ("IMAGE", "PBRSET"):
        box.template_ID(ch, "image", open="image.open")
        r = box.row(align=True)
        r.prop(ch, "scale")
        r.prop(ch, "use_uv", text="UV", toggle=True)
        if key == "height":
            box.prop(ch, "value", text="Height (mm)")
    elif ch.source == "TINTED_GRUNGE":
        box.template_ID(ch, "grunge", open="image.open")
        box.prop(ch, "variation", slider=True)


def draw_content(layout, mat, layer):
    opx(layout, "realworn.pbrset_load", icon="FILEBROWSER")
    for key, label in CHANNELS:
        _channel(layout, layer, key, label)
    if layer.normal_image is not None:
        r = layout.row(align=True)
        r.label(text=layer.normal_image.name, icon="NORMALS_FACE")
        r.prop(layer, "normal_strength", text="")
    row = layout.row(align=True)
    row.prop(layer, "use_variation", toggle=True)
    if layer.use_variation:
        row.prop(layer, "variation", slider=True, text="")
        row.prop(layer, "variation_scale", text="")
    if layer.type == "WATER":
        box = layout.box()
        box.label(text="Water", icon="MOD_FLUIDSIM")
        for p in ("darken", "depth", "edge"):
            box.prop(layer.water, p, slider=True)
    elif layer.type == "DAMAGE":
        box = layout.box()
        box.label(text="Damage", icon="MOD_BOOLEAN")
        box.prop(layer.damage, "depth_mode", expand=True)
        box.prop(layer.damage, "inner")
        for p in ("depth_mm", "reveal", "rim_height", "rim_width", "rim_brightness", "sharpness"):
            box.prop(layer.damage, p)
        if layer.damage.depth_mode == "GEOMETRY":
            for p in ("threshold", "size_min", "size_max", "density", "debris", "live"):
                box.prop(layer.damage, p)
            opx(box, "realworn.damage_apply", icon="CHECKMARK")
        if layer.damage.get("rw_warning"):  # DMG-9 guards (closed mesh, too coarse)
            box.label(text=layer.damage["rw_warning"], icon="ERROR")
        opx(box, "realworn.damage_dirt", icon="BRUSH_DATA")
    elif layer.type == "DECAL":
        box = layout.box()
        box.label(text="Decal", icon="IMAGE_DATA")
        box.prop(layer.decal, "empty")
        box.prop(layer.decal, "mode", expand=True)
        box.prop(layer.decal, "darken", slider=True)
        opx(box, "realworn.decal_bake", icon="RENDER_STILL")
    elif layer.type == "PAINT":
        opx(layout, "realworn.paint_enter", text="Paint Colour", icon="TPAINT_HLT").target = "CONTENT"


def draw_mask(layout, mat, layer):
    st = mat.realworn
    layout.prop(st, "mask_view", toggle=True, icon="MOD_MASK")
    box = layout.box()
    box.label(text="Ingredients (start at 0: pure painting)")
    for i, ing in enumerate(layer.ingredients):
        r = box.row(align=True)
        r.label(text=ing.bl_rna.properties["kind"].enum_items[ing.kind].name)
        r.prop(ing, "amount", slider=True, text="")
        op = opx(r, "realworn.ingredient_remove", text="", icon="X")
        op.index = i
        if ing.kind == "GRUNGE":
            r2 = box.row(align=True)
            r2.template_ID(ing, "image", open="image.open")
            r3 = box.row(align=True)
            for p in ("scale", "rotation", "contrast"):
                r3.prop(ing, p)
            box.prop(ing, "invert")
        elif ing.kind in LT.GENERATOR_KINDS:
            r3 = box.row(align=True)
            r3.prop(ing, "width")
            r3.prop(ing, "contrast")
        elif ing.kind == "UP":
            box.prop(ing, "angle")
        elif ing.kind == "REFERENCE":
            box.prop_search(ing, "ref_layer_id", st, "layers", text="Layer")
    if hasattr(bpy.types, "REALWORN_OT_ingredient_add"):
        box.operator_menu_enum("realworn.ingredient_add", "kind", text="Add Ingredient", icon="ADD")
    box = layout.box()
    row = box.row(align=True)
    row.prop(layer, "lock_source")
    if layer.lock_source != "NONE":
        row.prop(layer, "lock_strength", slider=True, text="")
    r = box.row(align=True)
    r.prop(layer, "threshold", slider=True)
    r.prop(layer, "softness", slider=True)
    r = box.row(align=True)
    r.prop(layer, "use_height_blend", toggle=True)
    if layer.use_height_blend:
        r.prop(layer, "height_blend", text="")
    r = layout.row(align=True)
    opx(r, "realworn.mask_preset_save", icon="FILE_TICK")
    opx(r, "realworn.mask_preset_load", icon="FILEBROWSER")


def draw_brush(layout, context, mat, layer):
    sp = context.scene.realworn
    ob = context.active_object
    col = layout.column(align=True)
    row = col.row(align=True)
    row.scale_y = 1.3
    if ob is not None and ob.mode == "TEXTURE_PAINT":
        opx(row, "realworn.paint_exit", icon="LOOP_BACK")
    else:
        opx(row, "realworn.paint_enter", icon="BRUSH_DATA").layer = layer.id
    row = col.row(align=True)
    for mode, icon in (("PAINT", "ADD"), ("ERASE", "REMOVE"), ("RESET", "LOOP_BACK")):
        opx(row, "realworn.paint_mode", text=mode.title(), icon=icon).mode = mode
    row = col.row(align=True)
    opx(row, "realworn.mask_fill", icon="SNAP_FACE").value = 1.0
    opx(row, "realworn.mask_fill", text="Clear", icon="X").value = 0.0
    box = layout.box()
    box.label(text="Grunge", icon="TEXTURE")
    box.template_icon_view(sp, "grunge_image", show_labels=True, scale=4.0, scale_popup=5.0)
    box.prop(sp, "grunge_mode", expand=True)
    r = box.row(align=True)
    r.prop(sp, "grunge_contrast", slider=True)
    r.prop(sp, "grunge_invert", toggle=True)
    opx(box, "realworn.grunge_select", icon="CHECKMARK")
    ts = context.tool_settings
    ups = ts.image_paint.unified_paint_settings if ts and ts.image_paint else None
    brush = ts.image_paint.brush if ts and ts.image_paint else None
    if ups is not None:
        col = layout.column(align=True)
        col.prop(ups, "size", slider=True)
        col.prop(ups, "strength", slider=True)
    if brush is not None and brush.name.startswith("RW "):
        col = layout.column(align=True)
        col.prop(brush, "spacing")
        if brush.mask_texture_slot is not None:
            col.prop(brush.mask_texture_slot, "use_random", text="Random Angle")
        col.prop(brush, "curve_distance_falloff_preset", text="Falloff")


def draw_main(self, context):
    lay = self.layout
    ob, mat = _context_material(context)
    if not _draw_header(lay, context, ob, mat):
        return
    _draw_layers(lay, mat)
    st = mat.realworn
    if not len(st.layers):
        lay.label(text="Add a layer with +, then paint it", icon="INFO")
        return
    layer = st.layers[min(st.active_layer_index, len(st.layers) - 1)]
    sp = context.scene.realworn
    lay.prop(sp, "layer_tab", expand=True)
    if sp.layer_tab == "CONTENT":
        draw_content(lay, mat, layer)
    elif sp.layer_tab == "MASK":
        draw_mask(lay, mat, layer)
    else:
        draw_brush(lay, context, mat, layer)
    row = lay.row(align=True)
    row.operator("realworn.remove", icon="X")


class RW_PT_bake(_Base, bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_label = "Bake"
    bl_idname = "RW_PT_bake"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ob, mat = _context_material(context)
        return mat is not None and injector.is_setup(mat)

    def draw(self, context):
        p = context.scene.realworn
        lay = self.layout
        ob, mat = _context_material(context)
        if mat.realworn.baked:
            lay.label(text="Showing baked textures", icon="IMAGE_DATA")
        opx(lay, "realworn.flatten", icon="RENDERLAYERS")
        lay.prop(p, "bake_resolution")
        lay.prop(p, "bake_folder")
        row = lay.row(align=True)
        opx(row, "realworn.bake", icon="RENDER_STILL")
        opx(row, "realworn.restore_live", icon="LOOP_BACK")
        row = lay.row(align=True)
        row.prop(p, "export_preset", text="")
        opx(row, "realworn.export_textures", icon="EXPORT")


class RW_PT_tools(_Base, bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_label = "Decals, Ground, Debug"
    bl_idname = "RW_PT_tools"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        p = context.scene.realworn
        lay = self.layout
        lay.template_icon_view(p, "decal_image", show_labels=True, scale=4.0)
        lay.prop(p, "decal_mode", expand=True)
        lay.prop(p, "decal_size")
        row = lay.row(align=True)
        for cursor in (False, True):
            op = opx(row, "realworn.decal_place", text="At Cursor" if cursor else "Place Decal",
                     icon="PIVOT_CURSOR" if cursor else "RESTRICT_SELECT_OFF")
            op.use_cursor, op.mode, op.size = cursor, p.decal_mode, p.decal_size
        row = lay.row(align=True)
        row.operator("realworn.mark_ground", icon="VIEW_PERSPECTIVE").state = True
        row.operator("realworn.mark_ground", text="", icon="X").state = False
        lay.operator("realworn.validate", icon="CHECKMARK")
        lay.operator("realworn.remove_all", icon="TRASH")
        from ..props import prefs
        pr = prefs()
        if pr is not None and pr.developer_mode:
            row = lay.row(align=True)
            row.operator("realworn.reload", icon="FILE_REFRESH")
            row.operator("realworn.rebuild_assets", icon="NODETREE")


class RW_PT_main(_Base, bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_label = "RealWorn"
    bl_idname = "RW_PT_main"
    draw = draw_main


class RW_PT_image_main(_Base, bpy.types.Panel):
    """The same panel in the Image Editor sidebar, so painting in 2D UV view also works."""
    bl_space_type = "IMAGE_EDITOR"
    bl_label = "RealWorn"
    bl_idname = "RW_PT_image_main"
    draw = draw_main


_classes = (RW_UL_layers, RW_PT_main, RW_PT_bake, RW_PT_tools, RW_PT_image_main)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

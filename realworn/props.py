"""PropertyGroups: the v3 layer data model (material.realworn.layers) plus object, scene and add-on
preferences.

The layer list is the source of truth. Every property's update callback is one of two kinds:
VALUE writes straight into the matching node of RW_Stack::<material> (no recompile, no EEVEE
shader rebuild); STRUCT calls compiler.compile() for that material.
"""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)

from .core import kinds as K
from .core import puddle as P

KIND_ITEMS = [(k, K.label(k), "New {} layer".format(K.label(k)), K.INFO[k]["icon"], i)
              for i, k in enumerate(K.KINDS)]
CONTENT_ITEMS = [("TEXTURE", "Texture", "A loaded texture set, box mapped"),
                 ("TINT_BELOW", "Tint Below", "A recoloured copy of the Base (the classic duplicated material with "
                                              "Hue/Saturation): its texture shows, the layers in between do not"),
                 ("COLOR", "Color", "A flat colour with roughness (a plain BSDF)")]
SOURCE_ITEMS = [("LIVE", "Live", "The classic Bevel / AO nodes, evaluated in Cycles"),
                ("BAKED", "Baked", "Baked to an image on RW_Paint: looks the same in EEVEE, renders faster")]
DECAL_BLEND_ITEMS = [("NORMAL", "Normal", "Graffiti and stickers keep their own colour"),
                     ("DARKEN", "Darken", "Drips, dirt and mold multiply the surface below; its texture stays visible")]
UV_ITEMS = [("CUBE", "Cube Projection", "Cube Projection then Pack Islands (the classic way; buildings, props)"),
            ("SMART", "Smart UV", "Smart UV Project (organic shapes)"),
            ("EXISTING", "Use Existing", "Copy the object's own UV map (clean, non-overlapping layouts)")]
RES_ITEMS = [(str(r), str(r), "") for r in (256, 512, 1024, 2048, 4096)]
DECAL_RES_ITEMS = [("2048", "2K", ""), ("4096", "4K", "Recommended"), ("8192", "8K", "Large buildings")]
PUDDLE_PRESET_ITEMS = [(k, n, ("A wet film over every flat face, plus puddles: {}" if k in P.FILM_PRESETS else
                               "Water level, halo and depth look: {}").format(n.lower())) for k, n, _ in P.PRESETS]
SURFACE_ITEMS = [("NONE", "Custom", "Keep your own Height Scale and dip settings")] + [
    (k, n, "Height Scale and broad dips for {}".format(n.lower())) for k, n, _ in P.SURFACES]
PUDDLE_SOURCE_ITEMS = [("AUTO", "Auto", "Water collects in the low spots of the ground, nothing painted"),
                       ("PAINT", "Paint", "Water only where you paint (it still follows the ground)"),
                       ("AUTO_AND_PAINT", "Auto and Paint",
                        "Auto puddles, plus painting to add (white) or dry out (black) spots")]
HEIGHT_SOURCE_ITEMS = [("STACK", "Stack", "The base height plus what the layers below add (Reveal holes fill)"),
                       ("BASE", "Base Only", "Only the base material's height map"),
                       ("NONE", "None", "Flat: only Broad Dips and painting shape the water")]
TINT_ITEMS = [("CLEAR", "Clear", "Clean rain water: dark, cool, see-through"),
              ("MUDDY", "Muddy", "Brown water that hides the ground quickly"),
              ("OILY", "Oily", "Clear water with an iridescent sheen in patches"),
              ("CUSTOM", "Custom", "Your own tint colour")]
EXPORT_ITEMS = [("UNITY_URP", "Unity URP", "BaseMap, MetallicSmoothness, Normal (OpenGL)"),
                ("UNITY_HDRP", "Unity HDRP", "BaseColor, MaskMap (M, AO, Detail, Smoothness), Normal (OpenGL)"),
                ("UNREAL", "Unreal ORM", "BaseColor, ORM (AO, Rough, Metal), Normal (DirectX)"),
                ("GLTF", "glTF", "baseColor, metallicRoughness (G rough, B metal), normal (OpenGL)")]


# ------------------------------------------------------------------ callbacks
def _v(prop):
    """VALUE update for one property: Blender's update callbacks do not say which property changed,
    so each value property gets its own callback that names it."""
    def update(self, context):
        from .core import compiler
        compiler.on_value(self, prop)
    return update


def _struct(self, context):
    from .core import compiler
    compiler.on_struct(self)


def _active_layer(self, context):
    from .core import compiler
    compiler.on_active_layer(self)


def _true_depth(self, context):
    from .core import compiler, reveal
    reveal.sync(self.id_data)
    compiler.on_struct(self)


def _puddle_preset(self, context):
    from .core import compiler
    mat = self.id_data
    with compiler.batch(mat):
        for k, v in P.preset_values(self.puddle_preset).items():
            setattr(self, k, v)
    compiler.on_struct(self)


def _surface(self, context):
    from .core import compiler
    if self.surface == "NONE":
        return
    mat = self.id_data
    with compiler.batch(mat):
        for k, v in P.preset_values(self.surface, P.SURFACES).items():
            setattr(self, k, v)
    compiler.on_struct(self)


def _puddle_outline_items(self, context):
    from .core import grunge
    return grunge.puddle_outline_items()


def _pick_puddle_outline(self, context):
    from .core import grunge
    grunge.set_puddle_outline(self.puddle_outline)


def _library_items(self, context):
    from .core import pbrset
    p = prefs()
    return pbrset.library_enum_items(p.texture_folder if p is not None else "")


def _grunge_items(self, context):
    from .core import grunge
    return grunge.library_enum_items("grunges")


def _alpha_items(self, context):
    from .core import grunge
    return grunge.library_enum_items("alphas")


def _decal_items(self, context):
    from .core import grunge
    return grunge.library_enum_items("decals")


def _pick_alpha(self, context):
    from .core import grunge
    grunge.set_damage_alpha(self.damage_alpha)


def _pick_decal(self, context):
    from .core import grunge
    grunge.set_stencil_decal(self.decal_image)


# ------------------------------------------------------------------ data
class RWTextureSet(bpy.types.PropertyGroup):
    """A loaded PBR folder (LT-1): maps found by name, box mapped at Scale metres per tile."""
    name: StringProperty(name="Name", default="")
    folder: StringProperty(name="Folder", default="", subtype="DIR_PATH")
    color: PointerProperty(name="Color", type=bpy.types.Image, update=_struct)
    roughness: PointerProperty(name="Roughness", type=bpy.types.Image, update=_struct)
    gloss: BoolProperty(name="Glossiness", default=False, update=_struct,
                        description="The roughness map is a glossiness map (used inverted)")
    metallic: PointerProperty(name="Metallic", type=bpy.types.Image, update=_struct)
    height: PointerProperty(name="Height", type=bpy.types.Image, update=_struct)
    normal: PointerProperty(name="Normal", type=bpy.types.Image, update=_struct)
    normal_dx: BoolProperty(name="DirectX Normal", default=False)
    ao: PointerProperty(name="AO", type=bpy.types.Image, update=_struct)
    packed: PointerProperty(name="Packed ARM / ORM", type=bpy.types.Image, update=_struct,
                            description="R: ambient occlusion, G: roughness, B: metallic")
    scale: FloatProperty(name="Scale", default=1.0, min=0.01, soft_max=20.0, subtype="DISTANCE",
                         update=_v("scale"), description="Size of one texture tile in metres")
    roughness_offset: FloatProperty(name="Roughness", default=0.0, min=-1.0, max=1.0, update=_v("roughness_offset"),
                                    description="Added to the roughness map")
    normal_strength: FloatProperty(name="Normal Strength", default=1.0, min=0.0, max=4.0,
                                   description="Kept for the texture set; box mapping has no tangents, so relief "
                                               "comes from the height map (Bump Strength)")
    bump: FloatProperty(name="Bump Strength", default=0.02, min=0.0, soft_max=0.2, subtype="DISTANCE",
                        update=_v("bump"), description="Displacement Scale: metres of height "
                                                       "over the height map's 0..1")

    # the height map's 2nd / 98th percentiles (0..1), measured once: Puddle normalises by them
    height_lo: FloatProperty(name="Height Low", default=0.0, options={"HIDDEN"})
    height_hi: FloatProperty(name="Height High", default=1.0, options={"HIDDEN"})
    height_measured: StringProperty(name="Height Measured", default="", options={"HIDDEN"},
                                    description="Name of the height image the range was measured on")

    def loaded(self):
        return self.color is not None or self.packed is not None or self.height is not None


class RWLayer(bpy.types.PropertyGroup):
    id: StringProperty(name="ID", default="", description="Stable id used in node names")
    kind: EnumProperty(name="Kind", items=KIND_ITEMS, default="PAINT")
    name: StringProperty(name="Name", default="Layer")
    visible: BoolProperty(name="Visible", default=True, update=_struct)
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_v("opacity"))
    # content
    content: EnumProperty(name="Content", items=CONTENT_ITEMS, default="TINT_BELOW", update=_struct)
    texture: PointerProperty(type=RWTextureSet)
    color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, min=0.0, max=1.0, default=(0.5, 0.5, 0.5),
                               update=_v("color"))
    roughness: FloatProperty(name="Roughness", default=0.5, min=0.0, max=1.0, update=_v("roughness"))
    hue: FloatProperty(name="Hue", default=0.0, min=-0.5, max=0.5, update=_v("hue"))
    saturation: FloatProperty(name="Saturation", default=0.0, min=-1.0, max=1.0, update=_v("saturation"))
    value: FloatProperty(name="Value", default=0.0, min=-1.0, max=1.0, update=_v("value"))
    # mask
    mask_image: PointerProperty(name="Mask", type=bpy.types.Image, update=_struct,
                                description="Painted mask (Paint, Reveal, optional on Edge Wear and Dirt) or the "
                                            "RGBA decal image (Decals)")
    baked_image: PointerProperty(name="Baked Source", type=bpy.types.Image, update=_struct,
                                 description="Edge Wear / Dirt source baked to RW_Paint (Bake Edges and AO)")
    breakup_grunge: PointerProperty(name="Breakup", type=bpy.types.Image, update=_struct)
    breakup_amount: FloatProperty(name="Amount", default=0.0, min=0.0, max=1.0, update=_v("breakup_amount"),
                                  description="How much the grunge is subtracted from the mask (0: off)")
    breakup_scale: FloatProperty(name="Breakup Scale", default=0.5, min=0.01, soft_max=10.0, subtype="DISTANCE",
                                 update=_v("breakup_scale"), description="Grunge tile size in metres")
    breakup_contrast: FloatProperty(name="Breakup Contrast", default=0.0, min=0.0, max=0.95,
                                    update=_v("breakup_contrast"), description="The grunge's own Color Ramp")
    breakup_offset: FloatProperty(name="Breakup Offset", default=0.0, update=_v("breakup_offset"),
                                  description="Moves the grunge so layers never line up")
    sharpness: FloatProperty(name="Sharpness", default=0.5, min=0.0, max=1.0, update=_v("sharpness"),
                             description="The Color Ramp after the subtract: soft (0) to hard (1)")
    threshold: FloatProperty(name="Threshold", default=0.5, min=0.0, max=1.0, update=_v("threshold"),
                             description="Moves the mask's edge in or out")
    mask_res: IntProperty(name="Mask Resolution", default=0, min=0, max=8192,
                          description="0: from texel density (2048 px per metre)")
    # kind-specific
    depth_mm: FloatProperty(name="Depth", default=2.0, min=0.0, soft_max=30.0, update=_v("depth_mm"),
                            description="Reveal: millimetres the holes sit below the surface")
    true_depth: BoolProperty(name="True Depth", default=False, update=_true_depth,
                             description="Real displacement with adaptive subdivision (Cycles); needs mesh density")
    edge_dark: FloatProperty(name="Edge Darkening", default=0.3, min=0.0, max=1.0, update=_v("edge_dark"),
                             description="A thin darker band where a hole meets the surface")
    width_mm: FloatProperty(name="Width", default=5.0, min=0.1, soft_max=50.0, update=_v("width_mm"),
                            description="Edge Wear: Bevel radius in millimetres")
    distance_cm: FloatProperty(name="Distance", default=20.0, min=0.1, soft_max=200.0, update=_v("distance_cm"),
                               description="Dirt: ambient occlusion distance in centimetres")
    only_local: BoolProperty(name="Only Local", default=False, update=_v("only_local"),
                             description="Dirt: ignore other objects")
    edge_source: EnumProperty(name="Source", items=SOURCE_ITEMS, default="LIVE", update=_struct)
    bevel_samples: IntProperty(name="Bevel Samples", default=8, min=1, max=128, update=_v("bevel_samples"))
    decal_blend: EnumProperty(name="Blend", items=DECAL_BLEND_ITEMS, default="NORMAL", update=_struct)
    decal_res: EnumProperty(name="Resolution", items=DECAL_RES_ITEMS, default="4096")
    # Puddle (core/puddle.py): water where the water level is above the ground; depths in mm
    puddle_preset: EnumProperty(name="Preset", items=PUDDLE_PRESET_ITEMS, default=P.DEFAULT_PRESET,
                                update=_puddle_preset)
    puddle_source: EnumProperty(name="Source", items=PUDDLE_SOURCE_ITEMS, default="AUTO_AND_PAINT", update=_struct)
    height_source: EnumProperty(name="Height Source", items=HEIGHT_SOURCE_ITEMS, default="STACK", update=_struct)
    surface: EnumProperty(name="Surface", items=SURFACE_ITEMS, default="NONE", update=_surface,
                          description="Sets Height Scale and Broad Dips for a kind of ground")
    height_scale_mm: FloatProperty(name="Height Scale", default=10.0, min=0.1, soft_max=50.0,
                                   update=_v("height_scale_mm"),
                                   description="Millimetres the base height map's range spans for the water")
    water_level_mm: FloatProperty(name="Water Level", default=-2.0, soft_min=-15.0, soft_max=15.0,
                                  update=_v("water_level_mm"),
                                  description="Raises or lowers every puddle together: down for water only in "
                                              "cracks, up for large pools (mm)")
    paint_depth_mm: FloatProperty(name="Paint Depth", default=20.0, min=0.0, soft_max=60.0,
                                  update=_v("paint_depth_mm"),
                                  description="How far painting lowers (white) or raises (black) the ground (mm)")
    broad_dips: BoolProperty(name="Broad Dips", default=False, update=_struct,
                             description="Large soft dips in the ground (always on when the base has no height map)")
    dip_depth_mm: FloatProperty(name="Dip Depth", default=15.0, min=0.0, soft_max=60.0, update=_v("dip_depth_mm"))
    dip_scale_m: FloatProperty(name="Dip Size", default=2.5, min=0.1, soft_max=10.0, subtype="DISTANCE",
                               update=_v("dip_scale_m"), description="Size of the broad dips in metres")
    depth_look_mm: FloatProperty(name="Depth Look", default=8.0, min=0.2, soft_max=40.0, update=_v("depth_look_mm"),
                                 description="How quickly the ground fades under the water (mm)")
    halo: FloatProperty(name="Halo", default=1.0, min=0.0, soft_max=3.0, update=_v("halo"),
                        description="How far the damp ring around the water spreads")
    edge_width_mm: FloatProperty(name="Wet Edge", default=1.5, min=0.05, soft_max=10.0, update=_v("edge_width_mm"),
                                 description="Width of the wet, glossy band (mm of depth)")
    halo_width_mm: FloatProperty(name="Halo Width", default=6.0, min=0.0, soft_max=30.0, update=_v("halo_width_mm"),
                                 description="Width of the damp halo (mm of depth)")
    deep_threshold_mm: FloatProperty(name="Deep From", default=6.0, min=0.1, soft_max=30.0,
                                     update=_v("deep_threshold_mm"),
                                     description="Water deeper than this is a flat mirror (mm)")
    darkening: FloatProperty(name="Darkening", default=1.0, min=0.0, max=1.0, update=_v("darkening"),
                             description="How much wet porous ground darkens")
    water_tint: EnumProperty(name="Water Tint", items=TINT_ITEMS, default="CLEAR", update=_struct)
    tint_color: FloatVectorProperty(name="Tint", subtype="COLOR", size=3, min=0.0, max=1.0,
                                    default=P.TINTS["CLEAR"], update=_v("tint_color"))
    flat_threshold: FloatProperty(name="Flat Faces", default=0.92, min=0.0, max=1.0, update=_v("flat_threshold"),
                                  description="Water only stands where the face points up at least this much "
                                              "(normal Z)")
    wind_ripple: FloatProperty(name="Wind Ripple", default=0.0, min=0.0, max=1.0, update=_v("wind_ripple"),
                               description="A faint static ripple on deep water")
    tide_mark: FloatProperty(name="Tide Mark", default=0.0, min=0.0, max=1.0, update=_v("tide_mark"),
                             description="A faint darker ring at the outer edge of the damp halo")
    debris_settle: FloatProperty(name="Debris Settle", default=0.0, min=0.0, max=1.0, update=_v("debris_settle"),
                                 description="Darkening in the deepest water, like silt")
    # Wet Film: a thin skin of water over every flat face (0: off, no extra nodes)
    wet_film: FloatProperty(name="Wet Film", default=0.0, min=0.0, max=1.0, update=_v("wet_film"),
                            description="Rain-soaked ground: every flat face glossy under a thin film of water")
    film_relief: FloatProperty(name="Relief Through Film", default=P.FILM_DEFAULTS["film_relief"], min=0.0,
                               max=1.0, update=_v("film_relief"),
                               description="How much the ground's relief breaks the film's reflections into "
                                           "streaks (0: mirror)")
    film_grunge: PointerProperty(name="Film Breakup", type=bpy.types.Image, update=_struct,
                                 description="The texture that varies the film (empty: Noise)")
    film_scale_m: FloatProperty(name="Film Scale", default=P.FILM_DEFAULTS["film_scale_m"], min=0.2, max=10.0,
                                subtype="DISTANCE", update=_v("film_scale_m"),
                                description="Size of the film's wet and calm patches in metres, independent of "
                                            "the texture")
    dry_patches: FloatProperty(name="Dry Patches", default=P.FILM_DEFAULTS["dry_patches"], min=0.0, max=1.0,
                               update=_v("dry_patches"), description="Patches where the film has dried (0: wet "
                                                                     "everywhere)")
    film_gloss: FloatProperty(name="Film Gloss", default=P.FILM_DEFAULTS["film_gloss"], min=0.0, max=0.2,
                              update=_v("film_gloss"), description="Coat roughness of a full film")
    show_advanced: BoolProperty(name="Advanced", default=False)


class RW_MaterialProps(bpy.types.PropertyGroup):
    applied: BoolProperty(name="Set Up", default=False)
    snapshot: StringProperty(name="Snapshot", default="")
    schema_version: IntProperty(name="Schema", default=0)
    mode: StringProperty(name="Mode", default="", description="CHANNEL or SHADER")
    stack: PointerProperty(name="Stack", type=bpy.types.NodeTree)
    layers: CollectionProperty(type=RWLayer)
    active_layer_index: IntProperty(name="Layer", default=0, update=_active_layer)
    base_active: BoolProperty(name="Base Selected", default=False,
                              description="The Base row is selected in the panel")
    base: PointerProperty(type=RWTextureSet)
    base_hue: FloatProperty(name="Hue", default=0.0, min=-0.5, max=0.5, update=_v("base_hue"))
    base_saturation: FloatProperty(name="Saturation", default=0.0, min=-1.0, max=1.0, update=_v("base_saturation"))
    base_value: FloatProperty(name="Value", default=0.0, min=-1.0, max=1.0, update=_v("base_value"))
    source_material: StringProperty(name="Source Material", default="",
                                    description="Material this one was duplicated from by Setup")
    owner: StringProperty(name="Object", default="")
    mask_view: BoolProperty(name="Mask View", default=False, update=_struct,
                            description="Show the selected layer's final mask in black and white")
    baked: BoolProperty(name="Baked", default=False)


class RW_ObjectProps(bpy.types.PropertyGroup):
    pass


class RW_SceneProps(bpy.types.PropertyGroup):
    uv_method: EnumProperty(name="Paint UV", items=UV_ITEMS, default="CUBE")
    apply_scale: BoolProperty(name="Apply Scale", default=True,
                              description="Apply unapplied object scale at Setup so box-mapped textures do not stretch")
    texture: EnumProperty(name="Texture", items=_library_items, description="Texture sets in your library folder")
    grunge: EnumProperty(name="Grunge", items=_grunge_items)
    damage_alpha: EnumProperty(name="Damage Alpha", items=_alpha_items, update=_pick_alpha)
    decal_image: EnumProperty(name="Decal", items=_decal_items, update=_pick_decal)
    puddle_outline: EnumProperty(name="Puddle Outline", items=_puddle_outline_items, update=_pick_puddle_outline,
                                 description="A grunge for ragged puddle outlines (the Puddle brush's mask)")
    bake_resolution: EnumProperty(name="Resolution", items=RES_ITEMS, default="2048")
    bake_folder: StringProperty(name="Folder", default="//rw_bake/", subtype="DIR_PATH")
    export_preset: EnumProperty(name="Engine", items=EXPORT_ITEMS, default="UNREAL")


class RW_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    mask_storage: EnumProperty(name="Mask Storage", items=[
        ("PACKED", "Packed in .blend", "Masks live inside the .blend file (default)"),
        ("PNG", "PNG Files", "Masks are saved under //textures/realworn/<object>/")], default="PACKED")
    texel_density: IntProperty(name="Texel Density", default=2048, min=64, max=8192,
                               description="Mask pixels per metre of the object's largest dimension")
    texture_folder: StringProperty(name="Texture Library", subtype="DIR_PATH", default="",
                                   description="Folder of texture sets (Poly Haven, ambientCG downloads work as they are)")
    grunge_folder: StringProperty(name="Grunge Folder", subtype="DIR_PATH", default="",
                                  description="Extra folder of black and white grunge images")
    alpha_folder: StringProperty(name="Damage Alpha Folder", subtype="DIR_PATH", default="",
                                 description="Extra damage alphas (subfolders become categories)")
    decal_folder: StringProperty(name="Decal Folder", subtype="DIR_PATH", default="",
                                 description="Extra decals (subfolders become categories: Drips, Dirt, Graffiti...)")
    recent_textures: StringProperty(name="Recent", default="[]", options={"HIDDEN"})
    developer_mode: BoolProperty(name="Developer Mode", default=False,
                                 description="Show Reload Add-on in the Debug panel")

    def draw(self, context):
        col = self.layout.column()
        for p in ("mask_storage", "texel_density", "texture_folder", "grunge_folder", "alpha_folder",
                  "decal_folder", "developer_mode"):
            col.prop(self, p)


def prefs():
    """Add-on preferences, or None when running unregistered as an add-on (tests)."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


_classes = (RWTextureSet, RWLayer, RW_MaterialProps, RW_ObjectProps, RW_SceneProps, RW_Preferences)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.realworn = PointerProperty(type=RW_SceneProps)
    bpy.types.Object.realworn = PointerProperty(type=RW_ObjectProps)
    bpy.types.Material.realworn = PointerProperty(type=RW_MaterialProps)


def unregister():
    del bpy.types.Material.realworn
    del bpy.types.Object.realworn
    del bpy.types.Scene.realworn
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

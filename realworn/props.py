"""PropertyGroups: the v2 layer data model (material.realworn.layers) plus object, scene and
add-on preferences.

The layer list is the source of truth. Every property's update callback is one of two kinds
(CMP-4): VALUE writes straight into the matching node input of RW_Stack::<material> (no
recompile, no EEVEE shader rebuild); STRUCT calls compiler.compile() for that material.
"""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)

from .core import layer_types as LT


def _items(seq, labels=None):
    return [(k, (labels or {}).get(k, k.replace("_", " ").title()), "") for k in seq]


TYPE_ITEMS = [(k, LT.TYPES[k]["label"], "New {} layer".format(LT.TYPES[k]["label"].lower()), LT.TYPES[k]["icon"], i)
              for i, k in enumerate(LT.ORDER)]
SOURCE_ITEMS = [("FLAT", "Flat", "A single value"), ("IMAGE", "Image", "One image map, box-projected"),
                ("PBRSET", "PBR Set", "Maps detected by name in a folder"),
                ("TINTED_GRUNGE", "Tinted Grunge", "Flat colour varied by a grunge image")]
BLEND_ITEMS = _items(("MIX", "MULTIPLY", "OVERLAY", "ADD", "DARKEN", "MIN", "MAX", "SUBTRACT", "REPLACE"))
INGREDIENT_ITEMS = [("GRUNGE", "Grunge Fill", "A grunge image projected over the whole object"),
                    ("EDGE", "Edge", "Convex edges (rw_edge from RW_Masks)"),
                    ("CAVITY", "Cavity", "Concave corners (rw_cavity)"),
                    ("CONTACT", "Contact", "Near objects marked as Ground (rw_contact)"),
                    ("UP", "Up", "Faces pointing up (world normal Z)"),
                    ("REFERENCE", "Reference", "Another layer's final mask (layers below only)")]
LOCK_ITEMS = [("NONE", "None", "Strokes go exactly where painted"), ("EDGE", "Edge", "Keep paint on convex edges"),
              ("CAVITY", "Cavity", "Keep paint in corners"), ("CONTACT", "Contact", "Keep paint near the ground"),
              ("UP", "Up", "Keep paint on top faces")]
DEPTH_ITEMS = [("SHADER", "Shader", "Dents through Bump; cheap, both engines"),
               ("DISPLACEMENT", "Displacement", "Real surface depth via material displacement"),
               ("GEOMETRY", "Geometry", "Boolean cutters where painted (RW_Damage)")]
INNER_ITEMS = [("CONCRETE", "Concrete Aggregate", ""), ("STEEL", "Bare Steel", ""), ("WOOD", "Raw Wood", ""),
               ("BRICK", "Brick Core", ""), ("PBRSET", "PBR Set", "Inner material from a folder")]
GRUNGE_MODE_ITEMS = [("STAMP", "Stamp", "Each dab samples a random patch (dirt, rust, dust)"),
                     ("PROJECTED", "Projected", "Grunge fixed in view, revealed as you paint"),
                     ("STENCIL", "Stencil", "One exact pattern you move, scale and rotate on screen"),
                     ("FILL", "Fill", "Use the grunge as this layer's Grunge Fill ingredient")]
DECAL_MODE_ITEMS = [("FULL", "Full", "Color with alpha, roughness, optional normal map"),
                    ("GRIME", "Grime", "Only darkens and changes roughness (stains, soot, leaks)"),
                    ("DAMAGE", "Damage", "Reveals what is below and adds a dent")]
RES_ITEMS = [(str(r), str(r), "") for r in (256, 512, 1024, 2048, 4096)]
EXPORT_ITEMS = [("UNITY_URP", "Unity URP", "BaseMap, MetallicSmoothness, Normal (OpenGL)"),
                ("UNITY_HDRP", "Unity HDRP", "BaseColor, MaskMap (M, AO, Detail, Smoothness), Normal (OpenGL)"),
                ("UNREAL", "Unreal ORM", "BaseColor, ORM (AO, Rough, Metal), Normal (DirectX)"),
                ("GLTF", "glTF", "baseColor, metallicRoughness (G rough, B metal), normal (OpenGL)")]


# ------------------------------------------------------------------ callbacks
def _v(prop):
    """VALUE update for one property: Blender's update callbacks do not say which property
    changed, so each value property gets its own callback that names it."""
    def update(self, context):
        from .core import compiler
        compiler.on_value(self, prop)
    return update


def _struct(self, context):
    from .core import compiler
    compiler.on_struct(self)


def _ground(self, context):
    from .core import masks
    masks.mark_ground(self.id_data, self.is_ground, sync_prop=False)


def _decal_items(self, context):
    from .core import decals
    return decals.library_enum_items()


def _grunge_items(self, context):
    from .core import grunge
    return grunge.library_enum_items()


# ------------------------------------------------------------------ layer data
class RWChannel(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Enabled", default=True, update=_struct)
    source: EnumProperty(name="Source", items=SOURCE_ITEMS, default="FLAT", update=_struct)
    color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, min=0.0, max=1.0, default=(0.5, 0.5, 0.5),
                               update=_v("color"))
    value: FloatProperty(name="Value", default=0.5, soft_min=0.0, soft_max=1.0, update=_v("value"))
    image: PointerProperty(name="Image", type=bpy.types.Image, update=_struct)
    blend: EnumProperty(name="Blend", items=BLEND_ITEMS, default="MIX", update=_struct)
    scale: FloatProperty(name="Scale", default=1.0, min=0.001, soft_max=20.0, subtype="DISTANCE", update=_v("scale"),
                         description="Size of one image tile in metres (box projection)")
    use_uv: BoolProperty(name="Use Object UV", default=False, update=_struct,
                         description="Map the image with the object's own UV map instead of box projection")
    variation: FloatProperty(name="Variation", default=0.6, min=0.0, max=1.0, update=_v("variation"),
                             description="Tinted Grunge: how much the grunge varies the colour")
    grunge: PointerProperty(name="Grunge", type=bpy.types.Image, update=_struct,
                            description="Tinted Grunge: the black and white image that varies the colour")


class RWIngredient(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Kind", items=INGREDIENT_ITEMS, default="GRUNGE", update=_struct)
    amount: FloatProperty(name="Amount", default=0.0, min=0.0, max=1.0, update=_v("amount"))
    image: PointerProperty(name="Image", type=bpy.types.Image, update=_struct)
    ref_layer_id: StringProperty(name="Layer", default="", update=_struct)
    scale: FloatProperty(name="Scale", default=1.0, min=0.001, soft_max=20.0, subtype="DISTANCE", update=_v("scale"))
    rotation: FloatProperty(name="Rotation", default=0.0, subtype="ANGLE", update=_v("rotation"))
    contrast: FloatProperty(name="Contrast", default=0.0, min=-1.0, max=1.0, update=_v("contrast"))
    invert: BoolProperty(name="Invert", default=False, update=_v("invert"))
    seed: FloatProperty(name="Seed", default=0.0, update=_v("seed"), description="Offsets the grunge projection")
    angle: FloatProperty(name="Angle", default=0.7853982, min=0.0, max=1.5707964, subtype="ANGLE", update=_v("angle"),
                         description="Up: faces within this angle of straight up count")
    width: FloatProperty(name="Width", default=0.015, min=0.0, soft_max=0.5, subtype="DISTANCE", update=_v("width"),
                         description="Edge / Cavity / Contact width in metres (shared by the object's layers)")


class RWWater(bpy.types.PropertyGroup):
    darken: FloatProperty(name="Darken", default=0.65, min=0.0, max=1.0, update=_v("darken"),
                          description="Colour multiplier where wet (scaled by the base roughness)")
    depth: FloatProperty(name="Depth", default=0.0, min=0.0, max=1.0, update=_v("depth"),
                         description="0 thin wet film, 1 standing water (base bump and height fade out)")
    edge: FloatProperty(name="Edge Darkening", default=0.15, min=0.0, max=1.0, update=_v("edge"),
                        description="Darker ring along the mask boundary, like a drying puddle edge")


class RWDamage(bpy.types.PropertyGroup):
    depth_mode: EnumProperty(name="Depth", items=DEPTH_ITEMS, default="SHADER", update=_struct)
    inner: EnumProperty(name="Inner Material", items=INNER_ITEMS, default="CONCRETE", update=_struct)
    depth_mm: FloatProperty(name="Depth (mm)", default=3.0, min=0.0, soft_max=30.0, update=_v("depth_mm"))
    rim_height: FloatProperty(name="Rim Height (mm)", default=0.6, min=0.0, soft_max=5.0, update=_v("rim_height"))
    rim_width: FloatProperty(name="Rim Width", default=0.25, min=0.01, max=1.0, update=_v("rim_width"))
    rim_brightness: FloatProperty(name="Rim Brightness", default=0.35, min=0.0, max=1.0, update=_v("rim_brightness"))
    sharpness: FloatProperty(name="Edge Sharpness", default=0.8, min=0.0, max=1.0, update=_v("sharpness"))
    threshold: FloatProperty(name="Threshold", default=0.5, min=0.0, max=1.0, update=_v("threshold"),
                             description="Geometry mode: mask value above which cutters spawn")
    size_min: FloatProperty(name="Size Min", default=0.015, min=0.001, soft_max=0.5, subtype="DISTANCE",
                            update=_v("size_min"))
    size_max: FloatProperty(name="Size Max", default=0.04, min=0.001, soft_max=0.5, subtype="DISTANCE",
                            update=_v("size_max"))
    density: FloatProperty(name="Density", default=400.0, min=0.0, soft_max=5000.0, update=_v("density"),
                           description="Geometry mode: cutters per square metre of painted area")
    debris: BoolProperty(name="Debris", default=False, update=_v("debris"))
    live: BoolProperty(name="Live Updates", default=True,
                       description="Geometry mode: re-cut after each stroke (off on heavy meshes)")
    inner_image_folder: StringProperty(name="Inner PBR Set", subtype="DIR_PATH", default="", update=_struct)


class RWDecal(bpy.types.PropertyGroup):
    empty: PointerProperty(name="Projector", type=bpy.types.Object, update=_struct)
    image: PointerProperty(name="Image", type=bpy.types.Image, update=_struct)
    normal_image: PointerProperty(name="Normal Map", type=bpy.types.Image, update=_struct)
    mode: EnumProperty(name="Mode", items=DECAL_MODE_ITEMS, default="FULL", update=_struct)
    darken: FloatProperty(name="Darken", default=0.5, min=0.0, max=1.0, update=_v("darken"))


class RWLayer(bpy.types.PropertyGroup):
    id: StringProperty(name="ID", default="", description="Stable id used in node names")
    name: StringProperty(name="Name", default="Layer")
    type: EnumProperty(name="Type", items=TYPE_ITEMS, default="CUSTOM")
    visible: BoolProperty(name="Visible", default=True, update=_struct)
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_v("opacity"))
    color: PointerProperty(type=RWChannel)
    roughness: PointerProperty(type=RWChannel)
    metallic: PointerProperty(type=RWChannel)
    height: PointerProperty(type=RWChannel)
    mask_image: PointerProperty(name="Mask", type=bpy.types.Image, update=_struct)
    content_image: PointerProperty(name="Content", type=bpy.types.Image, update=_struct)
    ingredients: CollectionProperty(type=RWIngredient)
    active_ingredient: IntProperty(default=0)
    lock_source: EnumProperty(name="Edge Lock", items=LOCK_ITEMS, default="NONE", update=_struct)
    lock_strength: FloatProperty(name="Lock Strength", default=0.0, min=0.0, max=1.0, update=_v("lock_strength"),
                                 description="0: strokes go where painted; 1: they only survive on the lock source")
    lock_width: FloatProperty(name="Lock Width", default=0.015, min=0.0, soft_max=0.5, subtype="DISTANCE",
                              update=_v("lock_width"))
    threshold: FloatProperty(name="Threshold", default=0.5, min=0.0, max=1.0, update=_v("threshold"))
    softness: FloatProperty(name="Softness", default=1.0, min=0.0, max=1.0, update=_v("softness"),
                            description="Low softness turns soft strokes into crisp, chipped boundaries")
    use_height_blend: BoolProperty(name="Height Blend", default=False, update=_struct)
    height_blend: FloatProperty(name="Height Blend Amount", default=0.5, min=0.0, max=2.0, update=_v("height_blend"))
    use_variation: BoolProperty(name="Color Variation", default=False, update=_struct)
    variation: FloatProperty(name="Variation", default=0.2, min=0.0, max=1.0, update=_v("variation"))
    variation_scale: FloatProperty(name="Variation Scale", default=0.5, min=0.01, soft_max=10.0,
                                   subtype="DISTANCE", update=_v("variation_scale"))
    use_vertex_mask: BoolProperty(name="Vertex Colour Mask", default=False, update=_struct,
                                  description="Paint the mask as vertex colours (meshes without usable UVs)")
    mask_res: IntProperty(name="Resolution", default=0, min=0, max=8192, description="0: from texel density")
    water: PointerProperty(type=RWWater)
    damage: PointerProperty(type=RWDamage)
    decal: PointerProperty(type=RWDecal)


class RW_MaterialProps(bpy.types.PropertyGroup):
    applied: BoolProperty(name="Set Up", default=False)
    snapshot: StringProperty(name="Snapshot", default="")
    schema_version: IntProperty(name="Schema", default=0)
    mode: StringProperty(name="Mode", default="", description="CHANNEL or SHADER")
    stack: PointerProperty(name="Stack", type=bpy.types.NodeTree)
    layers: CollectionProperty(type=RWLayer)
    active_layer_index: IntProperty(name="Layer", default=0)
    source_material: StringProperty(name="Source Material", default="",
                                    description="Material this one was duplicated from by Setup (SET-3)")
    owner: StringProperty(name="Object", default="")
    mask_view: BoolProperty(name="Mask View", default=False, update=_struct,
                            description="Show the active layer's final mask as greyscale")
    baked: BoolProperty(name="Baked", default=False)


class RW_ObjectProps(bpy.types.PropertyGroup):
    is_ground: BoolProperty(name="Ground", default=False, update=_ground,
                            description="Contact generators measure distance to ground objects")


class RW_SceneProps(bpy.types.PropertyGroup):
    add_type: EnumProperty(name="Layer Type", items=TYPE_ITEMS, default="DIRT")
    layer_tab: EnumProperty(name="Tab", items=[("CONTENT", "Content", "", "MATERIAL", 0),
                                               ("MASK", "Mask", "", "MOD_MASK", 1),
                                               ("BRUSH", "Brush", "", "BRUSH_DATA", 2)], default="CONTENT")
    use_existing_uv: BoolProperty(name="Use Existing UV", default=False,
                                  description="Copy the object's UV map into RW_Paint instead of Smart UV Project")
    grunge_image: EnumProperty(name="Grunge", items=_grunge_items)
    grunge_mode: EnumProperty(name="Mode", items=GRUNGE_MODE_ITEMS, default="STAMP")
    decal_image: EnumProperty(name="Decal", items=_decal_items, description="Decal image from the library")
    decal_mode: EnumProperty(name="Mode", items=DECAL_MODE_ITEMS, default="FULL")
    decal_size: FloatProperty(name="Size", min=0.01, max=20.0, default=0.6, subtype="DISTANCE")
    bake_resolution: EnumProperty(name="Resolution", items=RES_ITEMS, default="1024")
    bake_folder: StringProperty(name="Folder", default="//rw_bake/", subtype="DIR_PATH")
    export_preset: EnumProperty(name="Engine", items=EXPORT_ITEMS, default="UNREAL")


class RW_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    mask_storage: EnumProperty(name="Mask Storage", items=[
        ("PACKED", "Packed in .blend", "Masks live inside the .blend file (default)"),
        ("PNG", "PNG Files", "Masks are saved under //textures/realworn/<object>/")], default="PACKED")
    texel_density: IntProperty(name="Texel Density", default=1024, min=64, max=8192,
                               description="Mask pixels per metre of the object's largest dimension")
    grunge_folder: StringProperty(name="Grunge Folder", subtype="DIR_PATH", default="",
                                  description="Extra folder of black and white grunge images")
    decal_folder: StringProperty(name="Decal Library Folder", subtype="DIR_PATH", default="",
                                 description="Extra folder of decal images (name.png, optional name_nrm.png)")
    developer_mode: BoolProperty(name="Developer Mode", default=False,
                                 description="Show Reload Add-on and Rebuild Assets in the Debug panel")

    def draw(self, context):
        col = self.layout.column()
        for p in ("mask_storage", "texel_density", "grunge_folder", "decal_folder", "developer_mode"):
            col.prop(self, p)


def prefs():
    """Add-on preferences, or None when running unregistered as an add-on (tests)."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


_classes = (RWChannel, RWIngredient, RWWater, RWDamage, RWDecal, RWLayer, RW_MaterialProps, RW_ObjectProps,
            RW_SceneProps, RW_Preferences)


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

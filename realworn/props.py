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
DETAIL_MODE_ITEMS = [
    ("ERODE", "Erode", "Push the mask down where the detail is dark, then sharpen (default)"),
    ("BURN", "Burn", "Color Burn the mask against the detail (Blender Guru look)"),
    ("HEIGHT", "Height Compare", "The stroke is a water level against the detail as terrain: fills low spots first")]
DETAIL_SOURCE_ITEMS = [
    ("LAYER_GRUNGE", "Layer Grunge", "The grunge image below, box-projected in object space"),
    ("BASE_HEIGHT", "Base Height", "The base material's height map (falls back to the grunge without one)"),
    ("BASE_AO", "Base AO", "The base material's ambient occlusion map: dark crevices of the texture"),
    ("CONTENT_HEIGHT", "Content Height", "This layer's own PBR set height map"),
    ("GRUNGE2", "Second Grunge", "The second grunge image only (a different breakup from the stroke grunge)")]
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


def _mat_v(prop):
    """VALUE update for a material-level property (base height normalisation)."""
    def update(self, context):
        from .core import compiler
        compiler.on_material_value(self.id_data, prop)
    return update


def _active_layer(self, context):
    from .core import compiler
    compiler.on_active_layer(self)


def _damage_inner(self, context):
    """DMG-1: the inner material choice sets the Damage layer's channels to its look."""
    from .core import compiler, damage
    mat = self.id_data
    layer = mat.path_resolve(self.path_from_id().rsplit(".", 1)[0])
    with compiler.batch(mat):
        damage.set_inner(layer)
    compiler.on_struct(self)


def _ground(self, context):
    from .core import masks
    masks.mark_ground(self.id_data, self.is_ground, sync_prop=False)


def _grunge_look(self, context):
    from .core import grunge
    ts = context.tool_settings if context else None
    if ts is not None and ts.image_paint is not None:
        grunge.set_texture_look(ts.image_paint.brush, self.grunge_contrast, self.grunge_invert)


def _decal_items(self, context):
    from .core import decals
    return decals.library_enum_items()


def _content_items(self, context):
    from .core import pbrset
    p = prefs()
    kind = "ALL"
    ob = context.active_object if context else None
    mat = ob.active_material if ob is not None and ob.type == "MESH" else None
    if mat is not None and mat.realworn.layers and 0 <= mat.realworn.active_layer_index < len(mat.realworn.layers):
        kind = mat.realworn.layers[mat.realworn.active_layer_index].type
    return pbrset.library_enum_items(p.content_folder if p is not None else "", kind)


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
    invert: BoolProperty(name="Invert", default=False, update=_struct,
                         description="Use 1 - image (a glossiness map as roughness); set when loading a PBR set")


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
    inner: EnumProperty(name="Inner Material", items=INNER_ITEMS, default="CONCRETE", update=_damage_inner)
    depth_mm: FloatProperty(name="Depth (mm)", default=3.0, min=0.0, soft_max=30.0, update=_v("depth_mm"))
    rim_height: FloatProperty(name="Rim Height (mm)", default=0.6, min=0.0, soft_max=5.0, update=_v("rim_height"))
    rim_width: FloatProperty(name="Rim Width", default=0.25, min=0.01, max=1.0, update=_v("rim_width"))
    rim_brightness: FloatProperty(name="Rim Brightness", default=0.35, min=0.0, max=1.0, update=_v("rim_brightness"))
    sharpness: FloatProperty(name="Edge Sharpness", default=0.8, min=0.0, max=1.0, update=_v("sharpness"))
    reveal: FloatProperty(name="Reveal", default=0.6, min=0.0, max=1.0, update=_v("reveal"),
                          description="How much of a dent breaks through to the inner material")
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


class RWDetail(bpy.types.PropertyGroup):
    """Edge Detail (PRD v2.1 EDG-1..EDG-7). Strength 0 is off: the stage has no nodes at all."""
    mode: EnumProperty(name="Mode", items=DETAIL_MODE_ITEMS, default="ERODE", update=_struct)
    source: EnumProperty(name="Source", items=DETAIL_SOURCE_ITEMS, default="LAYER_GRUNGE", update=_struct)
    strength: FloatProperty(name="Strength", default=0.0, min=0.0, max=1.0, update=_v("strength"),
                            description="How much the detail decides the edge (0: off, no nodes)")
    width: FloatProperty(name="Edge Width", default=0.05, min=0.01, max=0.5, update=_v("width"),
                         description="Softness of the final edge: small is hard")
    threshold: FloatProperty(name="Threshold", default=0.5, min=0.0, max=1.0, update=_v("threshold"),
                             description="Shifts the boundary in or out")
    contrast: FloatProperty(name="Detail Contrast", default=0.0, min=-1.0, max=1.0, update=_v("contrast"))
    invert: BoolProperty(name="Invert Detail", default=False, update=_v("invert"))
    protect: BoolProperty(name="Protect Interior", default=True, update=_v("protect"),
                          description="Keep the solid middle of a stroke whole; only its boundary breaks up")
    image: PointerProperty(name="Grunge", type=bpy.types.Image, update=_struct,
                           description="Layer Grunge source (and the fallback when the base has no height)")
    scale: FloatProperty(name="Scale", default=0.25, min=0.001, soft_max=10.0, subtype="DISTANCE",
                         update=_v("scale"), description="Grunge tile size in metres")
    rotation: FloatProperty(name="Rotation", default=0.0, subtype="ANGLE", update=_v("rotation"))
    offset: FloatProperty(name="Offset", default=0.0, update=_v("offset"))
    cubic: BoolProperty(name="Cubic", default=False, update=_struct,
                        description="Cubic interpolation: magnified grunge stays smooth in extreme close-ups")
    image2: PointerProperty(name="Second Grunge", type=bpy.types.Image, update=_struct,
                            description="A second breakup mixed into any source (two scales of breakup)")
    scale2: FloatProperty(name="Scale 2", default=0.08, min=0.001, soft_max=10.0, subtype="DISTANCE",
                          update=_v("scale2"))
    mix2: FloatProperty(name="Mix", default=0.0, min=0.0, max=1.0, update=_v("mix2"),
                        description="How much the second grunge varies the detail (0: off, no nodes)")
    anti_tile: BoolProperty(name="Anti-Tiling", default=False, update=_struct,
                            description="Random rotation and offset per cell so a small grunge does not visibly repeat")


class RWLook(bpy.types.PropertyGroup):
    """Content look (PRD v2.1 CNT-1..CNT-4): textured colour, roughness and micro relief for the
    layer type, on top of the layer's Color and Roughness values."""
    enabled: BoolProperty(name="Textured Look", default=False, update=_struct,
                          description="Vary colour, roughness and micro relief like the real material")
    color_var: FloatProperty(name="Color Variation", default=0.4, min=0.0, max=1.0, update=_v("color_var"))
    rough_var: FloatProperty(name="Roughness Variation", default=0.4, min=0.0, max=1.0, update=_v("rough_var"))
    micro: FloatProperty(name="Micro Normal", default=0.5, min=0.0, max=4.0, update=_v("micro"),
                         description="Micro relief strength (grit, pitting, brushing), through the shared bump")
    scale: FloatProperty(name="Detail Scale", default=0.3, min=0.001, soft_max=10.0, subtype="DISTANCE",
                         update=_v("scale"), description="Size of the look's variation in metres")


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
    normal_image: PointerProperty(name="Normal Map", type=bpy.types.Image, update=_struct,
                                  description="PBR Set normal map (OpenGL); used when the layer maps by UV")
    normal_strength: FloatProperty(name="Normal Strength", default=1.0, min=0.0, max=4.0,
                                   update=_v("normal_strength"))
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
    detail: PointerProperty(type=RWDetail)
    look: PointerProperty(type=RWLook)
    ao_image: PointerProperty(name="AO", type=bpy.types.Image, update=_struct,
                              description="PBR Set ambient occlusion: darkens the layer's colour in crevices")
    normal_dx: BoolProperty(name="DirectX Normal", default=False, update=_struct,
                            description="The normal map is DirectX (green flipped); detected when loading a PBR set")


class RW_MaterialProps(bpy.types.PropertyGroup):
    applied: BoolProperty(name="Set Up", default=False)
    snapshot: StringProperty(name="Snapshot", default="")
    schema_version: IntProperty(name="Schema", default=0)
    mode: StringProperty(name="Mode", default="", description="CHANNEL or SHADER")
    stack: PointerProperty(name="Stack", type=bpy.types.NodeTree)
    layers: CollectionProperty(type=RWLayer)
    active_layer_index: IntProperty(name="Layer", default=0, update=_active_layer)
    source_material: StringProperty(name="Source Material", default="",
                                    description="Material this one was duplicated from by Setup (SET-3)")
    owner: StringProperty(name="Object", default="")
    mask_view: BoolProperty(name="Mask View", default=False, update=_struct,
                            description="Show the active layer's final mask as greyscale")
    view_channel: EnumProperty(name="View", items=[("MASK", "Mask", ""), ("COLOR", "Colour", "")], default="MASK",
                               update=_struct, description="Internal: Mask View shows the mask or the layer colour")
    baked: BoolProperty(name="Baked", default=False)
    # v2.1
    v21: BoolProperty(name="v2.1 Defaults", default=False,
                      description="New layers get the v2.1 Edge Detail defaults (set by Setup or Apply v2.1 Defaults)")
    base_ao_kind: StringProperty(name="Base AO", default="", description="IMAGE or NONE (captured)")
    base_ao_image: StringProperty(name="Base AO Image", default="")
    base_ao_lo: FloatProperty(name="AO Low", default=0.0, update=_mat_v("base_ao_lo"))
    base_ao_hi: FloatProperty(name="AO High", default=1.0, update=_mat_v("base_ao_hi"))
    base_height_kind: StringProperty(name="Base Height", default="",
                                     description="IMAGE, SOCKET or NONE: what the base's height is (captured)")
    base_height_image: StringProperty(name="Base Height Image", default="")
    base_height_lo: FloatProperty(name="Height Low", default=0.0, update=_mat_v("base_height_lo"),
                                  description="Base height that maps to 0 (2nd percentile at capture)")
    base_height_hi: FloatProperty(name="Height High", default=1.0, update=_mat_v("base_height_hi"),
                                  description="Base height that maps to 1 (98th percentile at capture)")
    detail_split: BoolProperty(name="Before / After", default=False, update=_struct,
                               description="Mask View shows the mask before (left half of the view) and after (right half) Edge Detail")


class RW_ObjectProps(bpy.types.PropertyGroup):
    is_ground: BoolProperty(name="Ground", default=False, update=_ground,
                            description="Contact generators measure distance to ground objects")
    hero: BoolProperty(name="Hero", default=False,
                       description="Hero object: masks at 4096 px per metre (2048..8192 px) for extreme close-ups; "
                                   "Upgrade Masks resamples existing paint")


class RW_SceneProps(bpy.types.PropertyGroup):
    add_type: EnumProperty(name="Layer Type", items=TYPE_ITEMS, default="DIRT")
    layer_tab: EnumProperty(name="Tab", items=[("CONTENT", "Content", "", "MATERIAL", 0),
                                               ("MASK", "Mask", "", "MOD_MASK", 1),
                                               ("BRUSH", "Brush", "", "BRUSH_DATA", 2)], default="CONTENT")
    use_existing_uv: BoolProperty(name="Use Existing UV", default=False,
                                  description="Copy the object's UV map into RW_Paint instead of Smart UV Project")
    grunge_image: EnumProperty(name="Grunge", items=_grunge_items)
    grunge_mode: EnumProperty(name="Mode", items=GRUNGE_MODE_ITEMS, default="STAMP")
    grunge_contrast: FloatProperty(name="Contrast", default=1.0, min=0.0, max=5.0, update=_grunge_look,
                                   description="Grunge contrast (brush texture, or the Fill ingredient)")
    grunge_invert: BoolProperty(name="Invert", default=False, update=_grunge_look)
    decal_image: EnumProperty(name="Decal", items=_decal_items, description="Decal image from the library")
    content_set: EnumProperty(name="PBR Set", items=_content_items,
                              description="PBR sets in the content library that suit this layer type")
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
    texel_density: IntProperty(name="Texel Density", default=2048, min=64, max=8192,
                               description="Mask pixels per metre of the object's largest dimension")
    grunge_folder: StringProperty(name="Grunge Folder", subtype="DIR_PATH", default="",
                                  description="Extra folder of black and white grunge images")
    decal_folder: StringProperty(name="Decal Library Folder", subtype="DIR_PATH", default="",
                                 description="Extra folder of decal images (name.png, optional name_nrm.png)")
    content_folder: StringProperty(name="Content Library Folder", subtype="DIR_PATH", default="",
                                   description="Folder of PBR sets (ambientCG or Poly Haven downloads work as they are; "
                                               "optional category folders: Dirt, Rust, Metal, Concrete...)")
    developer_mode: BoolProperty(name="Developer Mode", default=False,
                                 description="Show Reload Add-on and Rebuild Assets in the Debug panel")

    def draw(self, context):
        col = self.layout.column()
        for p in ("mask_storage", "texel_density", "grunge_folder", "decal_folder", "content_folder", "developer_mode"):
            col.prop(self, p)


def prefs():
    """Add-on preferences, or None when running unregistered as an add-on (tests)."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


_classes = (RWChannel, RWIngredient, RWWater, RWDamage, RWDecal, RWDetail, RWLook, RWLayer, RW_MaterialProps, RW_ObjectProps,
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

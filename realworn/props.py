"""PropertyGroups for scene, object and material state, plus add-on preferences.

Scene and object values are mirrored into custom properties (rw_*) by update callbacks;
shaders read those through Attribute nodes, so no drivers are needed.
"""

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)

PRESET_ITEMS = [
    ("AUTO", "Auto", "Pick a preset from the material's metallic and roughness"),
    ("painted_metal", "Painted Metal", "Crisp chips revealing primer then bare steel, rusts"),
    ("bare_metal", "Bare Metal", "Edges polish instead of chipping, rusts"),
    ("concrete", "Concrete", "Soft broad wear, porous, strong darkening when wet"),
    ("wood", "Wood", "Edges lighten and roughen to raw wood"),
    ("plastic", "Plastic", "Edge scuffs whiten and roughen"),
]
PREVIEW_ITEMS = [
    ("NONE", "None", "Normal shading"),
    ("EDGE", "Edge", "rw_edge convex edge mask"),
    ("CAVITY", "Cavity", "rw_cavity concave mask"),
    ("CONTACT", "Contact", "rw_contact ground contact mask"),
    ("SHELTER", "Shelter", "rw_shelter: covered by an occluder"),
    ("PUDDLE", "Puddle", "Final puddle mask"),
    ("WETNESS", "Wetness", "Effective wetness w"),
    ("DUST", "Dust", "Final dust mask"),
    ("GRIME", "Grime", "Contact and splash grime mask"),
    ("STREAK", "Streak", "Vertical streak mask"),
]
EDGE_SOURCE_ITEMS = [
    ("ATTRIBUTE", "Attribute", "rw_edge from the RW_Masks modifier (Cycles and EEVEE)"),
    ("BEVEL", "Bevel Node", "Shader Bevel node, Cycles only; EEVEE falls back to Attribute"),
    ("MAX", "Max of Both", "Maximum of the attribute and the Bevel node (Bevel part Cycles only)"),
]
CAVITY_SOURCE_ITEMS = [
    ("ATTRIBUTE", "Attribute", "rw_cavity from the RW_Masks modifier"),
    ("RAYCAST", "Raycast", "Live shader Raycast cavity (Cycles and EEVEE, slower)"),
    ("MAX", "Max of Both", "Maximum of the attribute and the Raycast cavity"),
]
DECAL_MODE_ITEMS = [
    ("FULL", "Full", "Color with alpha, roughness, optional normal map"),
    ("GRIME", "Grime", "Only darkens and changes roughness (stains, soot, leaks)"),
    ("DAMAGE", "Damage", "Forces the edge-wear reveal inside the decal and adds height"),
]
RES_ITEMS = [(str(r), str(r), "") for r in (256, 512, 1024, 2048, 4096)]


def _sync_scene(self, context):
    from .core import weather
    weather.sync_scene(self.id_data)


def _sync_ground_z(self, context):
    from .core import weather
    weather.update_ground_z(self.id_data)
    weather.sync_scene(self.id_data)


def _set_preview(self, context):
    from .core import preview
    preview.set_preview(self.id_data, self.mask_preview)


def _sync_object(self, context):
    from .core import weather
    weather.sync_object(self.id_data)


def _sync_sources(self, context):
    from .core import injector
    injector.update_sources(self.id_data, context.scene if context else None)


def _decal_items(self, context):
    from .core import decals
    return decals.library_enum_items()


class RW_SceneProps(bpy.types.PropertyGroup):
    age: FloatProperty(name="Age", min=0.0, max=1.0, default=0.4, update=_sync_scene,
                       description="Edge wear spread and rust amount for every weathered material")
    dirt: FloatProperty(name="Dirt", min=0.0, max=1.0, default=0.4, update=_sync_scene,
                        description="Cavity dirt, contact and splash grime")
    dust: FloatProperty(name="Dust", min=0.0, max=1.0, default=0.2, update=_sync_scene,
                        description="Dust on upward-facing surfaces (none where wet)")
    wetness: FloatProperty(name="Wetness", min=0.0, max=1.0, default=0.0, update=_sync_scene,
                           description="0 dry, 0.35 damp, 0.7 wet, above 0.6 puddles form on ground objects")
    rain: BoolProperty(name="Rain", default=False, update=_sync_scene,
                       description="Animated ripples in puddles, droplets and active streaks")
    splash_height: FloatProperty(name="Splash Height", min=0.0, max=3.0, default=0.4, subtype="DISTANCE",
                                 update=_sync_scene, description="Height of splash grime and moisture climb")
    ground_z_auto: BoolProperty(name="Auto Ground Z", default=True, update=_sync_ground_z,
                                description="Use the lowest ground object's minimum Z")
    ground_z: FloatProperty(name="Ground Z", default=0.0, subtype="DISTANCE", update=_sync_scene,
                            description="Reference height for splash grime and moisture climb")
    preset: EnumProperty(name="Preset", items=PRESET_ITEMS, default="AUTO",
                         description="Preset used by Apply")
    mask_preview: EnumProperty(name="Mask Preview", items=PREVIEW_ITEMS, default="NONE", update=_set_preview,
                               description="Show one mask as greyscale on every weathered object")
    # Decals
    decal_image: EnumProperty(name="Decal", items=_decal_items, description="Decal image from the library")
    decal_mode: EnumProperty(name="Mode", items=DECAL_MODE_ITEMS, default="FULL")
    decal_size: FloatProperty(name="Size", min=0.01, max=20.0, default=0.6, subtype="DISTANCE")
    leak_seed: IntProperty(name="Seed", default=0, min=0)
    # Damage defaults for Add Damage
    dmg_strength: FloatProperty(name="Strength", min=0.0, max=1.0, default=0.5)
    dmg_seed: IntProperty(name="Seed", default=0, min=0)
    dmg_size_min: FloatProperty(name="Size Min", min=0.001, max=2.0, default=0.03, subtype="DISTANCE")
    dmg_size_max: FloatProperty(name="Size Max", min=0.001, max=2.0, default=0.08, subtype="DISTANCE")
    dmg_density: FloatProperty(name="Density", min=0.0, max=100.0, default=6.0, description="Chips per metre of edge")
    dmg_corners: BoolProperty(name="Corners", default=True)
    dmg_debris: BoolProperty(name="Debris", default=False)
    # Bake
    bake_resolution: EnumProperty(name="Resolution", items=RES_ITEMS, default="1024")
    bake_folder: StringProperty(name="Folder", default="//rw_bake/", subtype="DIR_PATH")
    bake_masks: BoolProperty(name="Masks", default=True, description="Also bake rw_edge, rw_cavity and friends")


class RW_ObjectProps(bpy.types.PropertyGroup):
    applied: BoolProperty(name="Applied", default=False)
    preset: StringProperty(name="Preset", default="")
    wear: FloatProperty(name="Wear", min=0.0, max=3.0, default=1.0, update=_sync_object,
                        description="Multiplies edge wear for this object only")
    dirt: FloatProperty(name="Dirt", min=0.0, max=3.0, default=1.0, update=_sync_object,
                        description="Multiplies dirt and grime for this object only")
    seed: FloatProperty(name="Seed", default=0.0, update=_sync_object,
                        description="Offsets every breakup noise so duplicates wear differently")
    edge_source: EnumProperty(name="Edge Source", items=EDGE_SOURCE_ITEMS, default="ATTRIBUTE", update=_sync_sources)
    cavity_source: EnumProperty(name="Cavity Source", items=CAVITY_SOURCE_ITEMS, default="ATTRIBUTE",
                                update=_sync_sources)
    is_ground: BoolProperty(name="Ground", default=False)
    is_occluder: BoolProperty(name="Occluder", default=False)


class RW_MaterialProps(bpy.types.PropertyGroup):
    applied: BoolProperty(name="Applied", default=False)
    preset: StringProperty(name="Preset", default="")
    snapshot: StringProperty(name="Snapshot", default="")
    schema_version: IntProperty(name="Schema", default=0)
    mode: StringProperty(name="Mode", default="", description="CHANNEL or SHADER")
    baked: BoolProperty(name="Baked", default=False)
    decals: StringProperty(name="Decals", default="[]", description="JSON list of decal empty names")


class RW_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    decal_folder: StringProperty(name="Decal Library Folder", subtype="DIR_PATH", default="",
                                 description="Extra folder of decal images (name.png, optional name_nrm.png)")
    default_preset: EnumProperty(name="Default Preset", items=PRESET_ITEMS, default="AUTO")
    developer_mode: BoolProperty(name="Developer Mode", default=False,
                                 description="Show Reload Add-on and Rebuild Assets in the Debug panel")
    log_level: EnumProperty(name="Log Level", items=[("INFO", "Info", ""), ("DEBUG", "Debug", "")], default="INFO")

    def draw(self, context):
        col = self.layout.column()
        for p in ("decal_folder", "default_preset", "developer_mode", "log_level"):
            col.prop(self, p)


def prefs():
    """Add-on preferences, or None when running unregistered as an add-on (tests)."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


_classes = (RW_SceneProps, RW_ObjectProps, RW_MaterialProps, RW_Preferences)


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

"""Names, prefixes and schema versions shared by every RealWorn module.

Nothing else in the code base hardcodes an attribute, property or group name.
"""

SCHEMA = 1
LOG_PREFIX = "[RealWorn]"

# Mesh attributes (point domain floats unless noted).
ATTR_EDGE = "rw_edge"
ATTR_CAVITY = "rw_cavity"
ATTR_CONTACT = "rw_contact"
ATTR_SHELTER = "rw_shelter"
ATTR_DAMAGE = "rw_damage"
ATTR_PAINT = "rw_paint"          # corner-domain byte color, painted by the user
ATTR_CUT = "rw_cut"              # internal: cutter faces inside RW_Damage
ATTR_CORNER = "rw_corner"        # internal: corner cutter points inside RW_Damage
MASK_ATTRS = (ATTR_EDGE, ATTR_CAVITY, ATTR_CONTACT, ATTR_SHELTER)

# Scene custom properties, read by shaders through Attribute (View Layer).
SC_AGE = "rw_age"
SC_DIRT = "rw_dirt"
SC_DUST = "rw_dust"
SC_WETNESS = "rw_wetness"
SC_RAIN = "rw_rain"
SC_GROUND_Z = "rw_ground_z"
SC_SPLASH = "rw_splash_height"
SC_PREVIEW = "rw_preview"
SCENE_PROPS = (SC_AGE, SC_DIRT, SC_DUST, SC_WETNESS, SC_RAIN, SC_GROUND_Z, SC_SPLASH, SC_PREVIEW)

# Object custom properties, read by shaders through Attribute (Object).
OB_SEED = "rw_seed"
OB_WEAR = "rw_wear"
OB_DIRT = "rw_dirt_amt"
OB_GROUND = "rw_is_ground"
OBJECT_PROPS = (OB_SEED, OB_WEAR, OB_DIRT, OB_GROUND)

# Mask preview codes (scene property rw_preview).
PREVIEW_CODES = {
    "NONE": 0, "EDGE": 1, "CAVITY": 2, "CONTACT": 3, "SHELTER": 4, "PUDDLE": 5, "WETNESS": 6,
    "DUST": 7, "GRIME": 8, "STREAK": 9,
}

# Node groups.
GN_MASKS = "RW_Masks"
GN_DAMAGE = "RW_Damage"
SH_STACK = "RW_Stack"
SH_BREAKUP = "RW_Breakup"
SH_SHADING_MASKS = "RW_ShadingMasks"
SH_L_EDGE = "RW_L_EdgeWear"
SH_L_RUST = "RW_L_Rust"
SH_L_DECALS = "RW_L_DecalApply"
SH_L_CAVITY = "RW_L_CavityDirt"
SH_L_GRIME = "RW_L_Grime"
SH_L_DUST = "RW_L_Dust"
SH_L_WET = "RW_L_Wetness"
SH_L_WET_DRY = "RW_L_WetnessDry"
SH_L_WET_RAIN = "RW_L_WetnessRain"
SH_DECAL = "RW_L_Decal"
SH_DECAL_PROJECT = "RW_DecalProject"
SH_BEVEL_EDGE = "RW_BevelEdge"
SH_RAY_CAVITY = "RW_RayCavity"
ALL_GROUPS = (
    GN_MASKS, GN_DAMAGE, SH_BREAKUP, SH_SHADING_MASKS, SH_L_EDGE, SH_L_RUST, SH_L_DECALS,
    SH_L_CAVITY, SH_L_GRIME, SH_L_DUST, SH_L_WET, SH_L_WET_DRY, SH_L_WET_RAIN, SH_STACK, SH_DECAL, SH_DECAL_PROJECT,
    SH_BEVEL_EDGE, SH_RAY_CAVITY,
)

# Modifiers.
MOD_MASKS = "RW_Masks"
MOD_DAMAGE = "RW_Damage"

# Collections.
COLL_GROUND = "RW_Ground"
COLL_OCCLUDERS = "RW_Occluders"
COLL_DECALS = "RW_Decals"

# Nodes inserted into user materials.
NODE_PREFIX = "RW::"
STACK_WET_NODE = "wetness"  # node name of the wetness group inside RW_Stack
OWNED_PROP = "rw_owned"
FRAME_LABEL = "RealWorn"
DECAL_PREFIX = "RW_Decal_"
INNER_PREFIX = "RW_Inner_"
MAX_DECALS_PER_MATERIAL = 16

# Shader channels moved through RW_Stack (Principled input names, 5.x).
CHANNELS = (
    "Base Color", "Metallic", "Roughness", "Normal",
    "Coat Weight", "Coat Roughness", "Coat IOR", "Coat Normal",
)
NORMAL_CHANNELS = ("Normal", "Coat Normal")


def node_name(role):
    """Node name for an inserted node with the given role, e.g. ``RW::stack.0``."""
    return NODE_PREFIX + role


def is_rw_name(name):
    return name.startswith(NODE_PREFIX)


def decal_name(image_name):
    stem = image_name.rsplit(".", 1)[0]
    return DECAL_PREFIX + stem


def inner_material_name(preset_id):
    return INNER_PREFIX + preset_id

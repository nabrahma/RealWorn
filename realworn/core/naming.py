"""Names, prefixes and schema versions shared by every RealWorn module.

Nothing else in the code base hardcodes an attribute, property, image or group name.
"""

SCHEMA = 2  # v2: layer stack (material.realworn.layers); v0.7 files used 1
LOG_PREFIX = "[RealWorn]"

# Mesh attributes written by RW_Masks / RW_Damage (point-domain floats unless noted).
ATTR_EDGE = "rw_edge"
ATTR_CAVITY = "rw_cavity"
ATTR_CONTACT = "rw_contact"
ATTR_DAMAGE = "rw_damage"
ATTR_CUT = "rw_cut"              # internal: cutter faces inside RW_Damage
ATTR_CORNER = "rw_corner"        # internal: corner cutter points inside RW_Damage
ATTR_VMASK = "rw_vmask_"         # + layer id: corner byte colour, vertex-colour mask fallback (PNT-11)
MASK_ATTRS = (ATTR_EDGE, ATTR_CAVITY, ATTR_CONTACT)

# The paint UV map (SET-4): every mask is sampled through it, never through the user's UVs.
UV_PAINT = "RW_Paint"

# Object custom properties.
OB_GROUND = "rw_is_ground"
OB_SETUP = "rw_setup"            # JSON: original slots, UV state (written by Setup, read by Remove)

# Node groups built by builders/ (shared, appended from assets/realworn_nodes.blend).
GN_MASKS = "RW_Masks"
GN_DAMAGE = "RW_Damage"
SH_LEVELS = "RW_P_Levels"
SH_PAINT_OVER = "RW_P_PaintOver"
SH_EDGE_LOCK = "RW_P_EdgeLock"
SH_HEIGHT_BLEND = "RW_P_HeightBlend"
SH_UP = "RW_P_Up"
SH_CONTRAST = "RW_P_Contrast"
SH_WATER = "RW_P_Water"
SH_DAMAGE = "RW_P_Damage"
SH_DECAL_PROJECT = "RW_DecalProject"
SH_VARIATION = "RW_P_Variation"
ALL_GROUPS = (GN_MASKS, GN_DAMAGE, SH_PAINT_OVER, SH_EDGE_LOCK, SH_HEIGHT_BLEND, SH_LEVELS, SH_UP, SH_CONTRAST,
              SH_VARIATION, SH_WATER, SH_DECAL_PROJECT)

# Per-material stack group (CMP-1): only core/compiler.py edits its contents.
STACK_PREFIX = "RW_Stack::"

# Modifiers.
MOD_MASKS = "RW_Masks"
MOD_DAMAGE = "RW_Damage"
MOD_DISP_SUBDIV = "RW_DisplaceSubdiv"

# Collections.
COLL_GROUND = "RW_Ground"
COLL_DECALS = "RW_Decals"

# Nodes inserted into user materials (top level) and inside stack groups.
NODE_PREFIX = "RW::"
OWNED_PROP = "rw_owned"
FRAME_LABEL = "RealWorn"
DECAL_PREFIX = "RW_Decal_"
INNER_PREFIX = "RW_Inner_"
UNIQUE_SUFFIX = ".RW"            # SET-3: material duplicated for one object
DEFAULT_MATERIAL = "RW_Default"  # SET-1: given to empty slots
MAX_DECALS_PER_MATERIAL = 16

# Image tags (custom properties on images RealWorn creates).
IMG_MASK = "rw_mask"             # value: "<object>/<layer id>"
IMG_CONTENT = "rw_content"

# Stack group interface (SET-6). Inputs come from the captured base; outputs feed Principled.
STACK_INPUTS = (
    ("Base Color", "COLOR", (0.8, 0.8, 0.8, 1.0)),
    ("Roughness", "FLOAT", 0.5),
    ("Metallic", "FLOAT", 0.0),
    ("Normal", "VECTOR", None),
    ("Height", "FLOAT", 0.5),
    ("Coat Weight", "FLOAT", 0.0),
    ("Coat Roughness", "FLOAT", 0.03),
    ("Coat IOR", "FLOAT", 1.5),
    ("Coat Normal", "VECTOR", None),
)
STACK_OUTPUTS = (
    ("Base Color", "COLOR"), ("Roughness", "FLOAT"), ("Metallic", "FLOAT"), ("Normal", "VECTOR"),
    ("Coat Weight", "FLOAT"), ("Coat Roughness", "FLOAT"), ("Coat IOR", "FLOAT"), ("Coat Normal", "VECTOR"),
    ("Displacement", "FLOAT"), ("Coverage", "FLOAT"), ("Mask View", "FLOAT"),
)
# Principled inputs routed through the stack.
CHANNELS = ("Base Color", "Roughness", "Metallic", "Normal", "Coat Weight", "Coat Roughness", "Coat IOR",
            "Coat Normal")
NORMAL_CHANNELS = ("Normal", "Coat Normal")


def node_name(role):
    """Top-level node name for an inserted node with the given role, e.g. ``RW::stack.0``."""
    return NODE_PREFIX + role


def layer_node(layer_id, role):
    """Node name inside a stack group: ``RW::<layer_id>::<role>`` (CMP-3)."""
    return "{}{}::{}".format(NODE_PREFIX, layer_id, role)


def is_rw_name(name):
    return name.startswith(NODE_PREFIX)


def stack_group_name(material_name):
    return STACK_PREFIX + material_name


def mask_image_name(object_name, layer_name):
    return "RW_{}_{}_mask".format(object_name, layer_name)


def content_image_name(object_name, layer_name):
    return "RW_{}_{}_content".format(object_name, layer_name)


def unique_material_name(name):
    return name + UNIQUE_SUFFIX


def decal_name(image_name):
    stem = image_name.rsplit(".", 1)[0]
    return DECAL_PREFIX + stem


def inner_material_name(kind):
    return INNER_PREFIX + kind

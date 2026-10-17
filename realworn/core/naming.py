"""Names, prefixes and schema versions shared by every RealWorn module.

Nothing else in the code base hardcodes an attribute, property, image or node name.
"""

SCHEMA = 3  # v3: the layer kinds of core/kinds.py (material.realworn.layers); v2.x files used 2, v0.7 files 1
LOG_PREFIX = "[RealWorn]"

# The paint UV map: every painted mask is sampled through it, never through the user's UVs.
UV_PAINT = "RW_Paint"

# Object custom properties.
OB_SETUP = "rw_setup"            # JSON: original slots, UV state (written by Setup, read by Remove)

# Per-material stack group: only core/compiler.py edits its contents.
STACK_PREFIX = "RW_Stack::"

# Modifiers.
MOD_SUBDIV = "RW_TrueDepth"      # REV-5: adaptive Simple subdivision for True depth

# Nodes inserted into user materials (top level) and inside stack groups.
NODE_PREFIX = "RW::"
OWNED_PROP = "rw_owned"
FRAME_LABEL = "RealWorn"
UNIQUE_SUFFIX = ".RW"            # SET-6: material duplicated for one object
DEFAULT_PREFIX = "RW_"           # SET-1: RW_<object>, given to objects without a material

# Image tags (custom properties on images RealWorn creates).
IMG_MASK = "rw_mask"             # value: "<object>/<layer id>"
IMG_BAKED_SOURCE = "rw_baked_source"  # ENG-2: baked Edge Wear / Dirt source

# Stack group interface. Inputs come from the wrapped base; outputs feed the Principled BSDF and,
# for Displacement, an owned Displacement node on the Material Output (metres).
STACK_INPUTS = (
    ("Base Color", "COLOR", (0.8, 0.8, 0.8, 1.0)),
    ("Roughness", "FLOAT", 0.5),
    ("Metallic", "FLOAT", 0.0),
    ("Normal", "VECTOR", None),
)
STACK_OUTPUTS = (
    ("Base Color", "COLOR"), ("Roughness", "FLOAT"), ("Metallic", "FLOAT"), ("Normal", "VECTOR"),
    ("Displacement", "FLOAT"), ("Coverage", "FLOAT"), ("Mask View", "FLOAT"), ("Mask Color", "COLOR"),
)
# Principled inputs routed through the stack.
CHANNELS = ("Base Color", "Roughness", "Metallic", "Normal")
NORMAL_CHANNELS = ("Normal", "Coat Normal")
# Routed through the stack only while the material has a Puddle layer (the water is a clear coat);
# otherwise the material's tree is exactly as without RealWorn's puddles.
COAT_INPUTS = (
    ("Coat Weight", "FLOAT", 0.0),
    ("Coat Roughness", "FLOAT", 0.03),
    ("Coat IOR", "FLOAT", 1.5),
    ("Coat Normal", "VECTOR", None),
    ("Thin Film Thickness", "FLOAT", 0.0),
)
COAT_CHANNELS = tuple(name for name, _, _ in COAT_INPUTS)


def node_name(role):
    """Top-level node name for an inserted node with the given role, e.g. ``RW::stack.0``."""
    return NODE_PREFIX + role


def layer_node(layer_id, role):
    """Node name inside a stack group: ``RW::<layer_id>::<role>``."""
    return "{}{}::{}".format(NODE_PREFIX, layer_id, role)


def is_rw_name(name):
    return name.startswith(NODE_PREFIX)


def stack_group_name(material_name):
    return STACK_PREFIX + material_name


def mask_image_name(object_name, layer_name, kind="mask"):
    return "RW_{}_{}_{}".format(object_name, layer_name, kind)


def unique_material_name(name):
    return name + UNIQUE_SUFFIX


def default_material_name(object_name):
    return DEFAULT_PREFIX + object_name

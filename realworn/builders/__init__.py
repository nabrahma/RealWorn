"""Builders: Python that creates every RealWorn node group (source of truth).

Order matters: a group is built after the groups it instances.
"""

from . import gn_damage, gn_masks, sh_damage, sh_decal, sh_edge_detail, sh_layer_parts, sh_water

BUILDERS = (gn_masks, gn_damage, sh_layer_parts, sh_edge_detail, sh_water, sh_damage, sh_decal)


def build_all():
    """Build every node group into bpy.data and return them."""
    groups = []
    for b in BUILDERS:
        built = b.build()
        groups.extend(built if isinstance(built, list) else [built])
    return groups

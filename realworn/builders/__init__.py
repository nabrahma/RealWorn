"""Builders: Python that creates every RealWorn node group (source of truth).

Order matters: a group is built after the groups it instances.
"""

from . import gn_masks

BUILDERS = (gn_masks,)


def build_all():
    """Build every node group into bpy.data and return them."""
    groups = []
    for b in BUILDERS:
        groups.extend(b.build())
    return groups

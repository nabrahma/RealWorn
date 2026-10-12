"""Builders: Python that creates every RealWorn node group (source of truth)."""

BUILDERS = ()


def build_all():
    """Build every node group into bpy.data and return them."""
    groups = []
    for b in BUILDERS:
        groups.extend(b.build())
    return groups

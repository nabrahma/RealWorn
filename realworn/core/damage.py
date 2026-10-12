"""Geometry damage (M6). Placeholder until M6: only removal is needed by Remove."""

from . import naming


def remove_damage(obj):
    mod = obj.modifiers.get(naming.MOD_DAMAGE)
    if mod is not None:
        obj.modifiers.remove(mod)
        return True
    return False

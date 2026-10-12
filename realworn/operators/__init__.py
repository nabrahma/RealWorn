"""Operators: thin wrappers that validate context and call core."""

from . import apply, bake, damage, debug, decals, ground, paint

_modules = (apply, bake, damage, debug, decals, ground, paint)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()

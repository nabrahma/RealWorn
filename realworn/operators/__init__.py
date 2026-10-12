"""Operators: thin wrappers that validate context and call core."""

from . import bake, content, debug, decals, ground, grunge, paint, setup

_modules = (setup, paint, grunge, content, decals, bake, ground, debug)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()

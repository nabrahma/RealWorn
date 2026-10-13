"""Operators: thin wrappers that validate context and call core."""

from . import bake, debug, library, paint, setup, textures

_modules = (setup, paint, textures, library, bake, debug)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()

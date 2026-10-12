"""Operators: thin wrappers that validate context and call core."""

from . import debug, ground, paint, setup

_modules = (setup, paint, ground, debug)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()

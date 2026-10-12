"""Operators: thin wrappers that validate context and call core."""

from . import apply, debug, paint

_modules = (apply, debug, paint)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()

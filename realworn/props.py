"""PropertyGroups for scene, object and material state, plus add-on preferences."""

import bpy

_classes = ()


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

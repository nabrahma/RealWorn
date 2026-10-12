"""Shared operator helpers: every operator also works headless with explicit object names."""

import bpy

OBJECTS_DESC = "Comma-separated object names; empty uses the selection"


def target_objects(context, names, meshes_only=True):
    if names:
        obs = [bpy.data.objects.get(n.strip()) for n in names.split(",") if n.strip()]
        obs = [o for o in obs if o is not None]
    else:
        obs = list(context.selected_objects) if context.selected_objects else (
            [context.active_object] if context.active_object else [])
    if meshes_only:
        obs = [o for o in obs if o.type == "MESH"]
    return obs


def scene_of(context):
    return context.scene or bpy.context.scene

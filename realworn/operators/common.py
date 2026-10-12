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


def report_all(op, reps):
    for level, msg in reps:
        op.report({level}, msg)


def resolve_material(context, object_name="", material_name=""):
    """(object, material) from explicit names, else the active object's active material."""
    ob = bpy.data.objects.get(object_name) if object_name else context.active_object
    if material_name:
        mat = bpy.data.materials.get(material_name)
        return ob, mat
    if ob is None or ob.type != "MESH":
        return ob, None
    return ob, ob.active_material


def resolve_layer(mat, layer_id=""):
    """Index of the layer with `layer_id`, else the material's active layer index."""
    if layer_id:
        for i, ly in enumerate(mat.realworn.layers):
            if ly.id == layer_id or ly.name == layer_id:
                return i
    return max(0, min(mat.realworn.active_layer_index, len(mat.realworn.layers) - 1))

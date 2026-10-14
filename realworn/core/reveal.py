"""Reveal's True depth (REV-5): the material switches to Displacement and Bump and the objects get
an adaptive Simple subdivision (Cycles dices it; EEVEE uses the fixed viewport level). Off by
default. Turning it off restores the material's own displacement method and
removes the modifier."""

import bpy

from . import naming

VIEWPORT_LEVELS = 2
DISP_METHOD_KEY = "rw_disp_method"
DENSE_EDGE = 0.02  # metres: a mesh edge longer than this is too coarse for millimetre holes


def wants_true_depth(mat):
    return any(ly.visible and ly.kind == "REVEAL" and ly.true_depth for ly in mat.realworn.layers)


def subdiv_modifier(obj):
    return obj.modifiers.get(naming.MOD_SUBDIV)


def ensure_subdiv(obj):
    mod = subdiv_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(naming.MOD_SUBDIV, "SUBSURF")
        mod.subdivision_type = "SIMPLE"
        mod.levels = VIEWPORT_LEVELS
        mod.render_levels = VIEWPORT_LEVELS + 1
        mod.show_expanded = False
    if hasattr(mod, "use_adaptive_subdivision"):
        mod.use_adaptive_subdivision = True
    return mod


def remove_subdiv(obj):
    mod = subdiv_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)


def density_warning(obj):
    """'' or a warning when the mesh is too coarse for True depth without the subdivision."""
    import numpy as np
    me = obj.data
    if not me.edges:
        return ""
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    co, ev = co.reshape(-1, 3), ev.reshape(-1, 2)
    longest = float(np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1).max()) * max(obj.scale)
    if longest > DENSE_EDGE:
        return ("Coarse mesh (edges up to {:.0f} cm): True depth relies on adaptive subdivision in Cycles; "
                "EEVEE shows the fixed level {}".format(longest * 100, VIEWPORT_LEVELS))
    return ""


def sync(mat):
    """Bring the material's displacement method and its objects' modifiers in line with the layers."""
    from . import compiler
    on = mat.realworn.applied and wants_true_depth(mat)
    if on:
        if DISP_METHOD_KEY not in mat:
            mat[DISP_METHOD_KEY] = mat.displacement_method
        mat.displacement_method = "BOTH"
    elif DISP_METHOD_KEY in mat:
        mat.displacement_method = mat[DISP_METHOD_KEY]
        del mat[DISP_METHOD_KEY]
    for obj in compiler.objects_using(mat):
        others = any(m is not None and m is not mat and m.realworn.applied and wants_true_depth(m)
                     for m in obj.data.materials)
        if on or others:
            ensure_subdiv(obj)
        else:
            remove_subdiv(obj)
    return on


def restore(mat):
    if DISP_METHOD_KEY in mat:
        mat.displacement_method = mat[DISP_METHOD_KEY]
        del mat[DISP_METHOD_KEY]

"""Application handlers: never lose paint on save (SAV-2), never save Mask View, decal upkeep."""

import bpy
from bpy.app.handlers import persistent


@persistent
def _on_save_pre(_dummy):
    from .core import images, injector
    for mat in bpy.data.materials:  # Mask View is a viewing aid, never part of the saved look
        if mat.node_tree is not None and mat.realworn.applied and mat.realworn.mask_view:
            injector.set_mask_view(mat, False)
            mat["rw_restore_mask_view"] = True
    images.save_all()


@persistent
def _on_save_post(_dummy):
    from .core import injector
    for mat in bpy.data.materials:
        if mat.get("rw_restore_mask_view"):
            del mat["rw_restore_mask_view"]
            injector.set_mask_view(mat, True)


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        from .core import decals
    except ImportError:
        return
    decals.on_depsgraph_update(scene, depsgraph)


_HANDLERS = (
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
)


def register():
    for lst, fn in _HANDLERS:
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)

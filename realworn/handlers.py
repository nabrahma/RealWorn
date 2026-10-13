"""Application handlers: never lose paint on save (SAV-2), never save Mask View."""

import bpy
from bpy.app.handlers import persistent


@persistent
def _on_save_pre(filepath, *_args):
    from .core import compiler, images, injector
    for mat in bpy.data.materials:  # Mask View is a viewing aid, never part of the saved file
        if mat.node_tree is not None and mat.realworn.applied and mat.realworn.mask_view:
            with compiler.batch(mat):
                mat.realworn.mask_view = False
            injector.set_mask_view(mat, False)
            mat["rw_restore_mask_view"] = True
    images.save_all(filepath if isinstance(filepath, str) and filepath else None)


@persistent
def _on_save_post(*_args):
    from .core import compiler, injector
    for mat in bpy.data.materials:
        if mat.get("rw_restore_mask_view"):
            del mat["rw_restore_mask_view"]
            with compiler.batch(mat):
                mat.realworn.mask_view = True
            injector.set_mask_view(mat, True)


_HANDLERS = (
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
)


def register():
    for lst, fn in _HANDLERS:
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)

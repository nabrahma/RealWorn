"""Application handlers: never lose paint on save (SAV-2), never save Mask View, decal upkeep."""

import bpy
from bpy.app.handlers import persistent


@persistent
def _on_load_post(*_args):
    """Files saved with an older RealWorn get the current shared groups and recompiled stacks."""
    from .core import assets
    try:
        assets.upgrade_open_file()
    except Exception as ex:  # never block loading a file
        print("[RealWorn] upgrade on load failed:", ex)


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


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        from .core import damage, decals, images
    except ImportError:
        return
    decals.on_depsgraph_update(scene, depsgraph)
    for upd in depsgraph.updates:  # DMG-4: a stroke on a Geometry-mode Damage mask re-cuts
        if isinstance(upd.id, bpy.types.Image):
            img = bpy.data.images.get(upd.id.name)
            if img is not None and images.is_rw_image(img):
                damage.refresh_live(img)


_HANDLERS = (
    (bpy.app.handlers.load_post, _on_load_post),
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

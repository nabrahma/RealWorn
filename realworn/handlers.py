"""Application handlers: re-sync on load, end Mask Preview on save, decal upkeep."""

import bpy
from bpy.app.handlers import persistent


@persistent
def _on_load(_dummy):
    from .core import weather
    weather.resync_all()


@persistent
def _on_save_pre(_dummy):
    """MASK-6: Mask Preview never gets saved into a file."""
    from .core import preview
    for scene in bpy.data.scenes:
        if scene.realworn.mask_preview != "NONE":
            scene.realworn.mask_preview = "NONE"
    preview.restore_all()


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        from .core import decals
    except ImportError:
        return
    if hasattr(decals, "on_depsgraph_update"):
        decals.on_depsgraph_update(scene, depsgraph)


_HANDLERS = (
    (bpy.app.handlers.load_post, _on_load),
    (bpy.app.handlers.save_pre, _on_save_pre),
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

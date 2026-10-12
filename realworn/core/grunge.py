"""Grunge library (GRN-1): bundled generated grunges plus the user's folder. Brush modes arrive
at P3."""

import os

import bpy

from . import assets

GRUNGE_DIR = os.path.join(assets.ASSET_DIR, "grunges")
_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")


def _user_folder():
    try:
        from ..props import prefs
        p = prefs()
        return bpy.path.abspath(p.grunge_folder) if p and p.grunge_folder else ""
    except Exception:
        return ""


def library():
    """[(file name, absolute path)] of grunge images (bundled first, then the user folder)."""
    out = []
    for folder in (GRUNGE_DIR, _user_folder()):
        if folder and os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(_EXT):
                    out.append((f, os.path.join(folder, f)))
    return out


_previews = None
_enum_items = []


def library_enum_items():
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    for i, (name, path) in enumerate(library()):
        icon = 0
        if _previews is not None:
            if name not in _previews:
                _previews.load(name, path, "IMAGE")
            icon = _previews[name].icon_id
        _enum_items.append((name, os.path.splitext(name)[0].replace("_", " ").title(), path, icon, i))
    if not _enum_items:
        _enum_items.append(("NONE", "No grunges found", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None

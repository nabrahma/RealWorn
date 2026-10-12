"""Context overrides that work in every caller: UI operators, headless tests, and code run from
a timer (where bpy.context has no window, so screen members like active_object or
edit_object do not exist and edit-mode operators fail their poll)."""

import bpy


def window_area(kind="VIEW_3D"):
    """(window, screen, area, region) of the largest area of `kind`, or Nones headless."""
    wm = bpy.context.window_manager
    wins = list(wm.windows) if wm is not None else []
    for win in wins:
        areas = [a for a in win.screen.areas if a.type == kind]
        if areas:
            area = max(areas, key=lambda a: a.width * a.height)
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            return win, win.screen, area, region
    if wins:
        win = wins[0]
        area = win.screen.areas[0] if win.screen.areas else None
        region = next((r for r in area.regions if r.type == "WINDOW"), None) if area else None
        return win, win.screen, area, region
    return None, None, None, None


def override(obj=None, kind="VIEW_3D", **extra):
    """kwargs for bpy.context.temp_override: window/area when there is one, plus object members."""
    out = {}
    win, screen, area, region = window_area(kind)
    if win is not None:
        out.update(window=win, screen=screen)
        if area is not None:
            out["area"] = area
        if region is not None:
            out["region"] = region
    if obj is not None:
        out.update(active_object=obj, object=obj, selected_objects=[obj], selected_editable_objects=[obj])
    out.update(extra)
    return out

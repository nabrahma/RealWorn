"""The sidebar can't be drawn headless, so check what it references instead: every icon name is a
real Blender icon and every operator it calls is registered (except those of later milestones,
listed here until they land; the list must be empty at P8)."""

import os
import re

import bpy

from realworn.core import layer_types as LT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOT_YET = {"damage_apply", "decal_bake", "decal_place", "flatten", "bake", "restore_live", "export_textures",
           "mask_preset_save", "mask_preset_load"}


def _sources():
    out = ""
    for p in ("realworn/ui/panels.py", "realworn/props.py"):
        with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
            out += fh.read()
    return out


def test_icons_exist():
    icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys())
    bad = [(k, v["icon"]) for k, v in LT.TYPES.items() if v["icon"] not in icons]
    bad += [i for i in set(re.findall(r'icon="([A-Z0-9_]+)"', _sources())) if i not in icons]
    assert not bad, bad


def test_panel_operators_are_registered():
    names = set(re.findall(r'"realworn\.([a-z_]+)"', _sources()))
    missing = {n for n in names if not hasattr(bpy.types, "REALWORN_OT_" + n)}
    assert missing <= NOT_YET, sorted(missing - NOT_YET)
    print("\n[ui] operators still to come: {}".format(sorted(missing)))

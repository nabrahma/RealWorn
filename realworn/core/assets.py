"""Load RealWorn node groups from assets/realworn_nodes.blend.

The .blend is a build artifact written by ``build_asset_file`` from the Python
builders. Every group carries ``rw_schema`` and ``rw_build``; the loader never
mixes versions: a group with a different schema or build is upgraded in place
(users remapped to the fresh copy).
"""

import hashlib
import json
import os
import re

import bpy

from . import naming

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(PKG_DIR, "assets")
ASSET_BLEND = os.path.join(ASSET_DIR, "realworn_nodes.blend")
ASSET_META = os.path.join(ASSET_DIR, "realworn_nodes.json")
_HASHED = ("builders", os.path.join("core", "naming.py"))
_DUP = re.compile(r"^(RW_\w+)\.\d{3}$")


def builder_hash():
    """Hash of every builder source plus naming.py, line endings normalised."""
    h = hashlib.sha1()
    files = []
    for item in _HASHED:
        p = os.path.join(PKG_DIR, item)
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".py")]
        else:
            files.append(p)
    for f in files:
        h.update(os.path.basename(f).encode())
        with open(f, "rb") as fh:
            h.update(fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def _meta():
    try:
        with open(ASSET_META, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def asset_build():
    """Build id of the asset file on disk, or of the builders if there is none."""
    return _meta().get("build") or builder_hash()


def asset_stale():
    meta = _meta()
    return (not os.path.exists(ASSET_BLEND) or meta.get("schema") != naming.SCHEMA
            or meta.get("build") != builder_hash())


def build_asset_file():
    """Run every builder and write the asset .blend plus its metadata sidecar."""
    from ..builders import build_all
    groups = build_all()
    bid = builder_hash()
    for g in groups:
        g["rw_schema"] = naming.SCHEMA
        g["rw_build"] = bid
    os.makedirs(ASSET_DIR, exist_ok=True)
    bpy.data.libraries.write(ASSET_BLEND, set(groups), fake_user=True, compress=True)
    with open(ASSET_META, "w", encoding="utf-8") as fh:
        json.dump({"schema": naming.SCHEMA, "build": bid, "groups": sorted(g.name for g in groups)},
                  fh, indent=1)
    return ASSET_BLEND, len(groups)


def _is_current(group, build):
    return group.get("rw_schema") == naming.SCHEMA and group.get("rw_build") == build


def _dedupe():
    """Fold `RW_X.001` copies created by append back onto a current `RW_X`."""
    build = asset_build()
    for g in list(bpy.data.node_groups):
        m = _DUP.match(g.name)
        if not m:
            continue
        base = bpy.data.node_groups.get(m.group(1))
        if base is not None and _is_current(base, build):
            g.user_remap(base)
            bpy.data.node_groups.remove(g)
        elif base is None:
            g.name = m.group(1)


def ensure_groups(names=naming.ALL_GROUPS):
    """Make sure each named group exists in the open file at the current version.

    Returns the number of groups appended or upgraded.
    """
    build = asset_build()
    todo = [n for n in names if n not in bpy.data.node_groups
            or not _is_current(bpy.data.node_groups[n], build)]
    if not todo:
        return 0
    olds = {}
    for n in todo:
        g = bpy.data.node_groups.get(n)
        if g is not None:
            g.name = n + ".rw_old"
            olds[n] = g
    if os.path.exists(ASSET_BLEND):
        with bpy.data.libraries.load(ASSET_BLEND, link=False) as (src, dst):
            dst.node_groups = [n for n in src.node_groups if n in todo]
        loaded = [g for g in dst.node_groups if g is not None]
    else:  # repo without a built asset file: build in memory
        from ..builders import build_all
        loaded = build_all()
        for g in loaded:
            g["rw_schema"] = naming.SCHEMA
            g["rw_build"] = build
    for g in loaded:
        g.use_fake_user = False
    _dedupe()
    for n, old in olds.items():
        new = bpy.data.node_groups.get(n)
        if new is not None:
            old.user_remap(new)
        bpy.data.node_groups.remove(old)
    _dedupe()
    return len(todo)


def group(name):
    ensure_groups((name,))
    return bpy.data.node_groups[name]


def upgrade_open_file():
    """Upgrade any RealWorn group already in the file to the current asset build."""
    present = [n for n in naming.ALL_GROUPS if n in bpy.data.node_groups]
    return ensure_groups(present) if present else 0


def remove_unused_groups():
    """Delete RealWorn groups with no users (used by Remove All)."""
    removed = 0
    for _ in range(4):  # nested groups free up their children on the next pass
        for g in list(bpy.data.node_groups):
            if g.name.startswith("RW_") and g.users == 0:
                bpy.data.node_groups.remove(g)
                removed += 1
    return removed

"""Shared fixtures. Blender-only fixtures are skipped when bpy is unavailable."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "_out")

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except ImportError:
    HAVE_BPY = False

if not HAVE_BPY:
    collect_ignore_glob = ["test_*.py"]  # only tests/pure runs outside Blender


@pytest.fixture
def empty_scene():
    """A fresh empty file; every Blender test starts from no leftover state."""
    import bpy
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    yield bpy.context.scene


@pytest.fixture
def out_dir():
    os.makedirs(OUT, exist_ok=True)
    return OUT

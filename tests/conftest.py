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


@pytest.fixture(autouse=True)
def detail_defaults_by_suite(request):
    """New layers get the v2.1 Edge Detail defaults only in the v2.1 suites (test_v21_*). The v2.0
    suites keep measuring v2.0 masks, so they stay a regression check of everything v2.1 left
    unchanged (PRD v2.1: the full v2.0 suite must stay green)."""
    if not HAVE_BPY:
        yield
        return
    from realworn.core import detail
    saved = detail.DEFAULTS_FOR_NEW_LAYERS
    detail.DEFAULTS_FOR_NEW_LAYERS = os.path.basename(str(request.fspath)).startswith("test_v21")
    yield
    detail.DEFAULTS_FOR_NEW_LAYERS = saved

"""Pure-Python tests import realworn.core modules without running the bpy-only package init."""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "realworn" not in sys.modules:
    try:
        import bpy  # noqa: F401
    except ImportError:
        pkg = types.ModuleType("realworn")
        pkg.__path__ = [os.path.join(ROOT, "realworn")]
        core = types.ModuleType("realworn.core")
        core.__path__ = [os.path.join(ROOT, "realworn", "core")]
        sys.modules["realworn"] = pkg
        sys.modules["realworn.core"] = core

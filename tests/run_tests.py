"""Headless entry point for every Blender-side test.

    $BLENDER_BIN --background --factory-startup --python tests/run_tests.py
    $BLENDER_BIN --background --factory-startup --python tests/run_tests.py -- -k injector -x
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
for p in (os.path.join(TESTS, "_vendor"), TESTS, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import realworn
    realworn.register()
    import pytest
    code = pytest.main([TESTS, "-p", "no:cacheprovider", "-q", "--ignore", os.path.join(TESTS, "_vendor")] + args)
    sys.stdout.flush()
    os._exit(int(code))


main()

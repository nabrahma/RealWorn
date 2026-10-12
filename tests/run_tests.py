"""Headless entry point for every Blender-side test.

    $BLENDER_BIN --background --factory-startup --python tests/run_tests.py
    $BLENDER_BIN --background --factory-startup --python tests/run_tests.py -- -k injector -x
    ... -- --update-snapshots      regenerate tests/snapshots references
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
    if "--update-snapshots" in args:
        args.remove("--update-snapshots")
        os.environ["RW_UPDATE_SNAPSHOTS"] = "1"
    import realworn
    realworn.register()
    from realworn.core import assets
    if assets.asset_stale():
        path, n = assets.build_asset_file()
        print("[RealWorn] rebuilt assets ({} groups) -> {}".format(n, path))
    import pytest
    code = pytest.main([TESTS, "-p", "no:cacheprovider", "-q", "--ignore", os.path.join(TESTS, "_vendor")] + args)
    sys.stdout.flush()
    os._exit(int(code))


main()

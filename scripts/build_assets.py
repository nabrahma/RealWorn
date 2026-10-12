"""Run every builder and write realworn/assets/realworn_nodes.blend.

    $BLENDER_BIN --background --factory-startup --python scripts/build_assets.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from realworn.core import assets
    path, n = assets.build_asset_file()
    print("[RealWorn] wrote {} node groups to {}".format(n, path))


if __name__ == "__main__":
    main()

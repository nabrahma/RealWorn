"""Download ~12 CC0 Poly Haven materials (1k .blend + textures) into tests/corpus/<asset>/.

Dev-only, never shipped with the add-on. Picks the most downloaded asset per category so the
set is stable over time; pass --list to see the choice without downloading.

    python tests/corpus/fetch.py [--res 1k] [--list]
    python tests/corpus/fetch.py --reference        # v3 reference test sets
    python tests/corpus/fetch.py --road             # the Puddle tests' reference road
"""

import argparse
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.polyhaven.com"
UA = {"User-Agent": "RealWorn-dev-test-corpus/0.7 (test corpus fetcher)"}
# category -> how many assets; covers bricks, concrete, painted/rusty metal, wood, asphalt, tiles, plaster
WANT = [("brick", 2), ("concrete", 2), ("metal", 2), ("wood", 2), ("asphalt", 1), ("tiles", 1),
        ("plaster", 1), ("cobblestone", 1)]
# v3: the sets the reference wall uses (base plaster, second material, under-material)
REFERENCE_SETS = ["red_plaster_weathered", "beige_wall_001", "plaster_grey_04"]
# the reference road of the Puddle tests: asphalt, cobblestones, tiles
ROAD_SETS = ["aerial_asphalt_01", "cobblestone_floor_04", "interior_tiles"]


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def choose():
    assets = json.loads(_get(API + "/assets?t=textures"))
    picked = []
    for cat, n in WANT:
        cands = sorted((k for k, v in assets.items() if cat in v.get("categories", []) and k not in picked),
                       key=lambda k: -assets[k].get("download_count", 0))
        picked += cands[:n]
    return picked


def fetch(asset, res):
    files = json.loads(_get("{}/files/{}".format(API, asset)))
    blend = files["blend"][res]["blend"]
    dest = os.path.join(HERE, asset)
    os.makedirs(os.path.join(dest, "textures"), exist_ok=True)
    targets = [(blend["url"], os.path.join(dest, os.path.basename(blend["url"])))]
    for rel, info in blend.get("include", {}).items():
        targets.append((info["url"], os.path.join(dest, *rel.split("/"))))
    for url, path in targets:
        if not os.path.exists(path):
            data = _get(url)
            with open(path, "wb") as fh:
                fh.write(data)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1k")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--assets", nargs="*", help="fetch these asset ids instead of the category picks")
    ap.add_argument("--reference", action="store_true", help="fetch the reference wall texture sets")
    ap.add_argument("--road", action="store_true", help="fetch the reference road texture sets (Puddle tests)")
    a = ap.parse_args()
    picked = a.assets if a.assets else (REFERENCE_SETS if a.reference else ROAD_SETS if a.road else choose())
    print("assets:", ", ".join(picked))
    if a.list:
        return
    for asset in picked:
        print("  ->", fetch(asset, a.res))


if __name__ == "__main__":
    main()

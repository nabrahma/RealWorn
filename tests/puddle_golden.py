"""Puddle material trees with Wet Film at 0, compared against the trees RealWorn 3.3.0 built for
the same scenes: the wet film must add nothing until it is turned on.

tests/fixtures/puddle_trees_3.3.0.json holds a SHA-256 of each serialized tree (the layer stack
and the material), made by running this file with a 3.3.0 checkout first on sys.path:

    git worktree add scratch/v330 v3.3.0
    "$BLENDER_BIN" --background --factory-startup --python tests/puddle_golden.py -- scratch/v330
"""

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "fixtures", "puddle_trees_3.3.0.json")

CONFIGS = {
    "default": {},
    "extras": dict(broad_dips=True, puddle_source="AUTO_AND_PAINT", paint=True, wind_ripple=0.4, tide_mark=0.3,
                   debris_settle=0.5, water_tint="OILY"),
    "true_depth": dict(true_depth=True, water_tint="MUDDY", height_source="BASE"),
    "paint_only": dict(puddle_source="PAINT", paint=True, water_tint="CUSTOM", tint_color=(0.3, 0.1, 0.05),
                       opacity=0.6),
}


def build(sc, out_dir, settings):
    """A bowl-shaped ground with one Puddle layer set to `settings`. Returns the material."""
    from realworn.core import compiler, images, layers
    from test_puddles import bowl, make_set, plane
    count = iter(range(100))
    new_id, layers.new_id = layers.new_id, lambda: "golden{:02d}".format(next(count))
    try:
        ob, mat = plane(sc, name="Golden")
        layers.load_texture(mat, make_set(out_dir, "golden", bowl(64)), scale=2.0)
        ly = layers.add_layer(mat, "PUDDLE")
    finally:
        layers.new_id = new_id
    with compiler.batch(mat):
        for k, v in settings.items():
            if k != "paint":
                setattr(ly, k, v)
    if settings.get("paint"):
        images.ensure_mask(ob, mat, ly)
    compiler.compile(mat)
    return mat


def digests(mat):
    from realworn.core import snapshot
    out = {}
    for key, tree in (("stack", mat.realworn.stack), ("material", mat.node_tree)):
        text = snapshot.dumps(snapshot.serialize(tree, include_owned=True))
        out[key] = hashlib.sha256(text.encode()).hexdigest()
    return out


def main(checkout):
    import bpy
    root = os.path.dirname(HERE)
    sys.path[:0] = [os.path.join(HERE, "_vendor"), HERE, os.path.abspath(checkout)]
    import realworn
    realworn.register()
    out_dir = os.path.join(root, "tests", "_out")
    result = {}
    for name, settings in CONFIGS.items():
        bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
        result[name] = digests(build(bpy.context.scene, out_dir, settings))
    import tomllib
    with open(os.path.join(os.path.dirname(realworn.__file__), "blender_manifest.toml"), "rb") as fh:
        version = tomllib.load(fh)["version"]
    with open(GOLDEN, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"version": version, "trees": result}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote", GOLDEN, "from", realworn.__file__, version)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])

"""Generate the bundled decal library (procedural, original CC0 work).

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_decals.py [-- --sheet PATH]

Writes realworn/assets/decals/<Category>/*.png (1024 px RGBA) and removes older bundled decals.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from realworn.builders import gen_decals  # noqa: E402

OUT = os.path.join(ROOT, "realworn", "assets", "decals")


def contact_sheet(path, cell=256):
    import bpy
    import numpy as np
    d = gen_decals.make_all(cell)
    names = sorted(d)
    sheet = np.zeros((cell, len(names) * cell, 4), np.float32)
    for i, n in enumerate(names):
        rgba = d[n]
        bg = np.full(rgba.shape[:2] + (3,), 0.55, np.float32)  # grey wall behind the decal
        a = rgba[..., 3:4]
        sheet[:, i * cell:(i + 1) * cell, :3] = np.flipud(bg * (1 - a) + rgba[..., :3] * a)
        sheet[:, i * cell:(i + 1) * cell, 3] = 1.0
    img = bpy.data.images.new("sheet", len(names) * cell, cell)
    img.pixels.foreach_set(sheet.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    print("sheet:", ", ".join(names))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    names = gen_decals.generate(OUT)
    print("wrote {} decals to {}".format(len(names), OUT))
    if "--sheet" in args:
        contact_sheet(args[args.index("--sheet") + 1])

"""Generate the bundled grunge library (procedural, original CC0 work).

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_grunges.py [-- --sheet PATH]

Writes realworn/assets/grunges/*.png (512 px, 8-bit greyscale, tileable).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from realworn.builders import gen_grunges  # noqa: E402

OUT = os.path.join(ROOT, "realworn", "assets", "grunges")


def contact_sheet(path, cols=5, cell=160):
    import bpy
    import numpy as np
    g = gen_grunges.make_all(256)
    names = sorted(g)
    rows = (len(names) + cols - 1) // cols
    sheet = np.ones((rows * cell, cols * cell, 4), np.float32)
    for i, n in enumerate(names):
        r, c = divmod(i, cols)
        a = g[n][::2, ::2][:cell - 8, :cell - 8]
        y0 = (rows - 1 - r) * cell + 4
        sheet[y0:y0 + a.shape[0], c * cell + 4:c * cell + 4 + a.shape[1], :3] = np.flipud(a)[..., None]
    img = bpy.data.images.new("sheet", cols * cell, rows * cell)
    img.pixels.foreach_set(sheet.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    print("sheet:", ", ".join(names))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = gen_grunges.generate(OUT)
    print("wrote {} grunges to {}".format(len(names), OUT))
    if "--sheet" in args:
        contact_sheet(args[args.index("--sheet") + 1])

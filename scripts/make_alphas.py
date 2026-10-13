"""Generate the bundled damage alphas (procedural, original CC0 work).

    "$BLENDER_BIN" --background --factory-startup --python scripts/make_alphas.py [-- --sheet PATH]

Writes realworn/assets/alphas/*.png (512 px, 8-bit greyscale).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from realworn.builders import gen_alphas  # noqa: E402

OUT = os.path.join(ROOT, "realworn", "assets", "alphas")


def contact_sheet(path, cell=256):
    import bpy
    import numpy as np
    a = gen_alphas.make_all(cell)
    names = sorted(a)
    sheet = np.ones((cell, len(names) * cell, 4), np.float32)
    for i, n in enumerate(names):
        sheet[:, i * cell:(i + 1) * cell, :3] = np.flipud(a[n])[..., None]
    img = bpy.data.images.new("sheet", len(names) * cell, cell)
    img.pixels.foreach_set(sheet.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    print("sheet:", ", ".join(names))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = gen_alphas.generate(OUT)
    print("wrote {} alphas to {}".format(len(names), OUT))
    if "--sheet" in args:
        contact_sheet(args[args.index("--sheet") + 1])

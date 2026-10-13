"""Edge Detail sources and defaults (PRD v2.1 EDG-1..EDG-10, SRC-1..SRC-3).

The painted mask says WHERE; a full-resolution detail value d decides the EDGE. Sources:
  LAYER_GRUNGE  the layer's grunge, box-projected in object space (Scale in metres)
  BASE_HEIGHT   the base material's own height, sampled once per material: the stack's Height
                input (the base's image node, outside the stack) normalised by one shared Map
                Range inside the stack (RW::stack::bh) with the 2nd / 98th percentiles captured
                here (SRC-1, SRC-2). A procedural base height uses the socket with a user range
                (SRC-3). Without a base height, BASE_HEIGHT falls back to the layer grunge.

Core code takes explicit datablocks.
"""

import numpy as np

from . import compiler, injector, layer_types as LT, naming

# New layers get the per-type Edge Detail defaults when the material is a v2.1 material. Tests of
# v2.0 behaviour turn this off (tests/conftest.py) so the v2.0 suite measures v2.0 masks.
DEFAULTS_FOR_NEW_LAYERS = True


# ------------------------------------------------------------------ base height
def base_height_socket(mat):
    """The socket feeding the stack's Height input (the base's height), or None."""
    tree = mat.node_tree
    if tree is None:
        return None
    for st in injector.stacks(tree):
        s = st.inputs.get("Height")
        if s is not None and s.is_linked:
            return s.links[0].from_socket
    return None


def has_base_height(mat):
    return base_height_socket(mat) is not None


def _image_of(sock):
    node = sock.node
    if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
        return node.image
    return None


def percentiles(image, lo=2.0, hi=98.0):
    """(p_lo, p_hi) of an image's first channel (NumPy), or None when it has no pixels."""
    w, h = image.size
    if not w or not h:
        return None
    px = np.empty(w * h * image.channels, np.float32)
    image.pixels.foreach_get(px)
    v = px.reshape(-1, image.channels)[:, 0]
    if v.size > 1_000_000:  # a strided sample is plenty for percentiles
        v = v[:: v.size // 1_000_000]
    a, b = np.percentile(v, (lo, hi))
    return float(a), float(b)


def capture_base(mat):
    """SRC-2 / SRC-3: record what the base height is and its normalisation range. Returns kind."""
    st = mat.realworn
    sock = base_height_socket(mat)
    kind, name, lo, hi = "NONE", "", 0.0, 1.0
    if sock is not None:
        img = _image_of(sock)
        rng = percentiles(img) if img is not None else None
        if rng is not None:
            kind, name = "IMAGE", img.name
            lo, hi = rng
            if hi - lo < 1e-4:
                hi = lo + 1e-4
        else:
            kind = "SOCKET"
            if st.base_height_kind == "SOCKET":  # keep the user's range on a recapture
                lo, hi = st.base_height_lo, st.base_height_hi
    with compiler.batch(mat):
        st.base_height_kind, st.base_height_image = kind, name
        st.base_height_lo, st.base_height_hi = lo, hi
    compiler.on_material_value(mat, "base_height_lo")
    return kind


# ------------------------------------------------------------------ sources
def grunge_of(layer):
    """The layer's grunge image: Edge Detail's own, else its first Grunge Fill ingredient's."""
    if layer.detail.image is not None:
        return layer.detail.image
    return next((i.image for i in layer.ingredients if i.kind == "GRUNGE" and i.image is not None), None)


def resolve(mat, layer):
    """(source actually used, grunge image or None); source None when the stage has nothing."""
    det = layer.detail
    if det.source == "BASE_HEIGHT" and has_base_height(mat):
        return "BASE_HEIGHT", None
    img = grunge_of(layer)
    return ("LAYER_GRUNGE", img) if img is not None else (None, None)


def source_density(obj, layer):
    """DIA-4: [(label, texels per cm)] of the layer's active Edge Detail source."""
    from . import diagnostics
    mat = layer.id_data
    src, img = resolve(mat, layer)
    if src == "LAYER_GRUNGE":
        return [("Grunge " + img.name, diagnostics.grunge_px_per_cm(img, layer.detail.scale))]
    if src == "BASE_HEIGHT":
        sock = base_height_socket(mat)
        img = _image_of(sock) if sock is not None else None
        uv = obj.data.uv_layers.active_render if obj.data.uv_layers else None
        if img is not None and uv is not None:
            k = diagnostics.uv_units_per_metre(obj, uv.name)
            return [("Base Height " + img.name, img.size[0] * k / 100.0)]
    return []


# ------------------------------------------------------------------ defaults
def apply_defaults(layer, kind):
    """Set the layer's Edge Detail to the per-type v2.1 defaults (callers batch and compile)."""
    from . import grunge
    d = LT.detail_defaults(kind)
    det = layer.detail
    det.mode, det.source = d["mode"], d["source"]
    det.strength, det.width, det.threshold = d["strength"], d["width"], d["threshold"]
    det.protect, det.scale = d["protect"], d["scale"]
    det.contrast, det.invert = 0.0, False
    if d["grunge"] and det.image is None:
        try:
            det.image = grunge.load(d["grunge"])
        except (KeyError, RuntimeError, OSError):
            det.image = None
    if kind == "DIRT" and d["mode"] == "HEIGHT":
        layer.use_height_blend = False  # Height Compare replaces v2.0's Height Blend


def apply_v21_defaults(mat):
    """EDG-9 'Apply v2.1 Defaults': capture the base, give every layer its type's Edge Detail
    defaults, and mark the material so new layers get them too. One recompile."""
    capture_base(mat)
    with compiler.batch(mat):
        for layer in mat.realworn.layers:
            apply_defaults(layer, layer.type)
        mat.realworn.v21 = True
    compiler.compile(mat)
    return len(mat.realworn.layers)


def wants_defaults(mat):
    return DEFAULTS_FOR_NEW_LAYERS and mat.realworn.v21

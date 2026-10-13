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

import os
import re

import bpy
import numpy as np

from . import compiler, injector, layer_types as LT, naming, nodeutil

_AO_WORDS = re.compile(r"(^|[_\-. ])(ao|ambientocclusion|ambient_occlusion|occlusion)([_\-. ]|$)")
_COLOR_WORDS = ("diff", "albedo", "basecolor", "base_color", "color", "col")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga", ".webp")

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


# ------------------------------------------------------------------ base AO (SRC-4)
def is_ao_name(name):
    return bool(_AO_WORDS.search(os.path.splitext(name.lower())[0]))


def base_ao_socket(mat):
    """The socket feeding the stack's AO input, or None."""
    tree = mat.node_tree
    for st in injector.stacks(tree) if tree is not None else []:
        s = st.inputs.get("AO")
        if s is not None and s.is_linked:
            return s.links[0].from_socket
    return None


def _base_color_node(tree):
    """The base colour image node (feeding a Principled Base Color, else named like a colour map)."""
    for st in injector.stacks(tree):
        src = nodeutil.link_source(st.inputs["Base Color"])
        if src is not None and src.node.bl_idname == "ShaderNodeTexImage":
            return src.node
    for n in tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image is not None and not nodeutil.is_owned(n) \
                and any(w in n.image.name.lower() for w in _COLOR_WORDS):
            return n
    return None


def find_ao(mat):
    """SRC-4: an AO image already in the material (connected or not), else one in the folder of the
    base colour image. Returns (node or None, image or None)."""
    tree = mat.node_tree
    for n in tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image is not None and is_ao_name(n.image.name):
            return n, n.image
    col = _base_color_node(tree)
    if col is not None and col.image is not None and col.image.filepath:
        folder = os.path.dirname(bpy.path.abspath(col.image.filepath))
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(_IMAGE_EXT) and is_ao_name(f):
                    return None, bpy.data.images.load(os.path.join(folder, f), check_existing=True)
    return None, None


def link_ao(mat, image, node=None):
    """Feed the stack's AO input from `node` (an image node in the user tree) or a new owned image
    node for `image` that reuses the base colour's mapping. Remove deletes the owned node and
    restores links exactly (snapshot)."""
    tree = mat.node_tree
    if node is None:
        node = nodeutil.find(tree, naming.BASE_AO_ROLE)
        if node is None:
            node = nodeutil.new(tree, "ShaderNodeTexImage", naming.BASE_AO_ROLE, frame=nodeutil.ensure_frame(tree))
            node.hide = True
        node.image = image
        image.colorspace_settings.name = "Non-Color"
        col = _base_color_node(tree)
        if col is not None:
            src = nodeutil.link_source(col.inputs["Vector"])
            if src is not None:
                tree.links.new(src, node.inputs["Vector"])  # the base's own mapping, reused
            node.projection = col.projection
    for st in injector.stacks(tree):
        tree.links.new(node.outputs["Color"], st.inputs["AO"])
    return node


def capture_ao(mat):
    """Detect the AO map, link it and record its 2nd / 98th percentiles. Returns kind."""
    st = mat.realworn
    sock = base_ao_socket(mat)
    img = _image_of(sock) if sock is not None else None
    if img is None:
        node, img = find_ao(mat)
        if img is not None:
            link_ao(mat, img, node)
    kind, lo, hi = "NONE", 0.0, 1.0
    rng = percentiles(img) if img is not None else None
    if rng is not None:
        kind, (lo, hi) = "IMAGE", rng
        hi = max(hi, lo + 1e-4)
    with compiler.batch(mat):
        st.base_ao_kind, st.base_ao_image = kind, img.name if img is not None else ""
        st.base_ao_lo, st.base_ao_hi = lo, hi
    compiler.on_material_value(mat, "base_ao_lo")
    return kind


def has_base_ao(mat):
    return base_ao_socket(mat) is not None


def refresh_base(mat):
    """SRC-8: recapture height, AO and their normalisation (after the user swapped base textures)
    without touching layers or paint."""
    kinds = (capture_base(mat), capture_ao(mat))
    compiler.compile(mat)
    return kinds


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


def content_height_image(layer):
    ch = layer.height
    return ch.image if ch.source in ("IMAGE", "PBRSET") and ch.image is not None else None


def resolve(mat, layer):
    """(source actually used, image or None); source None when the stage has nothing. Base Height,
    Base AO and Content Height fall back to the layer grunge when the map is missing (the panel
    says so); Second Grunge uses only image2."""
    det = layer.detail
    if det.source == "BASE_HEIGHT" and has_base_height(mat):
        return "BASE_HEIGHT", None
    if det.source == "BASE_AO" and has_base_ao(mat):
        return "BASE_AO", None
    if det.source == "CONTENT_HEIGHT" and content_height_image(layer) is not None:
        return "CONTENT_HEIGHT", content_height_image(layer)
    if det.source == "GRUNGE2":
        return ("GRUNGE2", det.image2) if det.image2 is not None else (None, None)
    img = grunge_of(layer)
    return ("LAYER_GRUNGE", img) if img is not None else (None, None)


def source_density(obj, layer):
    """DIA-4: [(label, texels per cm)] of the layer's active Edge Detail source."""
    from . import diagnostics
    mat = layer.id_data
    src, img = resolve(mat, layer)
    if src == "LAYER_GRUNGE":
        return [("Grunge " + img.name, diagnostics.grunge_px_per_cm(img, layer.detail.scale))]
    if src == "GRUNGE2":
        return [("Grunge " + img.name, diagnostics.grunge_px_per_cm(img, layer.detail.scale2))]
    if src == "CONTENT_HEIGHT":
        return [("Content Height " + img.name, diagnostics.grunge_px_per_cm(img, layer.height.scale))]
    if src in ("BASE_HEIGHT", "BASE_AO"):
        sock = base_height_socket(mat) if src == "BASE_HEIGHT" else base_ao_socket(mat)
        img = _image_of(sock) if sock is not None else None
        uv = obj.data.uv_layers.active_render if obj.data.uv_layers else None
        if img is not None and uv is not None:
            k = diagnostics.uv_units_per_metre(obj, uv.name)
            vsrc = nodeutil.link_source(sock.node.inputs["Vector"])
            if vsrc is not None and vsrc.node.bl_idname == "ShaderNodeMapping":  # the base's own tiling
                k *= abs(vsrc.node.inputs["Scale"].default_value[0]) or 1.0
            return [("{} {}".format("Base Height" if src == "BASE_HEIGHT" else "Base AO", img.name),
                     img.size[0] * k / 100.0)]
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
    if det.image is not None:  # SRC-7: the grunge's own suggested size
        det.scale = grunge.suggested_scale(det.image, d["scale"])
    det.mix2 = d["mix2"]
    if d["grunge2"] and det.image2 is None:
        try:
            det.image2 = grunge.load(d["grunge2"])
            det.scale2 = grunge.suggested_scale(det.image2, det.scale2)
        except (KeyError, RuntimeError, OSError):
            det.image2, det.mix2 = None, 0.0
    if kind == "DIRT" and d["mode"] == "HEIGHT":
        layer.use_height_blend = False  # Height Compare replaces v2.0's Height Blend
    look = LT.look_defaults(kind)  # CNT-1: textured content look for effect types
    if look is not None:
        lk = layer.look
        lk.enabled = True
        lk.color_var, lk.rough_var, lk.micro, lk.scale = look["color_var"], look["rough_var"], look["micro"], look["scale"]
    if kind == "DAMAGE":
        layer.damage.carve = "FOLLOW_BASE"  # DMG-10: v2.1 default
    if kind == "RUST" and layer.color.source == "TINTED_GRUNGE":
        layer.color.source = "FLAT"  # the look does the variation (and the orange rim)


def apply_v21_defaults(mat):
    """EDG-9 'Apply v2.1 Defaults': capture the base, give every layer its type's Edge Detail
    defaults, and mark the material so new layers get them too. One recompile."""
    capture_base(mat)
    capture_ao(mat)
    with compiler.batch(mat):
        for layer in mat.realworn.layers:
            apply_defaults(layer, layer.type)
        mat.realworn.v21 = True
    compiler.compile(mat)
    return len(mat.realworn.layers)


def wants_defaults(mat):
    return DEFAULTS_FOR_NEW_LAYERS and mat.realworn.v21

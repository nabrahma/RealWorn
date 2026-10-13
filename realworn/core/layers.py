"""Layer list editing (add, remove, move, duplicate).

Every edit happens inside compiler.batch() and ends with exactly one compile(). Layer order is
stack order: index 0 sits directly on the Base. A new layer drops into its kind's usual place
(UI-1, kinds.ORDER); the user can drag it anywhere.
"""

import random
import uuid

import bpy

from . import compiler
from . import kinds as K


def new_id():
    return uuid.uuid4().hex[:8]


def _unique_name(mat, base):
    names = {ly.name for ly in mat.realworn.layers}
    if base not in names:
        return base
    i = 2
    while "{} {}".format(base, i) in names:
        i += 1
    return "{} {}".format(base, i)


def _grunge(name):
    from . import grunge
    try:
        return grunge.load("grunges", name)
    except KeyError:
        return None


def apply_defaults(layer, kind, preset=None, variation_index=0):
    """The kind's defaults (and a preset's) on a fresh layer."""
    from . import grunge
    d = K.defaults(kind, preset)
    layer.kind = kind
    gname = d.pop("breakup", None)
    if kind == "VARIATION":  # VAR-3: each new Variation gets another grunge and a random offset
        gname = K.VARIATION_GRUNGES[variation_index % len(K.VARIATION_GRUNGES)]
        layer.breakup_offset = round(random.Random(layer.id).uniform(0.0, 10.0), 3)
    d.pop("alpha", None)
    for key, value in d.items():
        setattr(layer, key, value)
    if gname:
        layer.breakup_grunge = _grunge(gname)
        layer.breakup_scale = grunge.suggested_scale(gname, 0.5)


def add_layer(mat, kind="PAINT", preset=None, name=None, index=None):
    """Add a layer of `kind` (with an optional preset) at its default stack position, or at
    `index`, select it and return it. Painted kinds show nothing until painted."""
    st = mat.realworn
    variations = sum(1 for ly in st.layers if ly.kind == "VARIATION")
    with compiler.batch(mat):
        ly = st.layers.add()
        ly.id = new_id()
        label = next((n for k, n in K.preset_items(kind) if k == preset), None) if preset else None
        ly.name = _unique_name(mat, name or label or K.label(kind))
        apply_defaults(ly, kind, preset, variations)
        last = len(st.layers) - 1
        if index is None:
            index = K.insert_index([x.kind for x in list(st.layers)[:last]], kind)
        index = max(0, min(index, last))
        if index != last:
            st.layers.move(last, index)
        st.active_layer_index = index
        st.base_active = False
    compiler.compile(mat)
    return st.layers[index]


def index_of(mat, layer_id):
    for i, ly in enumerate(mat.realworn.layers):
        if ly.id == layer_id:
            return i
    raise KeyError(layer_id)


def _owned_images(ly):
    return [i for i in (ly.mask_image, ly.baked_image) if i is not None]


def remove_layer(mat, index, delete_images=True):
    st = mat.realworn
    ly = st.layers[index]
    imgs = _owned_images(ly) if delete_images else []
    with compiler.batch(mat):
        st.layers.remove(index)
        st.active_layer_index = max(0, min(st.active_layer_index, len(st.layers) - 1))
    compiler.compile(mat)
    for img in imgs:
        if img.users == 0:
            bpy.data.images.remove(img)


def move_layer(mat, index, direction):
    """direction +1 moves up (towards the top of the stack), -1 down. Returns the new index."""
    st = mat.realworn
    new = index + direction
    if new < 0 or new >= len(st.layers):
        return index
    with compiler.batch(mat):
        st.layers.move(index, new)
        st.active_layer_index = new
    compiler.compile(mat)
    return new


def copy_props(src, dst, skip=("id", "name")):
    """Deep copy of PropertyGroup values (pointers to IDs are shared, collections copied)."""
    for p in src.bl_rna.properties:
        k = p.identifier
        if k == "rna_type" or k in skip:
            continue
        val = getattr(src, k)
        if p.type == "COLLECTION":
            dc = getattr(dst, k)
            dc.clear()
            for item in val:
                copy_props(item, dc.add(), skip=())
        elif p.type == "POINTER" and isinstance(val, bpy.types.PropertyGroup):
            copy_props(val, getattr(dst, k), skip=())
        else:
            try:
                setattr(dst, k, val)
            except (AttributeError, TypeError):
                pass


def duplicate_layer(mat, index):
    from . import naming
    st = mat.realworn
    with compiler.batch(mat):
        ly = st.layers.add()
        # add() can reallocate the collection: look the source up again after it
        src = st.layers[index]
        copy_props(src, ly)
        ly.id = new_id()
        ly.name = _unique_name(mat, src.name)
        for attr in ("mask_image", "baked_image"):
            img = getattr(src, attr)
            if img is not None:
                dup = img.copy()
                dup.name = img.name + ".dup"
                tag = naming.IMG_MASK if attr == "mask_image" else naming.IMG_BAKED_SOURCE
                dup[tag] = "{}/{}".format(st.owner, ly.id)
                if img.packed_file is not None or img.is_dirty or not img.filepath:
                    try:
                        dup.pack()
                    except RuntimeError:
                        pass
                setattr(ly, attr, dup)
        last = len(st.layers) - 1
        st.layers.move(last, index + 1)
        st.active_layer_index = index + 1
    compiler.compile(mat)
    return st.layers[index + 1]


def load_texture(mat, paths, layer=None, scale=None):
    """Load Texture (LT-1, LT-5) into a layer, or into the Base when `layer` is None. Loading over a
    set replaces its maps and keeps every other setting and the paint. Returns the channels found."""
    from . import pbrset
    ts = layer.texture if layer is not None else mat.realworn.base
    with compiler.batch(mat):
        done = pbrset.assign(ts, paths, scale)
        if layer is not None and done and layer.kind != "DECALS":
            layer.content = "TEXTURE"
    compiler.compile(mat)
    return done

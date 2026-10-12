"""Layer list editing (add, remove, move, duplicate) and reference validation.

Every edit happens inside compiler.batch() and ends with exactly one compile(). Layer order
equals stack order: index 0 is directly above Base.
"""

import uuid

import bpy

from . import compiler, naming
from . import layer_types as LT


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


def apply_defaults(layer, kind):
    d = LT.defaults(kind)
    layer.type = kind
    for ch in LT.CHANNEL_NAMES:
        c = getattr(layer, ch)
        dc = d[ch]
        c.enabled = dc["enabled"]
        c.source = dc["source"]
        c.blend = dc["blend"]
        if ch == "color":
            c.color = dc["value"]
        else:
            c.value = dc["value"]
    for k in ("use_height_blend", "height_blend", "lock_source", "lock_strength", "threshold", "softness"):
        setattr(layer, k, d[k])


def add_layer(mat, kind="CUSTOM", name=None, index=None):
    """Add a layer above the active one (or at `index`); returns it. Nothing shows until painted:
    the mask starts empty and every ingredient amount is 0 (PRD core workflow step 3)."""
    st = mat.realworn
    with compiler.batch(mat):
        ly = st.layers.add()
        ly.id = new_id()
        ly.name = _unique_name(mat, name or LT.TYPES[kind]["label"])
        apply_defaults(ly, kind)
        if kind == "DECAL":
            ly.threshold, ly.softness = 0.5, 1.0
        last = len(st.layers) - 1
        if index is None:
            index = st.active_layer_index + 1 if len(st.layers) > 1 else 0
        index = max(0, min(index, last))
        if index != last:
            st.layers.move(last, index)
        st.active_layer_index = index
    compiler.compile(mat)
    return st.layers[index]


def index_of(mat, layer_id):
    for i, ly in enumerate(mat.realworn.layers):
        if ly.id == layer_id:
            return i
    raise KeyError(layer_id)


def remove_layer(mat, index, delete_images=True):
    st = mat.realworn
    ly = st.layers[index]
    lid = ly.id
    imgs = [i for i in (ly.mask_image, ly.content_image) if i is not None] if delete_images else []
    with compiler.batch(mat):
        st.layers.remove(index)
        for other in st.layers:  # references to the deleted layer become empty
            for ing in other.ingredients:
                if ing.kind == "REFERENCE" and ing.ref_layer_id == lid:
                    ing.ref_layer_id = ""
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
        fix_references(mat)
    compiler.compile(mat)
    return new


def fix_references(mat):
    """ING-5: a layer may only reference layers below it; references pointing up are cleared."""
    below = set()
    cleared = 0
    for ly in mat.realworn.layers:
        for ing in ly.ingredients:
            if ing.kind == "REFERENCE" and ing.ref_layer_id and ing.ref_layer_id not in below:
                ing.ref_layer_id = ""
                cleared += 1
        below.add(ly.id)
    return cleared


def layers_below(mat, layer):
    out = []
    for ly in mat.realworn.layers:
        if ly == layer or ly.id == layer.id:
            break
        out.append(ly)
    return out


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
    st = mat.realworn
    src = st.layers[index]
    with compiler.batch(mat):
        ly = st.layers.add()
        copy_props(src, ly)
        ly.id = new_id()
        ly.name = _unique_name(mat, src.name)
        for attr in ("mask_image", "content_image"):
            img = getattr(src, attr)
            if img is not None:
                dup = img.copy()
                dup.name = img.name + ".dup"
                dup[naming.IMG_MASK if attr == "mask_image" else naming.IMG_CONTENT] = "{}/{}".format(
                    st.owner, ly.id)
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


def set_visible(mat, index, state):
    mat.realworn.layers[index].visible = state  # structural: the callback recompiles

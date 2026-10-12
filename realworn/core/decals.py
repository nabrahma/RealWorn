"""Projector decals as layers (DEC-1..DEC-6).

A decal is an Empty (cube display) named RW_Decal_<image> in the RW_Decals collection plus a
Decal layer on each layered material of the object it was placed on. The layer projects the
image through Texture Coordinate > Object of that Empty, with a facing fade so side faces never
stretch, and has a paintable mask like any other layer (tear a poster, fade a stain). Layer
order decides what covers it: Dirt and Water above a decal make it dirty and wet (DEC-4).
"""

import os

import bpy
from mathutils import Matrix, Vector

from . import assets, naming

DECAL_DIR = os.path.join(assets.ASSET_DIR, "decals")
MODES = ("FULL", "GRIME", "DAMAGE")


class DecalError(Exception):
    pass


# ---------------------------------------------------------------- library
def _user_folder():
    try:
        from ..props import prefs
        p = prefs()
        return bpy.path.abspath(p.decal_folder) if p and p.decal_folder else ""
    except Exception:
        return ""


def library():
    """[(file name, absolute path)] of decal images; *_nrm.png are normal maps, not decals."""
    out = []
    for folder in (DECAL_DIR, _user_folder()):
        if folder and os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")) and \
                        not os.path.splitext(f)[0].endswith("_nrm"):
                    out.append((f, os.path.join(folder, f)))
    return out


_previews = None
_enum_items = []  # keep strings alive for Blender's enum callback


def library_enum_items():
    global _previews
    _enum_items.clear()
    try:
        import bpy.utils.previews
        if _previews is None:
            _previews = bpy.utils.previews.new()
    except Exception:
        _previews = None
    for i, (name, path) in enumerate(library()):
        icon = 0
        if _previews is not None:
            if name not in _previews:
                _previews.load(name, path, "IMAGE")
            icon = _previews[name].icon_id
        _enum_items.append((name, os.path.splitext(name)[0].replace("_", " ").title(), path, icon, i))
    if not _enum_items:
        _enum_items.append(("NONE", "No decals found", "", 0, 0))
    return _enum_items


def free_previews():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None


def _path_for(name):
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for n, p in library():
        if n == name or os.path.splitext(n)[0] == name:
            return p
    raise DecalError("decal image '{}' not found in the library".format(name))


def load_image(name, non_color=False):
    path = _path_for(name)
    for img in bpy.data.images:
        if img.filepath and os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(path):
            return img
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def _normal_map_for(path):
    stem, ext = os.path.splitext(path)
    p = stem + "_nrm" + ext
    return p if os.path.exists(p) else None


# ------------------------------------------------------------ decal objects
def is_decal(ob):
    return ob is not None and ob.type == "EMPTY" and bool(ob.get("rw_decal"))


def decal_objects():
    return [o for o in bpy.data.objects if is_decal(o)]


def ensure_collection(scene):
    coll = bpy.data.collections.get(naming.COLL_DECALS)
    if coll is None:
        coll = bpy.data.collections.new(naming.COLL_DECALS)
    if scene is not None and coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def projection_normal(empty):
    return (empty.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()


def _corners(empty):
    mw = empty.matrix_world
    return [mw @ Vector((x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]


def _aabb(points):
    xs, ys, zs = zip(*points)
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def intersecting_objects(empty, scene):
    """Meshes whose world bounds overlap the decal box (DEC-9 lists these)."""
    lo, hi = _aabb(_corners(empty))
    out = []
    for ob in scene.objects:
        if ob.type != "MESH" or is_decal(ob):
            continue
        blo, bhi = _aabb([ob.matrix_world @ Vector(c) for c in ob.bound_box])
        if all(blo[i] <= hi[i] and bhi[i] >= lo[i] for i in range(3)):
            out.append(ob)
    return out


def orientation(normal, rotation=0.0, up=(0.0, 0.0, 1.0)):
    """3x3 basis: Z = surface normal, Y = world up projected on the surface (image stays upright)."""
    z = Vector(normal).normalized()
    upv = Vector(up)
    y = upv - z * z.dot(upv)
    if y.length < 1e-4:  # floor or ceiling: keep image Y along world Y
        y = Vector((0, 1, 0)) - z * z.dot(Vector((0, 1, 0)))
    y.normalize()
    x = y.cross(z).normalized()
    m = Matrix((x, y, z)).transposed()
    return m @ Matrix.Rotation(rotation, 3, "Z")


def place(obj, image, location, normal, size=0.6, mode="FULL", rotation=0.0, height=None, depth=None,
          scene=None):
    """DEC-1: Empty at a surface point plus a Decal layer on every layered material of `obj`.
    Returns (empty, [layers], report list)."""
    from . import layers, setup
    if mode not in MODES:
        raise DecalError("mode must be one of {}".format(MODES))
    scene = scene or bpy.context.scene
    img = load_image(image)
    w, h = img.size
    height = height if height is not None else size * (h / w if w else 1.0)
    depth = depth if depth is not None else max(0.1, min(size, height) * 0.5)
    empty = bpy.data.objects.new(naming.decal_name(img.name), None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 1.0
    rot = orientation(normal, rotation)
    empty.matrix_world = Matrix.Translation(Vector(location)) @ (rot @ Matrix.Diagonal(
        (size / 2.0, height / 2.0, depth / 2.0))).to_4x4()
    ensure_collection(scene).objects.link(empty)
    empty["rw_decal"] = True
    nrm_path = _normal_map_for(_path_for(image))
    nrm = load_image(nrm_path, non_color=True) if nrm_path else None
    rep, made = [], []
    if not setup.is_setup(obj):
        rep += setup.setup_object(obj)
    for mat in setup.layered_materials(obj):
        if sum(1 for ly in mat.realworn.layers if ly.type == "DECAL") >= naming.MAX_DECALS_PER_MATERIAL:
            rep.append(("WARNING", "{}: {} decal layers already; bake one into a layer first".format(
                mat.name, naming.MAX_DECALS_PER_MATERIAL)))
            continue
        from . import compiler
        with compiler.batch(mat):
            ly = layers.add_layer(mat, "DECAL", name=os.path.splitext(img.name)[0].replace("_", " ").title(),
                                  index=len(mat.realworn.layers))
            ly.decal.empty = empty
            ly.decal.image = img
            ly.decal.normal_image = nrm
            ly.decal.mode = mode
            if mode == "GRIME":  # DEC-3: channel-only
                ly.color.enabled = False
                ly.metallic.enabled = False
        compiler.compile(mat)
        made.append(ly)
    empty["rw_targets"] = [m.name for m in setup.layered_materials(obj)]
    if not made:
        rep.append(("WARNING", "Decal placed but no layer was added"))
    return empty, made, rep


def update_normal(empty):
    """Keep the facing fade aligned when a decal Empty is rotated (value-only, no recompile)."""
    n = projection_normal(empty)
    for mat in bpy.data.materials:
        g = mat.realworn.stack if mat.realworn.applied else None
        if g is None:
            continue
        for ly in mat.realworn.layers:
            if ly.type == "DECAL" and ly.decal.empty == empty:
                node = g.nodes.get(naming.layer_node(ly.id, "decal.normal"))
                if node is not None:
                    cur = Vector([node.inputs[a].default_value for a in "XYZ"])
                    if (cur - n).length > 1e-5:
                        for i, a in enumerate("XYZ"):
                            node.inputs[a].default_value = n[i]


def decal_layers(mat):
    return [ly for ly in mat.realworn.layers if ly.type == "DECAL"]


def delete_decal(empty):
    """Delete the Empty and every Decal layer projecting through it."""
    from . import compiler
    for mat in bpy.data.materials:
        if not mat.realworn.applied:
            continue
        idx = [i for i, ly in enumerate(mat.realworn.layers) if ly.type == "DECAL" and ly.decal.empty == empty]
        if idx:
            with compiler.batch(mat):
                for i in reversed(idx):
                    mat.realworn.layers.remove(i)
                mat.realworn.active_layer_index = max(0, min(mat.realworn.active_layer_index,
                                                             len(mat.realworn.layers) - 1))
            compiler.compile(mat)
    bpy.data.objects.remove(empty)


# ----------------------------------------------------------- compiler side
def build_projection(b, layer, cur, ctx):
    """Projected image alpha * box * facing fade: the decal layer's procedural mask part."""
    d = layer.decal
    if d.empty is None or d.image is None:
        return None
    assets.ensure_groups((naming.SH_DECAL_PROJECT,))
    tc = b.named("ShaderNodeTexCoord", "decal.tc")
    tc.object = d.empty
    pj = b.group(naming.SH_DECAL_PROJECT, "decal.project")
    b.links.new(tc.outputs["Object"], pj.inputs["Vector"])
    im = b.named("ShaderNodeTexImage", "decal.img")
    im.image = d.image
    im.extension = "CLIP"
    b.links.new(pj.outputs["UV"], im.inputs["Vector"])
    nvec = b.named("ShaderNodeCombineXYZ", "decal.normal")  # world direction the decal faces
    n = projection_normal(d.empty)
    for i, axis in enumerate("XYZ"):
        nvec.inputs[axis].default_value = n[i]
    geo = b.named("ShaderNodeNewGeometry", "decal.geo")
    facing = b.vmath("DOT_PRODUCT", geo.outputs["Normal"], nvec.outputs[0])
    fade = b.smooth(facing, 0.45, 0.6)
    ctx["decal_color"] = im.outputs["Color"]
    ctx["decal_image_node"] = im
    ctx["decal_uv"] = pj.outputs["UV"]
    return b.clamp(b.mul_all(im.outputs["Alpha"], pj.outputs["Box"], fade))


def apply_content(b, layer, mask, cur, ctx):
    """FULL: image colour + roughness (+ normal map); GRIME: darken + roughness only (DEC-3);
    DAMAGE: darken and dent."""
    d = layer.decal
    col = ctx.pop("decal_color", None)
    if col is None:
        return
    b.layer_color = col
    darken = b.value_node("decal.darken", d.darken)
    lum = b.lum(col)
    if d.mode == "FULL" and layer.color.enabled:
        cur["Base Color"] = b.mix(mask, cur["Base Color"], col)
    else:  # grime / damage: darken by the image's darkness
        k = b.inv(b.mul_all(mask, b.inv(lum), darken))
        cur["Base Color"] = b.mix(1.0, cur["Base Color"], b.comb(k, k, k), blend="MULTIPLY")
    if layer.roughness.enabled:
        rv = b.value_node("roughness.value", layer.roughness.value)
        cur["Roughness"] = b.mixf(mask, cur["Roughness"], rv)
    if layer.metallic.enabled and d.mode == "FULL":
        mv = b.value_node("metallic.value", layer.metallic.value)
        cur["Metallic"] = b.mixf(mask, cur["Metallic"], mv)
    if d.mode == "DAMAGE":
        if cur["Height"] is None:
            cur["Height"] = b.value_node("h0", 0.0)
        cur["Height"] = b.sub(cur["Height"], b.mul_all(mask, b.inv(lum), 2.0))
        ctx["height_used"] = True
    if d.normal_image is not None and d.mode == "FULL":
        nm_img = b.named("ShaderNodeTexImage", "decal.nrm")
        nm_img.image = d.normal_image
        nm_img.extension = "CLIP"
        b.links.new(ctx["decal_uv"], nm_img.inputs["Vector"])
        nmap = b.named("ShaderNodeNormalMap", "decal.nmap")
        b.links.new(nm_img.outputs["Color"], nmap.inputs["Color"])
        cur["Normal"] = b.mixv(mask, cur["Normal"], nmap.outputs["Normal"])


# ------------------------------------------------------- depsgraph upkeep
_state = {"objects": -1}


def on_depsgraph_update(scene, depsgraph):
    """Rotated Empties update their facing normal; deleted Empties drop their layers' nodes."""
    from . import compiler
    n = len(bpy.data.objects)
    if n < _state["objects"]:
        for mat in bpy.data.materials:
            if mat.realworn.applied and any(ly.type == "DECAL" and ly.decal.empty is None
                                            for ly in mat.realworn.layers):
                g = mat.realworn.stack
                if g is not None and any(nd.name.endswith("::decal.tc") and nd.object is None for nd in g.nodes
                                         if nd.bl_idname == "ShaderNodeTexCoord"):
                    compiler.compile(mat)
    _state["objects"] = n
    for upd in depsgraph.updates:
        idb = upd.id
        if isinstance(idb, bpy.types.Object) and upd.is_updated_transform and idb.get("rw_decal"):
            ob = bpy.data.objects.get(idb.name)
            if ob is not None:
                update_normal(ob)


# ------------------------------------------------------ DEC-5 bake to layer
def bake_into_layer(obj, mat, layer, scene=None):
    """Project the decal (with its painted tears) into the layer's own colour image, turn it into a
    Paint layer and delete the Empty when no other layer still uses it."""
    from . import bake, compiler, images, layers as L
    scene = scene or bpy.context.scene
    if layer.type != "DECAL" or layer.decal.empty is None:
        raise DecalError("not a placed decal layer")
    idx = L.index_of(mat, layer.id)
    res = layer.mask_res or images.texel_resolution(obj)
    tmp_c = bake.new_image("rw_tmp_decal_color", res, "Non-Color")
    tmp_a = bake.new_image("rw_tmp_decal_alpha", res, "Non-Color")
    try:
        bake.bake_layer_view(scene, obj, mat, idx, "COLOR", tmp_c)
        bake.bake_layer_view(scene, obj, mat, idx, "MASK", tmp_a)
        layer = mat.realworn.layers[idx]
        content = images.create_mask(obj, layer, res=res, kind="content")
        bake.compose_rgba(tmp_c, tmp_a, content)
        images.store(content, obj)
    finally:
        for t in (tmp_c, tmp_a):
            bpy.data.images.remove(t)
    empty = layer.decal.empty
    old_mask = layer.mask_image
    with compiler.batch(mat):
        layer.type = "PAINT"
        layer.content_image = content
        layer.mask_image = None
        layer.decal.empty = None
        layer.decal.image = None
        layer.decal.normal_image = None
        layer.color.enabled, layer.color.color, layer.color.source = True, (1.0, 1.0, 1.0), "FLAT"
        layer.threshold, layer.softness = 0.5, 1.0
    compiler.compile(mat)
    if old_mask is not None and old_mask.users == 0:
        bpy.data.images.remove(old_mask)
    still = any(ly.type == "DECAL" and ly.decal.empty == empty for m in bpy.data.materials if m.realworn.applied
                for ly in m.realworn.layers)
    if empty is not None and not still:
        bpy.data.objects.remove(empty)
    return layer

"""v0.7 files: the clean Remove path.

v0.7 weathered materials still carry their snapshot (same format) under the same property names
(applied, snapshot, schema_version 1), so the original tree is restored exactly. Everything else
v0.7 left is removed too: its RW_Masks / RW_Damage modifiers, the rw_paint colour attribute,
object and scene rw_* custom properties, v0.7 decal Empties and node groups. Afterwards the
objects are clean and can be Set Up for painting.
"""

import bpy

from . import naming, nodeutil, snapshot

V07_MODIFIERS = ("RW_Masks", "RW_Damage")
V07_INNER_PREFIX = "RW_Inner_"
V07_GROUPS = ("RW_Stack", "RW_Breakup", "RW_ShadingMasks", "RW_L_EdgeWear", "RW_L_Rust", "RW_L_DecalApply",
              "RW_L_CavityDirt", "RW_L_Grime", "RW_L_Dust", "RW_L_Wetness", "RW_L_WetnessDry", "RW_L_WetnessRain",
              "RW_L_Decal", "RW_BevelEdge", "RW_RayCavity")
V07_SCENE_PROPS = ("rw_age", "rw_dirt", "rw_dust", "rw_wetness", "rw_rain", "rw_ground_z", "rw_splash_height",
                   "rw_preview")
V07_OBJECT_PROPS = ("rw_seed", "rw_wear", "rw_dirt_amt", "rw_is_ground")


def is_v07_material(mat):
    st = getattr(mat, "realworn", None)
    if st is None or mat.node_tree is None or not st.applied:
        return False
    if st.schema_version >= 2 and st.stack is not None:
        return False  # a v2.x or v3 stack
    return any(n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None and n.node_tree.name == "RW_Stack"
               for n in mat.node_tree.nodes) or st.schema_version < 2


def find_v07():
    """{'materials': [...], 'objects': [...]} still carrying v0.7 weathering."""
    mats = [m for m in bpy.data.materials if is_v07_material(m)]
    obs = [o for o in bpy.data.objects if o.type == "MESH" and naming.OB_SETUP not in o and (
        any(k in o for k in V07_OBJECT_PROPS) or "rw_paint" in o.data.color_attributes)]
    return {"materials": mats, "objects": obs}


def remove_v07():
    """Restore every v0.7 material exactly and clear v0.7 data. Returns report tuples."""
    rep = []
    found = find_v07()
    for m in found["materials"]:
        try:
            snap = snapshot.loads(m.realworn.snapshot)
        except ValueError:
            rep.append(("ERROR", "{}: v0.7 snapshot unreadable".format(m.name)))
            continue
        diffs = snapshot.restore(m.node_tree, snap)
        for n in [n for n in m.node_tree.nodes if nodeutil.is_owned(n)]:
            m.node_tree.nodes.remove(n)
        if diffs:
            rep.append(("WARNING", "{}: restored with {} difference(s): {}".format(m.name, len(diffs), diffs[0])))
        st = m.realworn
        st.applied = False
        st.snapshot = ""
        st.mode = ""
        st.schema_version = 0
        for k in ("preset", "decals"):
            if k in st:
                del st[k]
    for o in found["objects"]:
        for mod in [md for md in o.modifiers if md.name in V07_MODIFIERS]:
            o.modifiers.remove(mod)
        me = o.data
        if "rw_paint" in me.color_attributes and me.get("rw_created_paint", True):
            me.color_attributes.remove(me.color_attributes["rw_paint"])
        if "rw_created_paint" in me:
            del me["rw_created_paint"]
        for k in V07_OBJECT_PROPS:
            if k in o:
                del o[k]
    for sc in bpy.data.scenes:
        for k in V07_SCENE_PROPS:
            if k in sc:
                del sc[k]
    for e in [o for o in bpy.data.objects if o.type == "EMPTY" and o.get("rw_decal") and not _v2_decal(o)]:
        bpy.data.objects.remove(e)
    for name in V07_GROUPS:
        g = bpy.data.node_groups.get(name)
        if g is not None and g.users == 0:
            bpy.data.node_groups.remove(g)
    for m in [m for m in bpy.data.materials if m.name.startswith(V07_INNER_PREFIX) and m.users == 0]:
        bpy.data.materials.remove(m)
    rep.append(("INFO", "Removed v0.7 weathering from {} material(s) and {} object(s)".format(
        len(found["materials"]), len(found["objects"]))))
    return rep


def _v2_decal(empty):
    """A v2.x decal projector (handled by the v2 conversion, not by the v0.7 cleanup)."""
    return bool(empty.get("rw_v2_decal"))


# ================================================================ v2.x files
V2_ORDER = ("DIRT", "DUST", "RUST", "WEAR", "SCRATCHES", "WATER", "PAINT", "DAMAGE", "DECAL", "CUSTOM")
V2_MODIFIERS = ("RW_Masks", "RW_Damage", "RW_DisplaceSubdiv")
# v2 type -> (v3 kind, preset): a clear match keeps the painted mask; the rest is reported
V2_TO_V3 = {"PAINT": ("PAINT", None), "DIRT": ("PAINT", None), "DUST": ("PAINT", None), "RUST": ("PAINT", None),
            "CUSTOM": ("PAINT", None), "WEAR": ("REVEAL", None), "SCRATCHES": ("REVEAL", "SCRATCHES"),
            "DAMAGE": ("REVEAL", None)}


def is_v2_material(mat):
    st = getattr(mat, "realworn", None)
    return bool(st is not None and mat.node_tree is not None and st.applied and st.stack is not None
                and st.schema_version == 2)


def find_v2():
    return [m for m in bpy.data.materials if is_v2_material(m)]


def _raw(group, key, default=None):
    try:
        v = group.get(key, default) if group is not None else default
    except (TypeError, AttributeError):
        return default
    return v


def _v2_layers(mat):
    """The old layers as plain dicts, read from the raw ID properties v3 no longer defines."""
    out = []
    for ly in mat.realworn.layers:
        t = _raw(ly, "type", V2_ORDER.index("CUSTOM"))
        kind = V2_ORDER[t] if isinstance(t, int) and 0 <= t < len(V2_ORDER) else str(t)
        color = _raw(ly, "color")
        rough = _raw(ly, "roughness")
        dmg = _raw(ly, "damage")
        dec = _raw(ly, "decal")
        out.append({"type": kind, "name": ly.name, "visible": ly.visible, "opacity": ly.opacity,
                    "mask": ly.mask_image,
                    "color": tuple(_raw(color, "color", (0.5, 0.5, 0.5)))[:3],
                    "roughness": float(_raw(rough, "value", 0.5)),
                    "depth_mm": float(_raw(dmg, "depth_mm", 3.0)),
                    "empty": _raw(dec, "empty")})
    return out


def convert_v2(mat):
    """Convert one v2.x material: restore it exactly from its snapshot, set it up for v3 and rebuild
    the layers that have a clear match, keeping their painted masks. Returns report tuples."""
    from . import compiler, injector, layers as L, naming as N, pbrset, reveal
    rep = []
    if not is_v2_material(mat):
        return [("WARNING", "{}: not a v2.x material".format(mat.name))]
    old = _v2_layers(mat)
    objs = compiler.objects_using(mat)
    for o in objs:
        for mod in [md for md in o.modifiers if md.name in V2_MODIFIERS]:
            o.modifiers.remove(mod)
    for e in {d["empty"] for d in old if isinstance(d["empty"], bpy.types.Object)}:
        bpy.data.objects.remove(e)
    coll = bpy.data.collections.get("RW_Decals")
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)
    keep = [d["mask"] for d in old if d["mask"] is not None]
    for img in keep:
        img.use_fake_user = True  # survive the restore while no layer points at them
    diffs = injector.restore(mat)
    if diffs:
        for img in keep:
            img.use_fake_user = False
        return [("ERROR", "{}: v2 restore mismatch ({} diffs), left as it was: {}".format(
            mat.name, len(diffs), diffs[0]))]
    st = mat.realworn
    st.layers.clear()
    names = {p.identifier for p in st.bl_rna.properties}
    for k in [k for k in st.keys() if k not in names]:
        del st[k]  # v2 / v2.1 material settings v3 does not have
    pbrset.clear(st.base)
    reveal.restore(mat)
    injector.inject(mat)
    st.owner = objs[0].name if objs else st.owner
    for d in old:
        if d["type"] not in V2_TO_V3:
            rep.append(("WARNING", "{} / {}: {} layers have no v3 kind; not converted (Remove and redo, or "
                                   "paint it again)".format(mat.name, d["name"], d["type"].title())))
            continue
        kind, preset = V2_TO_V3[d["type"]]
        with compiler.batch(mat):
            ly = L.add_layer(mat, kind, preset, name=d["name"], index=len(st.layers))
            ly.content, ly.color, ly.roughness = "COLOR", d["color"], d["roughness"]
            ly.visible, ly.opacity = d["visible"], d["opacity"]
            if kind == "REVEAL":
                ly.depth_mm = d["depth_mm"] if d["type"] == "DAMAGE" else (0.3 if preset else 0.0)
                if d["type"] == "WEAR":
                    ly.edge_dark = 0.0
            if d["mask"] is not None:
                ly.mask_image = d["mask"]
                d["mask"][N.IMG_MASK] = "{}/{}".format(st.owner, ly.id)
                if d["mask"].colorspace_settings.name != "Non-Color":
                    d["mask"].colorspace_settings.name = "Non-Color"
        rep.append(("INFO", "{} / {}: {} -> {}{}".format(mat.name, d["name"], d["type"].title(), kind.title(),
                                                       " (painted mask kept)" if d["mask"] is not None else "")))
    for img in keep:
        img.use_fake_user = False
    compiler.compile(mat)
    from . import assets
    assets.remove_unused_groups()  # the v2 node groups nothing uses any more
    rep.append(("INFO", "{}: converted to v3; edge and cavity helpers, Edge Lock, Edge Detail, looks and geometry "
                        "damage are not in v3 (RealWorn 2.1 keeps them)".format(mat.name)))
    return rep


def convert_all_v2():
    rep = []
    for m in find_v2():
        rep += convert_v2(m)
    return rep

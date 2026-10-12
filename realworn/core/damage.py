"""Painted damage (DMG-1..DMG-9). Damage is a layer: you paint where things are broken, and the
layer's Depth decides how real the break is. All three depths read the same painted mask, so
you can paint once and switch later.

SHADER        RW_P_Damage: dent + rim through Bump, inner material in the broken area (default)
DISPLACEMENT  the same height feeds the Material Output Displacement (injector.sync_outputs) and
              RealWorn adds a Subdivision Surface modifier (adaptive in Cycles, fixed level 2 in
              the viewport / EEVEE)
GEOMETRY      RW_Damage modifier: Boolean cutters only where the mask passes Threshold; break
              faces get RW_Inner_<kind>; optional debris on RW_Ground; Apply makes it permanent
"""

import bmesh
import bpy

from . import assets, masks, naming

# DMG-1 inner materials: (base colour, metallic, roughness)
INNER_LOOK = {
    "CONCRETE": ((0.55, 0.53, 0.49), 0.0, 0.95),
    "STEEL": ((0.56, 0.57, 0.58), 1.0, 0.35),
    "WOOD": ((0.62, 0.45, 0.27), 0.0, 0.8),
    "BRICK": ((0.48, 0.20, 0.12), 0.0, 0.9),
    "PBRSET": ((0.5, 0.5, 0.5), 0.0, 0.8),
}


class DamageError(Exception):
    pass


# ---------------------------------------------------------------- queries
def damage_modifier(obj):
    m = obj.modifiers.get(naming.MOD_DAMAGE)
    return m if m is not None and m.type == "NODES" else None


def subdiv_modifier(obj):
    return obj.modifiers.get(naming.MOD_DISP_SUBDIV)


def manifold_problem(obj):
    """DMG-9: None if the mesh is closed and manifold, else a short reason."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        if not bm.faces:
            return "has no faces"
        bad = sum(1 for e in bm.edges if not e.is_manifold)
        if bad:
            return "{} non-manifold or open edge(s)".format(bad)
        return None
    finally:
        bm.free()


def coarse_for_displacement(obj, mm=3.0):
    """DMG-9: suggested subdivision level when the mesh is too coarse for displacement detail
    (0 = fine). Aims for edges under ~8x the dent depth."""
    me = obj.data
    if not me.edges:
        return 0
    mean = sum((me.vertices[e.vertices[0]].co - me.vertices[e.vertices[1]].co).length for e in me.edges) / len(me.edges)
    mean *= max(abs(s) for s in obj.scale)
    target = max(mm * 0.008, 1e-3)
    level = 0
    while mean > target and level < 6:
        mean *= 0.5
        level += 1
    return level


def damage_layers(mat, mode=None):
    return [ly for ly in mat.realworn.layers if ly.visible and ly.type == "DAMAGE"
            and (mode is None or ly.damage.depth_mode == mode)]


# ----------------------------------------------------------- inner material
def inner_material(kind):
    """RW_Inner_<kind> for Geometry-mode break faces (plain Principled with the inner look)."""
    name = naming.inner_material_name(kind.lower())
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        col, metal, rough = INNER_LOOK.get(kind, INNER_LOOK["CONCRETE"])
        bsdf.inputs["Base Color"].default_value = (*col, 1.0)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
        mat["rw_created"] = True
    return mat


def set_inner(layer):
    """DMG-1: choosing an inner material sets the layer's channels to its look."""
    col, metal, rough = INNER_LOOK.get(layer.damage.inner, INNER_LOOK["CONCRETE"])
    layer.color.color = col
    layer.metallic.value = metal
    layer.roughness.value = rough


# ------------------------------------------------------------- shader block
def content_mask(b, layer, mask, ctx):
    """Build the dent group first; the layer's channels (inner material) blend by its Reveal Mask."""
    d = layer.damage
    raw = getattr(b, "raw_mask", None)
    g = b.group(naming.SH_DAMAGE, "damage", Mask=mask, Raw=raw if raw is not None else mask, Depth=d.depth_mm,
                Rim_Height=d.rim_height, Rim_Width=d.rim_width, Rim_Brightness=d.rim_brightness,
                Sharpness=d.sharpness, Reveal=d.reveal)
    ctx["damage_group"] = g
    return b.outp(g, "Reveal Mask")


def apply_shader(b, layer, mask, cur, ctx):
    """Rim brightening and the dent height; Displacement mode routes the height to displacement."""
    d = layer.damage
    g = ctx.pop("damage_group", None) or b.nodes[naming.layer_node(layer.id, "damage")]
    cur["Base Color"] = b.mix(b.outp(g, "Brighten"), cur["Base Color"], (1.0, 1.0, 1.0))
    height = b.outp(g, "Height")
    if d.depth_mode == "DISPLACEMENT":
        ctx["displacement"] = height if ctx["displacement"] is None else b.add(ctx["displacement"], height)
    elif d.depth_mode == "SHADER":
        if cur["Height"] is None:
            cur["Height"] = b.value_node("h0", 0.0)
        cur["Height"] = b.add(cur["Height"], height)
        ctx["height_used"] = True
    # GEOMETRY: the cut is real geometry; the shader only shows the inner look and the rim colour


_SHADER_INPUTS = {"depth_mm": "Depth", "rim_height": "Rim Height", "rim_width": "Rim Width",
                  "rim_brightness": "Rim Brightness", "sharpness": "Sharpness", "reveal": "Reveal"}
_GEO_INPUTS = {"threshold": "Threshold", "density": "Density", "size_min": "Size Min", "size_max": "Size Max",
               "debris": "Debris"}


def value_targets(layer, prop):
    sock = _SHADER_INPUTS.get(prop)
    return [("damage", sock, getattr(layer.damage, prop))] if sock else []


def on_value(mat, layer, prop):
    """Geometry-mode values go to the RW_Damage modifier (no shader recompile). Returns True when
    handled, None to fall through to the shader targets."""
    if prop not in _GEO_INPUTS:
        return None
    from . import compiler
    for obj in compiler.objects_using(mat):
        mod = damage_modifier(obj)
        if mod is not None:
            masks.set_input(mod, _GEO_INPUTS[prop], getattr(layer.damage, prop))
    return True


# --------------------------------------------------------------- modifiers
def sync(mat):
    """After a compile: each object using `mat` gets RW_Damage while a Geometry-mode Damage layer
    exists, and the displacement subdivision while a Displacement-mode one does."""
    from . import compiler
    geo = damage_layers(mat, "GEOMETRY")
    disp = damage_layers(mat, "DISPLACEMENT")
    for obj in compiler.objects_using(mat):
        if geo:
            ensure_geometry(obj, geo[0])
        else:
            remove_geometry(obj)
        if disp:
            ensure_subdiv(obj)
        else:
            remove_subdiv(obj)


def ensure_geometry(obj, layer):
    why = manifold_problem(obj)
    if why:
        layer.damage["rw_warning"] = "{}: {}; Geometry damage needs a closed mesh".format(obj.name, why)
        remove_geometry(obj)
        return None
    if "rw_warning" in layer.damage:
        del layer.damage["rw_warning"]
    assets.ensure_groups((naming.GN_DAMAGE,))
    mod = damage_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(naming.MOD_DAMAGE, "NODES")
        mod.node_group = bpy.data.node_groups[naming.GN_DAMAGE]
        mod.show_expanded = False
    masks.place_modifier(obj, mod)
    mm = masks.masks_modifier(obj)
    if mm is not None:
        masks.place_modifier(obj, mm)
    d = layer.damage
    masks.set_input(mod, "Mask", layer.mask_image)
    masks.set_input(mod, "Inner Material", inner_material(d.inner))
    for prop, sock in _GEO_INPUTS.items():
        masks.set_input(mod, sock, getattr(d, prop))
    ground = masks.ensure_collection(naming.COLL_GROUND)
    masks.set_input(mod, "Ground", None if obj.name in ground.objects else ground)  # no self-cycle
    return mod


def remove_geometry(obj):
    mod = damage_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)
        return True
    return False


def ensure_subdiv(obj, viewport_levels=2):
    mod = subdiv_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(naming.MOD_DISP_SUBDIV, "SUBSURF")
        mod.subdivision_type = "SIMPLE"
        mod.levels = viewport_levels
        mod.render_levels = viewport_levels + 1
        mod.show_expanded = False
    if hasattr(mod, "use_adaptive_subdivision"):
        mod.use_adaptive_subdivision = True  # Cycles dices adaptively; EEVEE uses the fixed levels
    return mod


def remove_subdiv(obj):
    mod = subdiv_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)


def refresh_live(image):
    """DMG-4: after a stroke, re-cut objects whose Geometry-mode Damage layer uses `image`."""
    n = 0
    for mat in bpy.data.materials:
        if not mat.realworn.applied:
            continue
        for ly in damage_layers(mat, "GEOMETRY"):
            if ly.mask_image == image and ly.damage.live:
                from . import compiler
                for obj in compiler.objects_using(mat):
                    obj.update_tag()
                    n += 1
    return n


def apply_geometry(obj):
    """DMG-8: make Geometry-mode damage permanent (the modifier is applied to the mesh)."""
    from . import ctx
    mod = damage_modifier(obj)
    if mod is None:
        return False
    with bpy.context.temp_override(**ctx.override(obj)):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return True


def add_dirt_in_damage(mat, damage_layer):
    """DMG-6: a Dirt layer above the Damage layer whose mask references it."""
    from . import compiler, layers
    idx = layers.index_of(mat, damage_layer.id)
    ly = layers.add_layer(mat, "DIRT", name="Dirt in " + damage_layer.name, index=idx + 1)
    with compiler.batch(mat):
        ing = ly.ingredients.add()
        ing.kind = "REFERENCE"
        ing.ref_layer_id = damage_layer.id
        ing.amount = 1.0
        ly.threshold, ly.softness = 0.3, 0.6
    compiler.compile(mat)
    return ly

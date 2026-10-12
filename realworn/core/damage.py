"""Damage (DMG-1..DMG-9).

v2 P1 state: the v0.7 RW_Damage modifier helpers (seed/strength cutters) are kept for P6, which
makes damage a painted layer (Shader, Displacement and Geometry depth). The compiler hooks
apply_shader / on_value / value_targets are no-ops until then.
"""

import bmesh
import bpy

from . import assets, masks, naming

# preset -> inner material kind; kind -> (base color, metallic, roughness)
INNER_KIND = {"painted_metal": "steel", "bare_metal": "steel", "concrete": "concrete", "wood": "wood",
              "plastic": "plastic"}
INNER_LOOK = {
    "steel": ((0.55, 0.55, 0.56), 1.0, 0.35),
    "concrete": ((0.62, 0.60, 0.56), 0.0, 0.95),
    "wood": ((0.75, 0.58, 0.38), 0.0, 0.80),
    "plastic": ((0.85, 0.84, 0.80), 0.0, 0.60),
}
DEFAULTS = {"Strength": 0.5, "Seed": 0, "Size Min": 0.03, "Size Max": 0.08, "Density": 6.0, "Corners": True,
            "Debris": False}


class DamageError(Exception):
    pass


def damage_modifier(obj):
    m = obj.modifiers.get(naming.MOD_DAMAGE)
    return m if m is not None and m.type == "NODES" else None


def manifold_problem(obj):
    """None if the mesh is closed and manifold, else a short reason (DMG-6)."""
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


def inner_material(kind):
    """RW_Inner_<kind>: raw concrete, bare steel, light raw wood or whitened plastic."""
    name = naming.inner_material_name(kind)
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        col, metal, rough = INNER_LOOK[kind]
        bsdf.inputs["Base Color"].default_value = (*col, 1.0)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
    return mat


def add_damage(obj, scene=None, settings=None):
    """Add (or update) RW_Damage. Raises DamageError for non-manifold meshes."""
    if not masks.is_supported(obj):
        raise DamageError("{}: not a local mesh".format(obj.name))
    why = manifold_problem(obj)
    if why:
        raise DamageError("{}: {}, damage needs a closed manifold mesh".format(obj.name, why))
    assets.ensure_groups((naming.GN_DAMAGE,))
    mod = damage_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(naming.MOD_DAMAGE, "NODES")
        mod.node_group = bpy.data.node_groups[naming.GN_DAMAGE]
        mod.show_expanded = False
        for k, v in DEFAULTS.items():
            masks.set_input(mod, k, v)
    masks.place_modifier(obj, mod)
    if masks.masks_modifier(obj) is not None:
        masks.place_modifier(obj, masks.masks_modifier(obj))
    masks.set_input(mod, "Inner Material", inner_material((settings or {}).pop("inner", "concrete")))
    ground = masks.ensure_collection(naming.COLL_GROUND)
    masks.set_input(mod, "Ground", None if obj.name in ground.objects else ground)  # no self-cycle
    for k, v in (settings or {}).items():
        masks.set_input(mod, k, v)
    return mod


def set_show_viewport(obj, state):
    """DMG-8: Boolean evaluation is the slowest part; hide it in the viewport, keep it in renders."""
    mod = damage_modifier(obj)
    if mod is not None:
        mod.show_viewport = state


def remove_damage(obj):
    mod = damage_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)
        return True
    return False


remove_geometry = remove_damage


# ------------------------------------------------------- compiler hooks (P6)
def apply_shader(b, layer, mask, cur, ctx):
    return None


def on_value(mat, layer, prop):
    return None


def value_targets(layer, prop):
    return []

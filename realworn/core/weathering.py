"""Per-object orchestration: Apply, Update, Remove, Remove All (W1, W8).

Operators call these; tests call them directly with explicit datablocks.
"""

import zlib

import bpy

from . import assets, injector, masks, naming, preview


def stable_seed(name):
    """Seed from a stable hash of the object name (independent of Python's hash salt)."""
    return float(zlib.crc32(name.encode("utf-8")) % 10007) / 10.0


def _put(idblock, key, value):
    if idblock.get(key) != value:
        idblock[key] = value
        return True
    return False


def ensure_scene_defaults(scene):
    """The v0.7 stack reads fixed scene values (the weather sliders were removed in v2 P0)."""
    for k, v in naming.SCENE_DEFAULTS.items():
        if k not in scene:
            scene[k] = v


def sync_object(obj):
    """Mirror per-object values into rw_* custom properties read by Attribute (Object) nodes."""
    p = obj.realworn
    changed = False
    changed |= _put(obj, naming.OB_SEED, float(p.seed))
    changed |= _put(obj, naming.OB_WEAR, float(p.wear))
    changed |= _put(obj, naming.OB_DIRT, float(p.dirt))
    changed |= _put(obj, naming.OB_GROUND, 1.0 if p.is_ground else 0.0)
    if changed:
        obj.update_tag()
    return changed


def clear_object(obj):
    for k in naming.OBJECT_PROPS:
        if k in obj:
            del obj[k]


def materials_of(obj):
    seen = []
    for slot in obj.material_slots:
        m = slot.material
        if m is not None and m not in seen:
            seen.append(m)
    return seen


def users_of(mat):
    return [o for o in bpy.data.objects if o.type == "MESH" and mat in materials_of(o)]


def apply_object(obj, scene, preset="AUTO", mask_settings=None):
    """Weather one object. Returns a list of (level, message) report tuples."""
    rep = []
    if not masks.is_supported(obj):
        return [("WARNING", "{}: not a local mesh, skipped".format(obj.name))]
    masks.ensure_masks(obj, mask_settings)
    p = obj.realworn
    if not p.applied:
        p.seed = stable_seed(obj.name)
        p.applied = True
    p.preset = preset
    sync_object(obj)
    ensure_scene_defaults(scene)
    if not obj.material_slots or all(s.material is None for s in obj.material_slots):
        rep.append(("WARNING", "{}: no material, only masks were added".format(obj.name)))
    for mat in materials_of(obj):
        try:
            state = injector.apply(mat, preset, obj.name)
            if state == "applied" and mat.users > 1:
                n = len(users_of(mat))
                if n > 1:
                    rep.append(("INFO", "{}: shared by {} objects (masks and seeds stay per object)".format(mat.name, n)))
        except injector.InjectError as ex:
            rep.append(("WARNING", str(ex)))
    injector.update_sources(obj, scene)
    return rep


def update_object(obj, scene, preset=None):
    """Re-apply preset values without re-injecting."""
    preset = preset or obj.realworn.preset or "AUTO"
    obj.realworn.preset = preset
    for mat in materials_of(obj):
        if injector.is_applied(mat):
            injector.set_preset_values(mat, injector.resolve_preset(mat, preset, obj.name))
    sync_object(obj)


def remove_object(obj, scene=None):
    """Remove RealWorn from one object. Shared materials are restored only when no other
    weathered object still uses them. Returns report tuples."""
    rep = []
    from . import damage  # late import: damage builds on masks
    damage.remove_damage(obj)
    for mat in materials_of(obj):
        others = [o for o in users_of(mat) if o is not obj and o.realworn.applied]
        if others:
            rep.append(("INFO", "{}: kept, still used by {}".format(mat.name, others[0].name)))
            continue
        preview.disable(mat) if preview.PREVIEW_KEY in mat else None
        diffs = injector.remove(mat)
        if diffs:
            rep.append(("ERROR", "{}: restore mismatch ({} diffs), snapshot kept: {}".format(
                mat.name, len(diffs), diffs[0])))
    masks.remove_masks(obj)
    coll = bpy.data.collections.get(naming.COLL_GROUND)
    if coll is not None and obj.name in coll.objects:
        coll.objects.unlink(obj)
    clear_object(obj)
    p = obj.realworn
    p.applied = False
    p.preset = ""
    p.is_ground = False
    return rep


def remove_all():
    """W8: remove every trace of RealWorn from the file."""
    rep = []
    preview.restore_all()
    from . import decals
    decals.remove_all_decals()
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and (obj.realworn.applied or masks.masks_modifier(obj)
                                   or obj.modifiers.get(naming.MOD_DAMAGE)):
            obj.realworn.applied = False  # so shared materials are not kept for each other
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and (masks.masks_modifier(obj) or obj.modifiers.get(naming.MOD_DAMAGE)
                                   or obj.get(naming.OB_SEED) is not None):
            rep += remove_object(obj)
    for mat in list(bpy.data.materials):
        if injector.is_applied(mat):
            diffs = injector.remove(mat)
            if diffs:
                rep.append(("ERROR", "{}: restore mismatch, snapshot kept".format(mat.name)))
        if mat.name.startswith(naming.INNER_PREFIX) and mat.users == 0:
            bpy.data.materials.remove(mat)
    for name in (naming.COLL_GROUND, naming.COLL_DECALS):
        coll = bpy.data.collections.get(name)
        if coll is not None:
            bpy.data.collections.remove(coll)
    for scene in bpy.data.scenes:
        for k in naming.SCENE_PROPS:
            if k in scene:
                del scene[k]
    assets.remove_unused_groups()
    return rep

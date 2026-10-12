"""Per-object orchestration: Apply, Update, Remove, Remove All (W1, W8).

Operators call these; tests call them directly with explicit datablocks.
"""

import bpy

from . import assets, injector, masks, naming, preview, weather


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
        p.seed = weather.stable_seed(obj.name)
        p.applied = True
    p.preset = preset
    weather.sync_object(obj)
    weather.sync_scene(scene)
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
    weather.sync_object(obj)


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
    for coll_name in (naming.COLL_GROUND, naming.COLL_OCCLUDERS):
        coll = bpy.data.collections.get(coll_name)
        if coll is not None and obj.name in coll.objects:
            coll.objects.unlink(obj)
    weather.clear_object(obj)
    p = obj.realworn
    p.applied = False
    p.preset = ""
    p.is_ground = False
    p.is_occluder = False
    if scene is not None:
        weather.update_ground_z(scene)
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
    for name in (naming.COLL_GROUND, naming.COLL_OCCLUDERS, naming.COLL_DECALS):
        coll = bpy.data.collections.get(name)
        if coll is not None:
            bpy.data.collections.remove(coll)
    for scene in bpy.data.scenes:
        for k in naming.SCENE_PROPS:
            if k in scene:
                del scene[k]
    assets.remove_unused_groups()
    return rep

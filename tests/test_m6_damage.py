"""M6 acceptance: Boolean chips and corner breaks, rw_damage, inner material, non-destructive
and removable, manifold check, seed, debris, viewport toggle."""

import time

import bpy
import pytest

from fixtures import make_scenes as ms
from perf_log import record
from realworn.core import damage, masks, naming, weather, weathering


def _evaluated(ob, depsgraph=None):
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    dg.update()
    e = ob.evaluated_get(dg)
    me = e.to_mesh()
    inner = {i for i, m in enumerate(me.materials) if m and m.name.startswith(naming.INNER_PREFIX)}
    out = {
        "verts": len(me.vertices),
        "co": [ob.matrix_world @ v.co for v in me.vertices],
        "inner_faces": sum(1 for p in me.polygons if p.material_index in inner),
        "attrs": {a.name: [d.value for d in a.data] for a in me.attributes
                  if a.name in (naming.ATTR_DAMAGE, naming.ATTR_EDGE) and a.data_type == "FLOAT"},
        "names": sorted(a.name for a in me.attributes),
    }
    e.to_mesh_clear()
    return out


@pytest.fixture
def setup(empty_scene):
    sc = empty_scene
    floor = ms.street(sc)
    box = ms.sharp_cube(sc, name="Block", size=1.0, cuts=6, location=(0, 0, 0.6),
                        material=ms.principled("BlockMat", (0.55, 0.53, 0.5), roughness=0.85))
    weathering.apply_object(floor, sc, "concrete")
    weathering.apply_object(box, sc, "concrete")
    weather.mark_ground(floor, sc)
    return sc, floor, box


def test_chips_inner_material_and_rw_damage(setup):
    sc, floor, box = setup
    before = _evaluated(box)
    t = time.perf_counter()
    mod = damage.add_damage(box, sc, {"Strength": 0.7})
    r = _evaluated(box)
    dt = time.perf_counter() - t
    print("\n[damage] verts {} -> {}, inner faces {}, eval {:.3f} s".format(before["verts"], r["verts"],
                                                                           r["inner_faces"], dt))
    record("RW_Damage add + evaluate, 1 m cube (6 cuts), strength 0.7", dt, "s", None)
    names = [m.name for m in box.modifiers]
    assert names.index(naming.MOD_DAMAGE) < names.index(naming.MOD_MASKS)  # DMG-1: before the masks
    assert r["inner_faces"] > 50
    dmg = r["attrs"][naming.ATTR_DAMAGE]
    assert sum(v > 0.5 for v in dmg) > 50
    assert naming.ATTR_CUT not in r["names"] and naming.ATTR_CORNER not in r["names"]
    # chips are inside the masks' reach: break rims get edge wear too
    edge = r["attrs"][naming.ATTR_EDGE]
    rim = [e for e, d in zip(edge, dmg) if 0.1 < d < 0.9]
    print("[damage] mean rw_edge on break rims {:.3f}".format(sum(rim) / len(rim)))
    assert sum(rim) / len(rim) > 0.3
    inner = masks.get_input(mod, "Inner Material")
    assert inner.name == naming.inner_material_name("concrete") and inner.realworn.applied


def test_non_destructive_and_removable(setup):
    sc, floor, box = setup
    n_orig = len(box.data.vertices)
    clean = _evaluated(box)
    damage.add_damage(box, sc)
    assert len(box.data.vertices) == n_orig  # mesh data untouched (modifier based)
    assert damage.remove_damage(box)
    assert naming.MOD_DAMAGE not in box.modifiers
    assert _evaluated(box)["verts"] == clean["verts"]


def test_non_manifold_skipped(empty_scene):
    plane = bpy.data.objects.new("Plane", bpy.data.meshes.new("Plane"))
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=1.0)
    bm.to_mesh(plane.data)
    empty_scene.collection.objects.link(plane)
    with pytest.raises(damage.DamageError, match="manifold"):
        damage.add_damage(plane, empty_scene)
    assert not plane.modifiers


def test_seed_changes_layout_strength_scales(setup):
    sc, floor, box = setup
    mod = damage.add_damage(box, sc, {"Strength": 0.6, "Seed": 1})
    a = _evaluated(box)
    masks.set_input(mod, "Seed", 2)
    b = _evaluated(box)
    masks.set_input(mod, "Seed", 1)
    a2 = _evaluated(box)
    assert a["verts"] != b["verts"] and a["verts"] == a2["verts"]  # same seed, same result
    masks.set_input(mod, "Strength", 0.15)
    weak = _evaluated(box)
    print("\n[damage] inner faces at strength 0.6 vs 0.15: {} vs {}".format(a["inner_faces"], weak["inner_faces"]))
    assert weak["inner_faces"] < a["inner_faces"]


def test_corner_breaks(setup):
    sc, floor, box = setup
    mod = damage.add_damage(box, sc, {"Strength": 0.0, "Corners": True, "Density": 0.0})
    with_c = _evaluated(box)
    masks.set_input(mod, "Corners", False)
    without = _evaluated(box)
    print("\n[damage] corner-only inner faces with/without corners: {} / {}".format(
        with_c["inner_faces"], without["inner_faces"]))
    assert with_c["inner_faces"] > 0 and without["inner_faces"] == 0


def test_debris_lands_on_ground(setup):
    sc, floor, box = setup
    damage.add_damage(box, sc, {"Strength": 0.8, "Debris": True})
    r = _evaluated(box)
    low = [c for c in r["co"] if c.z < 0.08]  # the block's base is at z = 0.1
    print("\n[damage] debris vertices on the ground: {}".format(len(low)))
    assert low and min(c.z for c in low) > -0.1


def test_viewport_toggle(setup):
    sc, floor, box = setup
    mod = damage.add_damage(box, sc, {"Strength": 0.7})
    damage.set_show_viewport(box, False)
    assert mod.show_viewport is False and mod.show_render is True
    weathering.remove_object(box, sc)  # Remove on the object also removes its damage
    assert naming.MOD_DAMAGE not in box.modifiers

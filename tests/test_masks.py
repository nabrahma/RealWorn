"""M1 mask engine acceptance tests (PRD M1, MASK-1..MASK-9)."""

import time

import bpy
import pytest

from fixtures import make_scenes as ms
from realworn.core import masks, naming, preview

EPS = 1e-4


def _eval(ob):
    masks.ensure_masks(ob)
    return masks.read_masks(ob, bpy.context.evaluated_depsgraph_get())


def _mean(vals):
    return sum(vals) / len(vals) if vals else float("nan")


def _local(ob, co):
    return ob.matrix_world.inverted() @ co


def _on_cube_edge(p, h):
    return sum(abs(abs(c) - h) < EPS for c in p) >= 2


def _face_centre(p, h, margin):
    """On a face, at least `margin` away from every edge of that face."""
    on_face = [abs(abs(c) - h) < EPS for c in p]
    if sum(on_face) != 1:
        return False
    return all(on or abs(c) < h - margin for c, on in zip(p, on_face))


@pytest.mark.parametrize("maker", [ms.sharp_cube, ms.lowpoly_cube])
def test_edge_thresholds_on_cubes(empty_scene, maker):
    ob = maker(empty_scene)
    r = _eval(ob)
    pts = [_local(ob, c) for c in r["co"]]
    edge_vals = [v for p, v in zip(pts, r[naming.ATTR_EDGE]) if _on_cube_edge(p, 1.0)]
    face_vals = [v for p, v in zip(pts, r[naming.ATTR_EDGE]) if _face_centre(p, 1.0, 0.4)]
    assert edge_vals and face_vals
    print("\n[{}] edge mean on 90deg edges {:.3f} ({} pts), face centres {:.3f} ({} pts)".format(
        ob.name, _mean(edge_vals), len(edge_vals), _mean(face_vals), len(face_vals)))
    assert _mean(edge_vals) >= 0.7
    assert _mean(face_vals) <= 0.1


def test_bevel_cube_edges(empty_scene):
    """A 4 cm, 3-segment bevel: inner bevel edges are 30 deg (detected), the boundary rows
    15 deg (not). Wear covers the middle of the bevel; a bevel much wider than Edge Width
    needs a wider Edge Width to be fully covered (documented in M1 notes)."""
    ob = ms.bevel_cube(empty_scene)
    r = _eval(ob)
    pts = [_local(ob, c) for c in r["co"]]
    arc = [v for p, v in zip(pts, r[naming.ATTR_EDGE]) if sum(abs(c) > 1.0 - 0.04 + EPS for c in p) >= 2]
    mid = [v for p, v in zip(pts, r[naming.ATTR_EDGE])
           if sum(abs(c) > 0.975 for c in p) >= 2 and sum(abs(c) > 0.999 for c in p) == 0]
    face = [v for p, v in zip(pts, r[naming.ATTR_EDGE]) if sum(abs(c) > 0.999 for c in p) == 1
            and sum(abs(c) < 0.6 for c in p) == 2]
    print("\n[bevel] arc mean {:.3f} ({}), arc middle {:.3f} ({}), face {:.3f} ({})".format(
        _mean(arc), len(arc), _mean(mid), len(mid), _mean(face), len(face)))
    assert _mean(mid) >= 0.7
    assert _mean(arc) >= 0.5
    assert _mean(face) <= 0.1
    masks.set_input(masks.masks_modifier(ob), "Edge Width", 0.04)
    r2 = masks.read_masks(ob, bpy.context.evaluated_depsgraph_get())
    arc2 = [v for p, v in zip(pts, r2[naming.ATTR_EDGE]) if sum(abs(c) > 1.0 - 0.04 + EPS for c in p) >= 2]
    print("[bevel] arc mean with Edge Width 0.04: {:.3f}".format(_mean(arc2)))
    assert _mean(arc2) >= 0.7


def test_cavity_in_inside_corner(empty_scene):
    ob = ms.l_block(empty_scene)
    r = _eval(ob)
    pts = [_local(ob, c) for c in r["co"]]
    corner = [v for p, v in zip(pts, r[naming.ATTR_CAVITY]) if abs(p.x - 1) < EPS and abs(p.z - 1) < EPS]
    far = [v for p, v in zip(pts, r[naming.ATTR_CAVITY]) if abs(p.z) < EPS and p.x > 1.5]
    print("\n[L] cavity inside corner {:.3f} ({}), far floor {:.3f}".format(_mean(corner), len(corner), _mean(far)))
    assert _mean(corner) >= 0.6
    assert _mean(far) <= 0.1
    # the convex outer edges are not cavities
    outer = [v for p, v in zip(pts, r[naming.ATTR_CAVITY]) if abs(p.x - 2) < EPS and abs(p.z - 1) < EPS]
    assert _mean(outer) <= 0.1


def test_lowpoly_auto_presubdivide(empty_scene):
    ob = ms.lowpoly_cube(empty_scene)
    r = _eval(ob)
    assert len(ob.data.vertices) == 8
    assert len(r["co"]) > 8 * 20, "auto pre-subdivide should add vertices to hold the band"
    mod = masks.masks_modifier(ob)
    masks.set_input(mod, "Pre-Subdivide", 0)
    r0 = masks.read_masks(ob, bpy.context.evaluated_depsgraph_get())
    assert len(r0["co"]) == 8


def test_widths_respect_object_scale(empty_scene):
    a = ms.sharp_cube(empty_scene, name="Unit", size=2.0, cuts=31, location=(0, 0, 1))
    b = ms.sharp_cube(empty_scene, name="Scaled", size=0.2, cuts=31, location=(5, 0, 1))
    b.scale = (10, 10, 10)
    for o in (a, b):
        masks.ensure_masks(o, {"Pre-Subdivide": 0, "Edge Width": 0.15})
    dg = bpy.context.evaluated_depsgraph_get()
    ra, rb = masks.read_masks(a, dg), masks.read_masks(b, dg)
    diff = max(abs(x - y) for x, y in zip(ra[naming.ATTR_EDGE], rb[naming.ATTR_EDGE]))
    print("\n[scale] max per-vertex edge difference unit vs 10x scaled: {:.4f}".format(diff))
    assert diff < 1e-3
    # a scale-unaware mask would give the scaled cube a 10x narrower band
    assert _mean(rb[naming.ATTR_EDGE]) > 0.05


def test_modifier_order_keeps_subsurf_last(empty_scene):
    ob = ms.sharp_cube(empty_scene, cuts=2)
    ob.modifiers.new("Bevel", "BEVEL")
    ob.modifiers.new("Subsurf", "SUBSURF")
    masks.ensure_masks(ob)
    assert [m.type for m in ob.modifiers] == ["BEVEL", "NODES", "SUBSURF"]
    assert ob.modifiers[1].name == naming.MOD_MASKS


def test_remove_masks_restores_mesh(empty_scene):
    ob = ms.sharp_cube(empty_scene, cuts=2)
    masks.ensure_masks(ob)
    assert naming.ATTR_PAINT in ob.data.color_attributes
    masks.remove_masks(ob)
    assert not ob.modifiers
    assert naming.ATTR_PAINT not in ob.data.color_attributes


def test_contact_and_shelter(empty_scene):
    floor = ms.street(empty_scene)
    box = ms.sharp_cube(empty_scene, size=1.0, cuts=8, location=(0, 0, 0.5))
    rf = ms.roof(empty_scene, size=(3, 3, 0.1), location=(0, 0, 2.5))
    from realworn.core import weather
    weather.mark_ground(floor, empty_scene)
    weather.mark_occluder(rf)
    r = _eval(box)
    pts = [_local(box, c) for c in r["co"]]
    low = [v for p, v in zip(pts, r[naming.ATTR_CONTACT]) if p.z < -0.45]
    high = [v for p, v in zip(pts, r[naming.ATTR_CONTACT]) if p.z > 0.45]
    shel = _mean(r[naming.ATTR_SHELTER])
    print("\n[contact] bottom {:.3f} top {:.3f}; shelter mean under roof {:.3f}".format(_mean(low), _mean(high), shel))
    assert _mean(low) > 0.8 and _mean(high) < 0.05
    assert shel > 0.9
    weather.mark_occluder(rf, False)
    r2 = masks.read_masks(box, bpy.context.evaluated_depsgraph_get())
    assert _mean(r2[naming.ATTR_SHELTER]) < 0.05


def test_non_mesh_rejected(empty_scene):
    cu = bpy.data.objects.new("Curve", bpy.data.curves.new("c", "CURVE"))
    empty_scene.collection.objects.link(cu)
    assert not masks.is_supported(cu)
    with pytest.raises(TypeError):
        masks.ensure_masks(cu)


def test_mask_preview_roundtrip(empty_scene):
    mat = ms.principled("PreviewMat")
    ob = ms.sharp_cube(empty_scene, cuts=4, material=mat)
    masks.ensure_masks(ob)
    out = mat.node_tree.nodes["Material Output"]
    before = out.inputs["Surface"].links[0].from_node.name
    n_nodes = len(mat.node_tree.nodes)
    preview.set_preview(empty_scene, "EDGE")
    assert out.inputs["Surface"].links[0].from_node.name == "RW::preview"
    assert empty_scene[naming.SC_PREVIEW] == 1.0
    preview.set_preview(empty_scene, "CAVITY")
    assert mat.node_tree.nodes["RW::preview_attr"].attribute_name == naming.ATTR_CAVITY
    preview.set_preview(empty_scene, "NONE")
    assert out.inputs["Surface"].links[0].from_node.name == before
    assert len(mat.node_tree.nodes) == n_nodes


def test_masks_performance_100k(empty_scene):
    """MASK-8: a dense sharp cube (~100k verts, 12 convex edges) is the worst realistic case:
    proximity to many edge segments plus blur over every vertex."""
    ob = ms.sharp_cube(empty_scene, name="Dense", cuts=128)
    nverts = len(ob.data.vertices)
    masks.ensure_masks(ob, {"Pre-Subdivide": 0})
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    mod = masks.masks_modifier(ob)
    times = []
    for i in range(4):
        masks.set_input(mod, "Edge Width", 0.015 + 0.001 * (i + 1))
        t = time.perf_counter()
        dg.update()
        times.append(time.perf_counter() - t)
    r = masks.read_masks(ob, dg)
    assert len(r["co"]) == nverts and max(r[naming.ATTR_EDGE]) > 0.99  # evaluation really ran
    best, worst = min(times), max(times)
    print("\n[perf] RW_Masks on {} verts: depsgraph update best {:.1f} ms, worst {:.1f} ms".format(
        nverts, best * 1000, worst * 1000))
    from perf_log import record
    record("RW_Masks evaluation, {}k-vert sharp cube".format(nverts // 1000), best * 1000, "ms", 200,
           "best of 4 headless depsgraph updates")
    assert best < 0.2


def test_no_self_referencing_collections(empty_scene):
    """A ground object reading RW_Ground (or an occluder reading RW_Occluders) is a depsgraph
    cycle that made other objects see stale ground geometry on first evaluation."""
    from realworn.core import weather
    floor = ms.street(empty_scene)
    roof = ms.roof(empty_scene)
    for o in (floor, roof):
        masks.ensure_masks(o)
    weather.mark_ground(floor, empty_scene)
    weather.mark_occluder(roof)
    fm, rm = masks.masks_modifier(floor), masks.masks_modifier(roof)
    assert masks.get_input(fm, "Ground") is None and masks.get_input(fm, "Use Contact") is False
    assert masks.get_input(rm, "Occluders") is None and masks.get_input(rm, "Use Shelter") is False
    weather.mark_ground(floor, empty_scene, False)
    assert masks.get_input(fm, "Ground").name == naming.COLL_GROUND

"""PRD v2.1 damage carving: DMG-10 / DMG-11 (Follow Base) and acceptance test T11, DMG-12 (Edge
Detail on damage), DMG-13 (adaptive dicing, object space when instanced), DMG-14 (cutters follow
the carve)."""

import os

import bpy
import numpy as np
import pytest

import sharp_util as su
from perf_log import record
from realworn.core import compiler, damage, detail, layers, masks, naming

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")


@pytest.fixture
def bricks(empty_scene):
    base = su.corpus_material("red_brick")
    if base is None:
        pytest.skip("Poly Haven corpus not downloaded")
    ob, mat = su.wall(empty_scene, width=1.0, height=0.6, material=base)
    return empty_scene, ob, mat


def test_damage_defaults_follow_base(bricks):
    sc, ob, mat = bricks
    ly = layers.add_layer(mat, "DAMAGE")
    assert ly.damage.carve == "FOLLOW_BASE"
    assert (ly.detail.mode, ly.detail.source) == ("ERODE", "BASE_HEIGHT")  # DMG-12
    su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.5, 0.3), 0.15, 0.05))
    g = mat.realworn.stack.nodes[naming.layer_node(ly.id, "damage")]
    assert g.inputs["Follow"].default_value == 1.0
    assert g.inputs["Base Height"].links[0].from_node.name == naming.layer_node("stack", "bh")
    c0 = compiler.COMPILES["count"]
    ly.damage.carve = "FLAT"
    assert compiler.COMPILES["count"] == c0 and g.inputs["Follow"].default_value == 0.0  # live


def test_t11_carve_follows_the_bricks(bricks, out_dir):
    """T11: inside a painted damage patch on bricks, carved depth correlates with base height."""
    sc, ob, mat = bricks
    ly = layers.add_layer(mat, "DAMAGE")
    ly.detail.strength = 0.0  # the carve alone (Edge Detail would also shape the outline)
    su.paint_layer(ob, mat, ly, lambda r: su.soft_disk(r, (0.5, 0.3), 0.2, 0.04))
    from test_v21_resolution import _render_height
    from test_v21_sources import _ortho_front, _render_socket
    _ortho_front(sc, (0, 0, 0.3), 0.9, res=(720, 432))
    su.setup_render(sc, engine="CYCLES", samples=1)
    sc.cycles.pixel_filter_type = "BOX"
    depth = -_render_height(sc, mat, os.path.join(out_dir, "t11_height.exr"), scale=1.0)  # mm carved
    base = _render_socket(sc, mat, detail.base_height_socket(mat), os.path.join(out_dir, "t11_base.exr"))
    yy, xx = np.mgrid[0:432, 0:720]
    inside = np.hypot((xx - 359.5) / 720 * 0.9, (yy - 215.5) / 720 * 0.9) < 0.14  # solid part of the patch
    r = float(np.corrcoef(depth[inside], base[inside])[0, 1])
    ly.damage.carve = "FLAT"
    flat = -_render_height(sc, mat, os.path.join(out_dir, "t11_flat.exr"), scale=1.0)
    r_flat = float(np.corrcoef(flat[inside] + 1e-9 * np.arange(inside.sum()), base[inside])[0, 1])
    print("\n[T11] carved depth vs base height inside the patch: Pearson r = {:.2f} (flat carve: {:.2f}); "
          "depth {:.2f}..{:.2f} mm".format(r, r_flat, depth[inside].min(), depth[inside].max()))
    record("v2.1 T11 Follow Base: carved depth vs base height (Pearson r)", r, "", None,
           "target > 0.6; flat carve {:.2f}".format(r_flat))
    assert r > 0.6


def test_dmg13_adaptive_dicing_and_instancing(empty_scene):
    ob, mat = su.crate(empty_scene, size=1.0)
    ly = layers.add_layer(mat, "DAMAGE")
    ly.damage.depth_mode = "DISPLACEMENT"
    su.paint_layer(ob, mat, ly, lambda r: np.ones((r, r)))
    mod = damage.subdiv_modifier(ob)
    assert mod.subdivision_type == "SIMPLE" and mod.use_adaptive_subdivision and mod.adaptive_space == "PIXEL"
    assert "px" in damage.dicing_rate(ob, empty_scene)
    twin = bpy.data.objects.new("Twin", ob.data)  # a linked duplicate: instanced geometry
    empty_scene.collection.objects.link(twin)
    ly.damage.edge_length = 0.004
    compiler.compile(mat)
    assert mod.adaptive_space == "OBJECT" and mod.adaptive_object_edge_length == pytest.approx(0.004)
    assert "object space" in damage.dicing_rate(ob, empty_scene)


def test_dmg14_cutters_follow_the_carve(empty_scene):
    """Geometry depth: with Follow Base the cutters favour the high parts of the base."""
    base = su.corpus_material("red_brick")
    if base is None:
        pytest.skip("Poly Haven corpus not downloaded")
    ob, mat = su.crate(empty_scene, size=0.6, material=base)  # Geometry damage needs a closed mesh
    ly = layers.add_layer(mat, "DAMAGE")
    ly.detail.strength = 0.0
    ly.damage.density, ly.damage.threshold = 4000.0, 0.6
    su.paint_layer(ob, mat, ly, lambda r: np.full((r, r), 0.5))  # mask 0.5 everywhere: below threshold
    ly.damage.depth_mode = "GEOMETRY"
    mod = damage.damage_modifier(ob)
    assert mod is not None
    assert masks.get_input(mod, "Follow") == 1.0 and masks.get_input(mod, "Base Height") is not None
    dg = bpy.context.evaluated_depsgraph_get()

    def cut_faces():
        ob.update_tag()
        dg.update()
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.polygons)
        ev.to_mesh_clear()
        return n

    base_faces = len(ob.data.polygons)
    follow = cut_faces()
    ly.damage.carve = "FLAT"
    flat = cut_faces()
    print("\n[DMG-14] faces after cutting at mask 0.5, threshold 0.6: follow base {} (high bricks 2x0.5 > 0.6), "
          "flat {} (base {})".format(follow, flat, base_faces))
    assert flat == base_faces  # flat: 0.5 never passes 0.6, nothing is cut
    assert follow > base_faces  # follow base: brick faces (high) pass, so chips appear there

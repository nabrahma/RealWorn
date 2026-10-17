"""The reference road twice: RealWorn's (set up, texture loaded, a Puddle layer set with its
sliders) and a copy carrying the same paint layout with the plain-node puddle reference. Shared by
tests/test_puddles.py and the performance tests."""

import os

import bpy

from fixtures import make_road as MR
from fixtures import puddle_reference as PR
from fixtures import reference_wall as RW

# The look values per surface (the puddle model's settings, millimetres).
COMMON = dict(depth_look_mm=8.0, halo=1.0, edge_width_mm=1.5, halo_width_mm=6.0, deep_threshold_mm=6.0,
              darkening=1.0, flat_threshold=0.92, tint="CLEAR")
PUDDLES = {
    "asphalt": dict(COMMON, water_level_mm=-7.5, height_scale_mm=3.0, dips=True, dip_depth_mm=12.0, dip_scale_m=3.0),
    "cobble": dict(COMMON, water_level_mm=-4.0, height_scale_mm=20.0, dips=False),
    "tiles": dict(COMMON, water_level_mm=-2.0, height_scale_mm=6.0, dips=True, dip_depth_mm=4.0, dip_scale_m=2.0),
}
MARKING_RES = 2048

# The wet film per surface (the cobblestones use a library grunge as the Film Breakup, the others Noise).
GRUNGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "realworn", "assets", "grunges")
FILM_COMMON = dict(wet_film=1.0, film_relief=0.6, dry_patches=0.3, film_gloss=0.02, film_scale_m=1.5)
FILM = {
    "asphalt": dict(FILM_COMMON),
    "cobble": dict(FILM_COMMON, film_grunge="grime_clouds.png", film_scale_m=2.0),
    "tiles": dict(FILM_COMMON, dry_patches=0.0),
}


def puddle_values(p):
    """Layer property values for a settings dict."""
    out = {k: v for k, v in p.items() if k in ("water_level_mm", "height_scale_mm", "dip_depth_mm", "dip_scale_m",
                                                  "depth_look_mm", "halo", "edge_width_mm", "halo_width_mm",
                                                  "deep_threshold_mm", "darkening", "flat_threshold", "wet_film",
                                                  "film_relief", "dry_patches", "film_gloss", "film_scale_m")}
    out["broad_dips"] = bool(p.get("dips"))
    out["water_tint"] = p.get("tint", "CLEAR")
    out["puddle_source"] = "AUTO"
    return out


def add_puddle(mat, p):
    assert bpy.ops.realworn.layer_add(material=mat.name, kind="PUDDLE") == {"FINISHED"}
    ly = mat.realworn.layers[mat.realworn.active_layer_index]
    for k, v in puddle_values(p).items():
        setattr(ly, k, v)
    if p.get("film_grunge"):
        from realworn.core import grunge
        ly.film_grunge = grunge.load("grunges", p["film_grunge"])
    return ly


def reference_settings(p):
    """The settings as the plain-node reference takes them (the grunge as a file path)."""
    out = dict(p)
    if p.get("film_grunge"):
        out["film_grunge"] = os.path.join(GRUNGES, p["film_grunge"])
    return out


def build_pair(sc, marking=True, puddles=True, film=False):
    """The street, set up in RealWorn with its textures, marking and Puddle layers (with the wet
    film if `film`), plus the reference copies. Returns {key: (realworn object, reference object)}."""
    from realworn.core import images
    objs = MR.build_scene(sc)
    pairs = {}
    for key, ob in objs.items():
        assert bpy.ops.realworn.setup(objects=ob.name) == {"FINISHED"}
        mat = ob.material_slots[0].material
        assert bpy.ops.realworn.use_texture(material=mat.name, layer="BASE", path=MR.set_folder(key),
                                            scale=MR.SET_SCALE[key]) == {"FINISHED"}
        mat.realworn.base.bump = MR.BUMP
        ref = ob.copy()
        ref.data = ob.data.copy()
        ref.name = ob.name + "_Reference"
        for k in list(ref.keys()):
            del ref[k]
        sc.collection.objects.link(ref)
        mk = None
        if marking and key == "asphalt":
            pos, _, _ = RW.texel_positions(ob, "RW_Paint", MARKING_RES)
            arr = MR.marking_rgba(pos.reshape(-1, 3)).reshape(MARKING_RES, MARKING_RES, 4)
            assert bpy.ops.realworn.layer_add(material=mat.name, kind="DECALS") == {"FINISHED"}
            ly = mat.realworn.layers[mat.realworn.active_layer_index]
            ly.decal_res = str(MARKING_RES)
            ly.roughness = 0.6
            RW.write_image(images.ensure_mask(ob, mat, ly), arr)
            mk = RW.new_image("ref_marking", arr)
        settings = dict(PUDDLES[key], **FILM[key]) if film else PUDDLES[key]
        if puddles:
            add_puddle(mat, settings)
        maps = MR.set_maps(key)
        PR.build_material(ref, maps, MR.SET_SCALE[key], MR.BUMP, MR.height_range(maps["height"]),
                          reference_settings(settings) if puddles else _dry(PUDDLES[key]), marking=mk)
        pairs[key] = (ob, ref)
    return pairs


def _dry(p):
    return dict(p, water_level_mm=-1000.0)


def show(pairs, which):
    """Render only RealWorn's objects ('realworn') or the reference's ('reference')."""
    for ob, ref in pairs.values():
        ob.hide_render = which != "realworn"
        ref.hide_render = which != "reference"

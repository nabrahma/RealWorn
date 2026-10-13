"""REF-2: the reference wall built with RealWorn operators and sliders only (the other half of the
reference test). Shared by tests/test_v3_reference.py and the performance tests.

The look values come from the reference fixture; the conversions below turn the tutorial's Color
Ramp stops into RealWorn's Threshold and Sharpness sliders (the mask recipe, kinds.py).
"""

import bpy

from fixtures import reference_wall as R


def ramp_sliders(white, black):
    """Threshold and Sharpness that give a Variation (S = 1) the reference's grunge Color Ramp
    (white stop at `white`, black stop at `black`): M = ramp(1 - G) = (black - G) / (black - white)."""
    w = black - white
    return 1.0 - black + w / 2.0, (0.5 - w) / 0.49


def build_pair(sc, upto, res=2048, decal_res=2048):
    """The wall twice: RealWorn's (set up, RW_Paint) and a copy carrying the same layout for the
    reference material. Returns (realworn wall, reference wall, mask arrays)."""
    wall = R.build_scene(sc)
    assert bpy.ops.realworn.setup(objects=wall.name) == {"FINISHED"}
    ref = wall.copy()
    ref.data = wall.data.copy()
    ref.name = "Wall_Reference"
    for k in list(ref.keys()):
        del ref[k]
    sc.collection.objects.link(ref)
    arr = R.mask_arrays(ref, res)
    imgs = {"paint": R.new_image("ref_paint", arr["paint"]),
            "reveal": R.new_image("ref_reveal", arr["reveal"], float_buffer=True),
            "decal": R.new_image("ref_decal", R.mask_arrays(ref, decal_res)["decal"])}
    R.build_material(ref, imgs, upto=upto)
    return wall, ref, arr


def _layer(mat):
    st = mat.realworn
    return st.layers[st.active_layer_index]


def _grunge(mat, layer, name, size, offset):
    assert bpy.ops.realworn.breakup_pick(material=mat.name, layer=layer.id, grunge=name) == {"FINISHED"}
    layer.breakup_scale, layer.breakup_offset = size, offset


def realworn_look(wall, upto):
    """REF-2: the same look with RealWorn operators and sliders only."""
    last = R.STEPS.index(upto)
    on = lambda step: R.STEPS.index(step) <= last  # noqa: E731
    mat = wall.material_slots[0].material
    m = mat.name
    assert bpy.ops.realworn.use_texture(material=m, layer="BASE", path=R.set_folder("base"),
                                        scale=R.SET_SCALE) == {"FINISHED"}
    mat.realworn.base.bump = R.BUMP
    if on("second"):
        bpy.ops.realworn.layer_add(material=m, kind="VARIATION", preset="SECOND_MATERIAL")
        ly = _layer(mat)
        bpy.ops.realworn.use_texture(material=m, layer=ly.id, path=R.set_folder("second"), scale=R.SET_SCALE)
        ly.texture.bump = R.BUMP
        _grunge(mat, ly, R.SECOND["grunge"], R.SECOND["size"], R.SECOND["offset"])
        ly.breakup_amount = 1.0
        ly.threshold, ly.sharpness = ramp_sliders(R.SECOND["white"], R.SECOND["black"])
    if on("variations"):
        for v, preset in zip(R.VARIATIONS, ("WASHED_OUT", "DARK_PATCHES", "DIRT_PATCHES")):
            bpy.ops.realworn.layer_add(material=m, kind="VARIATION", preset=preset)
            ly = _layer(mat)
            _grunge(mat, ly, v["grunge"], v["size"], v["offset"])
            ly.breakup_amount = 1.0
            ly.threshold, ly.sharpness = ramp_sliders(v["white"], v["black"])
            if "color" in v:
                ly.color, ly.roughness = v["color"], v["roughness"]
    return mat

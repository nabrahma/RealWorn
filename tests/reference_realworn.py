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


def build_pair(sc, upto, res=2048, decal_res=2048, skip=()):
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
    R.build_material(ref, imgs, upto=upto, skip=skip)
    return wall, ref, arr


def _layer(mat):
    st = mat.realworn
    return st.layers[st.active_layer_index]


def _grunge(mat, layer, name, size, offset):
    assert bpy.ops.realworn.breakup_pick(material=mat.name, layer=layer.id, grunge=name) == {"FINISHED"}
    layer.breakup_scale, layer.breakup_offset = size, offset


def ramp_stops_sliders(black, white):
    """Threshold and Sharpness for a reference Color Ramp black at `black`, white at `white`."""
    w = white - black
    return (black + white) / 2.0, (0.5 - w) / 0.49


def realworn_look(wall, upto, skip=()):
    """REF-2: the same look with RealWorn operators and sliders only."""
    last = R.STEPS.index(upto)
    on = lambda step: R.STEPS.index(step) <= last and step not in skip  # noqa: E731
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
    if on("paint"):  # Tint Below with a hue shift, chipped by a grunge (Mix Subtract), then a ramp
        bpy.ops.realworn.layer_add(material=m, kind="PAINT")
        ly = _layer(mat)
        h, s_, v_ = R.PAINT["hsv"]
        ly.hue, ly.saturation, ly.value = h - 0.5, s_ - 1.0, v_ - 1.0
        _grunge(mat, ly, R.PAINT["grunge"], R.PAINT["size"], R.PAINT["offset"])
        ly.breakup_amount = R.PAINT["amount"]
        ly.threshold, ly.sharpness = ramp_stops_sliders(R.PAINT["black"], R.PAINT["white"])
        ly.mask_res = 2048
    if on("reveal"):  # Plaster Gray 04 under a damage mask, 2 mm deep
        bpy.ops.realworn.layer_add(material=m, kind="REVEAL")
        ly = _layer(mat)
        bpy.ops.realworn.use_texture(material=m, layer=ly.id, path=R.set_folder("under"), scale=R.SET_SCALE)
        ly.texture.bump = R.BUMP
        ly.depth_mm = R.REVEAL["depth"] * 1000.0
        ly.threshold, ly.sharpness = ramp_stops_sliders(R.REVEAL["black"], R.REVEAL["white"])
        ly.edge_dark = 0.0  # REV-6 is RealWorn's one extra over the tutorial
        ly.mask_res = 2048
    return mat


def write_masks(wall, res=2048, decal_res=2048):
    """The NumPy masks of the fixture into RealWorn's own painted images (what painting would do)."""
    from realworn.core import images
    mat = wall.material_slots[0].material
    arr = R.mask_arrays(wall, res)
    decal = None
    for ly in mat.realworn.layers:
        key = {"PAINT": "paint", "REVEAL": "reveal", "DECALS": "decal"}.get(ly.kind)
        if key is None:
            continue
        img = images.ensure_mask(wall, mat, ly)
        if key == "decal":
            if decal is None:
                decal = R.mask_arrays(wall, decal_res)["decal"] if decal_res != res else arr["decal"]
            data = decal
        else:
            data = arr[key]
        assert img.size[0] == data.shape[0], (ly.name, img.size[0], data.shape[0])
        R.write_image(img, data)
    return arr

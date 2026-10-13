from realworn.core import naming


def test_all_attribute_names_use_prefix():
    for n in (naming.OB_SETUP, naming.IMG_MASK, naming.IMG_BAKED_SOURCE, naming.OWNED_PROP):
        assert n.startswith("rw_"), n


def test_node_name_roundtrip():
    assert naming.is_rw_name(naming.node_name("stack.0"))
    assert naming.is_rw_name(naming.layer_node("ab12cd34", "ramp"))
    assert naming.layer_node("ab12cd34", "ramp") == "RW::ab12cd34::ramp"
    assert not naming.is_rw_name("Principled BSDF")


def test_stack_interface_covers_principled_channels():
    ins = [n for n, _, _ in naming.STACK_INPUTS]
    outs = [n for n, _ in naming.STACK_OUTPUTS]
    for ch in naming.CHANNELS:
        assert ch in ins and ch in outs, ch
    assert "Displacement" in outs and "Mask View" in outs and "Coverage" in outs


def test_image_and_material_names():
    assert naming.mask_image_name("Crate", "Dirt") == "RW_Crate_Dirt_mask"
    assert naming.mask_image_name("Crate", "Grime", "decal") == "RW_Crate_Grime_decal"
    assert naming.unique_material_name("Paint") == "Paint.RW"
    assert naming.default_material_name("Wall") == "RW_Wall"
    assert naming.stack_group_name("Paint.RW") == "RW_Stack::Paint.RW"

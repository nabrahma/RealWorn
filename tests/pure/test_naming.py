from realworn.core import naming


def test_all_attribute_names_use_prefix():
    for n in (naming.ATTR_EDGE, naming.ATTR_CAVITY, naming.ATTR_CONTACT, naming.ATTR_DAMAGE, naming.ATTR_VMASK,
              naming.OB_GROUND, naming.OB_SETUP, naming.IMG_MASK, naming.IMG_CONTENT):
        assert n.startswith("rw_"), n


def test_group_names_use_prefix_and_are_unique():
    assert all(g.startswith("RW_") for g in naming.ALL_GROUPS)
    assert len(set(naming.ALL_GROUPS)) == len(naming.ALL_GROUPS)


def test_node_name_roundtrip():
    assert naming.is_rw_name(naming.node_name("stack.0"))
    assert naming.is_rw_name(naming.layer_node("ab12cd34", "levels"))
    assert naming.layer_node("ab12cd34", "levels") == "RW::ab12cd34::levels"
    assert not naming.is_rw_name("Principled BSDF")


def test_stack_interface_covers_principled_channels():
    ins = [n for n, _, _ in naming.STACK_INPUTS]
    outs = [n for n, _ in naming.STACK_OUTPUTS]
    for ch in naming.CHANNELS:
        assert ch in ins and ch in outs, ch
    assert "Height" in ins and "Displacement" in outs and "Mask View" in outs


def test_image_and_material_names():
    assert naming.mask_image_name("Crate", "Dirt") == "RW_Crate_Dirt_mask"
    assert naming.unique_material_name("Paint") == "Paint.RW"
    assert naming.stack_group_name("Paint.RW") == "RW_Stack::Paint.RW"

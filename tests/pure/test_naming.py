from realworn.core import naming


def test_all_attribute_names_use_prefix():
    for n in (naming.ATTR_EDGE, naming.ATTR_CAVITY, naming.ATTR_CONTACT,
              naming.ATTR_DAMAGE, naming.ATTR_PAINT) + naming.SCENE_PROPS + naming.OBJECT_PROPS:
        assert n.startswith("rw_"), n


def test_group_names_use_prefix_and_are_unique():
    assert all(g.startswith("RW_") for g in naming.ALL_GROUPS)
    assert len(set(naming.ALL_GROUPS)) == len(naming.ALL_GROUPS)


def test_node_name_roundtrip():
    assert naming.is_rw_name(naming.node_name("stack.0"))
    assert not naming.is_rw_name("Principled BSDF")

import bpy


def test_addon_registers_sidebar_panel(empty_scene):
    assert hasattr(bpy.types, "RW_PT_scene")
    assert bpy.types.RW_PT_scene.bl_category == "RealWorn"


def test_blender_version_is_supported():
    assert bpy.app.version >= (5, 2, 0)

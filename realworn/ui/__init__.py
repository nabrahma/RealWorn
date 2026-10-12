from . import paint_tools, panels


def register():
    panels.register()
    paint_tools.register()


def unregister():
    paint_tools.unregister()
    panels.unregister()

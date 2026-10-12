"""Paint override (W4): rw_paint corner colour, R adds wear, B removes layers 2-6, G keeps dry."""

from . import masks, naming

CHANNEL_COLORS = {"ADD": (1.0, 0.0, 0.0), "REMOVE": (0.0, 0.0, 1.0), "DRY": (0.0, 1.0, 0.0)}


def ensure(mesh):
    if masks.ensure_paint_attribute(mesh):
        mesh["rw_created_paint"] = True
    return mesh.color_attributes[naming.ATTR_PAINT]


def fill(mesh, rgb, vertex_filter=None):
    """Set rw_paint on every corner (or corners whose vertex passes `vertex_filter(co)`)."""
    attr = ensure(mesh)
    cols = [0.0] * (len(attr.data) * 4)
    attr.data.foreach_get("color", cols)
    for li, loop in enumerate(mesh.loops):
        if vertex_filter is None or vertex_filter(mesh.vertices[loop.vertex_index].co):
            cols[li * 4:li * 4 + 4] = [rgb[0], rgb[1], rgb[2], 1.0]
    attr.data.foreach_set("color", cols)
    mesh.update()


def set_brush(tool_settings, channel):
    """Red brush adds wear, blue removes it, green keeps dry; Ctrl paints black (clears)."""
    ups = tool_settings.vertex_paint.unified_paint_settings
    ups.use_unified_color = True
    ups.color = CHANNEL_COLORS[channel]
    ups.secondary_color = (0.0, 0.0, 0.0)
    brush = tool_settings.vertex_paint.brush
    if brush is not None and hasattr(brush, "color"):
        brush.color = CHANNEL_COLORS[channel]

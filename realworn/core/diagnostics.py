"""Sharpness diagnostics (PRD v2.1 DIA-1..DIA-4). Settings that quietly cap texture resolution or
blur textures, and the texel density that limits a layer's edge.

Everything takes explicit datablocks (preferences.system, scene, materials, objects), never
bpy.context. check() returns a list of findings for the panel and tests:
    {"id": "DIA-1", "level": "WARNING" | "INFO", "text": str, "fix": operator idname or None}
"""

import math

import numpy as np

from . import naming

_LIMIT_PX = {"CLAMP_OFF": None, "CLAMP_8192": 8192, "CLAMP_4096": 4096, "CLAMP_2048": 2048, "CLAMP_1024": 1024,
             "CLAMP_512": 512, "CLAMP_256": 256, "CLAMP_128": 128}
_ANISO = {"FILTER_0": 1, "FILTER_2": 2, "FILTER_4": 4, "FILTER_8": 8, "FILTER_16": 16}


def material_images(mat):
    """Every image a set-up material samples: base textures in its tree, RealWorn masks, content,
    channel images and grunges in its stack (deduplicated)."""
    out = {}

    def walk(tree, seen):
        if tree is None or tree.name in seen:
            return
        seen.add(tree.name)
        for n in tree.nodes:
            if n.bl_idname == "ShaderNodeTexImage" and n.image is not None:
                out[n.image.name] = n.image
            elif n.bl_idname == "ShaderNodeGroup":
                walk(n.node_tree, seen)

    if mat is not None and mat.node_tree is not None:
        walk(mat.node_tree, set())
    return list(out.values())


def largest_texture(mats):
    """(pixels, image name) of the largest image any of `mats` samples, or (0, None)."""
    best = (0, None)
    for m in mats:
        for img in material_images(m):
            px = max(img.size[0], img.size[1]) if img.has_data or img.size[0] else 0
            if px > best[0]:
                best = (px, img.name)
    return best


def check(system, scene, mats):
    """DIA-1..DIA-3 findings for these materials under these preferences and render settings."""
    found = []
    biggest, name = largest_texture(mats)
    if not biggest:
        return found
    lim = _LIMIT_PX.get(system.gl_texture_limit)
    if lim is not None and lim < biggest:
        found.append({"id": "DIA-1", "level": "WARNING", "fix": "realworn.fix_texture_limit",
                      "text": "Preferences > Viewport > Limit Size is {} px; {} is {} px. Textures are "
                              "shown (and EEVEE renders) at {} px".format(lim, name, biggest, lim)})
    if scene.render.use_simplify and hasattr(scene, "cycles"):
        cy = scene.cycles
        for where, key, res_key in (("viewport", "texture_limit", "texture_resolution"),
                                    ("render", "texture_limit_render", "texture_resolution_render")):
            tl = getattr(cy, key, "OFF")
            if tl != "OFF" and int(tl) < biggest:
                found.append({"id": "DIA-2", "level": "WARNING", "fix": "realworn.fix_simplify_textures",
                              "text": "Simplify caps Cycles {} textures at {} px ({} is {} px)".format(
                                  where, tl, name, biggest)})
            scale = getattr(cy, res_key, 1.0)
            if scale < 1.0:
                found.append({"id": "DIA-2", "level": "WARNING", "fix": "realworn.fix_simplify_textures",
                              "text": "Simplify scales Cycles {} textures to {:.0%}".format(where, scale)})
    if _ANISO.get(system.anisotropic_filter, 16) < 8:
        found.append({"id": "DIA-3", "level": "INFO", "fix": "realworn.fix_anisotropic",
                      "text": "Anisotropic filtering is {}x; oblique floors and walls blur below 8x".format(
                          _ANISO[system.anisotropic_filter])})
    return found


# ------------------------------------------------------------------ DIA-4 texel density
def _tri_areas(pts):
    a, b, c = pts[:, 0], pts[:, 1], pts[:, 2]
    cr = np.cross(b - a, c - a)
    return 0.5 * (np.linalg.norm(cr, axis=1) if cr.ndim == 2 else np.abs(cr))


def uv_units_per_metre(obj, uv_name=naming.UV_PAINT):
    """sqrt(UV area / world surface area) of the mesh: UV units per metre of surface."""
    me = obj.data
    if uv_name not in me.uv_layers or not me.polygons:
        return 0.0
    n = len(me.loop_triangles)
    if n == 0:
        return 0.0
    loops = np.empty(n * 3, np.int64)
    me.loop_triangles.foreach_get("loops", loops)
    verts = np.empty(n * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", verts)
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    m = np.array(obj.matrix_world, np.float64)
    co = co @ m[:3, :3].T + m[:3, 3]
    uv = np.empty(len(me.loops) * 2, np.float64)
    me.uv_layers[uv_name].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    world = _tri_areas(co[verts].reshape(n, 3, 3)).sum()
    uva = _tri_areas(uv[loops].reshape(n, 3, 2)).sum()
    return math.sqrt(uva / world) if world > 0 else 0.0


def mask_px_per_cm(obj, layer):
    """DIA-4: painted-mask texels per centimetre of surface for this layer (None: no mask)."""
    img = layer.mask_image
    if img is None:
        return None
    return img.size[0] * uv_units_per_metre(obj) / 100.0


def grunge_px_per_cm(image, scale_m):
    """DIA-4: texels per centimetre of a box-projected grunge `image` tiled every `scale_m` metres."""
    if image is None or scale_m <= 0:
        return None
    return image.size[0] / (scale_m * 100.0)


def readout(obj, layer):
    """Short DIA-4 lines for the panel: which source limits this layer's edge."""
    lines = []
    m = mask_px_per_cm(obj, layer)
    if m is not None:
        lines.append(("Mask", m))
    for name, px in detail_px_per_cm(obj, layer):
        lines.append((name, px))
    return lines


def limit_text(obj, layer):
    """DIA-5: which source limits the layer's edge, e.g. 'Base Height red_brick_disp_1k (4.1 px/cm)'."""
    rows = readout(obj, layer)
    detail_rows = detail_px_per_cm(obj, layer)
    if detail_rows:  # with Edge Detail on, the detail source decides the edge, not the mask (S2)
        rows = detail_rows
    elif getattr(layer, "detail", None) is not None and layer.detail.strength > 0:
        from . import detail
        src, _ = detail.resolve(layer.id_data, layer)
        if src in ("BASE_HEIGHT", "BASE_AO"):
            return "{} (procedural: no texel limit)".format("Base Height" if src == "BASE_HEIGHT" else "Base AO")
    if not rows:
        return "ingredients only (no painted mask)" if layer.ingredients else "nothing painted"
    name, px = min(rows, key=lambda r: r[1])
    return "{} ({:.1f} px/cm)".format(name, px)


def report_rows(obj, layer_widths):
    """DIA-5 table: [(layer name, W px or None, limiting source text)] for measured layers."""
    out = []
    for layer, w in layer_widths:
        out.append((layer.name, w, limit_text(obj, layer)))
    return out


def detail_px_per_cm(obj, layer):
    """(label, px per cm) of the layer's active Edge Detail source, when it has one (v2.1 Q1+)."""
    det = getattr(layer, "detail", None)
    if det is None or det.strength <= 0:
        return []
    from . import detail
    return detail.source_density(obj, layer)

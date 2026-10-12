"""Baking through RW_Paint (BAK-1..BAK-4) and the helpers decal baking uses (DEC-5).

Pattern from Ucupaint (bake_common.remember_before_bake / recover_bake_settings, see
docs/reference_notes.md; no code copied): remember everything a bake touches (engine, samples,
selection, active object, active UV), bake with the RW_Paint UV map, restore all of it, and fall
back from GPU to CPU if a GPU bake raises.
"""

import json
import os
import tempfile

import bpy
import numpy as np

from . import compiler, ctx, images, injector, naming, nodeutil

BAKE_CHANNELS = (("base_color", "Base Color", "sRGB"), ("roughness", "Roughness", "Non-Color"),
                 ("metallic", "Metallic", "Non-Color"), ("height", "Height", "Non-Color"))


class BakeError(Exception):
    pass


# ------------------------------------------------------------------ images
def new_image(name, res, colorspace="Non-Color", alpha=False, float_buffer=False):
    img = bpy.data.images.get(name)
    if img is not None and (tuple(img.size) != (res, res) or img.is_float != float_buffer):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, res, res, alpha=alpha, float_buffer=float_buffer)
    img.colorspace_settings.name = colorspace
    return img


def output_folder(folder):
    path = bpy.path.abspath(folder) if folder else ""
    if not path or (folder.startswith("//") and not bpy.data.filepath):
        path = os.path.join(tempfile.gettempdir(), "rw_bake")
    os.makedirs(path, exist_ok=True)
    return path


# ----------------------------------------------------------- bake runner
def _target_nodes(mats, img):
    for m in mats:
        nt = m.node_tree
        n = nodeutil.find(nt, "bake_target")
        if n is None:
            n = nodeutil.new(nt, "ShaderNodeTexImage", "bake_target", frame=nodeutil.ensure_frame(nt))
            n.hide = True
        n.image = img
        for other in nt.nodes:
            other.select = False
        n.select = True
        nt.nodes.active = n


def _drop_targets(mats):
    for m in mats:
        n = nodeutil.find(m.node_tree, "bake_target")
        if n is not None:
            m.node_tree.nodes.remove(n)


def run(scene, obj, mats, img, bake_type="EMIT", samples=4, margin=8):
    """Bake `bake_type` of `obj` into `img` through RW_Paint, restoring every setting it touches."""
    if naming.UV_PAINT not in obj.data.uv_layers:
        raise BakeError("{}: no RW_Paint UV map (click Setup)".format(obj.name))
    r = scene.render
    vl = bpy.context.view_layer
    saved = {"engine": r.engine, "samples": scene.cycles.samples, "denoise": scene.cycles.use_denoising,
             "device": scene.cycles.device, "active": vl.objects.active,
             "selected": [o for o in vl.objects if o.select_get()], "hide_render": obj.hide_render}
    r.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    obj.hide_render = False
    for o in saved["selected"]:
        o.select_set(False)
    obj.select_set(True)
    vl.objects.active = obj
    _target_nodes(mats, img)
    try:
        kw = dict(type=bake_type, margin=margin, use_clear=True, uv_layer=naming.UV_PAINT)
        if bake_type == "NORMAL":
            kw.update(normal_space="TANGENT")
        try:
            with bpy.context.temp_override(**ctx.override(obj, scene=scene, view_layer=vl)):
                bpy.ops.object.bake(**kw)
        except RuntimeError:
            if scene.cycles.device == "GPU":  # GPU bake failed: retry on the CPU (as Ucupaint does)
                scene.cycles.device = "CPU"
                with bpy.context.temp_override(**ctx.override(obj, scene=scene, view_layer=vl)):
                    bpy.ops.object.bake(**kw)
            else:
                raise
    finally:
        _drop_targets(mats)
        r.engine, scene.cycles.samples = saved["engine"], saved["samples"]
        scene.cycles.use_denoising, scene.cycles.device = saved["denoise"], saved["device"]
        obj.hide_render = saved["hide_render"]
        obj.select_set(False)
        for o in saved["selected"]:
            if o.name in vl.objects:
                o.select_set(True)
        vl.objects.active = saved["active"]
    return img


# ------------------------------------------------------- emission routing
def route_emission(mat, source):
    """Temporarily feed `source(tree)` (an output socket) to the surface as emission."""
    nt = mat.node_tree
    out = nodeutil.output_node(nt)
    if "rw_bake_surface" not in mat:
        src = nodeutil.link_source(out.inputs["Surface"])
        mat["rw_bake_surface"] = json.dumps(nodeutil.socket_ref(src) if src is not None else None)
    emis = nodeutil.find(nt, "bake_emit") or nodeutil.new(nt, "ShaderNodeEmission", "bake_emit",
                                                          frame=nodeutil.ensure_frame(nt))
    nt.links.new(source(nt), emis.inputs["Color"])
    nt.links.new(emis.outputs[0], out.inputs["Surface"])


def restore_emission(mat):
    nt = mat.node_tree
    for role in ("bake_emit",):
        n = nodeutil.find(nt, role)
        if n is not None:
            nt.nodes.remove(n)
    if "rw_bake_surface" in mat:
        src = nodeutil.resolve(nt, json.loads(mat["rw_bake_surface"]))
        out = nodeutil.output_node(nt)
        if src is not None and out is not None:
            nt.links.new(src, out.inputs["Surface"])
        del mat["rw_bake_surface"]


def stack_output(name):
    def get(nt):
        return injector.stacks(nt)[0].outputs[name]
    return get


def bake_layer_view(scene, obj, mat, layer_index, channel, img):
    """Bake one layer's Mask View ('MASK') or its own colour ('COLOR') into `img`."""
    st = mat.realworn
    prev = (st.active_layer_index, st.mask_view, st.view_channel)
    with compiler.batch(mat):
        st.active_layer_index = layer_index
        st.mask_view = True
        st.view_channel = channel
    compiler.compile(mat)
    try:
        route_emission(mat, stack_output("Layer Color" if channel == "COLOR" else "Mask View"))
        run(scene, obj, [mat], img, "EMIT")
    finally:
        restore_emission(mat)
        with compiler.batch(mat):
            st.active_layer_index, st.mask_view, st.view_channel = prev
        compiler.compile(mat)
    return img


def pixels(img):
    return images.pixels(img)


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def bleed(rgb, alpha, passes=12):
    """Push opaque colours outward into transparent texels so texture filtering at the edge does
    not blend towards black (the dark halo a straight copy gives)."""
    rgb = rgb.copy()
    w = (alpha > 0.5).astype(np.float32)
    for _ in range(passes):
        if w.min() > 0:
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(w.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            acc += np.roll(np.roll(rgb * w[..., None], dy, 0), dx, 1)
            cnt += np.roll(np.roll(w, dy, 0), dx, 1)
        grow = (w == 0) & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][..., None]
        w = np.maximum(w, grow.astype(np.float32))
    return rgb


def compose_rgba(color_img, alpha_img, target):
    """Baked emission colour (linear) + baked mask -> an RGBA image in the target's colour space."""
    c = pixels(color_img)[..., :3]
    a = pixels(alpha_img)[..., 0]
    c = bleed(c, a)
    if target.colorspace_settings.name.lower().startswith("srgb"):
        c = linear_to_srgb(c)
    out = np.empty(c.shape[:2] + (4,), np.float32)
    out[..., :3] = c
    out[..., 3] = a
    target.pixels.foreach_set(out.ravel())
    target.update()
    return target

"""Bake (W9): freeze weathering to images for export or render speed.

Base Color, Roughness and Metallic come from EMIT bakes of the RW_Stack outputs, Normal from a
tangent-space NORMAL bake of the final shader, and the masks (rw_edge, rw_cavity, rw_contact,
rw_shelter, rw_damage) from EMIT bakes of Attribute nodes. Swap then feeds the Principled BSDF
from the baked images; Restore Live Stack relinks the stack. Everything inserted is RealWorn-
owned, so Remove still restores the original material exactly.
"""

import json
import os
import tempfile

import bpy

from . import injector, naming, nodeutil, weathering

CHANNELS = (("base_color", "Base Color", "sRGB"), ("roughness", "Roughness", "Non-Color"),
            ("metallic", "Metallic", "Non-Color"))
MASKS = (naming.ATTR_EDGE, naming.ATTR_CAVITY, naming.ATTR_CONTACT, naming.ATTR_SHELTER, naming.ATTR_DAMAGE)
BAKE_KEY = "rw_bake_images"


class BakeError(Exception):
    pass


def output_folder(folder):
    path = bpy.path.abspath(folder) if folder else ""
    if not path or (folder.startswith("//") and not bpy.data.filepath):
        path = os.path.join(tempfile.gettempdir(), "rw_bake")
    os.makedirs(path, exist_ok=True)
    return path


def _image(name, res, colorspace):
    img = bpy.data.images.get(name)
    if img is not None and tuple(img.size) != (res, res):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, res, res, alpha=False)
    img.colorspace_settings.name = colorspace
    return img


def _materials(obj):
    return [m for m in weathering.materials_of(obj) if injector.is_applied(m)]


def _set_target(mats, img):
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


def _emit_from(mat, source):
    """Route `source(tree)` -> Emission -> Output; remembers the original surface link."""
    nt = mat.node_tree
    out = nodeutil.output_node(nt)
    if "rw_bake_surface" not in mat:
        mat["rw_bake_surface"] = json.dumps(nodeutil.socket_ref(nodeutil.link_source(out.inputs["Surface"]))
                                            if out.inputs["Surface"].is_linked else None)
    emit = nodeutil.find(nt, "bake_emit") or nodeutil.new(nt, "ShaderNodeEmission", "bake_emit",
                                                          frame=nodeutil.ensure_frame(nt))
    nt.links.new(source(nt), emit.inputs["Color"])
    nt.links.new(emit.outputs[0], out.inputs["Surface"])


def _restore_surface(mat):
    nt = mat.node_tree
    for role in ("bake_emit", "bake_attr", "bake_target"):
        n = nodeutil.find(nt, role)
        if n is not None:
            nt.nodes.remove(n)
    if "rw_bake_surface" in mat:
        ref = json.loads(mat["rw_bake_surface"])
        src = nodeutil.resolve(nt, ref)
        out = nodeutil.output_node(nt)
        if src is not None and out is not None:
            nt.links.new(src, out.inputs["Surface"])
        del mat["rw_bake_surface"]


def _attr_source(name):
    def src(nt):
        n = nodeutil.find(nt, "bake_attr") or nodeutil.new(nt, "ShaderNodeAttribute", "bake_attr",
                                                           frame=nodeutil.ensure_frame(nt))
        n.attribute_type = "GEOMETRY"
        n.attribute_name = name
        return n.outputs["Fac"]
    return src


def _stack_source(channel):
    def src(nt):
        return injector.stacks(nt)[0].outputs[channel]
    return src


def _run(scene, obj, bake_type, samples):
    scene.cycles.samples = samples
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0], active_object=obj, object=obj,
                                   selected_objects=[obj], selected_editable_objects=[obj]):
        bpy.ops.object.bake(type=bake_type, margin=8, use_clear=True)


def bake_object(obj, scene, resolution=1024, folder="//rw_bake/", masks=True, swap=True, samples=16):
    """Bake one weathered object. Returns {key: image} and saves PNGs to `folder`."""
    mats = _materials(obj)
    if not mats:
        raise BakeError("{}: no weathered material to bake".format(obj.name))
    if not obj.data.uv_layers:
        raise BakeError("{}: needs a UV map (Bake can create one with Smart UV Project)".format(obj.name))
    for m in mats:  # each baked object needs its own images, so shared materials become single user
        if len(weathering.users_of(m)) > 1:
            raise BakeError("{}: material '{}' is shared; make it single user first".format(obj.name, m.name))
    out_dir = output_folder(folder)
    r = scene.render
    saved = (r.engine, scene.cycles.samples, scene.cycles.use_denoising)
    r.engine = "CYCLES"
    scene.cycles.use_denoising = False
    images = {}
    try:
        passes = [(key, cs, _stack_source(ch)) for key, ch, cs in CHANNELS]
        if masks:
            passes += [(m, "Non-Color", _attr_source(m)) for m in MASKS]
        for key, cs, src in passes:
            img = _image("{}_{}".format(obj.name, key), resolution, cs)
            _set_target(mats, img)
            for m in mats:
                _emit_from(m, src)
            _run(scene, obj, "EMIT", 4)
            images[key] = img
        for m in mats:
            _restore_surface(m)
        img = _image("{}_normal".format(obj.name), resolution, "Non-Color")
        _set_target(mats, img)
        _run(scene, obj, "NORMAL", samples)
        images["normal"] = img
    finally:
        for m in mats:
            _restore_surface(m)
        r.engine, scene.cycles.samples, scene.cycles.use_denoising = saved
    for key, img in images.items():
        img.filepath_raw = os.path.join(out_dir, img.name + ".png")
        img.file_format = "PNG"
        img.save()
    if swap:
        for m in mats:
            swap_to_baked(m, images)
    return images


def _principled(tree, stack):
    return tree.nodes.get(stack.get("rw_principled", ""))


def swap_to_baked(mat, images):
    """Feed the Principled BSDF(s) from baked images instead of the live stack."""
    nt = mat.node_tree
    if mat.realworn.mode != "CHANNEL":
        return False
    remove_baked_nodes(mat)
    frame = nodeutil.ensure_frame(nt)
    nodes = {}
    for key, img in images.items():
        if key in ("base_color", "roughness", "metallic", "normal"):
            n = nodeutil.new(nt, "ShaderNodeTexImage", "bake_img." + key, frame=frame)
            n.image = img
            n.hide = True
            nodes[key] = n
    nmap = nodeutil.new(nt, "ShaderNodeNormalMap", "bake_nmap", frame=frame)
    nmap.hide = True
    nt.links.new(nodes["normal"].outputs["Color"], nmap.inputs["Color"])
    for st in injector.stacks(nt):
        p = _principled(nt, st)
        if p is None:
            continue
        x, y = injector._abs(st)
        for i, n in enumerate(list(nodes.values()) + [nmap]):
            injector._place(n, x + 30, y + 160 + i * 40)
        nt.links.new(nodes["base_color"].outputs["Color"], p.inputs["Base Color"])
        nt.links.new(nodes["roughness"].outputs["Color"], p.inputs["Roughness"])
        nt.links.new(nodes["metallic"].outputs["Color"], p.inputs["Metallic"])
        nt.links.new(nmap.outputs["Normal"], p.inputs["Normal"])
        for ch in ("Coat Weight", "Coat Roughness", "Coat IOR", "Coat Normal"):
            src = nodeutil.link_source(st.inputs[ch])
            if src is not None and not nodeutil.is_owned(src.node):  # the user's own coat input
                nt.links.new(src, p.inputs[ch])
            else:
                for link in list(p.inputs[ch].links):
                    nt.links.remove(link)
    mat[BAKE_KEY] = json.dumps({k: img.name for k, img in images.items()})
    mat.realworn.baked = True
    return True


def remove_baked_nodes(mat):
    nt = mat.node_tree
    for n in [n for n in nt.nodes if nodeutil.is_owned(n) and
              (n.name.startswith(naming.node_name("bake_img")) or n.name == naming.node_name("bake_nmap"))]:
        nt.nodes.remove(n)


def restore_live(mat):
    """Restore Live Stack: drop the baked images from the shader and relink RW_Stack."""
    nt = mat.node_tree
    remove_baked_nodes(mat)
    for st in injector.stacks(nt):
        p = _principled(nt, st)
        if p is None:
            continue
        for ch in naming.CHANNELS:
            nt.links.new(st.outputs[ch], p.inputs[ch])
    mat.realworn.baked = False
    return True

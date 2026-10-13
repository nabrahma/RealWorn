"""Baking through RW_Paint: Bake Material, Export Textures, and Bake Edges and AO (ENG-2).

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
             "device": scene.cycles.device, "active": vl.objects.active, "tile": scene.cycles.tile_size,
             "selected": [o for o in vl.objects if o.select_get()], "hide_render": obj.hide_render}
    r.engine = "CYCLES"
    scene.cycles.samples = samples
    # In an interactive session Blender 5.2.1 bakes nothing into an image larger than the render
    # tile (default 2048 px): the bake reports success and leaves the image black. Headless bakes
    # are fine. A tile as large as the image works around it (found in v3 R4, live).
    scene.cycles.tile_size = max(scene.cycles.tile_size, max(img.size))
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
        scene.cycles.tile_size = saved["tile"]
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
    n = nodeutil.find(nt, "bake_emit")
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


def bake_socket(scene, obj, mat, source, img, samples=4):
    """Bake any socket (via `source(tree)`) of the material as emission into `img`."""
    route_emission(mat, source)
    try:
        run(scene, obj, [mat], img, "EMIT", samples=samples)
    finally:
        restore_emission(mat)
    return img


def pixels(img):
    return images.pixels(img)


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


# ================================================================ Bake Material
MATERIAL_CHANNELS = (("base_color", "Base Color", "sRGB"), ("roughness", "Roughness", "Non-Color"),
                     ("metallic", "Metallic", "Non-Color"), ("height", "Displacement", "Non-Color"))
BAKED_KEY = "rw_baked_images"


def _float_to_target(src, target, srgb):
    px = pixels(src)
    if srgb:
        px[..., :3] = linear_to_srgb(px[..., :3])
    px[..., 3] = 1.0
    target.pixels.foreach_set(px.ravel())
    target.update()


def bake_material(obj, mat, scene=None, resolution=2048, folder="//rw_bake/", swap=True, samples=16):
    """UI-5: bake the whole stack to PBR textures on RW_Paint and swap the stack for them.
    Returns {key: image}; images are saved to `folder` (8-bit PNG, height as float EXR in metres)."""
    scene = scene or bpy.context.scene
    if not injector.is_setup(mat):
        raise BakeError("{}: not set up".format(mat.name))
    out_dir = output_folder(folder)
    result = {}
    for key, socket, cs in MATERIAL_CHANNELS:
        if key == "height" and not compiler.has_height(mat):
            continue
        raw = new_image("rw_tmp_bake", resolution, "Non-Color", float_buffer=True)
        bake_socket(scene, obj, mat, stack_output(socket), raw)
        img = new_image("{}_{}".format(bpy.path.clean_name(mat.name), key), resolution, cs,
                        float_buffer=(key == "height"))
        if key == "height":
            img.pixels.foreach_set(pixels(raw).ravel())
            img.update()
        else:
            _float_to_target(raw, img, cs == "sRGB")
        bpy.data.images.remove(raw)
        result[key] = img
    nimg = new_image("{}_normal".format(bpy.path.clean_name(mat.name)), resolution, "Non-Color")
    run(scene, obj, [mat], nimg, "NORMAL", samples=samples)
    result["normal"] = nimg
    for key, img in result.items():
        img[BAKED_KEY] = True
        img.filepath_raw = os.path.join(out_dir, img.name + (".exr" if img.is_float else ".png"))
        img.file_format = "OPEN_EXR" if img.is_float else "PNG"
        img.save()
    if swap:
        swap_to_baked(mat, result)
    return result


def _principled(tree, stack):
    return tree.nodes.get(stack.get("rw_principled", ""))


def constant_value(img, tol=1.5 / 255.0):
    """The single value of a flat greyscale bake, or None if it varies."""
    px = pixels(img)[..., 0]
    lo, hi = float(px.min()), float(px.max())
    return (lo + hi) / 2.0 if hi - lo <= tol else None


def remove_baked_nodes(mat):
    nt = mat.node_tree
    for n in [n for n in nt.nodes if nodeutil.is_owned(n) and n.name.startswith(naming.node_name("baked"))]:
        nt.nodes.remove(n)


def swap_to_baked(mat, images_by_key):
    """Feed the Principled BSDF(s) from the baked images (sampled through RW_Paint) instead of the
    live stack; the stack stays in the tree for Restore Live Stack. The baked normal map carries
    the relief, so the live displacement is unplugged."""
    nt = mat.node_tree
    remove_baked_nodes(mat)
    frame = nodeutil.ensure_frame(nt)
    uvn = nodeutil.new(nt, "ShaderNodeUVMap", "baked.uv", frame=frame)
    uvn.uv_map = naming.UV_PAINT
    uvn.hide = True
    nodes = {}
    for key, img in images_by_key.items():
        if key == "height":
            continue
        n = nodeutil.new(nt, "ShaderNodeTexImage", "baked." + key, frame=frame)
        n.image = img
        n.hide = True
        nt.links.new(uvn.outputs[0], n.inputs["Vector"])
        nodes[key] = n
    nmap = nodeutil.new(nt, "ShaderNodeNormalMap", "baked.nmap", frame=frame)
    nmap.uv_map = naming.UV_PAINT
    nmap.hide = True
    nt.links.new(nodes["normal"].outputs["Color"], nmap.inputs["Color"])
    for st in injector.stacks(nt):
        p = _principled(nt, st)
        if p is None:
            continue
        x, y = injector._abs(st)
        for i, n in enumerate([uvn] + list(nodes.values()) + [nmap]):
            injector._place(n, x + 30, y + 200 + i * 40)
        nt.links.new(nodes["base_color"].outputs["Color"], p.inputs["Base Color"])
        for key, sock in (("roughness", "Roughness"), ("metallic", "Metallic")):
            const = constant_value(images_by_key[key])
            if const is not None:  # a flat map costs a texture lookup per sample for nothing
                for link in list(p.inputs[sock].links):
                    nt.links.remove(link)
                p.inputs[sock].default_value = const
            else:
                nt.links.new(nodes[key].outputs["Color"], p.inputs[sock])
        nt.links.new(nmap.outputs["Normal"], p.inputs["Normal"])
    injector.unlink_displacement(mat)
    mat[BAKED_KEY] = json.dumps({k: img.name for k, img in images_by_key.items()})
    mat.realworn.baked = True
    return True


def restore_live(mat):
    """Restore Live Stack: drop the baked images from the shader and relink the stack."""
    nt = mat.node_tree
    remove_baked_nodes(mat)
    for st in injector.stacks(nt):
        p = _principled(nt, st)
        if p is None:
            continue
        for ch in naming.CHANNELS:
            nt.links.new(st.outputs[ch], p.inputs[ch])
    mat.realworn.baked = False
    if BAKED_KEY in mat:
        del mat[BAKED_KEY]
    injector.sync_outputs(mat)
    return True


# ================================================================ Export
NORMAL_CONVENTION = {"UNITY_URP": "OpenGL", "UNITY_HDRP": "OpenGL", "UNREAL": "DirectX", "GLTF": "OpenGL"}


def export_textures(mat, folder, preset="UNREAL", name=None):
    """UI-5: write the baked set with engine conventions (needs Bake Material first). Returns paths."""
    if BAKED_KEY not in mat:
        raise BakeError("{}: bake the material first".format(mat.name))
    if preset not in NORMAL_CONVENTION:
        raise BakeError("unknown preset {}".format(preset))
    imgs = {k: bpy.data.images[v] for k, v in json.loads(mat[BAKED_KEY]).items() if v in bpy.data.images}
    base = name or bpy.path.clean_name(mat.name)
    os.makedirs(folder, exist_ok=True)
    col = pixels(imgs["base_color"])
    rough = pixels(imgs["roughness"])[..., 0]
    metal = pixels(imgs["metallic"])[..., 0]
    nrm = pixels(imgs["normal"]).copy()
    if NORMAL_CONVENTION[preset] == "DirectX":
        nrm[..., 1] = 1.0 - nrm[..., 1]  # flip green for DirectX normal maps
    one, zero = np.ones_like(rough), np.zeros_like(rough)
    if preset == "UNITY_URP":
        out = {"BaseMap": (col, "sRGB"), "MetallicSmoothness": (np.dstack([metal, zero, zero, 1.0 - rough]), "Non-Color"),
               "Normal": (nrm, "Non-Color")}
    elif preset == "UNITY_HDRP":
        out = {"BaseColor": (col, "sRGB"), "MaskMap": (np.dstack([metal, one, zero, 1.0 - rough]), "Non-Color"),
               "Normal": (nrm, "Non-Color")}
    elif preset == "UNREAL":
        out = {"BaseColor": (col, "sRGB"), "ORM": (np.dstack([one, rough, metal, one]), "Non-Color"),
               "Normal": (nrm, "Non-Color")}
    else:
        out = {"baseColor": (col, "sRGB"), "metallicRoughness": (np.dstack([zero, rough, metal, one]), "Non-Color"),
               "normal": (nrm, "Non-Color")}
    paths = []
    for suffix, (arr, cs) in out.items():
        h, w = arr.shape[:2]
        img = bpy.data.images.new("rw_export", w, h, alpha=True)
        img.colorspace_settings.name = cs
        img.pixels.foreach_set(np.ascontiguousarray(arr, np.float32).ravel())
        path = os.path.join(folder, "{}_{}.png".format(base, suffix))
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        paths.append(path)
    return paths


# ================================================================ Bake Edges and AO
SOURCE_KINDS = ("EDGE_WEAR", "DIRT")


def bake_sources(obj, mat, scene=None, layer_ids=None, resolution=None, samples=32):
    """ENG-2: bake the Edge Wear and Dirt sources (Bevel / AO, before Breakup and Sharpness, which
    stay live) to float images on RW_Paint and switch those layers to Baked. Re-bake after
    changing the mesh. Returns {layer id: image}."""
    scene = scene or bpy.context.scene
    st = mat.realworn
    targets = [ly for ly in st.layers if ly.kind in SOURCE_KINDS and (layer_ids is None or ly.id in layer_ids)]
    res = resolution or images.texel_resolution(obj)
    done = {}
    saved = [(ly.id, ly.edge_source) for ly in targets]
    try:
        with compiler.batch(mat):
            for ly in targets:
                ly.edge_source = "LIVE"  # bake what the live nodes produce
        for ly in targets:
            compiler.SOURCE_VIEW[mat.name] = ly.id
            compiler.compile(mat)
            name = naming.mask_image_name(obj.name, ly.name, "baked")
            img = new_image(name, res, "Non-Color", float_buffer=True)
            bake_socket(scene, obj, mat, stack_output("Mask View"), img, samples=samples)
            img[naming.IMG_BAKED_SOURCE] = "{}/{}".format(obj.name, ly.id)
            images.store(img, obj)
            done[ly.id] = img
    finally:
        compiler.SOURCE_VIEW.pop(mat.name, None)
        with compiler.batch(mat):
            for lid, src in saved:
                ly = compiler.layer_by_id(mat, lid)
                if lid in done:
                    ly.baked_image, ly.edge_source = done[lid], "BAKED"
                else:
                    ly.edge_source = src
        compiler.compile(mat)
    return done

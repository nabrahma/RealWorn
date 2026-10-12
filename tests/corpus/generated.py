"""Code-generated corpus materials: the cases a downloaded library does not cover.

Each builder returns a new material. GENERATED maps a name to its builder.
"""

import bpy


def _clear(mat):
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    return nt


def _out(nt, x=600):
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    o.location = (x, 0)
    return o


def _image(name, size=32, color=(0.5, 0.5, 0.5, 1.0), non_color=False):
    img = bpy.data.images.get(name) or bpy.data.images.new(name, size, size)
    img.pixels = list(color) * (size * size)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def principled_basic():
    mat = bpy.data.materials.new("C_PrincipledBasic")
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.2, 0.4, 0.7, 1)
    b.inputs["Roughness"].default_value = 0.35
    return mat


def image_based():
    mat = bpy.data.materials.new("C_ImageBased")
    nt = _clear(mat)
    out = _out(nt)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-700, 0)
    col = nt.nodes.new("ShaderNodeTexImage")
    col.image = _image("c_col.png", color=(0.6, 0.3, 0.2, 1))
    col.location = (-400, 200)
    rough = nt.nodes.new("ShaderNodeTexImage")
    rough.image = _image("c_rough.png", color=(0.7, 0.7, 0.7, 1), non_color=True)
    rough.location = (-400, -50)
    nrm = nt.nodes.new("ShaderNodeTexImage")
    nrm.image = _image("c_nrm.png", color=(0.5, 0.5, 1.0, 1), non_color=True)
    nrm.location = (-400, -300)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.location = (-100, -300)
    for t in (col, rough, nrm):
        nt.links.new(tc.outputs["UV"], t.inputs["Vector"])
    nt.links.new(col.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(rough.outputs["Color"], b.inputs["Roughness"])
    nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def procedural():
    mat = bpy.data.materials.new("C_Procedural")
    nt = _clear(mat)
    out = _out(nt)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 7.3
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.1, 0.08, 0.05, 1)
    ramp.color_ramp.elements[1].position = 0.63
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.4
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def multi_principled():
    mat = bpy.data.materials.new("C_MultiPrincipled")
    nt = _clear(mat)
    out = _out(nt)
    a = nt.nodes.new("ShaderNodeBsdfPrincipled")
    a.inputs["Metallic"].default_value = 1.0
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.8, 0.1, 0.1, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    nt.links.new(noise.outputs["Fac"], mix.inputs[0])
    nt.links.new(a.outputs[0], mix.inputs[1])
    nt.links.new(b.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def coat_material():
    mat = bpy.data.materials.new("C_ExistingCoat")
    b = mat.node_tree.nodes["Principled BSDF"]
    v = mat.node_tree.nodes.new("ShaderNodeValue")
    v.outputs[0].default_value = 0.7
    mat.node_tree.links.new(v.outputs[0], b.inputs["Coat Weight"])
    b.inputs["Coat Roughness"].default_value = 0.2
    b.inputs["Coat IOR"].default_value = 1.6
    return mat


def displacement_material():
    mat = bpy.data.materials.new("C_Displacement")
    nt = mat.node_tree
    out = nt.nodes["Material Output"]
    noise = nt.nodes.new("ShaderNodeTexNoise")
    disp = nt.nodes.new("ShaderNodeDisplacement")
    nt.links.new(noise.outputs["Fac"], disp.inputs["Height"])
    nt.links.new(disp.outputs[0], out.inputs["Displacement"])
    return mat


def reroute_and_add():
    mat = bpy.data.materials.new("C_RerouteAdd")
    nt = _clear(mat)
    out = _out(nt)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    e = nt.nodes.new("ShaderNodeEmission")
    add = nt.nodes.new("ShaderNodeAddShader")
    r = nt.nodes.new("NodeReroute")
    nt.links.new(b.outputs[0], r.inputs[0])
    nt.links.new(r.outputs[0], add.inputs[0])
    nt.links.new(e.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs["Surface"])
    return mat


def grouped_principled():
    """Principled inside a node group: the group is opaque, so shader mode is used."""
    g = bpy.data.node_groups.get("C_ShaderGroup") or bpy.data.node_groups.new("C_ShaderGroup", "ShaderNodeTree")
    if not g.nodes:
        g.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        go = g.nodes.new("NodeGroupOutput")
        b = g.nodes.new("ShaderNodeBsdfPrincipled")
        g.links.new(b.outputs[0], go.inputs[0])
    mat = bpy.data.materials.new("C_GroupedPrincipled")
    nt = _clear(mat)
    out = _out(nt)
    gn = nt.nodes.new("ShaderNodeGroup")
    gn.node_tree = g
    nt.links.new(gn.outputs[0], out.inputs["Surface"])
    return mat


def toon():
    mat = bpy.data.materials.new("C_Toon")
    nt = _clear(mat)
    out = _out(nt)
    t = nt.nodes.new("ShaderNodeBsdfToon")
    t.inputs["Color"].default_value = (0.9, 0.5, 0.1, 1)
    nt.links.new(t.outputs[0], out.inputs["Surface"])
    return mat


def emission_only():
    mat = bpy.data.materials.new("C_EmissionOnly")
    nt = _clear(mat)
    out = _out(nt)
    e = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(e.outputs[0], out.inputs["Surface"])
    return mat


def empty_surface():
    mat = bpy.data.materials.new("C_EmptySurface")
    nt = _clear(mat)
    _out(nt)
    return mat


def muted_link():
    mat = bpy.data.materials.new("C_MutedLink")
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    v = nt.nodes.new("ShaderNodeRGB")
    l = nt.links.new(v.outputs[0], b.inputs["Base Color"])
    l.is_muted = True
    return mat


GENERATED = {f.__name__: f for f in (principled_basic, image_based, procedural, multi_principled, coat_material,
                                     displacement_material, reroute_and_add, grouped_principled, toon,
                                     emission_only, empty_surface, muted_link)}

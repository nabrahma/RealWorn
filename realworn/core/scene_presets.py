"""Scene presets (M7): Rainy Night — world volume, wet weather, practical lights, and a
compositor with glare (bloom), vignette and film grain."""

import bpy

PRESET_TAG = "rw_preset"


def _world(scene):
    w = bpy.data.worlds.get("RW_RainyNight") or bpy.data.worlds.new("RW_RainyNight")
    w[PRESET_TAG] = "rainy_night"
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.008, 0.012, 0.025, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.location = (0, -200)
    vol.inputs["Color"].default_value = (0.6, 0.7, 0.8, 1.0)
    vol.inputs["Density"].default_value = 0.012
    vol.inputs["Anisotropy"].default_value = 0.4
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    scene.world = w
    return w


def _lights(scene):
    """Two practical lights near the scene centre (a sodium lamp and a cyan sign)."""
    obs = [o for o in scene.objects if o.type == "MESH"]
    if obs:
        cs = [o.matrix_world.translation for o in obs]
        cx, cy = sum(c.x for c in cs) / len(cs), sum(c.y for c in cs) / len(cs)
    else:
        cx = cy = 0.0
    made = []
    for name, kind, color, power, loc in (
            ("RW_Night_Sodium", "POINT", (1.0, 0.55, 0.2), 350.0, (cx - 2.0, cy - 1.0, 3.2)),
            ("RW_Night_Neon", "AREA", (0.2, 0.85, 1.0), 220.0, (cx + 2.5, cy + 1.0, 2.2))):
        ob = bpy.data.objects.get(name)
        if ob is None:
            ob = bpy.data.objects.new(name, bpy.data.lights.new(name, kind))
            scene.collection.objects.link(ob)
        ob.data.color = color
        ob.data.energy = power
        if kind == "AREA":
            ob.data.size = 1.2
        ob.location = loc
        ob[PRESET_TAG] = "rainy_night"
        made.append(ob)
    return made


def _compositor(scene):
    ng = bpy.data.node_groups.get("RW_RainyNight_Comp")
    if ng is not None:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("RW_RainyNight_Comp", "CompositorNodeTree")
    ng[PRESET_TAG] = "rainy_night"
    # Blender 5.x: the scene's compositor group reads the render through a Render Layers node
    # (its Group Input stays empty) and its Group Output is the final image
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    gi, go = ng.nodes.new("CompositorNodeRLayers"), ng.nodes.new("NodeGroupOutput")
    gi.scene = scene
    glare = ng.nodes.new("CompositorNodeGlare")
    for kind in ("Bloom", "Fog Glow"):
        try:
            glare.inputs["Type"].default_value = kind
            break
        except TypeError:
            continue
    glare.inputs["Highlights Threshold"].default_value = 0.6
    glare.inputs["Strength"].default_value = 0.7
    ng.links.new(gi.outputs[0], glare.inputs["Image"])
    # vignette: soft ellipse mask, 0.55 at the corners -> 1 in the middle
    ell = ng.nodes.new("CompositorNodeEllipseMask")
    ell.inputs["Size"].default_value = (0.85, 0.75)
    blur = ng.nodes.new("CompositorNodeBlur")
    ng.links.new(ell.outputs[0], blur.inputs[0])
    for name, val in (("Size", (0.25, 0.25)),):
        if name in blur.inputs:
            try:
                blur.inputs[name].default_value = val
            except (TypeError, ValueError):
                pass
    vig = ng.nodes.new("ShaderNodeMapRange")
    vig.inputs["To Min"].default_value = 0.55
    ng.links.new(blur.outputs[0], vig.inputs["Value"])
    mul = ng.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    ng.links.new(glare.outputs[0], mul.inputs["A_Color" if "A_Color" in mul.inputs else 6])
    ng.links.new(vig.outputs[0], mul.inputs["B_Color" if "B_Color" in mul.inputs else 7])
    # film grain: fine noise in uniform image coordinates, +-3%
    coords = ng.nodes.new("CompositorNodeImageCoordinates")
    ng.links.new(gi.outputs[0], coords.inputs[0])
    noise = ng.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 900.0
    noise.inputs["Detail"].default_value = 0.0
    ng.links.new(coords.outputs[0], noise.inputs["Vector"])
    grain = ng.nodes.new("ShaderNodeMapRange")
    grain.inputs["To Min"].default_value = -0.03
    grain.inputs["To Max"].default_value = 0.03
    ng.links.new(noise.outputs["Fac"], grain.inputs["Value"])
    add = ng.nodes.new("ShaderNodeMix")
    add.data_type = "RGBA"
    add.blend_type = "ADD"
    add.inputs[0].default_value = 1.0
    ins = {s.identifier: s for s in add.inputs}
    outs = {s.identifier: s for s in mul.outputs}
    ng.links.new(outs["Result_Color"], ins["A_Color"])
    ng.links.new(grain.outputs[0], ins["B_Color"])
    ng.links.new(next(s for s in add.outputs if s.identifier == "Result_Color"), go.inputs[0])
    for i, n in enumerate((gi, glare, ell, blur, vig, mul, coords, noise, grain, add, go)):
        n.location = (i * 200, 0)
    scene.compositing_node_group = ng
    scene.render.use_compositing = True
    return ng


def rainy_night(scene):
    """Apply the Rainy Night look. Returns a list of what was set up."""
    p = scene.realworn
    p.wetness, p.rain, p.dirt, p.age, p.dust = 0.85, True, 0.6, 0.6, 0.0
    w = _world(scene)
    lights = _lights(scene)
    comp = _compositor(scene)
    vs = scene.view_settings
    vs.view_transform = "AgX"
    for look in ("AgX - Punchy", "Punchy"):
        try:
            vs.look = look
            break
        except TypeError:
            continue
    return [w.name] + [l.name for l in lights] + [comp.name]

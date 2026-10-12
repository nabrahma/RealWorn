"""Water layer (WAT-1..WAT-5): the compiler block around RW_P_Water.

The generic channels do the rest: the Water type's roughness channel (0.03, Mix) makes the
painted area glossy, which is WAT-5 too: any layer with low roughness reads as wet.
"""

from . import naming


def apply(b, layer, mask, cur, ctx):
    w = layer.water
    rough_node = b.nodes.get(naming.layer_node(layer.id, "roughness.value"))
    water_rough = rough_node.outputs[0] if rough_node is not None else layer.roughness.value
    g = b.group(naming.SH_WATER, "water", Color=cur["Base Color"], Coat_Weight=cur["Coat Weight"],
                Coat_Roughness=cur["Coat Roughness"], Coat_IOR=cur["Coat IOR"], Mask=mask,
                Base_Roughness=b.gi.outputs["Roughness"], Base_Metallic=b.gi.outputs["Metallic"],
                Water_Roughness=water_rough, Darken=w.darken, Depth=w.depth, Edge=w.edge)
    cur["Base Color"] = b.outp(g, "Color")
    cur["Coat Weight"] = b.outp(g, "Coat Weight")
    cur["Coat Roughness"] = b.outp(g, "Coat Roughness")
    cur["Coat IOR"] = b.outp(g, "Coat IOR")
    flatten = b.outp(g, "Flatten")
    if cur["Height"] is not None:  # WAT-3: standing water hides the relief of layers below
        cur["Height"] = b.mixf(flatten, cur["Height"], 0.0)
    ctx["flatten"] = flatten if ctx["flatten"] is None else b.max(ctx["flatten"], flatten)
    # the coat follows the flattened surface too
    cur["Coat Normal"] = b.mixv(flatten, cur["Coat Normal"], b.outp(b.named("ShaderNodeNewGeometry", "water.geo"),
                                                                       "Normal"))


def value_targets(layer, prop):
    sock = {"darken": "Darken", "depth": "Depth", "edge": "Edge"}.get(prop)
    return [("water", sock, getattr(layer.water, prop))] if sock else []

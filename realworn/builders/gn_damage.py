"""Builds the RW_Damage Geometry Nodes group: painted Geometry-mode damage (DMG-3, DMG-7).

Cutter points are scattered on the surface (Poisson disk) at Density per square metre; each point
carries RW_Paint interpolated inside its face and samples the Damage layer's painted mask (spike v2
d); only points where the mask passes Threshold are kept. Each cutter is a noisy icosphere (random size between Size Min and Max) pushed half
out along the surface normal so it bites a chip rather than drilling a hole. All cutters are
subtracted in ONE Mesh Boolean (Manifold, or Exact as a fallback). Cutter faces carry rw_cut,
which survives the Boolean, so break faces get the Inner Material and rw_damage. Optional debris
drops small rocks onto RW_Ground below the largest cutters.
"""

from ..core import naming
from ._dsl import Tree


def build():
    t = Tree.new_group(naming.GN_DAMAGE, "GEOMETRY")
    t.t.is_modifier = True
    t.t.description = "RealWorn painted geometry damage: Boolean chips where the Damage mask is painted"
    t.inp("Geometry", "GEO")
    img = t.t.interface.new_socket("Mask", in_out="INPUT", socket_type="NodeSocketImage")
    img.description = "The Damage layer's painted mask (sampled through RW_Paint)"
    t.inp("Threshold", "FLOAT", 0.5, 0.0, 1.0, subtype="FACTOR")
    t.inp("Density", "FLOAT", 400.0, 0.0, 100000.0, description="Cutters per square metre of painted area")
    t.inp("Size Min", "FLOAT", 0.015, 0.001, 2.0, subtype="DISTANCE")
    t.inp("Size Max", "FLOAT", 0.04, 0.001, 2.0, subtype="DISTANCE")
    t.inp("Seed", "INT", 0, 0, 100000)
    t.inp("Inner Material", "MATERIAL")
    t.inp("Use Exact", "BOOL", False, description="Exact Boolean solver (slower; for meshes Manifold rejects)")
    t.inp("Debris", "BOOL", False)
    t.inp("Ground", "COLLECTION")
    bimg = t.t.interface.new_socket("Base Height", in_out="INPUT", socket_type="NodeSocketImage")
    bimg.description = "v2.1 DMG-14: the base material's height map (cutters follow the carve)"
    buv = t.t.interface.new_socket("Base UV", in_out="INPUT", socket_type="NodeSocketString")
    buv.description = "UV map the base height image is mapped with"
    t.inp("Base Scale", "VECTOR", (1.0, 1.0, 1.0))
    t.inp("Base Low", "FLOAT", 0.0)
    t.inp("Base High", "FLOAT", 1.0)
    t.inp("Follow", "FLOAT", 0.0, 0.0, 1.0)
    t.out("Geometry", "GEO")

    geo = t.I("Geometry")
    seed = t.I("Seed")
    self_obj = t.node("GeometryNodeSelfObject")
    info = t.node("GeometryNodeObjectInfo", t.outp(self_obj), props={"transform_space": "ORIGINAL"})
    sx, sy, sz = t.sep(t.vmath("ABSOLUTE", t.outp(info, "Scale")))
    scale = t.max(t.div(t.add(t.add(sx, sy), sz), 3.0), 1e-6)
    smin, smax = t.div(t.I("Size Min"), scale), t.div(t.I("Size Max"), scale)

    # Scatter candidate points uniformly; each one inherits RW_Paint interpolated INSIDE its own
    # face (no seam averaging, no face-sized granularity), then keep only points whose painted mask
    # passes Threshold. Placement is texel-accurate whatever the mesh density.
    dens = t.mul(t.I("Density"), t.mul(scale, scale))  # per m^2 -> per object-space area
    dist = t.node("GeometryNodeDistributePointsOnFaces", geo, True, props={"distribute_method": "POISSON"},
                  Distance_Min=t.mul(smin, 0.8), Density_Max=dens, Seed=seed)
    uv = t.node("GeometryNodeInputNamedAttribute", naming.UV_PAINT, props={"data_type": "FLOAT_VECTOR"})
    tex = t.node("GeometryNodeImageTexture", props={"interpolation": "Linear"})
    t.links.new(t.gi.outputs["Mask"], tex.inputs["Image"])
    t.links.new(t.outp(uv, "Attribute"), tex.inputs["Vector"])
    painted = t.mul(t.outp(t.node("FunctionNodeSeparateColor", t.outp(tex, "Color")), "Red"), t.outp(tex, "Alpha"))
    # DMG-14: weight by the same follow-base factor as the shader carve, so real chips appear where
    # the carve is deepest (base height sampled through its own UV map and Mapping scale)
    buvn = t.node("GeometryNodeInputNamedAttribute", props={"data_type": "FLOAT_VECTOR"})
    t.links.new(t.gi.outputs["Base UV"], buvn.inputs["Name"])
    btex = t.node("GeometryNodeImageTexture", props={"interpolation": "Linear"})
    t.links.new(t.gi.outputs["Base Height"], btex.inputs["Image"])
    t.links.new(t.vmath("MULTIPLY", t.outp(buvn, "Attribute"), t.I("Base Scale")), btex.inputs["Vector"])
    bh = t.maprange(t.outp(t.node("FunctionNodeSeparateColor", t.outp(btex, "Color")), "Red"),
                    t.I("Base Low"), t.I("Base High"))
    painted = t.mul(painted, t.mixf(t.I("Follow"), 1.0, t.mul(bh, 2.0)))
    keep_pts = t.compare(painted, t.I("Threshold"), "GREATER_THAN")
    pts = t.outp(dist, "Points")
    normal = t.outp(dist, "Normal")
    pts = t.node("GeometryNodeStoreNamedAttribute", pts, True, "rw_cutter_n", normal,
                 props={"data_type": "FLOAT_VECTOR", "domain": "POINT"})
    pts = t.node("GeometryNodeDeleteGeometry", t.outp(pts), t.bool_op("NOT", keep_pts), props={"domain": "POINT"})
    idx = t.outp(t.node("GeometryNodeInputIndex"))
    size = t.outp(t.node("FunctionNodeRandomValue", smin, smax, ID=idx, Seed=t.add(seed, 13),
                         props={"data_type": "FLOAT"}))
    nrm = t.outp(t.node("GeometryNodeInputNamedAttribute", "rw_cutter_n", props={"data_type": "FLOAT_VECTOR"}))
    pushed = t.node("GeometryNodeSetPosition", t.outp(pts), True,
                    Offset=t.vmath("SCALE", nrm, scale=t.mul(size, 0.45)))
    rot = t.node("FunctionNodeRandomValue", (0.0, 0.0, 0.0), (6.2832, 6.2832, 6.2832), ID=idx,
                 Seed=t.add(seed, 29), props={"data_type": "FLOAT_VECTOR"})
    rot = t.node("FunctionNodeEulerToRotation", t.outp(rot))
    ico = t.node("GeometryNodeMeshIcoSphere", 1.0, 2)
    inst = t.node("GeometryNodeInstanceOnPoints", t.outp(pushed), True, t.outp(ico, "Mesh"),
                  Rotation=t.outp(rot), Scale=t.comb(size, size, size))
    cutters = t.node("GeometryNodeRealizeInstances", t.outp(inst))
    pos = t.outp(t.node("GeometryNodeInputPosition"))
    cn = t.outp(t.node("GeometryNodeInputNormal"))
    bumpy = t.sub(t.noise(t.vmath("SCALE", pos, scale=t.div(2.5, t.max(smax, 1e-4))), 1.0, detail=2.0), 0.5)
    cutters = t.node("GeometryNodeSetPosition", t.outp(cutters), True,
                     Offset=t.vmath("SCALE", cn, scale=t.mul_all(bumpy, smax, 0.9)))
    cutters = t.node("GeometryNodeStoreNamedAttribute", t.outp(cutters), True, naming.ATTR_CUT, 1.0,
                     props={"data_type": "FLOAT", "domain": "FACE"})
    cutters = t.node("GeometryNodeSetMaterial", t.outp(cutters), True, t.I("Inner Material"))

    boolean = {}
    for solver in ("MANIFOLD", "EXACT"):
        b = t.node("GeometryNodeMeshBoolean", props={"operation": "DIFFERENCE", "solver": solver})
        t.links.new(geo, b.inputs["Mesh 1"])
        t.links.new(t.outp(cutters), b.inputs["Mesh 2"])
        boolean[solver] = t.outp(b, "Mesh")
    result = t.switch(t.I("Use Exact"), boolean["MANIFOLD"], boolean["EXACT"], dtype="GEOMETRY")
    count = t.outp(t.node("GeometryNodeAttributeDomainSize", t.outp(pts), props={"component": "POINTCLOUD"}),
                   "Point Count")
    result = t.switch(t.compare(count, 0.5, "LESS_THAN"), result, geo, dtype="GEOMETRY")  # nothing painted

    cut = t.outp(t.node("GeometryNodeInputNamedAttribute", naming.ATTR_CUT, props={"data_type": "FLOAT"}))
    result = t.node("GeometryNodeSetMaterial", result, t.compare(cut, 0.5, "GREATER_THAN"), t.I("Inner Material"))
    result = t.node("GeometryNodeStoreNamedAttribute", t.outp(result), True, naming.ATTR_DAMAGE, cut,
                    props={"data_type": "FLOAT", "domain": "POINT"}, label="rw_damage")
    result = t.node("GeometryNodeRemoveAttribute", t.outp(result), Name=naming.ATTR_CUT)

    # DMG-7 debris: below the largest 40 % of cutters, dropped onto RW_Ground
    ground = t.node("GeometryNodeCollectionInfo", t.I("Ground"), props={"transform_space": "RELATIVE"})
    ground_mesh = t.node("GeometryNodeRealizeInstances", t.outp(ground))
    inv = t.node("FunctionNodeInvertMatrix", t.outp(info, "Transform"))
    down = t.vmath("NORMALIZE", t.outp(t.node("FunctionNodeTransformDirection", (0.0, 0.0, -1.0),
                                              t.outp(inv, "Matrix"))))
    large = t.compare(size, t.add(smin, t.mul(t.sub(smax, smin), 0.6)), "GREATER_THAN")
    big = t.node("GeometryNodeDeleteGeometry", t.outp(pts),
                 t.bool_op("NOT", t.bool_op("AND", large, t.I("Debris"))), props={"domain": "POINT"})
    ray = t.node("GeometryNodeRaycast", t.outp(ground_mesh), Source_Position=pos, Ray_Direction=down,
                 Ray_Length=t.div(100.0, scale))
    hits = t.node("GeometryNodeDeleteGeometry", t.outp(big), t.bool_op("NOT", t.outp(ray, "Is Hit")),
                  props={"domain": "POINT"})
    landed = t.node("GeometryNodeSetPosition", t.outp(hits), True, Position=t.outp(ray, "Hit Position"))
    rock = t.node("GeometryNodeMeshIcoSphere", 1.0, 1)
    rsize = t.outp(t.node("FunctionNodeRandomValue", t.mul(smin, 0.4), t.mul(smax, 0.6), ID=idx,
                          Seed=t.add(seed, 41), props={"data_type": "FLOAT"}))
    rocks = t.node("GeometryNodeInstanceOnPoints", t.outp(landed), True, t.outp(rock, "Mesh"), Rotation=t.outp(rot),
                   Scale=t.comb(rsize, t.mul(rsize, 0.8), t.mul(rsize, 0.55)))
    rocks = t.node("GeometryNodeRealizeInstances", t.outp(rocks))
    rocks = t.node("GeometryNodeSetMaterial", t.outp(rocks), True, t.I("Inner Material"))

    out = t.node("GeometryNodeJoinGeometry")
    t.links.new(t.outp(result), out.inputs[0])
    t.links.new(t.outp(rocks), out.inputs[0])
    t.O("Geometry", t.outp(out))
    t.layout()
    return [t.t]

"""Builds the RW_Damage Geometry Nodes group (DMG-1..DMG-9).

Cutters (noisy, displaced icospheres) are spread along convex edges by Density per metre,
thinned by Strength and a clustering noise; vertices where three or more convex edges meet
get larger corner cutters. All cutters are subtracted in ONE Mesh Boolean (Manifold, or
Exact as a fallback) so overlapping chips merge. Cutter faces carry rw_cut, which propagates
through the Boolean (M0 spike b), so break faces get the inner material and rw_damage.
Optional debris: small rocks dropped onto RW_Ground straight below the largest cutters.
"""

import math

from ..core import naming
from ._dsl import Tree


def build():
    t = Tree.new_group(naming.GN_DAMAGE, "GEOMETRY")
    t.t.is_modifier = True
    t.t.description = "RealWorn geometry damage: Boolean chips and corner breaks"
    t.inp("Geometry", "GEO")
    t.inp("Strength", "FLOAT", 0.5, 0.0, 1.0, subtype="FACTOR")
    t.inp("Seed", "INT", 0, 0, 100000)
    t.inp("Size Min", "FLOAT", 0.03, 0.001, 2.0, subtype="DISTANCE")
    t.inp("Size Max", "FLOAT", 0.08, 0.001, 2.0, subtype="DISTANCE")
    t.inp("Density", "FLOAT", 6.0, 0.0, 100.0, description="Cutters per metre of convex edge before thinning")
    t.inp("Corners", "BOOL", True)
    t.inp("Corner Scale", "FLOAT", 2.2, 1.0, 10.0)
    t.inp("Edge Angle Threshold", "FLOAT", math.radians(20), 0.0, math.pi, subtype="ANGLE",
          description="Edges sharper than this get chips (20 deg also catches 3-segment bevels)")
    t.inp("Inner Material", "MATERIAL")
    t.inp("Use Exact", "BOOL", False, description="Exact Boolean solver (slower; for meshes Manifold rejects)")
    t.inp("Debris", "BOOL", False)
    t.inp("Ground", "COLLECTION")
    t.out("Geometry", "GEO")

    geo = t.I("Geometry")
    seed = t.I("Seed")
    self_obj = t.node("GeometryNodeSelfObject")
    info = t.node("GeometryNodeObjectInfo", t.outp(self_obj), props={"transform_space": "ORIGINAL"})
    sx, sy, sz = t.sep(t.vmath("ABSOLUTE", t.outp(info, "Scale")))
    scale = t.max(t.div(t.add(t.add(sx, sy), sz), 3.0), 1e-6)
    smin, smax = t.div(t.I("Size Min"), scale), t.div(t.I("Size Max"), scale)

    angle = t.outp(t.node("GeometryNodeInputMeshEdgeAngle"), "Signed Angle")
    convex = t.compare(angle, t.I("Edge Angle Threshold"), "GREATER_THAN")
    pos = t.outp(t.node("GeometryNodeInputPosition"))

    # ---- edge cutter points
    curve = t.node("GeometryNodeMeshToCurve", geo, convex)
    spacing = t.div(t.div(1.0, t.max(t.I("Density"), 0.01)), scale)
    pts = t.node("GeometryNodeCurveToPoints", t.outp(curve), props={"mode": "LENGTH"}, Length=spacing)
    idx = t.outp(t.node("GeometryNodeInputIndex"))
    rnd = t.outp(t.node("FunctionNodeRandomValue", 0.0, 1.0, ID=idx, Seed=seed, props={"data_type": "FLOAT"}))
    cluster = t.noise(t.vmath("ADD", t.vmath("SCALE", pos, scale=t.mul(scale, 1.7)), t.comb(seed, seed, seed)), 1.0,
                      detail=1.0)
    keep = t.compare(rnd, t.mul(t.I("Strength"), t.add(0.2, t.mul(cluster, 1.3))), "LESS_THAN")
    edge_pts = t.node("GeometryNodeDeleteGeometry", t.outp(pts, "Points"), t.bool_op("NOT", keep),
                      props={"domain": "POINT"})

    # ---- corner cutter points: vertices with >= 3 convex edges
    conv_f = t.node("GeometryNodeFieldOnDomain", t.switch(convex, 0.0, 1.0),
                    props={"domain": "EDGE", "data_type": "FLOAT"})
    nb = t.outp(t.node("GeometryNodeInputMeshVertexNeighbors"), "Vertex Count")
    is_corner = t.compare(t.mul(t.outp(conv_f), nb), 2.5, "GREATER_THAN")
    crnd = t.outp(t.node("FunctionNodeRandomValue", 0.0, 1.0, ID=idx, Seed=t.add(seed, 7),
                         props={"data_type": "FLOAT"}))
    corner_sel = t.bool_op("AND", t.bool_op("AND", is_corner, t.I("Corners")),
                           t.compare(crnd, t.add(t.I("Strength"), 0.25), "LESS_THAN"))
    corner_pts = t.node("GeometryNodeMeshToPoints", geo, corner_sel, props={"mode": "VERTICES"})
    corner_pts = t.node("GeometryNodeStoreNamedAttribute", t.outp(corner_pts), True, naming.ATTR_CORNER, 1.0,
                        props={"data_type": "FLOAT", "domain": "POINT"})
    all_pts = t.node("GeometryNodeJoinGeometry")
    t.links.new(t.outp(edge_pts), all_pts.inputs[0])
    t.links.new(t.outp(corner_pts), all_pts.inputs[0])

    # ---- cutters: random size (corners larger), random rotation, noisy surface
    is_c = t.outp(t.node("GeometryNodeInputNamedAttribute", naming.ATTR_CORNER, props={"data_type": "FLOAT"}))
    size = t.outp(t.node("FunctionNodeRandomValue", smin, smax, ID=idx, Seed=t.add(seed, 13),
                         props={"data_type": "FLOAT"}))
    size = t.mul(size, t.mixf(is_c, 1.0, t.I("Corner Scale")))
    rot = t.node("FunctionNodeRandomValue", (0.0, 0.0, 0.0), (6.2832, 6.2832, 6.2832), ID=idx,
                 Seed=t.add(seed, 29), props={"data_type": "FLOAT_VECTOR"})
    rot = t.node("FunctionNodeEulerToRotation", t.outp(rot))
    # chips bite the edge from outside: push each cutter out along the edge bisector (the vertex
    # normal of the nearest mesh vertex) so its depth is ~half its size, not a drilled hole
    nearest = t.node("GeometryNodeSampleNearest", geo, props={"domain": "POINT"})
    bisector = t.node("GeometryNodeSampleIndex", geo, t.outp(t.node("GeometryNodeInputNormal"), "Normal"),
                      t.outp(nearest), props={"data_type": "FLOAT_VECTOR", "domain": "POINT"})
    pushed = t.node("GeometryNodeSetPosition", t.outp(all_pts), True,
                    Offset=t.vmath("SCALE", t.outp(bisector), scale=t.mul(size, 0.45)))
    ico = t.node("GeometryNodeMeshIcoSphere", 1.0, 2)
    inst = t.node("GeometryNodeInstanceOnPoints", t.outp(pushed), True, t.outp(ico, "Mesh"),
                  Rotation=t.outp(rot), Scale=t.comb(size, size, size))
    cutters = t.node("GeometryNodeRealizeInstances", t.outp(inst))
    nrm = t.outp(t.node("GeometryNodeInputNormal"))
    bumpy = t.sub(t.noise(t.vmath("SCALE", pos, scale=t.div(2.5, t.max(smax, 1e-4))), 1.0, detail=2.0), 0.5)
    cutters = t.node("GeometryNodeSetPosition", t.outp(cutters), True,
                     Offset=t.vmath("SCALE", nrm, scale=t.mul_all(bumpy, smax, 0.9)))
    cutters = t.node("GeometryNodeStoreNamedAttribute", t.outp(cutters), True, naming.ATTR_CUT, 1.0,
                     props={"data_type": "FLOAT", "domain": "FACE"})
    cutters = t.node("GeometryNodeSetMaterial", t.outp(cutters), True, t.I("Inner Material"))

    # ---- one batched Boolean (Manifold, or Exact as a fallback); Switch is lazy
    boolean = {}
    for solver in ("MANIFOLD", "EXACT"):
        b = t.node("GeometryNodeMeshBoolean", props={"operation": "DIFFERENCE", "solver": solver})
        t.links.new(geo, b.inputs["Mesh 1"])
        t.links.new(t.outp(cutters), b.inputs["Mesh 2"])
        boolean[solver] = t.outp(b, "Mesh")
    result = t.switch(t.I("Use Exact"), boolean["MANIFOLD"], boolean["EXACT"], dtype="GEOMETRY")
    no_cutters = t.compare(t.outp(t.node("GeometryNodeAttributeDomainSize", t.outp(all_pts),
                                         props={"component": "POINTCLOUD"}), "Point Count"), 0.5, "LESS_THAN")
    result = t.switch(no_cutters, result, geo, dtype="GEOMETRY")

    cut = t.outp(t.node("GeometryNodeInputNamedAttribute", naming.ATTR_CUT, props={"data_type": "FLOAT"}))
    result = t.node("GeometryNodeSetMaterial", result, t.compare(cut, 0.5, "GREATER_THAN"), t.I("Inner Material"))
    result = t.node("GeometryNodeStoreNamedAttribute", t.outp(result), True, naming.ATTR_DAMAGE, cut,
                    props={"data_type": "FLOAT", "domain": "POINT"}, label="rw_damage")
    result = t.node("GeometryNodeRemoveAttribute", t.outp(result), Name=naming.ATTR_CUT)

    # ---- debris below the largest cutters (corners), dropped onto RW_Ground
    ground = t.node("GeometryNodeCollectionInfo", t.I("Ground"), props={"transform_space": "RELATIVE"})
    ground_mesh = t.node("GeometryNodeRealizeInstances", t.outp(ground))
    inv = t.node("FunctionNodeInvertMatrix", t.outp(info, "Transform"))
    down = t.vmath("NORMALIZE", t.outp(t.node("FunctionNodeTransformDirection", (0.0, 0.0, -1.0),
                                              t.outp(inv, "Matrix"))))
    # the largest breaks: corner cutters or the top 30% of the size range, about 60% of them
    large = t.bool_op("OR", t.compare(is_c, 0.5, "GREATER_THAN"),
                      t.compare(size, t.add(smin, t.mul(t.sub(smax, smin), 0.7)), "GREATER_THAN"))
    drnd = t.outp(t.node("FunctionNodeRandomValue", 0.0, 1.0, ID=idx, Seed=t.add(seed, 53),
                         props={"data_type": "FLOAT"}))
    debris_sel = t.bool_op("AND", t.bool_op("AND", large, t.I("Debris")), t.compare(drnd, 0.6, "LESS_THAN"))
    big = t.node("GeometryNodeDeleteGeometry", t.outp(all_pts), t.bool_op("NOT", debris_sel),
                 props={"domain": "POINT"})
    ray = t.node("GeometryNodeRaycast", t.outp(ground_mesh), Source_Position=pos, Ray_Direction=down,
                 Ray_Length=t.div(100.0, scale))
    # drop misses first, then move: the raycast field is evaluated from the points' own positions
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
    clean = t.node("GeometryNodeRemoveAttribute", t.outp(out), Name=naming.ATTR_CORNER)
    t.O("Geometry", t.outp(clean))
    t.layout()
    return [t.t]

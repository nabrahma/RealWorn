"""Builds the RW_Masks Geometry Nodes group (MASK-1..MASK-5, rw_shelter for M4).

Writes point-domain float attributes on the (optionally pre-subdivided) mesh:
rw_edge     distance falloff to convex edges (signed angle > +threshold), blurred
rw_cavity   distance falloff to concave edges (signed angle < -threshold), blurred
rw_contact  distance falloff to the RW_Ground collection surfaces
rw_shelter  1 where a ray straight up (world Z) hits the RW_Occluders collection
Widths are world-space metres: they are divided by the object's mean scale.
"""

import math

from ..core import naming
from ._dsl import Tree

FACE_BUDGET = 1_500_000  # auto pre-subdivide never exceeds this many faces


def _falloff(t, dist, width):
    """1 at distance 0, smooth to 0 at `width`."""
    return t.maprange(dist, 0.0, width, 1.0, 0.0, interp="SMOOTHSTEP")


def _edge_distance_mask(t, mesh, selection, width, blur):
    """Mask that is 1 on the selected edges and falls off over `width`."""
    keep_only = t.node("GeometryNodeDeleteGeometry", mesh, t.bool_op("NOT", selection),
                       props={"domain": "EDGE", "mode": "EDGE_FACE"}, label="Keep selected edges")
    prox = t.node("GeometryNodeProximity", Target=t.outp(keep_only), props={"target_element": "EDGES"})
    dist, valid = t.outp(prox, "Distance"), t.outp(prox, "Is Valid")
    sharp = t.mul(_falloff(t, dist, width), valid)
    blurred = t.node("GeometryNodeBlurAttribute", sharp, blur, props={"data_type": "FLOAT"})
    # Blur works in vertex rings; bound its reach to 3x the width in metres so coarse
    # meshes do not smear the band across whole faces.
    reach = t.mul(_falloff(t, dist, t.mul(width, 3.0)), valid)
    return t.max(sharp, t.mul(t.outp(blurred), reach))


def build():
    t = Tree.new_group(naming.GN_MASKS, "GEOMETRY")
    t.t.is_modifier = True
    t.t.description = "RealWorn mask engine: writes rw_edge, rw_cavity, rw_contact, rw_shelter"
    t.inp("Geometry", "GEO")
    t.inp("Edge Angle Threshold", "FLOAT", math.radians(25), 0.0, math.pi, subtype="ANGLE",
          description="Edges sharper than this count as convex (wear) or concave (dirt)")
    t.inp("Edge Width", "FLOAT", 0.015, 0.0, 1.0, subtype="DISTANCE",
          description="World-space width of the edge wear band")
    t.inp("Cavity Width", "FLOAT", 0.03, 0.0, 1.0, subtype="DISTANCE",
          description="World-space width of the cavity dirt band")
    t.inp("Contact Width", "FLOAT", 0.15, 0.0, 5.0, subtype="DISTANCE",
          description="World-space distance over which ground contact grime fades")
    t.inp("Blur Iterations", "INT", 2, 0, 20, description="Softens the edge and cavity bands")
    t.inp("Pre-Subdivide", "INT", -1, -1, 3,
          description="Simple subdivisions before masking; -1 = auto (until edges are under 4x Edge Width, max 3)")
    t.inp("Use Contact", "BOOL", True, description="Compute contact grime against RW_Ground")
    t.inp("Ground", "COLLECTION")
    t.inp("Use Shelter", "BOOL", True, description="Compute shelter against RW_Occluders")
    t.inp("Occluders", "COLLECTION")
    t.out("Geometry", "GEO")

    geo = t.I("Geometry")

    # World-space widths -> object space via the mean absolute object scale.
    self_obj = t.node("GeometryNodeSelfObject")
    info = t.node("GeometryNodeObjectInfo", t.outp(self_obj), props={"transform_space": "ORIGINAL"})
    sx, sy, sz = t.sep(t.vmath("ABSOLUTE", t.outp(info, "Scale")))
    scale = t.max(t.div(t.add(t.add(sx, sy), sz), 3.0), 1e-6)
    edge_w = t.div(t.I("Edge Width"), scale)
    cav_w = t.div(t.I("Cavity Width"), scale)
    con_w = t.div(t.I("Contact Width"), scale)

    # MASK-3 auto pre-subdivide: levels so mean edge length <= 4 * edge width.
    ev = t.node("GeometryNodeInputMeshEdgeVertices")
    elen = t.vmath("DISTANCE", t.outp(ev, "Position 1"), t.outp(ev, "Position 2"))
    stat = t.node("GeometryNodeAttributeStatistic", geo, True, elen, props={"domain": "EDGE", "data_type": "FLOAT"})
    ratio = t.div(t.outp(stat, "Mean"), t.max(t.mul(edge_w, 4.0), 1e-6))
    need = t.math("CEIL", t.math("LOGARITHM", t.max(ratio, 1.0), 2.0))
    size = t.node("GeometryNodeAttributeDomainSize", geo, props={"component": "MESH"})
    budget = t.math("FLOOR", t.math("LOGARITHM", t.div(FACE_BUDGET, t.max(t.outp(size, "Face Count"), 1.0)), 4.0))
    auto = t.max(t.min(t.min(need, budget), 3.0), 0.0)
    level = t.switch(t.compare(t.I("Pre-Subdivide"), -0.5, "LESS_THAN"), t.I("Pre-Subdivide"), auto, dtype="INT")
    mesh = t.outp(t.node("GeometryNodeSubdivideMesh", geo, level))

    # Convex and concave edge masks from the signed edge angle (convex is POSITIVE in 5.x).
    angle = t.outp(t.node("GeometryNodeInputMeshEdgeAngle"), "Signed Angle")
    thr = t.I("Edge Angle Threshold")
    convex = t.compare(angle, thr, "GREATER_THAN")
    concave = t.compare(angle, t.mul(thr, -1.0), "LESS_THAN")
    edge = _edge_distance_mask(t, mesh, convex, edge_w, t.I("Blur Iterations"))
    cavity = _edge_distance_mask(t, mesh, concave, cav_w, t.I("Blur Iterations"))

    # Contact: distance to RW_Ground surfaces in this object's space.
    ground = t.node("GeometryNodeCollectionInfo", t.I("Ground"), props={"transform_space": "RELATIVE"})
    ground_mesh = t.node("GeometryNodeRealizeInstances", t.outp(ground))
    gprox = t.node("GeometryNodeProximity", Target=t.outp(ground_mesh), props={"target_element": "FACES"})
    contact = t.mul_all(_falloff(t, t.outp(gprox, "Distance"), con_w), t.outp(gprox, "Is Valid"),
                        t.I("Use Contact"))

    # Shelter: ray straight up in world space, expressed in object space.
    inv = t.node("FunctionNodeInvertMatrix", t.outp(info, "Transform"))
    up = t.vmath("NORMALIZE", t.outp(t.node("FunctionNodeTransformDirection", (0.0, 0.0, 1.0), t.outp(inv, "Matrix"))))
    occ = t.node("GeometryNodeCollectionInfo", t.I("Occluders"), props={"transform_space": "RELATIVE"})
    occ_mesh = t.node("GeometryNodeRealizeInstances", t.outp(occ))
    pos = t.outp(t.node("GeometryNodeInputPosition"))
    start = t.vmath("ADD", pos, t.vmath("SCALE", up, scale=t.div(0.01, scale)))
    ray = t.node("GeometryNodeRaycast", t.outp(occ_mesh), Source_Position=start, Ray_Direction=up,
                 Ray_Length=t.div(10000.0, scale))
    hit = t.mul(t.outp(ray, "Is Hit"), t.I("Use Shelter"))
    shelter = t.outp(t.node("GeometryNodeBlurAttribute", hit, 1, props={"data_type": "FLOAT"}))

    out = mesh
    for name, value in ((naming.ATTR_EDGE, edge), (naming.ATTR_CAVITY, cavity),
                        (naming.ATTR_CONTACT, contact), (naming.ATTR_SHELTER, shelter)):
        st = t.node("GeometryNodeStoreNamedAttribute", out, True, name, value,
                    props={"data_type": "FLOAT", "domain": "POINT"}, label=name)
        out = t.outp(st)
    t.O("Geometry", out)
    t.layout()
    return [t.t]

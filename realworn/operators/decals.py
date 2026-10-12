"""Decal operators: Place (modal), Place at Cursor, Auto Leaks, Clean Up Decals (W5, W6)."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from ..core import decals
from ..props import DECAL_MODE_ITEMS
from .common import OBJECTS_DESC, target_objects


def _report(op, reps):
    for level, msg in reps:
        op.report({level}, msg)


class RW_OT_decal_place(bpy.types.Operator):
    """Place a projector decal: move over a surface, scroll to scale, R to rotate, click to place, Esc to cancel"""
    bl_idname = "realworn.decal_place"
    bl_label = "Place Decal"
    bl_options = {"REGISTER", "UNDO"}

    image: StringProperty(name="Image", default="", description="Library file name; empty uses the panel choice")
    mode: EnumProperty(name="Mode", items=DECAL_MODE_ITEMS, default="FULL")
    size: FloatProperty(name="Size", default=0.6, min=0.01, subtype="DISTANCE")
    rotation: FloatProperty(name="Rotation", default=0.0, subtype="ANGLE")
    location: FloatVectorProperty(name="Location", size=3, subtype="XYZ")
    normal: FloatVectorProperty(name="Normal", size=3, default=(0.0, 0.0, 0.0),
                                description="Surface normal; non-zero places without the modal tool")
    use_cursor: BoolProperty(name="At 3D Cursor", default=False,
                             description="Place at the 3D cursor, projecting along the cursor's -Z")

    def _defaults(self, context):
        p = context.scene.realworn
        if not self.image:
            self.image = p.decal_image
        return p

    def execute(self, context):
        p = self._defaults(context)
        if self.use_cursor:
            cur = context.scene.cursor
            loc, nrm = cur.location.copy(), cur.matrix.to_3x3() @ Vector((0, 0, 1))
        else:
            loc, nrm = Vector(self.location), Vector(self.normal)
        if nrm.length < 1e-6:
            self.report({"ERROR"}, "Pass a normal or use the modal tool in the viewport")
            return {"CANCELLED"}
        try:
            empty, rep = decals.place(context.scene, self.image, loc, nrm, size=self.size, mode=self.mode,
                                      rotation=self.rotation)
        except decals.DecalError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        _report(self, rep)
        self.report({"INFO"}, "Placed {} on {}".format(empty.name, ", ".join(empty["rw_targets"]) or "nothing"))
        return {"FINISHED"}

    # ------------------------------------------------------------- modal
    def invoke(self, context, event):
        p = self._defaults(context)
        self.mode, self.size = p.decal_mode, p.decal_size
        if self.use_cursor or Vector(self.normal).length > 0:
            return self.execute(context)
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"WARNING"}, "Run Place Decal from the 3D Viewport")
            return {"CANCELLED"}
        self._prev = bpy.data.objects.new("RW_DecalPreview", None)
        self._prev.empty_display_type = "CUBE"
        context.scene.collection.objects.link(self._prev)
        self._hit = None
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Place decal: click to place, scroll to scale, R rotate, Esc cancel")
        return {"RUNNING_MODAL"}

    def _raycast(self, context, event):
        from bpy_extras import view3d_utils
        region, rv3d = context.region, context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        hit, loc, nrm, _i, ob, _m = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
        return (loc, nrm) if hit and not decals.is_decal(ob) else None

    def _update_preview(self):
        if self._hit is None:
            return
        loc, nrm = self._hit
        rot = decals.orientation(nrm, self.rotation)
        s = self.size / 2.0
        self._prev.matrix_world = Matrix.Translation(loc) @ (rot @ Matrix.Diagonal((s, s, max(0.05, s * 0.5)))).to_4x4()

    def _finish(self, context):
        bpy.data.objects.remove(self._prev)
        context.area.header_text_set(None)

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            self._hit = self._raycast(context, event)
            self._update_preview()
        elif event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            self.size *= 1.1 if event.type == "WHEELUPMOUSE" else 1 / 1.1
            self._update_preview()
        elif event.type == "R" and event.value == "PRESS":
            self.rotation += math.radians(15.0)
            self._update_preview()
        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self._hit is None:
                return {"RUNNING_MODAL"}
            self._finish(context)
            self.location, self.normal = self._hit
            context.scene.realworn.decal_size = self.size
            return self.execute(context)
        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self._finish(context)
            return {"CANCELLED"}
        else:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


class RW_OT_decal_auto_leaks(bpy.types.Operator):
    """Spawn grime leak decals below overhangs, sills and parapets of the selected objects"""
    bl_idname = "realworn.decal_auto_leaks"
    bl_label = "Auto Leaks"
    bl_options = {"REGISTER", "UNDO"}

    seed: IntProperty(name="Seed", default=0, min=0)
    spacing: FloatProperty(name="Spacing", default=1.5, min=0.2, max=10.0, subtype="DISTANCE")
    objects: StringProperty(name="Objects", description=OBJECTS_DESC, default="")

    def invoke(self, context, event):
        self.seed = context.scene.realworn.leak_seed
        return self.execute(context)

    def execute(self, context):
        obs = target_objects(context, self.objects)
        made, rep = decals.auto_leaks(context.scene, obs, seed=self.seed, spacing=self.spacing)
        _report(self, rep)
        self.report({"INFO"}, "Spawned {} leak decal(s)".format(len(made)))
        return {"FINISHED"}


class RW_OT_decal_cleanup(bpy.types.Operator):
    """Remove decal layers whose Empty was deleted and re-target decals that were moved"""
    bl_idname = "realworn.decal_cleanup"
    bl_label = "Clean Up Decals"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = decals.cleanup(context.scene, retarget=True)
        self.report({"INFO"}, "Updated {} decal layer set(s)".format(n))
        return {"FINISHED"}


_classes = (RW_OT_decal_place, RW_OT_decal_auto_leaks, RW_OT_decal_cleanup)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    decals.free_previews()

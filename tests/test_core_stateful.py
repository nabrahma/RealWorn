"""Stateful property test (PRD v3 "Other required suites"; Hypothesis RuleBasedStateMachine).

Random sequences of add (kind and preset), delete, move, hide, content and value changes, load and
swap a texture, synthetic paint, duplicate, compile, save and reload, remove and re-setup, across
the six kinds. Invariants after every step: the stack group exists and recompiling it changes
nothing (determinism), and no RW:: node belongs to a layer that is gone or hidden. At the end
Remove restores the object exactly.
"""

import os
import uuid

import bpy
import numpy as np
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from corpus.generated import GENERATED
from realworn.core import compiler, images, kinds as K, layers, naming, setup, snapshot
from test_core_setup import state_of, uv_cube

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
PRESETS = [(k, None) for k in K.KINDS] + [(k, p) for k in K.PRESETS for p, _ in K.preset_items(k)]


def _sets():
    """Two tiny texture sets on disk (made once per run)."""
    out = []
    for name, val in (("set_a_1m", 0.3), ("set_b_50cm", 0.7)):
        folder = os.path.join(OUT, "stateful_sets", name)
        if not os.path.isdir(folder):
            os.makedirs(folder)
            for suffix in ("diff", "rough", "disp"):
                img = bpy.data.images.new("t", 8, 8)
                img.pixels.foreach_set(np.full(256, val, np.float32))
                img.filepath_raw = os.path.join(folder, "{}_{}.png".format(name, suffix))
                img.file_format = "PNG"
                img.save()
                bpy.data.images.remove(img)
        out.append(folder)
    return out


class LayerStackMachine(RuleBasedStateMachine):
    @initialize(base=st.sampled_from(("principled_basic", "image_based", "procedural", "multi_principled")))
    def start(self, base):
        bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
        ob = uv_cube(bpy.context.scene, "Prop", material=GENERATED[base]())
        self.obj_name = ob.name
        self.initial = state_of(ob)
        self.sets = _sets()
        setup.setup_object(ob)
        self.mat_name = ob.material_slots[0].material.name

    # ---------------------------------------------------------------- access
    @property
    def ob(self):
        return bpy.data.objects[self.obj_name]

    @property
    def mat(self):
        return bpy.data.materials[self.mat_name]

    @property
    def n(self):
        return len(self.mat.realworn.layers)

    def layer(self, i):
        return self.mat.realworn.layers[i % self.n]

    # ----------------------------------------------------------------- rules
    @rule(kp=st.sampled_from(PRESETS))
    def add(self, kp):
        if self.n < 8:
            layers.add_layer(self.mat, kp[0], kp[1])

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7))
    def delete(self, i):
        layers.remove_layer(self.mat, i % self.n)

    @precondition(lambda self: self.n > 1)
    @rule(i=st.integers(0, 7), up=st.booleans())
    def move(self, i, up):
        layers.move_layer(self.mat, i % self.n, 1 if up else -1)

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7))
    def toggle(self, i):
        ly = self.layer(i)
        ly.visible = not ly.visible

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), content=st.sampled_from(K.CONTENTS))
    def set_content(self, i, content):
        self.layer(i).content = content

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), prop=st.sampled_from(("opacity", "hue", "saturation", "value", "sharpness",
                                                     "threshold", "breakup_amount", "breakup_contrast",
                                                     "depth_mm", "edge_dark", "width_mm", "distance_cm")),
          v=st.floats(0.0, 1.0))
    def value(self, i, prop, v):
        ly = self.layer(i)
        if prop in ("hue",):
            v -= 0.5
        if prop in ("depth_mm", "width_mm", "distance_cm"):
            v = 0.1 + v * 20.0
        if prop == "breakup_contrast":
            v *= 0.9
        setattr(ly, prop, v)

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), which=st.integers(0, 1), base=st.booleans())
    def load_texture(self, i, which, base):
        """LT-5: loading over a set swaps its maps and keeps everything else."""
        layers.load_texture(self.mat, self.sets[which], None if base else self.layer(i))

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), frac=st.floats(0.0, 1.0), seed=st.integers(0, 1000))
    def paint(self, i, frac, seed):
        ly = self.layer(i)
        if not K.paintable(ly.kind):
            return
        if ly.mask_image is None:
            ly.mask_image = images.create_mask(self.ob, ly, res=32)
        rng = np.random.default_rng(seed)
        px = (rng.random((32, 32)) < frac).astype(np.float32)
        ly.mask_image.pixels.foreach_set(np.repeat(px.ravel(), 4))
        ly.mask_image.update()

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7))
    def bake_toggle(self, i):
        ly = self.layer(i)
        if ly.kind in ("EDGE_WEAR", "DIRT"):
            ly.edge_source = "BAKED" if ly.edge_source == "LIVE" else "LIVE"

    @precondition(lambda self: 0 < self.n < 8)
    @rule(i=st.integers(0, 7))
    def duplicate(self, i):
        layers.duplicate_layer(self.mat, i % self.n)

    @rule()
    def recompile(self):
        compiler.compile(self.mat)

    @rule()
    def save_and_reload(self):
        # a fresh file per save: no version backups to rename, no clash between runs
        folder = os.path.join(OUT, "stateful")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "s_{}.blend".format(uuid.uuid4().hex[:8]))
        bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=path)
        os.remove(path)

    @rule()
    def remove_and_setup_again(self):
        assert setup.remove_object(self.ob) == []
        assert state_of(self.ob) == self.initial
        setup.setup_object(self.ob)
        self.mat_name = self.ob.material_slots[0].material.name

    # ------------------------------------------------------------ invariants
    @invariant()
    def deterministic_and_clean(self):
        if not hasattr(self, "mat_name"):
            return
        mat = self.mat
        g = mat.realworn.stack
        assert g is not None and mat.realworn.applied
        before = snapshot.dumps(snapshot.serialize(g, include_owned=True))
        compiler.compile(mat)
        assert snapshot.dumps(snapshot.serialize(g, include_owned=True)) == before
        live = {ly.id for ly in mat.realworn.layers if ly.visible} | {"stack", "base"}
        for nd in g.nodes:
            if nd.name.startswith(naming.NODE_PREFIX) and nd.name not in ("RW::in", "RW::out"):
                assert nd.name.split("::")[1] in live, nd.name

    def teardown(self):
        if hasattr(self, "obj_name") and self.obj_name in bpy.data.objects:
            assert setup.remove_object(self.ob) == []
            assert state_of(self.ob) == self.initial


LayerStackMachine.TestCase.settings = settings(max_examples=60, stateful_step_count=14, deadline=None,
                                               suppress_health_check=list(HealthCheck))
test_layer_stack_state_machine = LayerStackMachine.TestCase

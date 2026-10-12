"""Suite 3: stateful property test (Hypothesis RuleBasedStateMachine).

Random sequences of add, delete, move, toggle, change channel value / blend / enable,
synthetic paint, references, duplicate, compile, save and reload, remove and re-setup.
Invariants after every step: the stack group exists and recompiling it changes nothing
(determinism), no RW:: node belongs to a layer that is gone or hidden, references only point
down. At the end Remove restores the object exactly.
"""

import os
import uuid

import bpy
import numpy as np
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from corpus.generated import GENERATED
from realworn.core import compiler, images, layer_types as LT, layers, naming, setup, snapshot
from test_p1_setup import state_of, uv_cube

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
KINDS = ("DIRT", "DUST", "RUST", "WEAR", "SCRATCHES", "WATER", "PAINT", "DAMAGE", "CUSTOM")


class LayerStackMachine(RuleBasedStateMachine):
    @initialize(base=st.sampled_from(("principled_basic", "image_based", "procedural", "multi_principled")))
    def start(self, base):
        bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
        ob = uv_cube(bpy.context.scene, "Prop", material=GENERATED[base]())
        self.obj_name = ob.name
        self.initial = state_of(ob)
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

    # ----------------------------------------------------------------- rules
    @rule(kind=st.sampled_from(KINDS))
    def add(self, kind):
        if self.n < 8:
            layers.add_layer(self.mat, kind)

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
        ly = self.mat.realworn.layers[i % self.n]
        ly.visible = not ly.visible

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), ch=st.sampled_from(LT.CHANNEL_NAMES), v=st.floats(0.0, 1.0), on=st.booleans())
    def channel_value(self, i, ch, v, on):
        c = getattr(self.mat.realworn.layers[i % self.n], ch)
        if ch == "color":
            c.color = (v, 1.0 - v, v * 0.5)
        else:
            c.value = v
        c.enabled = on

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), ch=st.sampled_from(LT.CHANNEL_NAMES), k=st.integers(0, 4))
    def blend(self, i, ch, k):
        modes = LT.blends_for(ch)
        getattr(self.mat.realworn.layers[i % self.n], ch).blend = modes[k % len(modes)]

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), frac=st.floats(0.0, 1.0), seed=st.integers(0, 1000))
    def paint(self, i, frac, seed):
        ly = self.mat.realworn.layers[i % self.n]
        if ly.mask_image is None:
            ly.mask_image = images.create_mask(self.ob, ly, res=32)
        rng = np.random.default_rng(seed)
        px = (rng.random((32, 32)) < frac).astype(np.float32)
        ly.mask_image.pixels.foreach_set(np.repeat(px.ravel(), 4))
        ly.mask_image.update()

    @precondition(lambda self: self.n > 1)
    @rule(i=st.integers(0, 7), j=st.integers(0, 7), amount=st.floats(0.0, 1.0))
    def reference(self, i, j, amount):
        a, b = sorted(((i % self.n), (j % self.n)))
        if a == b:
            return
        top = self.mat.realworn.layers[b]
        with compiler.batch(self.mat):
            ing = top.ingredients.add()
            ing.kind = "REFERENCE"
            ing.ref_layer_id = self.mat.realworn.layers[a].id
            ing.amount = amount
        compiler.compile(self.mat)

    @precondition(lambda self: self.n > 0)
    @rule(i=st.integers(0, 7), amount=st.floats(0.0, 1.0))
    def up_ingredient(self, i, amount):
        ly = self.mat.realworn.layers[i % self.n]
        with compiler.batch(self.mat):
            ing = ly.ingredients.add()
            ing.kind = "UP"
            ing.amount = amount
        compiler.compile(self.mat)

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
        live = {ly.id for ly in mat.realworn.layers if ly.visible} | {"stack"}
        for nd in g.nodes:
            if nd.name.startswith(naming.NODE_PREFIX) and nd.name not in ("RW::in", "RW::out"):
                assert nd.name.split("::")[1] in live, nd.name
        below = set()
        for ly in mat.realworn.layers:
            for ing in ly.ingredients:
                if ing.kind == "REFERENCE" and ing.ref_layer_id:
                    assert ing.ref_layer_id in below
            below.add(ly.id)

    def teardown(self):
        if hasattr(self, "obj_name") and self.obj_name in bpy.data.objects:
            assert setup.remove_object(self.ob) == []
            assert state_of(self.ob) == self.initial


LayerStackMachine.TestCase.settings = settings(max_examples=60, stateful_step_count=14, deadline=None,
                                               suppress_health_check=list(HealthCheck))
test_layer_stack_state_machine = LayerStackMachine.TestCase

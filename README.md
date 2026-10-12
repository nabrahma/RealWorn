# RealWorn

One-click wear, grime, wetness, decals and damage for Blender 5.2 LTS, with one scene-level
weather controller that drives every weathered material at once. Internal tool (owner: Nabaskar).
Spec: [docs/PRD.md](docs/PRD.md). Milestone notes and screenshots: [docs/milestones](docs/milestones).

## Install

- Development: add a Local extension repository (Preferences > Get Extensions > Repositories)
  pointing at a folder that contains a link to `realworn/`, then enable RealWorn.
- Packaged: `python scripts/package.py` writes `dist/realworn-<version>.zip`; install it with
  Preferences > Get Extensions > Install from Disk.

Everything lives in the 3D Viewport sidebar tab **RealWorn**.

## Workflows

| Goal | Do this |
| --- | --- |
| Weather objects (W1) | Select meshes, pick a Preset (Auto, Painted Metal, Bare Metal, Concrete, Wood, Plastic), **Apply** |
| Set the mood (W2) | Scene Weather sliders: Age, Dirt, Dust, Wetness, Rain. Every weathered material updates live |
| Wet floors (W3) | Select the ground, **Mark as Ground**: puddles form there above Wetness 0.6, low areas first |
| Keep areas dry | Select roofs/awnings, **Mark as Occluder**: objects below stay dry and collect less dust |
| Hand-correct wear (W4) | **Paint Wear**: red adds wear, blue removes wear/dirt/dust, green keeps an area dry; Ctrl clears |
| Place a decal (W5) | Decals panel: pick an image and a mode (Full, Grime, Damage), **Place**, then move over a surface, scroll to scale, R to rotate, click |
| Leaks (W6) | Select buildings, **Auto Leaks** (seeded): grime streaks under sills, ledges and parapets |
| Break things (W7) | Damage panel: **Add Damage**, then tune Strength, Seed, sizes, Corners, Debris |
| Undo it all (W8) | **Remove** on objects, or Debug > **Remove All RealWorn Data**: materials restore exactly |
| Freeze (W9) | Bake panel: **Bake Selected** writes Base Color, Roughness, Metallic, Normal and mask images and uses them; **Restore Live Stack** goes back |
| Night look | Scene Weather > **Rainy Night**: wet weather, hazy world, two practical lights, bloom, vignette, grain |

Per object: Wear and Dirt multipliers, Seed (+ Randomise), Edge Source (Attribute, Bevel node
in Cycles, or both) and Cavity Source (Attribute, live Raycast, or both). Mask Settings exposes
the mask widths in metres, the angle threshold and pre-subdivision. Debug > Mask Preview shows
any mask (edge, cavity, contact, shelter, puddle, wetness, dust, grime, streak) as greyscale.

## How it works

- `RW_Masks` (Geometry Nodes) stores `rw_edge`, `rw_cavity`, `rw_contact`, `rw_shelter` on each mesh.
  Widths are world-space metres; coarse meshes are pre-subdivided automatically.
- The injector rewires each Principled BSDF through one shared `RW_Stack` group (edge wear, rust,
  decals, cavity dirt, contact/splash grime, dust, paint override, wetness) and snapshots the
  original tree, so Remove restores it exactly. Materials without a Principled get a Mix Shader overlay.
- Scene sliders are scene custom properties read by Attribute (View Layer) nodes; per-object values
  are object custom properties. The only driver in a file is the rain clock (`frame / 24`).
- Weathered files open and render identically without the add-on installed.

## Tips and limits

- Mask detail follows the mesh: large n-gons smear masks (the panel warns); a bevel much wider than
  Edge Width only wears in its middle, so raise Edge Width for chunky bevels.
- The live stack is a lot of shader for Cycles (+150-190% render time over bare Principled materials
  in the benchmark); **Bake** brings that down to about +20%. EEVEE stays interactive (16-27 fps on
  50 weathered objects, see docs/perf.md).
- Damage needs closed manifold meshes; bevelled corners get edge chips rather than corner breaks.
- At most 16 decals per material; bake to go further.

## Development

```
python -m pytest tests/pure                                                    # pure Python
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py      # all Blender tests
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py -- --update-snapshots
python tests/corpus/fetch.py                                                   # CC0 Poly Haven corpus
```

Node groups are built by Python in `realworn/builders/` (the asset .blend is generated).
Measurements: [docs/perf.md](docs/perf.md). M0 spike results: [docs/spikes.md](docs/spikes.md).

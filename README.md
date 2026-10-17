# RealWorn

[![tests](https://github.com/nabrahma/RealWorn/actions/workflows/tests.yml/badge.svg)](https://github.com/nabrahma/RealWorn/actions/workflows/tests.yml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Blender 5.2+](https://img.shields.io/badge/Blender-5.2%2B-orange.svg)](https://www.blender.org/download/)
[![Latest release](https://img.shields.io/github/v/release/nabrahma/RealWorn)](https://github.com/nabrahma/RealWorn/releases/latest)

Paintable texture layers for realistic buildings and surfaces in Blender, with no node editing.

Click **Setup**, load your texture sets into a few simple layers, and paint. RealWorn builds the
node tree for you, the same way you would by hand:

- box-mapped PBR textures;
- colour variation through grunges and Color Ramps;
- painted masks broken up by grunge;
- damage that reveals the material underneath;
- stencil-painted decals;
- Bevel edge wear and ambient-occlusion dirt.

Remove restores your original material exactly.

- **Requires** Blender 5.2 LTS or later.
- **Licence:** GPL-3.0-or-later.

## Features

- **One-click Setup.**
  - A box-mapped base material and a paint UV map in under 2 seconds.
  - Works on objects with or without a material.
  - Your own UV maps are never touched.
- **Load Texture.** Any Poly Haven or ambientCG folder loads with one pick:
  - colour, roughness or gloss, metallic, height, and packed ARM/ORM maps;
  - real-world size from the folder name.
- **Seven layer kinds.** Every layer is a material plus a mask: Variation, Paint, Reveal, Decals, Edge
  Wear, Dirt and Puddle.
- **Puddles.** Standing water in one click or painted, filling grout and dips first, with real depth:
  darker wet ground, a clear coat, deep water as a flat mirror.
- **One mask recipe for everything.** A source minus a grunge, then a ramp. You control it with
  three sliders: Breakup, Sharpness and Threshold.
- **Painting with Blender's own brushes.** Four ready-made brushes:
  - soft paint;
  - a damage brush with texture-mask alphas;
  - a stencil brush for decals;
  - a puddle brush, round or with a grunge outline.
- **Bundled libraries,** all generated from code and CC0:
  - 22 grunges;
  - 6 damage alphas;
  - 9 decals in categories.
- **One material, one shader.** All layers mix into a single Principled BSDF with one shared height
  for the bump. Renders cost less than an equivalent hand-built Mix Shader tree.
- **Bake and export.**
  - Bake Material freezes the whole stack into textures.
  - Export writes Unity URP/HDRP, Unreal (ORM, DirectX normal) or glTF sets.
- **Safe.**
  - Remove restores your original node tree, material slots and UV maps exactly.
  - Painted masks are saved with the file, and a save never loses paint.

## Install

1. Download `realworn-<version>.zip` from the [latest release](https://github.com/nabrahma/RealWorn/releases/latest),
   or build it yourself: `python scripts/package.py` writes `dist/realworn-<version>.zip`.
2. In Blender: **Edit > Preferences > Get Extensions > Install from Disk**, and pick the zip.
3. In the add-on preferences, set a **Texture Library** folder, such as your Poly Haven or
   ambientCG downloads, used as they are.
4. Optionally, add your own folders of damage alphas and decals. Subfolders become categories.

RealWorn lives in the 3D Viewport sidebar, tab **RealWorn**, and in the Image Editor sidebar.

## Quick start

1. Select an object and click **Setup**.
2. On the **Base** row, click **Load Texture** (or open the library) and set **Scale** in metres.
3. Add the layers you need. Each one is optional; a Base with a single Reveal or Decals layer is
   fine.

   | Add | What it does | How |
   | --- | --- | --- |
   | **Variation** | Colour variation over the base: Washed Out, Dark Patches, Dirt Patches, or a Second Material | Pick a grunge with Breakup; stack several, each subtle |
   | **Paint** | A painted area, such as old paint over plaster | Click **Paint** and brush it on; raise **Breakup Amount** to chip it |
   | **Reveal** | Damage that shows another material underneath | Load what's underneath, pick a damage alpha, Paint; **Depth** sets how deep |
   | **Decals** | Drips, dirt, graffiti, stickers on one transparent image | Pick a decal and paint through the stencil. Right-drag moves it, Ctrl right-drag rotates, Shift right-drag scales |
   | **Edge Wear** | Worn edges from the Bevel node | **Width** (mm) and Breakup; paint touch-ups if needed |
   | **Dirt** | Dirt in corners and crevices from ambient occlusion | **Distance** (cm), Breakup, Sharpness; paint extra dirt by hand |
   | **Puddle** | Standing water in the low spots of the ground | **Water Level**; paint to add water or dry spots out (see [Puddles](#puddles)) |

4. Finish with **Bake Material** for heavy renders, or **Export Textures** for a game engine.

New layers drop into a sensible place in the stack (variations low, dirt and puddles on top); the
arrows move them anywhere.

## The layer model

**Content**, one of:

- **Texture:** a loaded set, box mapped.
- **Tint Below:** a recoloured copy of the Base.
- **Color:** a flat colour and roughness.

Hue, Saturation and Value work on any content.

**Mask**, from the layer's kind:

| Kind | Mask source | Brush |
| --- | --- | --- |
| Variation | a grunge only | not painted |
| Paint | your painting | RW Soft |
| Edge Wear | Bevel edge detection, plus optional painting | RW Damage |
| Reveal | your painting; the content sits underneath, lowered by Depth | RW Damage |
| Decals | the painted decal image's own alpha | RW Stencil |
| Dirt | ambient occlusion, plus optional painting | RW Soft |
| Puddle | where a water level is above the ground (its own model, below), plus optional painting | RW Puddle |

**The mask recipe** (every kind but Puddle): `M = ramp(source − amount × ramp(grunge)) × opacity`.

- **Breakup** is the subtracted grunge.
- **Sharpness** sets the ramp's width.
- **Threshold** moves its edge.

Everything else sits under each layer's **Advanced** fold:

- Breakup Contrast, Scale and Offset;
- texture Roughness offset and Bump strength;
- edge darkening in Reveal holes;
- Bevel samples;
- the decal blend (Normal or Darken);
- mask resolution, Upgrade Mask, Fill and Clear.

If you open the Shader Editor, you'll find ordinary Blender nodes in one group per material,
`RW_Stack::<material>`, framed and labelled per layer.

## Brushes

| Brush | Used by | Settings |
| --- | --- | --- |
| RW Soft | Paint, Dirt | round, smooth falloff |
| RW Damage | Reveal, Edge Wear | damage alpha as Texture Mask, View Plane, Rake, Constant falloff |
| RW Stencil | Decals | the decal as a Stencil texture, Image Aspect, Override Overlay |
| RW Puddle | Puddle | round, smooth falloff, or a grunge as its mask for ragged outlines |

- **Erasing:** hold **Ctrl** to erase. On masks that paints black; on Decals it erases alpha; on a
  Puddle it raises the ground (dries a spot out).
- **Size and strength:** **F** sets brush size, **Shift F** strength.
- **Overlay:** while painting, an overlay names the layer, the brush and its shortcuts.
- **Pie menu:** the **RealWorn Paint** pie menu has no key by default. Assign one under
  Preferences > Keymap.

## Puddles

A **Puddle** layer puts standing water on the ground: in one click, by painting, or both. Water
collects where a water level is above the ground, so it fills grout, cracks and dips first and
follows the surface's grain, even where you paint it.

1. Select a road, floor or yard that is set up, with a texture loaded on the Base.
2. **Add > Puddle > Wet** (or Damp, Puddles, Soaked). The layer goes on top of the stack.
3. Drag **Water Level**: down for water only in the cracks, up for large pools.
4. For water exactly where you want it, set **Source** to Auto and Paint (the default) and click
   **Paint**:
   - white lowers the ground, so water collects there;
   - **Ctrl** raises it, to dry a spot out.

   Painting never paints water directly. It moves the ground, so painted puddles still fill
   grout before stone faces. **Source: Paint** gives water only where you paint.

**What changes with depth:**

| Zone | Looks like |
| --- | --- |
| Damp halo | ground slightly darker and less rough |
| Wet edge | darker by porosity (concrete a lot, metal hardly), with a thin glossy film |
| Shallow water | the ground seen through the water, darkening with depth; a clear coat at IOR 1.33 |
| Deep water | a flat mirror; the ground fades into the Water Tint |

**Main controls:** Preset, Source, Water Level, Depth Look (how fast the ground fades), Halo,
Water Tint (Clear, Muddy, Oily or Custom) and **True Depth**. True Depth gives real displacement
with the water held flat between raised stones, for low close-ups in Cycles.

**Under Advanced:**

- the ground: Height Source (the stack, the Base only, or flat), a **Surface** preset (Asphalt,
  Cobblestone, Tiles, Concrete, Dirt Road) and Height Scale;
- Paint Depth, and Broad Dips for road-scale hollows (always on when the Base has no height map);
- the zone widths and Darkening;
- Wind Ripple, Tide Mark, Debris Settle;
- the Flat Faces threshold: kerbs and walls never hold water.

**Seeing it:**

- **Mask View** shows the zones in colour: dry grey, halo, wet edge, shallow blue, deep navy.
- Puddles need something to reflect: lights, signs or a bright sky.
- In EEVEE, turn on **Ray Tracing** (Render Properties) for sharp reflections. The layer row
  reminds you.
- **Bake Material** bakes the coat too, so baked puddles stay wet.

## Edge Wear and Dirt in EEVEE

Bevel and Ambient Occlusion are exact in Cycles and approximate in EEVEE. **Bake Edges and AO**
bakes their sources to images:

- Breakup and Sharpness stay live.
- The result looks the same in both engines and renders faster.
- Re-bake after changing the mesh.

## Finishing

- **Bake Material:** freezes the stack into textures on the `RW_Paint` UV. **Restore Live Stack**
  goes back to editing.
- **Export Textures:** writes Unity URP/HDRP, Unreal or glTF texture sets.
- **True Depth** (Reveal and Puddle): real displacement with adaptive subdivision, off by default.
- **Remove:** restores the original material, UV maps and slots, and offers to export your painted
  masks first.

## Older files

- **RealWorn 2.x:** materials show **Convert to v3**.
  - Paint, Dirt, Rust, Dust and Custom layers become Paint layers.
  - Wear, Scratches and Damage become Reveal layers.
  - Painted masks are kept.
  - Water and projector decals are listed for you to redo.
- **RealWorn 0.7:** **Remove v0.7 Weathering** restores those materials exactly.

## Performance

Measured on an AMD Ryzen 7 6800HS, RTX 3060 Laptop GPU and Windows 11, with Blender 5.2.1. The
scene is a 3 m wall with a typical stack: three Variations, Paint, Reveal and Decals.

| Measure | Result |
| --- | --- |
| Setup, one 10k-vertex object | 1.3 s |
| Cycles render cost over the base material alone, GPU | +47% to +48% (the same look as a hand-built Mix Shader tree: +108%) |
| Same, after Bake Material | +3% to +4% |
| Mask memory, 1 m object | 144 MB |
| Bake Edges and AO, two 4K masks, GPU | 48 s |

Puddles, on a night street (asphalt, cobblestones, tiles; 960 x 540), against the same street
without them:

| Measure | Result |
| --- | --- |
| Cycles render cost, auto puddles, GPU, fixed 1024 samples | +11% |
| Same, Cycles defaults (adaptive sampling) | +21%: sharp reflections take more samples to clear |
| With painting and broad dips, fixed / defaults | +25% / +118% (broad dips add much more water) |
| True Depth, low close-up | +61% over shading only |
| Puddle paint mask, 1 m object | 64 MB (2048 px float) |

Bake Material before heavy final renders.

## Development

```sh
# test dependencies (pytest, hypothesis) for Blender's Python, into tests/_vendor
"$BLENDER_BIN" --background --factory-startup --python scripts/setup_test_env.py

python -m pytest tests/pure                                                  # pure Python tests
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py    # all Blender tests
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py -- -k reveal

python tests/corpus/fetch.py               # CC0 Poly Haven materials for the round-trip tests
python tests/corpus/fetch.py --reference   # the texture sets for the reference wall test
python scripts/package.py                  # dist/realworn-<version>.zip
```

- **Finding Blender:** set `BLENDER_BIN` in the environment or in a `.env` file at the repository
  root.
- **Local development:** add a Local extension repository in Blender's preferences, pointing at a
  folder that contains a link to `realworn/`.
- **Rebuilding assets:** the bundled grunges, damage alphas and decals are generated by code in
  `realworn/builders/`. Rebuild them with `scripts/make_grunges.py`, `scripts/make_alphas.py` and
  `scripts/make_decals.py`.
- **The reference wall test:**
  - `tests/fixtures/reference_wall.py` builds a weathered wall by hand with plain Blender nodes, and
    `tests/test_reference_wall.py` rebuilds it with RealWorn's operators. Both render in Cycles and
    must match: mean difference under 0.02, currently 0.0002.
  - It defines what "correct" means. Change RealWorn, not the reference.
  - Render outputs and performance logs go to `tests/_out/`.

### Layout

| Path | What |
| --- | --- |
| `realworn/core/` | Compiler, injector and snapshot (exact Remove), setup, images, bake, migration. No `bpy.context` |
| `realworn/operators/`, `realworn/ui/` | Operators, the sidebar panel, the paint overlay and pie menu |
| `realworn/builders/` | Generators for the bundled grunges, alphas and decals |
| `tests/` | Blender tests (run inside Blender), `tests/pure/` (plain Python), fixtures and the test corpus fetcher |
| `scripts/` | Packaging, asset generation, test environment setup |

### Design rules

- **The layer list is the source of truth.** `material.realworn.layers` is authoritative.
  - Only `core/compiler.py` creates nodes inside `RW_Stack::<material>`.
  - Only `core/injector.py` touches a material's top-level tree.
- **Remove must stay exact.** Setup followed by Remove restores the original tree exactly; the
  round-trip tests check this.
- **Painted masks are the user's work.** Never delete, resize destructively or overwrite them
  without an explicit user action.
- **Blender's own texture paint and brush system.** RealWorn creates its own brush assets and never
  edits the user's.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and the
design rules, and [CHANGELOG.md](CHANGELOG.md) for what changed in each release. Everyone taking part
follows the [Code of Conduct](CODE_OF_CONDUCT.md); report security problems as described in
[SECURITY.md](SECURITY.md).

## Licence

RealWorn is free software, released under the GNU General Public License v3.0 or later. See
[LICENSE](LICENSE). The bundled grunge, alpha and decal images are CC0. Third-party projects
studied during development are listed in [THIRD_PARTY.md](THIRD_PARTY.md).

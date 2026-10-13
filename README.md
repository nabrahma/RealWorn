# RealWorn 3

RealWorn gives you a complete building texturing workflow without building a single node.

- Click **Setup** once, load the textures you want into a few simple layers, and paint.
- Everything the tutorial wires by hand, RealWorn wires the same way, so the results look the same:
  - box mapping, the second material, grunge and Color Ramp variation;
  - painted masks with a subtracted grunge, damage that shows the plaster underneath;
  - the stencil-painted decal image, Bevel edge wear and AO dirt.

**Proven, not claimed:** `tests/test_v3_reference.py` builds the tutorial's wall by hand with plain
Blender nodes, builds it again with RealWorn's buttons and sliders, and renders both. On the full
wall the mean difference is 0.0002, against a limit of 0.02.

Blender 5.2 LTS. Internal tool (owner: Nabaskar). Spec: `docs/PRD_v3.md`. v2.1 (the many-feature
painter) is at git tag `v2.1-q4`.

## Install

- **Packaged:** `python scripts/package.py` writes `dist/realworn-3.0.0.zip`. Install it with
  Preferences > Get Extensions > Install from Disk.
- **Development:** a Local extension repository pointing at a folder that links `realworn/`.
- **Preferences:** set a **Texture Library** folder (your Poly Haven / ambientCG downloads, used as
  they are). Optionally add folders of damage alphas and decals; subfolders become categories.

Everything is in the 3D Viewport sidebar, tab **RealWorn** (also in the Image Editor sidebar).

## The tutorial, chapter by chapter, in RealWorn

| # | The tutorial does by hand | In RealWorn |
| --- | --- | --- |
| 1 | Find reference, gather textures | The same: put Poly Haven or ambientCG sets in your Texture Library folder |
| 2 | Material, image textures, Mapping, Texture Coordinate, Value, Box projection Blend 0.3, Displacement node, Surface set to Bump | **Setup**, then on the **Base** row **Load Texture** (or the library button). Set **Scale** in metres |
| 3 | A second material, Hue/Saturation, Mix Shader and a Mix color for displacement | **Add > Variation > Second Material**, Load Texture, Hue / Sat / Val |
| 4 | Color variation: duplicate the material, desaturate, grunge plus Color Ramp into the mix | **Add > Variation > Washed Out / Dark Patches / Dirt Patches**. Breakup picks the grunge; **Sharpness** and **Threshold** are the Color Ramp. Stack several, each subtle |
| 5 | Cube Projection, Pack Islands, a new image as a mask, texture paint | Done by Setup (the `RW_Paint` UV) and **Add > Paint**: click **Paint** on the row |
| 6 | Mix Subtract with a grunge and a Color Ramp to chip the paint | Raise the Paint layer's **Breakup Amount** |
| 7 | Damage: an under-material, a damage mask, a custom brush (Texture Mask, View Plane, Rake, Constant) | **Add > Reveal > Damage**: Load Texture for what is underneath, pick a **Damage Alpha**, Paint. **Depth** sets how deep the holes are |
| 8 | Decals: a 4K image with alpha 0, colour into a Principled, alpha into a Mix Shader, Stencil texture with Image Aspect, Override Overlay | **Add > Decals**: pick a decal in the library, Paint. Right-drag moves the stencil, Ctrl right-drag rotates, Shift right-drag scales |
| 9 | Edge wear: Bevel, Geometry Normal, Dot Product, Color Ramp, grunge through Map Range into the Bevel radius | **Add > Edge Wear**: Width (mm) and Breakup; Load Texture for what shows on the edges, or keep Tint Below |
| 10 | Dirt: Ambient Occlusion, Color Ramp, Less Than a grunge through Map Range | **Add > Dirt**: Distance (cm), Breakup, Sharpness, a dirt colour or texture |

If you open the Shader Editor you find the same kind of tree the tutorial builds: Image Textures
in Box projection, Hue/Saturation, Mix (Subtract), Color Ramps, Bevel and AO. It sits in one group
per material, `RW_Stack::<material>`, framed and labelled per layer.

## The model: every layer is a material plus a mask

**Content**, one of:

- **Texture:** a loaded set, box mapped.
- **Tint Below:** a recoloured copy of the Base, the tutorial's duplicated-material trick. The
  Base's texture shows; the layers in between do not.
- **Color:** a flat colour and roughness, the tutorial's plain BSDF.

Hue, Saturation and Value work on any content.

**Mask**, from the layer's kind:

| Kind | Mask comes from | Usual place |
| --- | --- | --- |
| Variation | a grunge only (no painting) | just above the Base |
| Paint | your painting | over the variations |
| Edge Wear | Bevel edge detection, plus optional painting | over the paint |
| Reveal | your painting with the Damage brush; the content sits under, with Depth | over the paint |
| Decals | the painted decal image's own alpha | over the damage |
| Dirt | ambient occlusion, plus optional painting | on top |

New layers drop into their usual place; move them anywhere with the arrows.

**One mask recipe for everything:** the source, minus a grunge through its own Color Ramp (the
tutorial's Mix Subtract), then a Color Ramp.

- **Breakup** is the subtracted grunge: pick it, set Amount and (under Advanced) Scale.
- **Sharpness** is the ramp's width, soft to hard; **Threshold** moves the edge.

Everything else sits under **Advanced**:

- Breakup Contrast, Scale and Offset;
- Roughness offset and Bump strength of a texture;
- Edge Darkening inside Reveal holes;
- Bevel Samples;
- the Decals blend (**Normal** or **Darken**);
- mask resolution, Upgrade Mask, Fill and Clear.

## Brushes and painting

RealWorn uses Blender's own texture paint, with three brushes of its own (your brushes are never
edited):

| Brush | Used by | Settings |
| --- | --- | --- |
| RW Soft | Paint, Dirt touch-ups | round, smooth falloff |
| RW Damage | Reveal, Edge Wear touch-ups | Texture Mask from the damage alpha, View Plane, Rake, Constant |
| RW Stencil | Decals | Texture from the decal, Stencil mapping, Image Aspect, Override Overlay |

**Erasing:**

- Hold **Ctrl** to erase: masks paint black; on Decals, Ctrl erases alpha.
- **F** sets the brush size and **Shift F** its strength.
- An overlay names the layer, the brush and its shortcuts.
- The **RealWorn Paint** pie menu has no key until you assign one: Preferences > Keymap, search
  "RealWorn Paint".

**Libraries (bundled, generated):**

- 22 grunges;
- 6 damage alphas: chips, small chips, cracks, scratches, gouges, impact;
- 9 decals in Drips, Dirt, Graffiti, Stickers, Mold and Cracks.

Add your own folders in Preferences.

## Edge Wear and Dirt in EEVEE: Bake Edges and AO

Bevel and AO are the tutorial's nodes and work best in Cycles; the layer row says "Live - Bake for
EEVEE" in Material Preview. **Bake Edges and AO** bakes their masks to images:

- Breakup and Sharpness stay live.
- Baked masks look the same in EEVEE and render faster.
- Re-bake after changing the mesh.

## Finishing

- **Bake Material:** freezes the whole stack into textures on `RW_Paint`. **Restore Live Stack**
  goes back to editing.
- **Export Textures:** writes Unity URP/HDRP, Unreal (ORM, DirectX normal) or glTF sets.
- **Remove:** restores your original material, UV maps and slots exactly, and offers to export
  your painted masks first.
- **Reveal True depth:** real displacement with adaptive subdivision. Off by default, as in the
  tutorial.

## Old files

- **RealWorn v2.x:** the panel offers **Convert to v3**.
  - Paint, Dirt, Rust, Dust and Custom layers become Paint layers.
  - Wear, Scratches and Damage become Reveal layers.
  - Each keeps its painted mask.
  - Water and projector decals are listed for you to redo.
- **v0.7:** **Remove v0.7 Weathering** restores those materials exactly.

## Measured (docs/perf.md; Windows 11, Ryzen 7 6800HS, RTX 3060 Laptop, Blender 5.2.1)

| Measure | Result | Budget |
| --- | --- | --- |
| The full reference wall vs the tutorial's hand-built tree | mean difference 0.0002, worst 32 px block 0.0012 | 0.02 / 0.06 |
| Setup, one 10k-vertex object (Cube Projection + Pack Islands) | 1.26 s | under 2 s |
| Cycles render cost of the tutorial's stack (3 Variations, Paint, Reveal, Decals) vs the Base alone, GPU | **+47% to +48%** (the tutorial's own node tree: +108%; v2.1: about +90%) | +40% |
| Same + Edge Wear and Dirt baked / live | +60% to +61% / +130% | +40% / none |
| After Bake Material | +4% | +15% |
| Mask memory of that stack, 1 m object | 144 MB | 180 MB |
| Add a layer: EEVEE ready (warm) | about 0.12 s | 0.5 s |

The +47% to +48% is mostly what the look costs: the tutorial's own tree costs more than twice as much
for the same image. Bake Material before heavy final renders.

## Development

```sh
python -m pytest tests/pure                                                    # pure Python
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py      # all Blender tests
python tests/corpus/fetch.py --reference                                         # the reference test's texture sets
python scripts/package.py                                                      # dist/realworn-<ver>.zip
```

Generated assets: `scripts/make_grunges.py`, `scripts/make_alphas.py`, `scripts/make_decals.py`.
Milestone notes and comparison images: `docs/milestones/R0` to `R5`. What changed from v2.1:
`docs/v3_map.md`.

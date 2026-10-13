# RealWorn 2.1 (Paint, Sharp Detail)

Paint wear, dirt, rust, water, decals and damage onto any material as layers, Substance-Painter
style, inside Blender 5.2 LTS. Each layer is a look (a PBR content) plus a paintable mask, with
optional edge, cavity and grunge ingredients. Internal tool (owner: Nabaskar).
Spec: [PRD v2](PRD%20v2%20RealWorn%20Paint%20(internal).md). Milestone notes and screenshots:
[docs/milestones](docs/milestones) (P0-P8). v0.7 (procedural one-click weathering) is tagged `v0.7`.

## Install

- Packaged: `python scripts/package.py` writes `dist/realworn-2.0.0.zip`; install it with
  Preferences > Get Extensions > Install from Disk.
- Development: a Local extension repository pointing at a folder that links `realworn/`.

Everything lives in the 3D Viewport sidebar tab **RealWorn** (also in the Image Editor sidebar).

## 5-minute quick start (a worn painted crate)

1. **Set Up** (0:00). Select a mesh with a material, sidebar RealWorn > **Setup**. RealWorn adds a
   `RW_Paint` UV map (Smart UV Project, or a copy of an existing non-overlapping UV) and an empty
   layer stack. Your render UV is never touched. No material? It gets a grey Principled one.
2. **Wear** (0:30). Layer list **+** > **Wear**. Wear starts edge-locked: click **Paint**, and
   careless strokes along the edges only chip the edges. Brush tab: pick a grunge (e.g.
   `chips_large`) and Stamp mode for broken-up chips. Paint Mode **Erase** removes, **Reset** clears.
3. **Dirt** (1:30). **+** > **Dirt**, Mask tab > **Add Ingredient** > Cavity. Raise the ingredient
   amount until crevices fill, then paint extra dirt where hands and feet would leave it.
4. **Rust** (2:30). **+** > **Rust**. Brush tab > Grunge > **Fill** with `rust_spots` (amount 0.4).
   Mask tab > **Add Ingredient** > Reference > Wear makes rust grow from the exposed metal.
5. **Decal** (3:15). Decals panel: pick `poster_01`, **Place Decal**, click on a face. It is a layer:
   paint its mask with Erase to tear it, and put a Dirt layer above it to dirty it.
6. **Water or damage** (4:00, optional). **+** > **Water** and paint a puddle; or **+** > **Damage**,
   paint where it is dented (Shader), raised (Displacement) or broken (Geometry, closed meshes).
7. **Bake** (4:30). Bake panel > **Bake Material** freezes the look into 7 maps for fast Cycles
   renders; **Restore Live Stack** goes back to editing. **Export Textures** writes Unity URP/HDRP,
   Unreal (ORM, DirectX normal) or glTF sets.

**Mask View** (Mask tab, or the pie menu) shows the selected layer's final mask in greyscale.
While painting, an overlay names the layer, mode and grunge; the **RealWorn Paint** pie menu
(Paint, Erase, Reset, Next/Previous Layer, Mask View, Exit) has no key by default: assign one in
Preferences > Keymap, search "RealWorn Paint".

## Layer types

| Type | Look | Notes |
| --- | --- | --- |
| Paint | colour you paint (content image) | the mask is where you painted |
| Wear | bare metal | edge-locked by default |
| Dirt, Dust, Grime | dark / pale / tinted films | Dust adds an Up ingredient |
| Rust | dark orange-brown, rough, tinted grunge | height optional |
| Water | wet darkening + coat; puddles flatten bump | metallic is left unchanged (deliberate) |
| Damage | Shader dents, Displacement, or Geometry breaks | Apply Damage makes geometry real |
| Decal | projected image (Full, Grime, Damage) | projector Empty; facing fade |
| Custom / PBR set | any colour, roughness, metallic, normal, height | Load PBR Set fills it from a folder |

Every value slider writes straight into the shader (no recompile); adding, removing, reordering,
hiding or switching an ingredient recompiles only that material's `RW_Stack::<material>` group,
which holds nodes only for what the visible layers use.

## Getting Substance-level sharpness (v2.1)

The painted mask says roughly **where** an effect goes; a full-resolution detail texture
decides the exact, crisp **edge**. That is how Substance gets its look (paint + grunge + levels).

- **Edge Detail** (Mask tab) is on by default for new effect layers. Pick its **Source**:
  - **Layer Grunge**: a black-and-white grunge, box-projected; chips, rust breakup, speckled dust.
  - **Base Height**: the base material's own height map. Dirt and Water use Height Compare on it,
    so they sink into grooves, mortar and pits first; Damage carves brick faces before mortar.
  - **Base AO**: the base's AO map, found next to its textures (or **Pick AO Image**).
  - **Content Height**: the layer's own PBR set height, so chipped paint follows the paint texture.
  - **Second Grunge**: mix a smaller breakup into any source (two scales of breakup).
- **Edge Width** is the main sharpness control (small = hard); **Threshold** moves the edge in or
  out. **Protect Interior** keeps the core of a stroke solid so only its edge breaks up.
- **Before / After** (Mask tab) shows the soft stroke on the left half of the view and the
  Edge Detail result on the right.
- Paint with soft brushes for Dirt, Dust and Water: the crisp edge comes from the detail, not the
  brush. Wear, Scratches and Damage default to the **RW Hard** brush.
- **Textured Look** (Content tab) gives each effect real variation: two browns and grit for Dirt,
  a dark core and orange rim for Rust, brushed streaks for Wear. Or load a PBR set (ambientCG and
  Poly Haven downloads work; set a Content Library folder in Preferences for thumbnails).
- Masks default to 2048 px per metre. **Hero** (Sharpness panel) gives 4096 px per metre for
  extreme close-ups; **Upgrade Masks** resamples existing paint without losing it.
- The **Sharpness** panel warns about settings that quietly blur textures (Limit Size, Simplify,
  anisotropic filtering) and has a **Sharpness Report**: the edge width of each layer in pixels
  and what limits it.
- Files from v2.0 look exactly as before until you click **Apply v2.1 Defaults**.

Measured on a 30 cm crate, 30 cm away, 1920 px wide: a soft painted Dirt stroke's edge went from
58 px (v2.0) to 1.7 px; Rust from 137 px to 2.3 px. Halving the mask resolution no longer changes
the edge (1 % spread across 512, 1024 and 2048 px masks). Details: docs/milestones/Q0 ... Q4.

## Saving, removing, old files

- Masks are 8-bit RGBA images on `RW_Paint`, sized by texel density. They are packed into the .blend
  by default, or written next to it as PNG (Preferences). Files render without the add-on.
- **Remove** restores the original material tree exactly (offers to export masks first).
- v0.7 files show a banner: **Remove v0.7 Weathering** restores those materials exactly; then Set Up.

## Measured limits (docs/perf.md, machine: Windows 11, RTX 3060 Laptop)

- Cycles render overhead of 4 typical live layers on a light 6-cube test scene, GPU (OptiX):
  - v2.0 stack (Edge Detail and looks off): about **+34-42%** with Cycles defaults, **+48%** per
    fixed sample; after Bake +15-22%.
  - v2.1 defaults (Edge Detail and textured looks on): **+92%** with Cycles defaults (budget +40%),
    **+115%** per fixed sample, **+32%** after Bake (budget +15%). Known limitation: crisp relief
    means the shared bump re-evaluates each relief layer's Edge Detail three times, and the looks
    add noise per shading point. Levers: turn off layer Height or Micro Normal where relief is
    not needed, Textured Look off on layers you do not see up close, Flatten finished layers, and
    Bake before heavy final renders.
- Material Preview, 10-layer crate with v2.1 defaults: about 146-154 fps. Changing a value never
  recompiles; a structural change recompiles in about 0.5 s, then EEVEE needs about 0.7 s if it
  has compiled that variant before and about 6 s when it has not (known limitation, budget 1 s).
- Masks: 8 layers at 2048 px take 128 MB as 8-bit; relief layers (Damage, Height on) are float,
  and Blender keeps float images at 32 bits in RAM, so 8 layers with 2 float take 224 MB.
- Mask detail on generated masks (Edge, Cavity, Contact) follows mesh density.
- Geometry damage needs closed manifold meshes; Bake excludes or errors on it (choose in Bake).

## Development

```sh
python -m pytest tests/pure                                                    # pure Python
"$BLENDER_BIN" --background --factory-startup --python tests/run_tests.py      # all Blender tests
python scripts/package.py                                                      # dist/realworn-<ver>.zip
```

Node groups are built by Python in `realworn/builders/` (the asset .blend is generated).
Measurements: [docs/perf.md](docs/perf.md). Spike results: [docs/spikes.md](docs/spikes.md).

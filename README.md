# RealWorn 2 (Paint)

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

## Saving, removing, old files

- Masks are 8-bit RGBA images on `RW_Paint`, sized by texel density. They are packed into the .blend
  by default, or written next to it as PNG (Preferences). Files render without the add-on.
- **Remove** restores the original material tree exactly (offers to export masks first).
- v0.7 files show a banner: **Remove v0.7 Weathering** restores those materials exactly; then Set Up.

## Measured limits (docs/perf.md, machine: Windows 11, RTX 3060 Laptop)

- Cycles render overhead of 4 typical live layers on a light 6-cube test scene, GPU (OptiX):
  **+34%** with Cycles defaults (budget +40%), **+15-19%** after Bake (budget +15%: on the line, varies run to run).
  Per fixed sample the shading itself costs more: **+48%** live and **+32%** baked (known
  limitation). On CPU the live overhead is about +80%. Bump re-evaluates every height-carrying
  mask, so disable layer Height where you do not need relief, and Bake before heavy finals.
- Material Preview with 10 layers: well above 30 fps; add-layer recompile about 0.25-0.3 s;
  EEVEE shaders ready about 0.3-0.5 s later.
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

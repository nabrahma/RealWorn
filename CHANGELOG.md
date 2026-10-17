# Changelog

All notable changes to RealWorn are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.4.0] - 2026-10-17

### Added
- **Wet Film** on the Puddle layer: rain-soaked ground, every flat face glossy under a thin film of
  water that follows the stone's relief, so reflections break into streaks.
  - Relief Through Film, Film Breakup (Noise or a library grunge) with its own Scale, Dry Patches
    and Film Gloss.
  - Presets: Rain-soaked, Just Rained and Drying. Damp, Wet, Puddles and Soaked keep the film off.
  - Standing water keeps its flat-mirror look on top of the film; kerbs and walls stay dry.
  - At Wet Film 0 the material is exactly as before.
  - Bake Material keeps the film.
- A storefront framing in the reference road scene (a lit window and a red light), and the wet
  film in the plain-node puddle reference.

### Fixed
- **Bake Material** baked normal maps turned by 90° on faces where Cube Projection rotated the
  paint UV map against the object's own UV map, so baked relief was lit from the wrong side. The
  bake took its tangents from the selected UV map; it now uses the paint UV map.
- With a Puddle layer, Bake Material bakes the coat's normal on its own instead of averaging it
  into the ground's.

## [3.3.0] - 2026-10-17

### Added
- **Puddle layer**, the seventh kind: standing water where a water level is above the ground.
  - One click (Damp, Wet, Puddles, Soaked) fills the low spots of the base height map first: grout,
    cracks, then dips.
  - Painting lowers or raises the ground, so painted puddles still follow its grain.
  - Depth per point: porosity darkening and a damp halo, a clear coat at IOR 1.33, the ground
    fading with depth, deep water as a flat mirror.
  - Water Tint (Clear, Muddy, Oily, Custom); Surface presets; Broad Dips; Wind Ripple, Tide Mark,
    Debris Settle.
  - True Depth with the water held flat at the level.
  - Mask View shows the zones in colour.
  - Bake Material bakes the coat too.
- The Coat channels go through the layer stack only while a material has a Puddle layer.
- A reference road scene and a plain-node puddle reference for the tests (`python tests/corpus/fetch.py --road`).
- Load Texture lists the texture sets of the RealIndex add-on when it is enabled, after the
  library folder's sets.
- Contributing guide, code of conduct, security policy, issue and pull request templates.
- Continuous integration for the pure-Python tests.

### Changed
- RealWorn works alongside other add-ons' shader layers, such as RealDust's dust. It never edits
  nodes another add-on owns, and keeps those layers on top through Setup, Bake Material and
  Restore Live Stack. While they are present, Remove takes out only RealWorn's nodes.

## [3.0.0] - 2026-10-14

A rebuild around a simpler model: every layer is a material plus a mask.

### Added
- **Layer kinds.** Six kinds: Variation, Paint, Reveal, Decals, Edge Wear and Dirt.
- **Mask recipe.** One recipe for every kind: a source minus a ramped grunge, then a ramp, set with
  Breakup, Sharpness and Threshold.
- **Load Texture.** Detects Poly Haven and ambientCG layouts, including packed ARM/ORM maps,
  gloss, DirectX normals and the size from the folder name. Comes with a texture library and Recent
  list.
- **Box mapping and bump.** Box mapping for every loaded map, and one shared height for the bump,
  with optional true displacement on Reveal layers.
- **Variation presets:** Washed Out, Dark Patches, Dirt Patches and Second Material.
- **Reveal layers.** Depth and edge darkening, a Scratches preset, and six generated damage alphas.
- **Decals layers.**
  - Transparent RGBA images painted through a stencil brush with Image Aspect.
  - Normal and Darken blends, and Ctrl-drag alpha erase.
  - A generated decal library in categories.
- **Edge Wear and Dirt.** Edge Wear comes from the Bevel node and Dirt from ambient occlusion.
  **Bake Edges and AO** bakes their sources so they look the same in EEVEE.
- **Layer panel.** Rename, status notes and a pinned Base row.
- **Convert 2.x materials,** keeping painted masks.
- **Reference wall test.** It compares RealWorn against the same look built by hand with plain
  nodes; the mean difference is 0.0002.

### Changed
- All layers mix into one Principled BSDF. Cycles render overhead for a typical stack fell from
  about +90% (2.1) to +47–48%; after Bake Material it is +3–4%.

### Removed
- Edge Detail, mask ingredients, textured looks, geometry and shader damage, projector decals,
  Water, and the sharpness tools. 2.x materials using them can be converted, and the parts with no
  equivalent are listed.

### Fixed
- Worked around Blender 5.2.1 baking black into images larger than the render tile in interactive
  sessions.

## [2.1.0] - 2026-10-13

### Added
- Edge Detail (Erode, Burn, Height Compare) driven by a grunge, the base material's height or AO,
  or the layer's own height.
- Textured looks per layer type, and a content library with thumbnails.
- Masks at 2048 px per metre by default, Hero masks, Upgrade Masks, and float masks for relief.
- Follow Base damage carving, a shared normal path, and one height for bump and displacement.
- Sharpness Report and diagnostics.

## [2.0.0] - 2026-10-13

### Added
- Paintable layer stack: Setup and exact Remove, a dedicated paint UV, mask painting with
  Blender's brushes, and a save handler.
- Generated grunge library and grunge brushes.
- Layer types with PBR set content, mask ingredients and Edge Lock.
- Painted damage (shader, displacement, geometry) and decals as layers.
- Bake Material, Flatten and export presets for Unity, Unreal and glTF.
- Migration from 0.7.

### Removed
- The scene weather system.

## [0.7.0] - 2026-10-12

### Added
- First release: procedural masks, material injector with exact removal, presets, scene
  weather, projector decals, boolean damage, and bake to textures.

[Unreleased]: https://github.com/nabrahma/RealWorn/compare/v3.4.0...HEAD
[3.4.0]: https://github.com/nabrahma/RealWorn/compare/v3.3.0...v3.4.0
[3.3.0]: https://github.com/nabrahma/RealWorn/compare/v3.0.0...v3.3.0
[3.0.0]: https://github.com/nabrahma/RealWorn/compare/v2.1.0...v3.0.0
[2.1.0]: https://github.com/nabrahma/RealWorn/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/nabrahma/RealWorn/compare/v0.7.0...v2.0.0
[0.7.0]: https://github.com/nabrahma/RealWorn/releases/tag/v0.7.0

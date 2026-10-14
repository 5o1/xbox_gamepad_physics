# Third-party notices

This repository records provenance separately from mechanical acceptance. A
visual asset appearing here does not mean that its scale, pivots, travel,
forces, or controller revision have been verified.

The project's own source code is licensed under MIT; see `LICENSE`
(Copyright (c) 2026 5o1). The licenses below continue to apply to the
identified third-party works and derivatives.
The selected Xbox One S source GLB, visual derivatives and packed Cycles scene are
stored under `assets/xbox_one_s/`. Other original archives, Blender files, HDR environments,
PDFs and large intermediates remain outside this Git repository.

## Xbox One S Controller/Gamepad (Animated)

- Creator: BatonyRobson
- Source: <https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4>
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
- Distributed model files: the unchanged source GLB in `assets/xbox_one_s/source/`,
  and the static GLB plus 16 geometry-only OBJ parts in `assets/xbox_one_s/visual/`.
  The static derivatives evaluate source frame 0 and bake transforms into world
  coordinates without decimation or scale fitting. Materials and textures are
  embedded in the static GLB. Attribution accompanies the files in
  `assets/xbox_one_s/README.md`. The closed per-component collision mesh base in
  `assets/xbox_one_s/collision_meshbase/` is a further derivative; its changes are
  listed in that directory's `README.md`. Superseded snapshots of it are kept unchanged
  in `assets/xbox_one_s/archive/` for provenance only; they are not in the release zip.
- v0.3.0 input zip: contains only the approved Xbox One S source GLB, static
  visual snapshot, collision meshbase, frozen v0.2.0 CoACD hulls, approved Cycles
  scene and the provenance/license files needed for these inputs. Runtime
  kinematics, motion, sim_visual, URDF/manifests and SDF meshes are generated
  locally by the wheel. Frozen CoACD is a meshbase derivative, not an unchanged
  author original; its source and parameters accompany that snapshot.
- CC BY 4.0 legal text: <https://creativecommons.org/licenses/by/4.0/legalcode>.
- Repository derivatives: rendered views and material/lighting comparisons in
  `build/experiments/xbox_one_s_batonyrobson_UNVERIFIED/`,
  `build/experiments/xbox_official_import_comparison/`, and
  `build/experiments/xbox_sketchfab_viewer_reference/`
- Changes: imported from the creator's FBX/glTF downloads, rendered from fixed
  cameras, tested under alternative lighting and color-management settings,
  and used to produce masks, difference images, and comparison composites.
  These changes do not establish dimensional or mechanical accuracy.

## Nintendo Switch Pro Controller

- Creator: lucasmunillaclavero
- Source: <https://sketchfab.com/3d-models/nintendo-switch-pro-controller-7b739b6bde5445e3ba4b861ed84fdfdf>
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
- Repository derivatives: rendered views in
  `build/experiments/switch_pro_lucasmunillaclavero_UNVERIFIED/` and the comparison page
  `build/experiments/controller_review.html`
- Changes: imported from the creator's FBX/glTF download and rendered from
  diagnostic camera directions. No mechanical part boundaries were inferred
  from the converted glTF splits.

## 3DControllerModels

- Publisher: CasperH2O
- Source revision: <https://github.com/CasperH2O/3DControllerModels/tree/f0d985618e7c74ca35d4c428228cb5263e3d471e>
- Repository license declaration: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- Repository derivatives: the retained Xbox 1914 appearance-candidate renders
  under `build/experiments/legacy_casper_1914_visual_parts/` and
  `build/experiments/legacy_casper_1914_width_scaled_1708_proxy_historical_ui_mislabeled_1708.png`
- Changes: the visual model was inspected, decomposed for diagnostic rendering,
  and width-scaled for comparison. It was rejected as the Xbox 1708 target. The
  latter retained screenshot is historical evidence of that rejection process;
  its in-image “Xbox One 1708” label was erroneous and is not an identity claim.
- Caveat: the upstream collection does not provide a separate provenance and
  attribution record for every model. The repository-wide declaration is
  recorded here without inferring more specific authorship.

## Wesk's Switch Pro Controller scan

- Creator: Wesk
- Source: <https://bitbuilt.net/forums/threads/switch-pro-controller-scan.5755/>
- License statement: <https://bitbuilt.net/forums/threads/wesks-3d-scans-license.5444/>
- License: [The Unlicense](https://unlicense.org/)
- Repository derivatives: clay diagnostic renders in
  `build/experiments/switch_pro_wesk/`
- Changes: the large STL scan was rendered from fixed diagnostic directions.
  The source scan remains outside this repository.

## Poly Haven HDR environments

The following environments were used in the rendering work:

- [Boiler Room](https://polyhaven.com/a/boiler_room)
- [Industrial Workshop Foundry](https://polyhaven.com/a/industrial_workshop_foundry)
- [Studio Small 08](https://polyhaven.com/a/studio_small_08)

Poly Haven publishes these assets under
[CC0 1.0](https://polyhaven.com/license). Standalone HDR/EXR files are not included;
download hashes and acquisition records are kept in `references/*_hdri.json`.
The user-selected Boiler Room environment is also packed unchanged in
`assets/xbox_one_s/render/Xbox_One_S_approved_cycles.blend` for the Cycles viewer.
It is by Oliksiy Yakovlyev, distributed by Poly Haven under CC0; its source and
hash are recorded in `references/boiler_room_hdri.json`.

These environments are licensed approximations, not copies of Sketchfab's
Industrial Room environment.

## gamepad-overlay

- Creator: Jacob McIntosh / sevaht
- Source: <https://github.com/sevaht/gamepad-overlay>
- Pinned revision: `31236cd6a029828c8b01966ddc1a92c31e5cd852`
- License: [The Unlicense](https://unlicense.org/)
- Distributed files: the SVG overlay core, renderer, Xbox layout and input
  renderer under `viewer/gamepad_overlay/`; exact hashes are recorded in
  `viewer/gamepad_overlay/upstream.json`.
- Project changes: vendored rendering/input files have local patches for
  continuous button values, exact state changes, D-pad highlight and Guide
  display. `viewer/gamepad_overlay/upstream.json` records the upstream revision
  and local patch history. The local `canonical_adapter.mjs`, dashboard and
  research theme translate the project's 32-channel state into renderer input
  and add experiment telemetry.

## Reference-only sources

iFixit photographs, FCC exhibits, manufacturer data sheets, Input Labs Alpakka
documents, and other research references are represented by URLs, locators, and
where available hashes in `references/`. They are not relicensed or redistributed
by this repository. Raw Sketchfab API responses, embedded platform pages, and
platform-UI screenshots are likewise excluded; only the licensed model-derived
render used as a visual oracle is retained.

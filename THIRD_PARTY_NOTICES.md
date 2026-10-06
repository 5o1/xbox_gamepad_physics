# Third-party notices

This repository records provenance separately from mechanical acceptance. A
visual asset appearing here does not mean that its scale, pivots, travel,
forces, or controller revision have been verified.

No license for the project's own source code is declared by this notice. The
licenses below apply only to the identified third-party works and derivatives.
Original model archives, Blender files, HDR environments, PDFs, and other large
source material are not stored in this Git repository.

## Xbox One S Controller/Gamepad (Animated)

- Creator: BatonyRobson
- Source: <https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4>
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
- Repository derivatives: rendered views and material/lighting comparisons in
  `results/xbox_one_s_batonyrobson_UNVERIFIED/`,
  `results/xbox_official_import_comparison/`, and
  `results/xbox_sketchfab_viewer_reference/`
- Changes: imported from the creator's FBX/glTF downloads, rendered from fixed
  cameras, tested under alternative lighting and color-management settings,
  and used to produce masks, difference images, and comparison composites.
  These changes do not establish dimensional or mechanical accuracy.

## Nintendo Switch Pro Controller

- Creator: lucasmunillaclavero
- Source: <https://sketchfab.com/3d-models/nintendo-switch-pro-controller-7b739b6bde5445e3ba4b861ed84fdfdf>
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
- Repository derivatives: rendered views in
  `results/switch_pro_lucasmunillaclavero_UNVERIFIED/` and the comparison page
  `results/controller_review.html`
- Changes: imported from the creator's FBX/glTF download and rendered from
  diagnostic camera directions. No mechanical part boundaries were inferred
  from the converted glTF splits.

## 3DControllerModels

- Publisher: CasperH2O
- Source revision: <https://github.com/CasperH2O/3DControllerModels/tree/f0d985618e7c74ca35d4c428228cb5263e3d471e>
- Repository license declaration: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- Repository derivatives: the retained Xbox 1914 appearance-candidate renders
  under `results/visual_parts/` and `results/current_candidate_front.png`
- Changes: the visual model was inspected, decomposed for diagnostic rendering,
  and width-scaled for comparison. It was rejected as the Xbox 1708 target.
- Caveat: the upstream collection does not provide a separate provenance and
  attribution record for every model. The repository-wide declaration is
  recorded here without inferring more specific authorship.

## Wesk's Switch Pro Controller scan

- Creator: Wesk
- Source: <https://bitbuilt.net/forums/threads/switch-pro-controller-scan.5755/>
- License statement: <https://bitbuilt.net/forums/threads/wesks-3d-scans-license.5444/>
- License: [The Unlicense](https://unlicense.org/)
- Repository derivatives: clay diagnostic renders in
  `results/switch_pro_wesk/`
- Changes: the large STL scan was rendered from fixed diagnostic directions.
  The source scan remains outside this repository.

## Poly Haven HDR environments

The following environments were used only to produce lighting diagnostics:

- [Boiler Room](https://polyhaven.com/a/boiler_room)
- [Industrial Workshop Foundry](https://polyhaven.com/a/industrial_workshop_foundry)
- [Studio Small 08](https://polyhaven.com/a/studio_small_08)

Poly Haven publishes these assets under
[CC0 1.0](https://polyhaven.com/license). The HDR/EXR files are not included;
download hashes and acquisition records are kept in `sources/*_hdri.json`.
These environments are licensed approximations, not copies of Sketchfab's
Industrial Room environment.

## Reference-only sources

iFixit photographs, FCC exhibits, manufacturer data sheets, Input Labs Alpakka
documents, and other research references are represented by URLs, locators, and
where available hashes in `sources/`. They are not relicensed or redistributed
by this repository. Raw Sketchfab API responses, embedded platform pages, and
platform-UI screenshots are likewise excluded; only the licensed model-derived
render used as a visual oracle is retained.

# Xbox One S visual mesh base

Author: BatonyRobson. Work: Xbox One S Controller/Gamepad (Animated).
Source: https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4
License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

Frozen, owner-reviewed snapshot (ruling 6, 2026-10-16).
This appearance base retains the reviewed STATIC_VISUAL geometry and textures for
backend appearance derivation. This freeze is repository-only: the build DAG,
loaders and resource packages do not consume it yet. Normal builds do not run
the maintainer command. It is not a collision or validated physical model.

Files: `visual_meshbase.glb`, `materials.json`, `manifest.json`, `README.md`.
The GLB preserves node names/transforms, vertices, normals, UVs and image bytes.
Only face index groups and the two material names/alphaMode differ from the
STATIC_VISUAL source. Empty groups are omitted. No rebaking or subdivision.

Generation: closed triangle/texel-square UV coverage, including boundary contact,
with REPEAT wrapping. A face is BLEND if exact alpha<255 or a one-texel 3x3 halo
contains alpha<250. Otherwise it is OPAQUE. Every split must pass the original
shared-index seam gate before output; it must never cut a shared vertex.
All parameters and provenance are in `manifest.json`.

The 256 BLEND faces cover alpha 64 only. `materials.json` records 64/255 for native
constant-opacity pass routing. Preserve source RGBA in SAPIEN 3.0.3: its textured
shader takes texture alpha directly. MuJoCo classic instead uses RGB plus the
material constant. Never multiply the GLB texture alpha by 64/255 a second time.
STATIC_VISUAL specularColorTexture differs from the author GLB specularTexture;
this snapshot retains STATIC_VISUAL, with reconciliation deferred.

Maintainer review command, from the checkout root (NumPy and Pillow required):

```sh
python3 scripts/build_visual_meshbase.py --output build/review/visual_meshbase
```

Revision rule: rerun this maintainer script; archive the intact old version under
`assets/xbox_one_s/archive/` before replacing the formal snapshot. The script
requires a new archive destination when overwriting the formal directory:

```sh
python3 scripts/build_visual_meshbase.py --output assets/xbox_one_s/visual_meshbase --archive assets/xbox_one_s/archive/visual_meshbase_PREVIOUS_REVIEW
```

Regeneration creates a review candidate, not automatic visual approval. Repeat
the import/render gates and obtain owner review before declaring a new freeze.
Prior gate results are historical evidence, not automatic approval of new bytes.
Evidence and the accepted 2026-10-16 decision are listed in the manifest.
Retain attribution, license and modification notes on distribution.
No author endorsement is claimed.

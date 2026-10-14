# Xbox One S collision mesh base

Author: BatonyRobson. Work: Xbox One S Controller/Gamepad (Animated).

- Source: https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4
- License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
- Full license: https://creativecommons.org/licenses/by/4.0/legalcode

This directory provides inputs for collision generation: 17 components, each stored as separate closed shells (watertight, manifold and outward-facing).
It retains touchable shapes rather than visual detail and is not a validated contact model.

Modifications:

- Convert to the simulation frame at the scale specified in the visual manifest, in metres with Z up.
- Main shell: repair two self-intersecting folds; close 7 circular openings (ABXY, Xbox button and both sticks) flush with the surrounding shell; fill the underside connector recess.
  On 2026-10-11, repair two remaining self-intersections: flip one quad diagonal on the inner slope below the top edge (without moving vertices) to avoid the sidewall and cap of the Xbox-button circular opening; replace two additional faces in the left fold repair. After repair, no closed shell contains self-intersecting triangles.
- Front plate: fill the USB recess and close the rear opening. Store the main shell and front plate separately without merging them.
- ABXY: retain only the keycaps; exclude lettering decoration and zero-thickness visual backing.
- Sticks: close the main body and the grip ring around the cap rim separately, allowing both to overlap within the same component.
- Other controls: close openings hidden inside the body.
- Exclude connector liners and tongues. Retain the top-edge recess, D-pad and Pair-button cavities unchanged.

Files:

- `meshes/`: 17 OBJ files in the simulation frame, in metres, with fixed 9-decimal precision.
- `manifest.json`: file list, provenance, attribution and component inclusion/exclusion decisions.
- Generator: `scripts/build_collision_meshbase.py` in the repository. It applies only to the reviewed source meshes above. If source meshes change later, this directory remains usable without regeneration.

Previous version: `assets/xbox_one_s/archive/collision_meshbase_2026-10-10/` retains the original 2026-10-10 asset snapshot (generated at commit `9bf91a3`, with 10 pairs of self-intersecting triangles in the main shell) for provenance only; it is no longer used for collision generation. The manifest records it under `previous_versions`.

When distributing copies, retain the author, source, license and modification notes above. No endorsement by the author is claimed.

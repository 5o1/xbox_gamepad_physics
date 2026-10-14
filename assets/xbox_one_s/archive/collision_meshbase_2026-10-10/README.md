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
- Front plate: fill the USB recess and close the rear opening. Store the main shell and front plate separately without merging them.
- ABXY: retain only the keycaps; exclude lettering decoration and zero-thickness visual backing.
- Sticks: close the main body and the grip ring around the cap rim separately, allowing both to overlap within the same component.
- Other controls: close openings hidden inside the body.
- Exclude connector liners and tongues. Retain the top-edge recess, D-pad and Pair-button cavities unchanged.

Files:

- `meshes/`: 17 OBJ files in the simulation frame, in metres, with fixed 9-decimal precision.
- `manifest.json`: file list, provenance, attribution and component inclusion/exclusion decisions.
- Generator: `scripts/build_collision_meshbase.py` in the repository. It applies only to the reviewed source meshes above. If source meshes change later, this directory remains usable without regeneration.

When distributing copies, retain the author, source, license and modification notes above. No endorsement by the author is claimed.

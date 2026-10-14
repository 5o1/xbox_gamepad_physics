# Frozen CoACD input snapshot

Source: xbox_gamepad_physics-resources-0.2.0.zip from Release v0.2.0, originally at common/xbox_one_s/collision/coacd/; 17 OBJ files were extracted unchanged. Tool version: coacd 1.0.14, single-threaded. See manifest.json for full parameters, per-shell thresholds and shell/hull counts. The meshbase in the same release archive matches all 19 files in the current ../collision_meshbase byte for byte; the comparison is recorded in the B1/B2 reports. This record does not assert provenance through hashes.

This is a reviewed frozen snapshot used by downstream sphere-press and teleoperation runs. Runtime builds only read it and do not rerun CoACD. Model source: BatonyRobson, CC BY 4.0. Convex decomposition of meshbase is a modification; see ../README.md for attribution and https://creativecommons.org/licenses/by/4.0/legalcode for the license text. The CoACD version and parameters are provenance evidence and confer no additional physical validation on the decomposition result.

Maintainer updates must use scripts/regenerate_collision_coacd.py, which archives the old snapshot before explicitly regenerating it. Regeneration does not automatically grant approval; it is excluded from normal user build-resources runs and is not invoked by the packager.

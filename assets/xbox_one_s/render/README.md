# User-selected Cycles scene

`Xbox_One_S_approved_cycles.blend` directly reuses the recipe for the user-approved
`boiler_room_vertical_fov35_strength_1p0.png`.
The file was prepared from the original Blender 4.5.9 scene, with the model, original materials and Boiler Room HDRI packed in.
See the parent directory's `approved_render.json` for settings and file hashes.

Fixed settings: Cycles, Boiler Room strength 1.0, no additional area lights, Standard / None / Exposure 0 /
Gamma 1, 35° vertical field of view, 64 samples and denoising; the camera background retains the original script's neutral background.

Open and render directly in Blender 4.5.9. `npm run viewer` renders interactive poses through a persistent Blender process;
the browser does not reimplement shading or lighting.

Model: BatonyRobson, CC BY 4.0; see `../README.md` for provenance and modifications.
Boiler Room: Oliksiy Yakovlyev / Poly Haven, CC0; source:
https://polyhaven.com/a/boiler_room .

Preparation script: `scripts/prepare_approved_cycles.py`. It reuses scene settings from the original
`scripts/render_reference_matched_probe.py`, selects only the user-approved strength 1.0,
and saves a distributable scene without overwriting historical files.

## 2026-10-14 private-path cleanup (decision 4)

Under the owner's decision, four kinds of path metadata were cleaned in place: open with load_ui=False; clear FileSelectParams.directory; change HDR Image.filepath and ImagePackedFile.filepath to relative original filenames; change Scene.render.filepath to a relative directory. Stale trailing bytes in fixed-length character fields were also overwritten, with no other scene properties changed. Mesh coordinates, topology, UVs and all packed image bytes remained identical; the HDR remained 23,613,147 B. The original is archived only in the node's task directory and is not distributed.

The decision 4 acceptance criteria were set in advance: same Blender 4.5.9 / GPU 0 / approved frame 0 and all original settings; five fresh renders each of the old and new scenes, interleaved; compare 10 old/old pairs and 25 new/old pairs. Maximum difference for all 35 pairs must be ≤1 level; the medians of differing-pixel counts and mean differences for new/old pairs must both be ≤1.5 times the corresponding old/old medians; heatmaps on the same color scale must show no new localized regions absent from old/old comparisons. Measured differing-pixel medians were 84.5 (old/old) and 86 (new/old); mean-difference medians were 0.000014670138888888888 and 0.000014930555555555555. All three criteria passed, and a final scan before replacement found zero actual private-path matches. See the release acceptance report for heatmaps and all 35 pair comparisons.

One text chunk containing private information was also removed from the reference PNG; IDAT bytes and decoded pixels are unchanged. The reference_sha256 in approved_render.json continues to identify the historically approved binding, while reference_file_sha256 identifies the current PNG with unchanged pixels and cleaned text metadata.

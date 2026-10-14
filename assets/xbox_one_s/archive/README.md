# Previous Xbox One S asset versions

This directory retains superseded asset snapshots for provenance only; they are excluded from builds, tests and release packages. Geometry and data files retain their original bytes; README text has been translated into English.

| Directory | Replaced by | Generator version | Reason for replacement |
| --- | --- | --- | --- |
| `collision_meshbase_2026-10-10/` | `../collision_meshbase/` (2026-10-11) | `scripts/build_collision_meshbase.py` at commit `9bf91a3` | The main shell has 10 pairs of nonadjacent self-intersecting triangles: the inner slope below the top edge crosses the sidewall and cap of the Xbox-button circular opening (8 pairs), and the cap of the left fold repair crosses two original faces (2 pairs). The other 16 components match the replacement version. |

The archived `manifest.json` remains unchanged; the `README.md` has been translated. Generator paths refer to the version used at the time.
The author, source and license match `../collision_meshbase/README.md` (BatonyRobson, CC-BY-4.0); retain this information when distributing copies.

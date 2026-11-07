# Experimental preview: known issues

Native loading, drive and signal integration are separate from contact readiness.
The following native scores describe the 2026-11-07 source worktree with frozen
common inputs. The final integrated v0.4.2 wheel still needs its own validation.

| Area | Historical observation | Boundary |
| --- | --- | --- |
| Frozen SDF 0.5 mm T4 | 23/26; all prior 22 passes retained, L3 newly passed | Guide, Pair and R3 still fail; thresholds unchanged |
| Guide | Minimum hold signal 0.931170017, below 0.95 | Contact readiness remains open |
| Pair | Physical event remains zero | Separate from the canonical32 game tensor; not fixed |
| L3 / R3 | L3 minimum 0.972152629; R3 minimum 0.949565874 | R3 fails even though its peak reaches one; no rounding into a pass |
| Point-force T3 v2 | New model 10/10, including 8.14 N positive controls and unloading | No sphere/contact servo; not a contact-physics qualification |
| Old-model point controls | Low loads are zero; both positive controls fail | The right positive-control tail is about 0.332497, not zero; no expected low-load misfire was reproduced |
| Sphere T3 v1 | Fixture invalidated by the owner | Retain records; do not use for physical conclusions |
| Native cone | Authored half-angle 22.954 degrees from approved 0.998 margin | Shared 23-degree bound unchanged; new chain has no arbitrary-load strict transient guarantee |
| Earlier transient limit | Earlier compensated topology had a free/N=64 sample at 23.001294 degrees | Historical failure is not erased or relabeled as current-wheel validation |
| Earlier free/N=1024 permutation | Root difference 4.2915 micrometres exceeded the 3-micrometre gate | No fresh full batch/scaling qualification for this component |
| Runtime preload | Naked USD lacks the -7.4 N generalized effort | Construct `cfg.class_type(cfg)`; keep Lab's persistent effort buffer in normal writes |
| Caller effort override | Replacing click effort targets removes the initialized bias | Compose new click commands with -7.4 N; other joints are unaffected |
| CoACD comparison | Earlier SDK cooking changed four large hulls to 32–38 vertices | Not evidence that cooked hulls equal the source geometry |
| Appearance | PreviewSurface and linear ABXY coverage; real-time RTX can blur ABXY | Not complete glTF dielectric-specular equivalence; path tracing is clearer |
| Generic build CLI | Native USD authoring requires caller-owned AppLauncher | Use the dedicated example/direct builder; no automatic platform startup |
| Training and hardware calibration | Not established | No RL or hardware-identified physics claim |

The historical native initialization check confirmed fixed/free scalar preload
buffers before binding, ordinary flushes, and asset reset under Lab 2.3.2. Full
stop/play reinitialization behavior follows the lifecycle implementation but was
not separately exercised. Historical batch results do not prove that a final
integrated wheel has passed the same boundaries.

Versioned scalar evidence and protocol digests are in
[the Isaac source summary](../../tests/acceptance/isaac/data/source_native_20261107.json).
Full private experiment archives are not required to load this preview.

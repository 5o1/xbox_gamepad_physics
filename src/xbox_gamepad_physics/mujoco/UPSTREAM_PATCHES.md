# MuJoCo SDF dependency patch

The active local dependency is `mujoco==3.16.0+concon.sdf3689.2`, built in
[GitHub Actions run 39195476197](https://github.com/5o1/mujoco/actions/runs/39195476197).
The engine, plugins, generated binding sources and Python extensions were built
from the same source checkout. No binary replacement is used in this package.

The maintenance repository is [5o1/mujoco](https://github.com/5o1/mujoco), branch
[`concon/3.16.0-sdf-sign-pr3689`](https://github.com/5o1/mujoco/tree/concon/3.16.0-sdf-sign-pr3689).
Its [maintenance notes](https://github.com/5o1/mujoco/blob/concon/3.16.0-sdf-sign-pr3689/CONCON_PATCHES.md)
contain the build and artifact-download instructions.

## Source and scope

The base is the official 3.16.0 release commit
`a892750516336d8358949f4518fcc4fbbd85beae`. The engine change is upstream
[PR #3689](https://github.com/google-deepmind/mujoco/pull/3689), pinned to
`89733a51f207c7fedafc855d22ffd4c38caa793a`. The PR was unmerged when adopted on
2026-10-19. The adopted wheel records fork source commit
`ac1bfe32700667d98b0eea412900beef5d98cbc2` in `mujoco/CONCON_BUILD.json`.

The correction uses adjacent face normals when the nearest mesh point lies on
an edge, and angle-weighted adjacent normals at vertices. This prevents the
confirmed exterior-to-interior sign errors. It does not change our meshes,
physical parameters, numerical/contact policies or acceptance fixtures. Recompile
models from source; existing `.mjb` files retain their old SDF coefficients.

## Installation and identity

Install the patched wheel from the fork Release
[`v3.16.0-concon.sdf3689.2`](https://github.com/5o1/mujoco/releases/tag/v3.16.0-concon.sdf3689.2)
(source commit `ac1bfe3`, GitHub Actions run 39195476197) into your own
Python 3.10 or 3.11 environment. Its SHA256SUMS lists
`cc0a30b4...6fc22a` (cp310) and `ca623da6...85b75d` (cp311).
The wheel is a Linux x86_64 build from Ubuntu 22.04 GCC, without a manylinux
portability claim. Native library LTO follows the upstream default (on); Python
extensions use the upstream CI LTO-off setting. Native API version strings remain
`3.16.0`; inspect distribution metadata to identify the patched installation:

```sh
python -c 'import importlib.metadata; print(importlib.metadata.version("mujoco"))'
python -c 'import mujoco,pathlib; print((pathlib.Path(mujoco.__file__).parent/"CONCON_BUILD.json").read_text())'
```

Full local fast regression passed after installation: 324 unittest cases
(268 passed, 56 skipped), 20 MuJoCo backend tests and 35 Node tests. Detailed
Python-version and contact results are recorded in the Chinese report below.
The subsequent full frozen contact recheck completed all 26 cases: 23 passed;
Pair, L3 and R3 failed, matching the SAPIEN baseline's three failures. All 23
previously passing baseline cases passed, with zero regressions. The complete
comparison is recorded in `build/experiments/mb_m2/gh_recheck_26/REPORT.md`.
Convergence and visual acceptance remain separate pending gates. This dependency
update does not by itself complete M2 acceptance.

## Previous failed installation

The earlier candidate `3.16.0+concon.sdf3689.1` combined a locally built engine
with official prebuilt Python extensions. Static SDF and rest checks passed, but
acceptance-model compilation segfaulted. That candidate was rolled back and
must not be used. The source-built `.2` package passes that compile boundary and
the full local fast regression. The exact native cause of the previous mixed
build's crash has not been isolated; do not attribute it to a proven ABI defect.

## Project records and rollback

- Build report: `build/experiments/mb_m2/gh_build/REPORT.md`.
- Latest full contact recheck: `build/experiments/mb_m2/gh_recheck_26/REPORT.md`.
- Historical failed attempt: `build/experiments/mb_m2/pr3689_install/REPORT.md`.
- Maintenance checkout: `build/third_party/mujoco/`.
- Official rollback wheel: `build/third_party/wheels/official/`.

To roll back, reinstall the retained official 3.16.0 wheel with `--no-index
--no-deps --force-reinstall`, then recompile models. The old official SDF sign
error will return; rollback is a dependency rollback, not a fix for that error.

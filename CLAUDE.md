# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Project scope, evidence rules, geometry-identity gates and networking rules live in AGENTS.md and apply in full:

@AGENTS.md

Use English for README, code, comments, configuration, and asset documentation. Keep `docs/` in Chinese.

## Commands

Python 3.10 is the baseline (RoboTwin/SAPIEN env). Node 22 (`.node-version`) for JS tests and the viewer.

```sh
# v0.3 user installation: Release wheel + input zip; not on PyPI
python3.10 -m pip install "./xbox_gamepad_physics-0.3.1-py3-none-any.whl[build,robotwin]"
python3.10 -m xbox_gamepad_physics build-resources --archive ./xbox_gamepad_physics-resources-0.3.1.zip --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
# Maintainer checkout: thin wrappers call the same packaged build chain; default build/resources
python3 scripts/build_resources.py
# Use the setup.py mirror in setuptools 59 development environments with dependencies already prepared
python3 -m pip install -e . --no-build-isolation
npm ci

# Full regression (unittest discover over tests/ + node --test tests/test_*.mjs)
python3 scripts/run_regression.py fast               # == npm test

# Experiment platform (run from the repo root; needs the RoboTwin/SAPIEN env and PyYAML)
python3 run_robotwin.py configs/smoke_full_controls.yaml --set params.steps=20
python3 run_robotwin.py configs/render_review.yaml --set scene.robotwin_root=/path/to/RoboTwin --output build/runs/review

# Single test
python3 -m unittest tests.infrastructure.test_resource_resolution -v
python3 -m unittest tests.test_kinematics.<Class>.<test_method>
node --test tests/test_drag2d.mjs

# Backend readiness (non-zero exit if any declared resource is missing / not ready)
python3 -m xbox_gamepad_physics status --backend all --profile full_controls
python3 -m xbox_gamepad_physics verify --backend all --profile full_controls

# Viewer kinematics source check
python3 scripts/build_kinematics.py --check

# Interactive viewer (Cycles-backed; needs Blender 4.5.9) and signal overlay
npm run viewer            # Open the printed viewer URL
npm run gamepad-overlay   # Open the printed canonical overlay URL
```

Many tests `skipIf` optional deps (numpy, torch, OpenCV, mujoco, sapien) and only fully run in the GPU-node environments. A skipped test is not a pass — say which ones skipped.

v0.3 supports Linux x86_64 + NVIDIA, Python 3.10, and the RoboTwin fork / SAPIEN 3.0.3 only. MuJoCo is outside the release scope: loading and explicit status/verify report this exclusion. The historical frozen tree remains in Git; related tests skip with an explanation.

## Architecture

**Experiment platform.** `run_robotwin.py` (repo root) runs an experiment from `configs/*.yaml`. Each experiment is one `run(cfg, ctx) -> metrics` function in `experiments/`, registered in `experiments/__init__.py`. Outputs go to `build/runs/<config>/<timestamp>/` (`config.yaml`, `meta.json`, `metrics.json`, artifacts). `experiments/` and `configs/` are checkout-only and never enter the wheel.

**Resource inputs and packaged builds.** The DAG and generators live in `src/xbox_gamepad_physics/builders/`; `scripts/` provides thin maintainer wrappers. The wheel includes versioned small evidence in `build_data/`, specs, and a One S asset-index slice. The input zip contains only the original author GLB, reviewed STATIC_VISUAL and inventory, meshbase, frozen v0.2.0 CoACD, the packed Cycles scene, and their provenance/licenses. Basic builds need no Blender and do not invoke CoACD. Kinematics, the motion contract, sim_visual, URDF/manifests, and SDF triangle meshes are generated on the user machine; SDF cooking occurs later during SAPIEN loading.

The resolver prioritizes the environment variable, checkout `build/resources/`, then downstream-project `.xbox_gamepad_physics/resources/`; use `--resources` for an independent directory. Explicit environment roots also undergo preparation. Inputs live in `<root>/inputs/`, with input receipts separate from output `.stamps/`; import offline with `--archive ... --offline`. `_resource_lock.json` points to the input zip. Missing/stale nodes and their downstream nodes rebuild locally without writing to HOME or site-packages.

The packager reads only its allowlist and does not run builders; Releases attach the wheel, input zip, and SHA256SUMS, with no PyPI publication. Project code is MIT; the third-party model remains CC BY 4.0, packed HDR remains CC0, and other code licenses remain applicable. The user `[build]` extra excludes coacd; only the maintainer `[maintainer]` extra declares it. Explicit `scripts/regenerate_collision_coacd.py --output <review-output> --archive <new-archive-dir>` archives the old snapshot before generating review outputs. Meshbase updates likewise archive first; new hulls are never adopted automatically.

The historical MuJoCo tree in `src/xbox_gamepad_physics/resource_data/mujoco/` remains in place, excluded from the runtime DAG, wheel, and input zip; do not restore its old generator.

**Layering:**
- `references/*.json` — evidence records (source, units, applicability, derivation, uncertainty). Builders read physical parameters from here (notably `references/full_controls.json`, `references/catalog.json`). `specs/` holds target specs and explicit unknowns; `assets/asset_index.json` is the source of truth for candidate/admission status.
- `common/xbox_one_s/` (in the resource root) — backend-neutral visual (glTF + 2K textures) and the **motion contract** (`motion/full_controls.json`: joint topology, per-axis ranges, radial constraints, signal bindings). Both backends and the signal controller read this one contract; backend manifests do not duplicate motion limits.
- `collision` reads frozen CoACD and locally prepares per-shell SDF OBJ meshes from meshbase, preserving output paths; only RoboTwin `full_controls` depends on this node.
- `<backend>/<profile>/manifest.json` (in the resource root) — format documented in `schemas/backend_manifest.schema.json` (documentation, not enforced at runtime); declares readiness flags and required files. v0.3 profiles are RoboTwin `full_controls` (20 active joints) and `left_stick`.
- `state.py` — versioned 32-channel `sdl3-gamepad-core-v1` tensor (6 SDL3 axes + 26 buttons) with `available_mask`, `task_mask`, `device_id`. Xbox One S uses 21 channels; Pair is a physical event, not a game channel. Adapt by channel name, never by index. The browser side uses the 21-float W3C layout only at its boundary (`W3C_STANDARD_TO_CANONICAL`).
- `controller.py` — `GamepadSignalController`: backend-independent mapping between named joint positions and `GamepadState` (normalization, saturation, dual-stick radial clamp, D-pad split, deadzones, masks), both directions.
- `robotwin/` and `mujoco/` — loaders that consume a caller-owned scene/`MjSpec` and pose. The RoboTwin loader gates only on readiness, file presence and joint-name agreement; the motion contract and `GamepadSignalController` still validate their own inputs, and the frozen MuJoCo layer keeps its checks. RoboTwin field ranges/finiteness and explicit URDF physics (inertials, limits, axes) are generator guarantees checked on built output by the asset tests (`tests/infrastructure/built_profile_checks.py`), not on every load; public handles expose joints by name only (qpos order is not API). The package never imports RoboTwin task modules or chooses table/fixture poses.
- `muble/` — exports MuJoCo body poses to drive accepted Blender objects.
- `viewer/` — browser kinematic inspector (Three.js picking + Blender/Cycles worker via `scripts/serve_viewer.py` / `scripts/cycles_worker.py`), plus the vendored `gamepad_overlay` SVG renderer with a canonical-state adapter.

**Readiness vs. validation:** "loads, steps and round-trips signals" (smoke examples in `examples/*_smoke.py`, CLI `verify`) is infrastructure readiness only. It is not visual acceptance (user confirms renders), contact/dynamics validation, or real-hardware calibration — keep those claims separate in docs, manifests and commit messages.

## Conventions

- Outputs of experiments, review videos and generated viewer kinematics go under `build/` (git-ignored); they describe one run, not current HEAD.
- `pyproject.toml` is canonical package metadata (setup.py reads its version); `setup.py` is a mirror for setuptools 59 — keep dependencies/extras in sync.
- Commit messages use conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Project scope, evidence rules, geometry-identity gates and networking rules live in AGENTS.md and apply in full:

@AGENTS.md

Human-facing docs (README, `docs/`) are written in Chinese; match that language when editing them.

## Commands

Python 3.10 is the baseline (RoboTwin/SAPIEN env). Node 22 (`.node-version`) for JS tests and the viewer.

```sh
# Setup
python3.10 -m venv .venv && .venv/bin/python -m pip install -r requirements/gpu-tested.freeze.txt
npm ci
python3 -m pip install -e .                          # add ".[mujoco]" / ".[robotwin]" for backends
python3 -m pip install -e . --no-build-isolation     # offline RoboTwin env (setuptools 59, uses setup.py)

# Full regression (unittest discover over tests/ + node --test tests/test_*.mjs)
python3 scripts/run_regression.py fast               # == npm test

# Single test
python3 -m unittest tests.infrastructure.test_mujoco_full_controls_asset -v
python3 -m unittest tests.test_kinematics.<Class>.<test_method>
node --test tests/test_drag2d.mjs

# Backend readiness (non-zero exit if any declared resource is missing / not ready)
python3 -m xbox_gamepad_physics status --backend all --profile full_controls
python3 -m xbox_gamepad_physics verify --backend all --profile full_controls

# Viewer kinematics source check
python3 scripts/build_kinematics.py --check

# Interactive viewer (Cycles-backed; needs Blender 4.5.9) and signal overlay
npm run viewer            # http://127.0.0.1:8766/
npm run gamepad-overlay   # http://127.0.0.1:8770/viewer/gamepad_overlay/index.html?source=canonical
```

Many tests `skipIf` optional deps (numpy, torch, OpenCV, mujoco, sapien) and only fully run in the GPU-node environments. A skipped test is not a pass — say which ones skipped.

MuJoCo/Filament work uses a separate Python 3.12 env (see `docs/importing.md`); the Filament renderer needs the patched `5o1/mujoco` opacity-texture branch, and a self-built MuJoCo needs the conda `libstdc++` activation scripts in `requirements/conda/`.

## Architecture

**Packaged resources are generated, then frozen.** Everything under `src/xbox_gamepad_physics/resource_data/` is build output checked into Git, produced by scripts in `scripts/` in this order:

```sh
python scripts/build_common_motion.py          # common/xbox_one_s/motion/full_controls.json
python scripts/build_robotwin_full_controls.py # robotwin/full_controls/ (URDF + manifest)
python scripts/build_mujoco_full_controls.py   # mujoco/full_controls/ (MJCF + manifest)
```

`assets/xbox_one_s/collision_meshbase/` is a frozen, reviewed source snapshot (closed per-component meshes) for future collision generation, not a rebuild step. `scripts/build_collision_meshbase.py` records how it was made and only accepts the reviewed source mesh; upstream mesh changes do not require regenerating it.

Tests in `tests/infrastructure/test_*_asset.py` rebuild into a temp dir and diff against the checked-in files (`test_*_is_fresh`). After changing a build script, an evidence file in `references/`, or the motion contract, rerun the affected builders and commit the regenerated resources together. Never hand-edit generated URDF/MJCF/manifests.

**Layering:**
- `references/*.json` — evidence records (source, units, applicability, derivation, uncertainty). Builders read physical parameters from here (notably `references/full_controls.json`, `references/catalog.json`). `specs/` holds target specs and explicit unknowns; `assets/asset_index.json` is the source of truth for candidate/admission status.
- `resource_data/common/xbox_one_s/` — backend-neutral visual (glTF + 2K textures) and the **motion contract** (`motion/full_controls.json`: joint topology, per-axis ranges, radial constraints, signal bindings). Both backends and the signal controller read this one contract; backend manifests do not duplicate motion limits.
- `resource_data/<backend>/<profile>/manifest.json` — validated by `schemas/backend_manifest.schema.json` and `profiles.py`; declares readiness flags and required files. Profiles: `full_controls` (both backends, 20 active joints) and `left_stick` (RoboTwin only).
- `state.py` — versioned 32-channel `sdl3-gamepad-core-v1` tensor (6 SDL3 axes + 26 buttons) with `available_mask`, `task_mask`, `device_id`. Xbox One S uses 21 channels; Pair is a physical event, not a game channel. Adapt by channel name, never by index. The browser side uses the 21-float W3C layout only at its boundary (`W3C_STANDARD_TO_CANONICAL`).
- `controller.py` — `GamepadSignalController`: backend-independent mapping between named joint positions and `GamepadState` (normalization, saturation, dual-stick radial clamp, D-pad split, deadzones, masks), both directions.
- `robotwin/` and `mujoco/` — loaders that consume a caller-owned scene/`MjSpec` and pose. Loaders gate on manifest readiness, file presence, explicit inertials, and joint-name agreement; public handles expose joints by name only (qpos order is not API). The package never imports RoboTwin task modules or chooses table/fixture poses.
- `muble/` — exports MuJoCo body poses to drive accepted Blender objects.
- `viewer/` — browser kinematic inspector (Three.js picking + Blender/Cycles worker via `scripts/serve_viewer.py` / `scripts/cycles_worker.py`), plus the vendored `gamepad_overlay` SVG renderer with a canonical-state adapter.

**Readiness vs. validation:** "loads, steps and round-trips signals" (smoke examples in `examples/*_smoke.py`, CLI `verify`) is infrastructure readiness only. It is not visual acceptance (user confirms renders), contact/dynamics validation, or real-hardware calibration — keep those claims separate in docs, manifests and commit messages.

## Conventions

- Outputs of experiments, review videos and generated viewer kinematics go under `build/` (git-ignored); they describe one run, not current HEAD.
- `pyproject.toml` is canonical package metadata; `setup.py` is a mirror for setuptools 59 — keep `package_data` in sync when adding resource directories.
- Commit messages use conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).

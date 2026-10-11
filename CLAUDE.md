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
python3 -m pip install -e ".[build]"                # add ".[mujoco]" / ".[robotwin]" for backends
python3 -m xbox_gamepad_physics build-resources     # build the resource DAG into build/resources/ (--force)
python3 -m pip install -e . --no-build-isolation     # offline RoboTwin env (setuptools 59, uses setup.py)

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
npm run viewer            # http://127.0.0.1:8766/
npm run gamepad-overlay   # http://127.0.0.1:8770/viewer/gamepad_overlay/index.html?source=canonical
```

Many tests `skipIf` optional deps (numpy, torch, OpenCV, mujoco, sapien) and only fully run in the GPU-node environments. A skipped test is not a pass — say which ones skipped.

MuJoCo/Filament work uses a separate Python 3.12 env (see `docs/importing.md`); the Filament renderer needs the patched `5o1/mujoco` opacity-texture branch, and a self-built MuJoCo needs the conda `libstdc++` activation scripts in `requirements/conda/`.

## Architecture

**Experiment platform.** `run_robotwin.py` (repo root) runs an experiment from `configs/*.yaml`. Each experiment is one `run(cfg, ctx) -> metrics` function in `experiments/`, registered in `experiments/__init__.py`. Outputs go to `build/runs/<config>/<timestamp>/` (`config.yaml`, `meta.json`, `metrics.json`, artifacts). `experiments/` and `configs/` are checkout-only and never enter the wheel.

**Resources are built, not committed.** Runtime resources are generated at build time from the sources in Git (`assets/`, `references/`, `specs/`, the frozen MuJoCo tree) by the explicit DAG in `scripts/build_resources.py`. Each node calls an existing generator's `build(output=..., <inputs>=...)`. The resolver in `src/xbox_gamepad_physics/resources.py` picks the resource root in this order:

1. `XBOX_GAMEPAD_PHYSICS_RESOURCES`
2. `<repo>/build/resources/` in a checkout
3. `<project>/.xbox_gamepad_physics/resources/` when installed as a dependency

Missing or stale resources are rebuilt locally, or downloaded as the release zip and checked against `_resource_lock.json`, which is generated only by `scripts/package_release_resources.py` and git-ignored. Staleness uses private per-node stamps of input contents; never assert hashes in tests or manifests. Tests build into a temp dir and inspect structure, they do not byte-diff. The wheel is code only. Running a generator directly writes to `build/standalone/` and reads inputs from `build/resources/`.

- MuJoCo is frozen: `src/xbox_gamepad_physics/resource_data/mujoco/` stays in Git and is copied as-is. Its generators read common resources that are no longer tracked, so its freshness test is skipped.
- `assets/xbox_one_s/collision_meshbase/` is a frozen, reviewed source snapshot (closed per-component meshes) for future collision generation, not a rebuild step. `scripts/build_collision_meshbase.py` records how it was made and only accepts the reviewed source mesh; upstream mesh changes do not require regenerating it. A deliberate repair regenerates it in place and first copies the previous snapshot unchanged to `assets/xbox_one_s/archive/` (recorded in its manifest's `previous_versions`).

**Layering:**
- `references/*.json` — evidence records (source, units, applicability, derivation, uncertainty). Builders read physical parameters from here (notably `references/full_controls.json`, `references/catalog.json`). `specs/` holds target specs and explicit unknowns; `assets/asset_index.json` is the source of truth for candidate/admission status.
- `common/xbox_one_s/` (in the resource root) — backend-neutral visual (glTF + 2K textures) and the **motion contract** (`motion/full_controls.json`: joint topology, per-axis ranges, radial constraints, signal bindings). Both backends and the signal controller read this one contract; backend manifests do not duplicate motion limits.
- `<backend>/<profile>/manifest.json` (in the resource root) — format documented in `schemas/backend_manifest.schema.json` (documentation, not enforced at runtime); declares readiness flags and required files. Profiles: `full_controls` (both backends, 20 active joints) and `left_stick` (RoboTwin only).
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

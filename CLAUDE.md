# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Project scope, evidence rules, geometry-identity gates and networking rules live in AGENTS.md and apply in full:

@AGENTS.md

Human-facing docs (README, `docs/`) are written in Chinese; match that language when editing them.

## Commands

Python 3.10 is the baseline (RoboTwin/SAPIEN env). Node 22 (`.node-version`) for JS tests and the viewer.

```sh
# v0.3.0 用户安装：Release wheel + 输入 zip，不上 PyPI
python3.10 -m pip install "./xbox_gamepad_physics-0.3.0-py3-none-any.whl[build,robotwin]"
python3.10 -m xbox_gamepad_physics build-resources --archive ./xbox_gamepad_physics-resources-0.3.0.zip --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
# 维护检出：薄包装调用包内同一构建链，默认 build/resources
python3 scripts/build_resources.py
# 已备好依赖的 setuptools 59 开发环境使用 setup.py 镜像
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
npm run viewer            # http://127.0.0.1:8766/
npm run gamepad-overlay   # http://127.0.0.1:8770/viewer/gamepad_overlay/index.html?source=canonical
```

Many tests `skipIf` optional deps (numpy, torch, OpenCV, mujoco, sapien) and only fully run in the GPU-node environments. A skipped test is not a pass — say which ones skipped.

v0.3.0 仅支持 Linux x86_64 + NVIDIA、Python 3.10、RoboTwin fork / SAPIEN 3.0.3。MuJoCo 不在发布范围，加载和显式 status/verify 会给出提示；历史冻结树留在 Git，相关测试注明原因跳过。

## Architecture

**Experiment platform.** `run_robotwin.py` (repo root) runs an experiment from `configs/*.yaml`. Each experiment is one `run(cfg, ctx) -> metrics` function in `experiments/`, registered in `experiments/__init__.py`. Outputs go to `build/runs/<config>/<timestamp>/` (`config.yaml`, `meta.json`, `metrics.json`, artifacts). `experiments/` and `configs/` are checkout-only and never enter the wheel.

**资源输入与包内构建。** DAG 和生成器在 `src/xbox_gamepad_physics/builders/`，`scripts/` 为维护者薄包装。wheel 带版本化 `build_data/` 小证据、specs 与 One S 资产索引切片。输入 zip 只含原作者 GLB、已审 STATIC_VISUAL 与 inventory、meshbase、v0.2.0 冻结 CoACD、packed Cycles 场景及其来源/许可。基础构建不需要 Blender，不调用 CoACD。运动学、运动契约、sim_visual、URDF/manifest 与 SDF 三角网格在用户机器生成；SDF cook 属后续 SAPIEN 加载阶段。

resolver 的根优先级为环境变量、检出 `build/resources/`、下游工程 `.xbox_gamepad_physics/resources/`；独立目录用 `--resources`。显式环境根也要 prepare。输入保存在 `<root>/inputs/`，输入 receipt 与输出 `.stamps/` 分离；离线通过 `--archive ... --offline` 导入。`_resource_lock.json` 指向输入 zip。缺失/过期节点及下游本地重建，不写 HOME 或 site-packages。

打包器只读白名单，不运行构建；Release 附 wheel、输入 zip、SHA256SUMS，不上 PyPI。自有代码 MIT，第三方模型 CC BY 4.0、packed HDR CC0 及其他代码许可各自保留。用户 `[build]` 不含 coacd；维护者 `[maintainer]` 才声明它，显式 `scripts/regenerate_collision_coacd.py --output <review-output> --archive <new-archive-dir>` 先归档旧快照，再生成待审结果。meshbase 更新同样先归档；不自动采用新凸包。

MuJoCo 历史树 `src/xbox_gamepad_physics/resource_data/mujoco/` 留在原地，不进运行时 DAG、wheel 或输入 zip，不恢复旧生成器。

**Layering:**
- `references/*.json` — evidence records (source, units, applicability, derivation, uncertainty). Builders read physical parameters from here (notably `references/full_controls.json`, `references/catalog.json`). `specs/` holds target specs and explicit unknowns; `assets/asset_index.json` is the source of truth for candidate/admission status.
- `common/xbox_one_s/` (in the resource root) — backend-neutral visual (glTF + 2K textures) and the **motion contract** (`motion/full_controls.json`: joint topology, per-axis ranges, radial constraints, signal bindings). Both backends and the signal controller read this one contract; backend manifests do not duplicate motion limits.
- `collision` 读取冻结 CoACD，并从 meshbase 本地准备逐壳 SDF OBJ，输出路径保持不变；只有 RoboTwin `full_controls` 依赖此节点。
- `<backend>/<profile>/manifest.json` (in the resource root) — format documented in `schemas/backend_manifest.schema.json` (documentation, not enforced at runtime); declares readiness flags and required files. v0.3.0 profiles 为 RoboTwin `full_controls`（20 个活动关节）与 `left_stick`。
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

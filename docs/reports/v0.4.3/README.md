# v0.4.3 发布与安装包验收

负责人已批准发布 `d5bf88e` 的 RoboTwin 按物理步长选择求解迭代策略（基于 `af2c7b7` 诊断提交）。本轮在 `release/v0.4.3` 准备发布，尚未推送、打 tag 或创建 Release。

主 wheel 为 `xbox_gamepad_physics-0.4.3-py3-none-any.whl`，SHA256 为 `1d98b767afcc316a545a9bd6119a76819951c6eebff7cd8016649a3654ef9a77`；配套输入包为 `xbox_gamepad_physics-resources-0.4.3.zip`。SAPIEN a3 wheel、源码重建包、`PUBLIC_ENGINE.json`、`REPORT.md` 和 `verification-summary.json` 从 [v0.4.2 Release](https://github.com/5o1/xbox_gamepad_physics/releases/tag/v0.4.2) 原样复用，下载后逐一核对该 Release 的 SHA256。后两份为历史引擎验证，不能当作本次手柄验收。`VALIDATION.json` 是本次安装包摘要。

## 本次变化与保留边界

- RoboTwin 读取调用方 scene 的物理步长：1 ms 选择 10/1，4 ms 选择 64/16；取不小于实际步长的最小已验证点。中间步长不因该选择而自动获得验收资格。超过 4 ms 使用 64/16 并发出 warning。显式 `solver_iterations` 优先，`pad.solver_policy` 可读回。加载后修改步长需要调用方重新配置迭代。
- 按键、摇杆的物性、信号阈值和归一化、MuJoCo/Isaac 后端实现、SAPIEN a3 引擎、原始 One S 几何和 2K 贴图不改。MuJoCo 保留固定 fork `3.16.0+concon.sdf3689.2`；Isaac 继续 Preview。
- 修复 `9851f97` 重构引入的源码 checkout 中 teleop gateway 导入错误；v0.4.2 wheel 的过时残留掩盖了该缺陷。`--ball-case` 现在和 server 一样是自由字符串，只透传，由需要球体实验时的 server/`BallProbe` 校验；帮助文本明确仅 checkout 可用。三个手指诊断模块的悬空 `finger_validate` 引用改为复用记录模块的通用有限值检查，没有把 harness 带回 `src/`。
- v0.4.2 wheel 误带了 17 个过时的构建残留文件，v0.4.3 已移除；这些文件不属于公开 API，逐项清单见下节及 [打包审核](packaging_audit.json)。

## 干净构建与残留清单

在全新的临时源码目录执行 `python3 -m build --wheel --no-isolation --outdir OUTPUT`；没有复制 setuptools 的 `build/` 或 `*.egg-info` 缓存，也没有删除仓库既有 handoff、experiments、resources。审核按 `pyproject.toml` 的包发现和 package-data 规则及 `setup.py` 实际镜像推算应有清单：包文件 161/161、dist-info 6/6、总计 167/167，无缺失、无多余；161 个包文件全部与最终源码字节一致，许可证字节一致。

以下 17 项均不在当前源码和新 wheel 中：

1. `xbox_gamepad_physics/acceptance/__init__.py`
2. `xbox_gamepad_physics/acceptance/cases.py`
3. `xbox_gamepad_physics/acceptance/performance.py`
4. `xbox_gamepad_physics/acceptance/records.py`
5. `xbox_gamepad_physics/acceptance/runner.py`
6. `xbox_gamepad_physics/acceptance/scoring.py`
7. `xbox_gamepad_physics/acceptance/views.py`
8. `xbox_gamepad_physics/build_data/acceptance/ruling20_sdf303_v1.json`
9. `xbox_gamepad_physics/build_data/specs/interactive_acceptance.json`
10. `xbox_gamepad_physics/isaac/diagnostics.py`
11. `xbox_gamepad_physics/isaac/press.py`
12. `xbox_gamepad_physics/mujoco/_manifest.py`
13. `xbox_gamepad_physics/mujoco/acceptance.py`
14. `xbox_gamepad_physics/mujoco/visual.py`
15. `xbox_gamepad_physics/teleop/ball_probe.py`
16. `xbox_gamepad_physics/teleop/finger_validate.py`
17. `xbox_gamepad_physics/teleop/validate.py`

AST 扫描 `src/`、`tests/`、`examples/`、`scripts/`，解析相对导入后未发现这些旧模块的真实引用。测试中的顶层 `teleop.ball_probe` 指向 checkout 的兼容包装，再转到 `tests.acceptance.robotwin.probe`，与已移除的 `xbox_gamepad_physics.teleop.ball_probe` 不同。四项新回归覆盖实际子进程 `gateway --help`、残留导入扫描、相对导入解析以及通用有限值检查。

Isaac 仅做源码身份核对：新 wheel 的 11 个 Isaac 模块逐字节等于 **v0.4.2 Git tag 的源码**，不是与含残留的旧 wheel 比较；本轮没有运行 Isaac。Python3.11/Lab2.3.2/Sim5.1/兼容 torch 仍由用户提供，USD authoring 仍需先启动 AppLauncher。

输入 zip 的 52 个 payload 和整个 ZIP 文件均与 v0.4.2 相同，SHA256 同为 `96dc0a6fd4a936dc82912ce331d2c4493e87cc02105332f4c4eeffa236f659ce`；没有重新生成几何、CoACD 或纹理。[资源逐项比较](resources_comparison.json)记录全部 payload SHA。生成的 `_resource_lock.json` 已匹配 0.4.3 版本/下载 URL 和实际归档 SHA。

## Fresh-install：仅指定计算节点 CPU

两个新隔离环境分别位于 `$NODE_ENVS/robotwin-release-v043` 和 `$NODE_ENVS/mujoco-release-v043`，运行镜像为 `$NODE_ROOT`（目录名带 `-v043`）。不继承 site-packages，不覆盖共享环境，不连接采集台。执行 CPU affinity `[8]`，`OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1`，`DISPLAY`、`CUDA_VISIBLE_DEVICES` 为空；没有 renderer。SAPIEN 的 Vulkan ICD 导入提示仍出现，本轮实际 scene 均为 `PhysxCpuSystem`。

QA 镜像只提供 tests/references，`PYTHONPATH=$NODE_ROOT/qa`，没有 checkout `src`。实际导入来自新环境 site-packages；安装后的 161 个包文件逐项与最终 wheel 核对，没有差异。RoboTwin 使用 Python 3.10.12 / SAPIEN `3.0.3+concon.physx5.6.1.a3`。

先安装经 v0.4.2 Release SHA 校验的 a3 和全部 `[build]` 依赖，再用 `pip install --no-index --no-deps "WHEEL[build,robotwin]"` 复用精确已安装依赖；`pip check` 通过。这个安装顺序避开 resolver 再次下载同一已验证 a3，不修改 wheel 的 extras、依赖 URL 或 SHA。安装后的 `gateway --help` 退出码 0。

资源通过安装包的 `build-resources --archive ... --offline` 正常 DAG 从输入 ZIP 重新生成，未复用旧产物。RoboTwin 公开 SDF 加载后有 20 个活动关节，质量 `0.2799999951967038` kg。原生 12 N 加载、读取公开信号、反解并序列化的信号为 0.9880152356345206，解码误差 0 m，卸载后为 0；未直接改写 q/qvel 或 drive target。与获批资源的 motion/URDF 物理内容比较通过。

| 协议 | T1 | T2 | 圆锥 | T3v2 | T4 | 失败 | 原通过项退化 | 迭代读回 | 耗时 s |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| 1 ms | 6/6 | 12/12 | 6/6 | 10/10 | 25/26 | Pair | 无 | 60/60 为 10/1 | 67.20 |
| 4 ms | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | Pair/L3/R3 | 无 | 60/60 为 64/16 | 32.41 |

两组均用正式入口 `tests.acceptance.robotwin.timestep_suite`、公开默认加载路径、`solver_override=null`；完整执行全部 26 项 T4。实际步长为 0.0010000000474974513 / 0.004000000189989805 s，`solver_policy.source=timestep_policy`，`accepted`、`readbacks_match` 均为 true。分数及失败集合与 `d5bf88e` 正式复跑一致。[安装包详细记录](robotwin_wheel_validation.json)包含 120 条策略/原生读回、每套通过集合、protocol/result SHA 和公开加载记录。

MuJoCo 在独立新环境使用 Python 3.10.12 / 固定 fork `3.16.0+concon.sdf3689.2`，先安装经 SHA 校验的引擎及依赖，再以 `--no-index --no-deps` 安装最终主 wheel 的 `[build,mujoco]` 组合，`pip check` 通过。公开 SDF 加载有 20 个关节，以 0.0005 s 原生步长步进 4100 步，q/qvel 全部有限；在 right click 原生广义坐标施加 12 N 外力、再卸载，公开信号 1.0 → 0.0，反解误差 8.62647311732339e-09 m，序列化往返一致。未写 q/qvel 或 drive target，没有跑完整冻结接触套件。[MuJoCo 安装包记录](mujoco_wheel_validation.json)明确其冒烟范围。

[环境版本清单](environment.json)记录两个隔离环境的解释器/全部 distribution 版本及 `include_system_site_packages=false`；[原始证据 SHA](evidence_sha256.json)记录节点逐步轨迹、生成资源、执行的 QA 源码和输入制品。已执行的 acceptance 源码与本地最终文件核对相同；大轨迹仍只在节点保存。

## 性能事实与已知限制

[前轮按步长诊断](../2026-11-10-timestep-solver/README.md)是单个指定节点、原采集台场景的离线基准，本次没有连接采集台或重跑性能筛样。1 ms/10/1、始终唤醒的冻结接触完整步：中位数 389.7 µs、p95 412.6 µs，**9/9000 步超过 800 µs，最大 1222.5 µs**。严格逐步上限未满足，尖峰原因未定位；不能把中位数/p95 当作端到端硬实时保证，测量也不含渲染、视频及输入传输。

Pair 等冻结失败、额外 overdrive-plus-press 短缺、严格瞬态/批量角度界限、任意负载接触、真实硬件标定及 RL 资格均未由本轮建立。CPU 物理可配 GPU 渲染，但本轮没有渲染；GPU 物理 click 预压仍不支持。MuJoCo 历史 T4 25/26、Isaac 历史 T4 23/26 见 [v0.4.2 报告](../v0.4.2/README.md)，本轮没有复跑它们的完整验收。

## Fast 回归与跳过项

`python3 scripts/run_regression.py fast` 退出码 0：unittest 337 项（327 通过、10 跳过），MuJoCo pytest 30 通过，Node 35 通过。为实际运行新增 gateway CLI 子进程检查，在本机项目环境直连补装了可选 aiohttp；既有 gateway 进程/视频测试因此也执行通过，没有 mock 或新增 skip。[完整跳过清单与原因](regression.json)：

| 测试 | 跳过原因 |
|---|---|
| `acceptance.robotwin.test_candidate_mapping.NativeTest.test_a1_rejects_native_d6_even_with_same_setter_name` | requires private a1 resource copy |
| `acceptance.robotwin.test_candidate_mapping.NativeTest.test_native_implicit_viscous_mapping_is_not_double_counted` | requires private resource copy |
| `acceptance.robotwin.test_candidate_mapping.NativeTest.test_native_new_and_legacy_resources` | requires private a1 resource copy |
| `infrastructure.test_common_runtime.GamepadStateTests.test_numeric_action_mask_preserves_gradients_on_active_channels` | Torch is an optional training dependency |
| `infrastructure.test_muble_adapter.MuBlEPoseExportTest.test_public_mujoco_handle_exports_muble_trace` | Historical resource tree is retained for provenance only. |
| `infrastructure.test_scene_injection.SceneInjectionTest.test_existing_scene_is_preserved` | SAPIEN is not installed |
| `test_backend_torch_signals.TorchSignalsTest.test_all_discontinuities_and_partial_asymmetric_mapping` | Optional torch is not installed |
| `test_backend_torch_signals.TorchSignalsTest.test_both_cpu_dtypes_match_oracle_and_preserve_pair` | Optional torch is not installed |
| `test_backend_torch_signals.TorchSignalsTest.test_masks_and_invalid_inputs` | Optional torch is not installed |
| `test_run_robotwin.SapienSmokeTest.test_smoke_twenty_steps_passes` | SAPIEN is an optional backend dependency |

以上跳过不算通过。新增回归均已实际执行；wheel 清单/许可/Isaac tag 字节审核另由正式脚本通过。所有提交文件在提交前运行 `python3 build/handoff/scan_staged.py`，结果为 0 hits；私有句柄、节点原始日志和大型轨迹不提交。

## 复现

在指定节点从已装包执行，示例中的变量由本地私有句柄配置：

```bash
export DISPLAY='' CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$NODE_ROOT/qa"
cd "$NODE_ROOT/qa"
taskset -c 8 "$NODE_ENVS/robotwin-release-v043/bin/python" -m xbox_gamepad_physics build-resources \
  --backend robotwin --archive "$NODE_ROOT/artifacts/xbox_gamepad_physics-resources-0.4.3.zip" \
  --resources "$NODE_ROOT/resources-robotwin" --offline
for dt in .001 .004; do
  taskset -c 8 "$NODE_ENVS/robotwin-release-v043/bin/python" \
    -m tests.acceptance.robotwin.timestep_suite --timestep "$dt" \
    --resources "$NODE_ROOT/resources-robotwin" --output "$NODE_ROOT/output/recheck-$dt"
done
```

新输出目录必须不存在；不要覆盖冻结证据。大型逐步轨迹与资源保留在 `$NODE_ROOT`，摘要和 SHA 收据单独归档。

## 我自行决定的选择

- 使用全新临时源码目录构建，保留仓库所有既有构建工作和原始数据。
- 发布附带原 a3 的 `REPORT.md` / `verification-summary.json`，明确其历史引擎验证范围；本版摘要用新的 `VALIDATION.json`。
- 复用现有 RoboTwin 公开加载/信号检查与正式 timestep suite；MuJoCo 仅补所要求的公开接口冒烟，不扩大到全套冻结验收。
- 三个诊断模块共用现有 record 层的通用有限值函数；gateway 只透传实验选项，不复制 harness 清单。
- 节点优先使用已有依赖缓存；下载均直连并校验锁定引擎 SHA，未用代理。隔离环境不继承共享 site-packages。

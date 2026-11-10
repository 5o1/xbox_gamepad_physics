# RoboTwin 按物理步长选择迭代：正式默认路径验收

方案 (a) 已实现。完整默认路径结果与前轮诊断一致，两组原通过项均无退化。**严格的“每一个测量步 ≤800 µs”性能要求未满足**：冻结接触完整步中位数 389.7 µs、p95 412.6 µs，但有 9/9000 步超限，最大 1222.5 µs。没有丢弃尖峰或通过调整物性追求过关。

本轮从 `perf/station-rtf` 的 `af2c7b7` 创建 `feat/robotwin-timestep-solver-policy`，只做本地提交，不推送、不发布或修改版本。仅在指定计算节点离线运行 CPU 仿真；镜像根目录为 `$NODE_ROOT`，目录名带 `-dt` 后缀，资源是本轮普通文件副本，原始资源和共享环境保持不变。没有连接采集台或物理硬件。

## 选择规则与实现

`references/full_controls.json` 的 `backend_options.robotwin.solver_iterations` 现在包含 `validated_points`，两个点分别给出 `timestep_s`、`position`、`velocity` 三个 Parameter：

| 已验证点 | 位置/速度迭代 | 证据 |
|---|---|---|
| 0.001 s | 10/1 | [1 ms 部署诊断](../2026-11-10-station-rtf/click_switch.md)，本轮正式入口复跑 |
| 0.004 s | 64/16 | [原双引擎 View 对照](../v0.4.2/robotwin_validation.json)，本轮正式入口复跑 |

各 Parameter 均有单位、source、locator、applicability、derivation、category 和不确定性原因。数值策略不解释为机械参数；力、阻尼、刚度、预压、限位及信号阈值不改。public references、packaged build_data 和版本化策略记录同步，原固定策略另存于 history。

加载器读取调用方 `scene.timestep`，选择不小于实际步长的最小已验证点：0.5 ms 用 10/1，2 ms 用 64/16。超过 4 ms 时用 64/16 并发出明确的 `RuntimeWarning`，继续使用；中间步长的选择不代表已验收。显式 `load_into_scene(..., solver_iterations=(p, v))` 优先。旧固定迭代资源保留兼容。

在当前 a3 环境检查了 `scene.timestep`、`get_timestep()` 的实现及原生读回，两者一致。[SAPIEN 3.0 原始场景实现](https://sapien-sim.github.io/docs/_modules/sapien/wrapper/scene.html)也定义了该接口。单精度读回需要 1e-7 相对容差处理边界相等；本次 1 ms/4 ms 的实际值见下表。`pad.solver_policy` 是不可变的加载时记录，包含实际读回、选中点、迭代及来源。加载后改变步长，由调用方负责重选/配置迭代。

高迭代可能通过接触同岛和岛合批扩散到手与机器人，依据及源码链接见[后端文档](../../robotwin_backend.md#按物理步长选择迭代2026-11-10)。本方案不引入限位切换，也不依赖休眠。

## 正式验收结果

入口为 `python3 -m tests.acceptance.robotwin.timestep_suite`。公共资源 DAG 在本轮资源副本中离线构建，随后使用公共资源解析和默认加载器，不传求解器 override。T4 全部 26 项均执行；摘要核对完整通过集合、原通过项退化和确切失败项，不能用总数抵消换项。

环境为 Python 3.10.12、SAPIEN `3.0.3+concon.physx5.6.1.a3`、xbox-gamepad-physics 0.4.2。CPU affinity 为 `[8]`，CPU TGS、`cpu_workers=0`，OMP/OpenBLAS/MKL 各 1，`DISPLAY` 和 `CUDA_VISIBLE_DEVICES` 为空，无 renderer。SAPIEN 导入输出 Vulkan ICD 提示，但两组实际 scene 均为 CPU-only，没有创建渲染系统。

| 协议 | T1 | T2 | 圆锥 | T3v2 | T4 | T4 失败 | 原通过项退化 | 墙钟 s |
|---|---:|---:|---:|---:|---:|---|---|---:|
| 1 ms | 6/6 | 12/12 | 6/6 | 10/10 | 25/26 | Pair | 无 | 65.67 |
| 4 ms | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | Pair/L3/R3 | 无 | 32.42 |

| 协议 | 实际步长 s | 每组原生迭代读回 | 选中点 s | 记录数 | 正式入口退出码 |
|---|---:|---|---:|---:|---:|
| 1 ms | 0.0010000000474974513 | 10/1 | 0.001 | 60/60 | 0 |
| 4 ms | 0.004000000189989805 | 64/16 | 0.004 | 60/60 | 0 |

全部记录的 `solver_policy.source` 为 `timestep_policy`，`solver_override` 为 null，`readbacks_match`、`accepted` 均为 true。Pair 仍是已知失败；上述结果不表示任意负载的接触就绪、实物标定或 RL 验收。

4 ms 冻结协议文件原字节保留。1 ms 显式传递时钟，保留原力学和判据：圆锥总 2000 步、加载 1000；T3v2 各阶段 1000/500/1000/500/500；T4 末 500 个 hold 样本、返中计时按 dt、阻塞 100 个步间隔、总预算 40000 步（40 s）。T1/T2 按秒采样，T1 保留两端点，共 6001 样本。球体仍是 4 mm/50 g。共享 runner/scorer 只把时间常量换算为协议 dt，在 4 ms 下保持原行为；历史 26 病例轨迹与评分比对及换算表单测通过。

重建产物的 joint_dynamics、contact_material、motion_contract、collision_variants、其余 backend_options 与原资源相同；公共 motion 文件、碰撞网格字节相同；URDF 所有物理 XML 元素相同，只有使用说明可能变化。选择的 calibration 为 `default:full_controls`，所有 override 映射为空。

## 始终唤醒的冻结接触性能

复用原 AQ 采集台场景基准、原冻结 L3 接触姿态及完整双臂/双手，使用本轮默认资源，不传 iterations、sleep-threshold 或 batch override。`--always-awake` 每个完整 backend step 前调用 root.wake_up，逐步读取唤醒后和步进后的 sleeping；唤醒及读回计入完整步。每次 backend call 为一个 1 ms 物理步。没有连接采集台。

3 次重复各测 3000 步。每次含准备/暖机共 5200 次调用，三组睡眠计数均为 0；实际步长都是 0.0010000000474974513 s，手柄及左右机器人均读回 10/1。冻结接触每次均为 3 对，平均/最大均为 25 个接触点。原生 sleep threshold 未改。

单位均为 µs/步。汇总的中位数/p95 是三次统计量的中位数，最大值和超限数包含所有 9000 个测量步。

| 重复 | 原生中位数 / p95 | 完整步中位数 / p95 | 完整步最大 | 完整步 >800 µs |
|---|---|---|---:|---:|
| 1 | 338.6 / 462.0 | 401.6 / 559.9 | 1222.5 | 9/3000 |
| 2 | 335.0 / 355.0 | 389.0 / 412.2 | 445.5 | 0/3000 |
| 3 | 335.3 / 355.0 | 389.7 / 412.6 | 468.7 | 0/3000 |
| 汇总 | 335.3 / 355.0 | 389.7 / 412.6 | 1222.5 | 9/9000 |

中位数和 p95 满足 800 µs；严格逐步上限未满足。尖峰原因未定位，不将其归因于任何未经检验的候选原因。只完成所要求的一组基准，没有重测筛样、调整物性或扩展调度诊断。测量范围不含循环外稀疏诊断、渲染、视频或输入传输，不能当作端到端硬实时保证。

## 本地测试与跳过项

使用项目 Python 环境执行 `python3 scripts/run_regression.py fast`，退出码 0：unittest 333 项（316 通过、17 跳过），MuJoCo pytest 30 通过，Node 35 通过。新增单元测试覆盖策略解析、精确命中、较小步长、两点之间、float32 边界、超范围 warning、显式覆盖、旧资源兼容、公共 handle，以及换算表和 runner/scorer 时间行为。没有修改 MuJoCo 或 Isaac 后端。

17 个跳过项如下；这些跳过不能被本轮节点 CPU 验收冒充补全：

| 测试（省略共同 tests 前缀） | 原因 |
|---|---|
| acceptance.robotwin.test_candidate_mapping.NativeTest.test_a1_rejects_native_d6_even_with_same_setter_name | 缺少私有 a1 资源副本 |
| acceptance.robotwin.test_candidate_mapping.NativeTest.test_native_implicit_viscous_mapping_is_not_double_counted | 缺少专用资源副本 |
| acceptance.robotwin.test_candidate_mapping.NativeTest.test_native_new_and_legacy_resources | 缺少私有 a1 资源副本 |
| infrastructure.test_common_runtime.GamepadStateTests.test_numeric_action_mask_preserves_gradients_on_active_channels | 未安装可选 torch |
| infrastructure.test_muble_adapter.MuBlEPoseExportTest.test_public_mujoco_handle_exports_muble_trace | 历史资源树仅保留溯源 |
| infrastructure.test_scene_injection.SceneInjectionTest.test_existing_scene_is_preserved | 本地未安装 SAPIEN |
| test_backend_torch_signals.TorchSignalsTest.test_all_discontinuities_and_partial_asymmetric_mapping | 未安装可选 torch |
| test_backend_torch_signals.TorchSignalsTest.test_both_cpu_dtypes_match_oracle_and_preserve_pair | 未安装可选 torch |
| test_backend_torch_signals.TorchSignalsTest.test_masks_and_invalid_inputs | 未安装可选 torch |
| test_run_robotwin.SapienSmokeTest.test_smoke_twenty_steps_passes | 本地未安装可选 SAPIEN |
| test_teleop_shutdown.GatewayShutdownTest.test_detached_gateway_logs_to_file_and_checked_cleanup | 缺少 aiohttp 或 gateway 测试解释器 |
| test_teleop_shutdown.GatewayShutdownTest.test_idle_watchdog_exits_with_broken_stdout | 同上 |
| test_teleop_shutdown.GatewayShutdownTest.test_shutdown_with_broken_stdout | 同上 |
| test_teleop_shutdown.GatewayShutdownTest.test_sigint_exits_with_broken_stdout | 同上 |
| test_teleop_shutdown.GatewayShutdownTest.test_sigterm_exits_with_broken_stdout | 同上 |
| test_teleop_shutdown.GatewayShutdownTest.test_stop_reason_and_stdout_errors_do_not_block_shutdown | 同上 |
| test_teleop_slow_clients.GatewaySlowClientsTest.test_real_gateway_slow_client_and_cancellation_contract | 缺少 aiohttp 和 FFmpeg 的 gateway 视频测试依赖 |

初次定向测试使用了缺少 numpy 的系统解释器；切换到已有项目环境后通过，未安装或覆盖节点环境。一次辅助物理对比脚本错误地索引不存在的 manifest 字段，修正为对实际公共 motion 文件和碰撞网格比较后通过；没有改动验收轨迹、评分或模拟参数。

## 复现与证据

[summary.json](summary.json)保留 120 条实际策略/迭代读回、每套完整通过集合、性能三次统计、睡眠计数及默认 calibration。[evidence_sha256.json](evidence_sha256.json)记录节点执行的源码、输入、产物和全部原始证据 SHA256。节点执行的 runtime/acceptance 源码已与提交前本地文件逐项核对，完全一致。提交前 `python3 build/handoff/scan_staged.py` 必须为 0 hits。

大型逐步轨迹保留在 `$NODE_ROOT/code/build/experiments/timestep_solver/`；本机 `build/experiments/timestep_solver/` 只保留小摘要、日志、计时 NPZ、SHA256 和只读连接句柄。私有句柄不提交，报告中没有节点主机名、用户名或绝对私有路径。

以下变量在节点上按只读句柄设置；`NODE_PYTHON` 指向 `$NODE_ENVS` 中的既有 a3 解释器：

```bash
export DISPLAY='' CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$NODE_ROOT/resources"
export PYTHONPATH="$NODE_ROOT/code:$NODE_ROOT/code/src:$NODE_ROOT/support/src"
cd "$NODE_ROOT/support"

taskset -c 8 "$NODE_PYTHON" -m tests.acceptance.robotwin.timestep_suite \
  --timestep .001 --resources "$NODE_ROOT/resources" \
  --output "$NODE_ROOT/code/build/acceptance-1ms-new"
taskset -c 8 "$NODE_PYTHON" -m tests.acceptance.robotwin.timestep_suite \
  --timestep .004 --resources "$NODE_ROOT/resources" \
  --output "$NODE_ROOT/code/build/acceptance-4ms-new"

taskset -c 8 "$NODE_PYTHON" \
  "$NODE_ROOT/code/experiments/robotwin/station_rtf/benchmark.py" \
  --aq-probe "$NODE_ROOT/support/reports/2026-11-09-realtime-input-lag/engine_probe.py" \
  --condition contact --always-awake --steps 3000 --repetitions 3 \
  --output "$NODE_ROOT/code/build/contact-1ms-new"
```

基准还需要设置 `GAMEPAD_VLA_WORKSPACE` 为指定节点原诊断使用的只读资产工作区；沿用本机忽略的 handles 记录，不改共享资源。公共资源副本已用 `prepare_resources(backends=("robotwin",), offline=True)` 重建；复跑无需改 manifest 或注入 override。

## 我自行决定的选择

- 使用 `validated_points` 加三个 Parameter 的结构；保留旧固定格式和版本化历史。
- 使用 SAPIEN 原生 `scene.timestep`，以 1e-7 相对容差处理 float32 的精确边界；不增加逐步监控或状态门槛。
- 将时间换算作为显式参数传递到现有验收函数，不沿用实验中的源码替换；复用原 T4 runner/scorer，只改按步长换算。
- 将每病例策略快照和原生读回写入摘要；完整比较失败集合及原通过项，防止分数相同掩盖退化。
- 基准增加 `--always-awake`、逐步睡眠读回、最大值和超限数；完整保留性能未达项。
- 为两个仍索引旧固定字段的历史诊断入口补最小兼容，显式覆盖同时支持新旧资源格式；默认路径分支不变。
- 两个 agent 分工：验收入口实现与复核；策略、资源、节点运行和交付由主线程完成。没有增加依赖。

完整改动文件清单见[changed_files.txt](changed_files.txt)。

# 采集台 CPU TGS 实时性诊断（2026-11-10）

**本轮测试范围内没有可行方案。** 指定的 12 组迭代扫描和 batch size 诊断均完成。最优的无新增上游退化组合是 **64/1 + 手柄实例 sleep threshold 0.5 J/kg + articulation batch size 1**：有接触的完整步中位数 **1126.7 µs**、p95 **1142.5 µs**，三次中位数范围 **1109.6–1130.1 µs**；原生步中位数也有 **1056.9 µs**，因此无论按 native 还是完整步，都超过 800 µs。按完整步中位数换算容量约 **0.89 RTF**，达不到 1 kHz 实时要求。

保留 preload、仅提高实例休眠阈值能解决无接触部分：64/16 下静态完整步 **262.7 µs**，100 Hz 双臂输入 **454.9 µs / p95 581.2 µs**，完整上游验收 **6/6、12/12、6/6、10/10、23/26**，原通过项无新增退化；接触时仍约 **1748.0 µs**。没有采用任何默认参数变更。

本轮从 `main` 的 `d05786cef6b15c4127b106622d45e6301a2c2d3f` 创建 `perf/station-rtf`。所有候选均为进程内 override，默认 profile、`references/`、默认 options 和共享环境未更改。只在指定计算节点执行 CPU 离线仿真；没有连接采集台、硬件或输入服务，没有 push、tag、release 或构建 SAPIEN。

## 基准与复现门

使用 AQ 的原始 `engine_probe.py`（SHA256 `a359b8e163deaa70b1cd91732b2843808dbe8e8ad4922ebf92fb3cf09241932b`）和维护资源副本，原样调用采集后端：双 AR5，各 7 DOF；双 G20，各 21 DOF；固定根 full_controls / SDF / robotwin 手柄；两边 articulation 各 28 DOF。使用 `dexhand_deploy` 的 `855081878c35d663b7774090cdcd3f4117d4c85a` 源码镜像；另一个只读 `dexhand_workstation` checkout 当时 HEAD 为 `d238efc`，因此没有把它误称为 `8550818` 或混入本次对照。

新环境为已有 a3 + 0.4.2，旧对照为已有独立 stock 3.0.3 + 0.4.1；没有在共享环境中安装、降级或覆盖包。处理器 Intel Xeon Platinum 8374C；CPU affinity 固定 `[8]`，PhysX `cpu_workers=0`（物理在调用线程执行），OMP/OpenBLAS/MKL 均 1，`CUDA_VISIBLE_DEVICES=''`、`DISPLAY=''`。SDF 构建线程不计入稳态计时。共享节点没有独占/锁频，重复范围反映本次条件下的波动。

每组独立建场景，暖机 500 步，再逐步测量 3,000 步，重复 3 次。表中中位数和 p95 分别是三次统计量的中位数，方括号是三次中位数的最小/最大值；完整步 p95 范围单独列出。完整的每次分布在原始摘要中。**全部耗时表单位为 µs/步，门槛为 800 µs。**

`native` 是 `scene.step()`；完整步是 `backend.step(0.001)`，包括控制数学、目标写入、被动力、接触查询和有限状态检查。每 100 步的独立诊断取样不在逐步完整步计时内；AQ 的原始累计 `total_us` 另包含这些诊断，保存在原始 JSON。容量 RTF 仅代表这个无渲染、无录制的 CPU 基准，不能替代采集台端到端 RTF。

无接触分静态和墙钟 100 Hz 合成双臂目标两组，沿用 AQ 的 `CollectionController` 最新输入路径。接触沿用 AQ 的冻结 L3 `hold/push` 姿态：200 ms 保持、1 s 插值、500 ms 稳态准备，左手手指压在手柄上，使用 station 的手增益/惯量适配；不是另一套 legacy 力峰值实验。原始 L3 输入及 SHA256 与源码快照一起归档。所有组读取实际 solver、休眠和接触状态；不通过删机器人、删 preload、删圆锥或改接触 offset 加速。

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `baseline-old-static` | 287.7 / 304.1 [287.6, 287.7] | 323.6 / 343.6 [323.1, 324.5] | [341.3, 346.1] | [False, False, False] | [0.0, 0.0, 0.0] |
| `baseline-old-active` | 315.2 / 343.1 [314.7, 315.5] | 529.6 / 686.5 [525.1, 529.9] | [684.4, 696.7] | [False, False, False] | [0.0, 0.0, 0.0] |
| `baseline-old-contact` | 325.0 / 344.6 [324.9, 325.3] | 381.6 / 404.8 [379.9, 384.8] | [395.3, 408.0] | [False, False, False] | [3.0, 3.0, 3.0] |
| `baseline-new-static` | 1479.4 / 1502.4 [1479.0, 1480.0] | 1518.6 / 1550.5 [1518.1, 1519.0] | [1535.5, 1551.0] | [False, False, False] | [0.0, 0.0, 0.0] |
| `baseline-new-active` | 1504.9 / 1561.4 [1502.5, 1507.3] | 1720.7 / 1907.4 [1717.2, 1723.1] | [1901.1, 1907.9] | [False, False, False] | [0.0, 0.0, 0.0] |
| `baseline-new-contact` | 1680.2 / 1700.7 [1675.4, 1683.2] | 1739.7 / 1766.7 [1736.3, 1750.9] | [1766.2, 1773.3] | [False, False, False] | [3.0, 3.0, 3.0] |


复现门通过：静态原生新/旧为 **1479.4 / 287.7 µs**，与 AQ 的约 1478 / 290 µs 一致；冻结接触为 **1680.2 / 325.0 µs**，均为 3 个接触对。默认完整上游验收也复现 6/12/6/10/23，因此继续后续实验。旧模型仅作对照，不作为合规优化候选。

## 休眠诊断

### 源版本与适用范围

本地 `SAPIEN/concon/public_a3/source_bundle/INPUTS.json:7-13` 记录 SAPIEN commit `731622eac5b140b320076c8a1b6eb4b553c3ccd4`、PhysX tag `107.3-physx-5.6.1` / commit `5ca9f472105a90d70d957c243cb0ef36fe251a9f`；本次还直连 NVIDIA GitHub tag API 核对了同一 commit。`source_bundle/patches/PhysX.patch` 仅修改构建配置与 convex cooking，未修改下面的休眠/求解文件。因此以下固定 PhysX commit 的源码适用于 a3 的这段机制。历史 `physx_drive_probe/source/` 的旧 PhysX 源码不混作 5.6.1 依据。

SAPIEN 源路径均相对于只读兄弟 checkout `SAPIEN/`，本仓库路径相对于当前 checkout。

### 已由源码确认的处理链

#### qf 是持久外力；写入唤醒不等于每帧重置唤醒计数器

本仓库 `src/xbox_gamepad_physics/robotwin/mappings.py:7-17` 在已有 qf 上叠加 preload，再调用一次 `set_qf`；loader 的调用点为 `loader.py:548-552`。SAPIEN `src/physx/articulation.cpp:325-332` 将向量写入 `cache.jointForce`，调用 `applyCache(eFORCE)`。PhysX 的 [jointForce 定义，L262-L269](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include/PxArticulationReducedCoordinate.h#L262-L269) 明确该外力逐帧持续，直到调用者改写。

写 cache 时，[DyFeatherstoneInverseDynamic.cpp L330-L339](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneInverseDynamic.cpp#L330-L339) 检查非零 jointForce 并设 `shouldWake`；[NpArticulationReducedCoordinate.cpp L169-L188](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/physx/src/NpArticulationReducedCoordinate.cpp#L169-L188) 将其传给 `wakeUpInternal`。后者在 [L1134-L1158](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/physx/src/NpArticulationReducedCoordinate.cpp#L1134-L1158) 按 `autowake` 更新计数器并唤醒。

**这一分支发生于写入 cache 时。没有在所核对的 CPU 每帧路径中找到“只要 qf 非零就每步重新调用 `setWakeCounter`”的分支。** API 头文件 [L464-L475](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include/PxArticulationReducedCoordinate.h#L464-L475) 把非零 joint/link force 列为必醒条件，但不能单凭这句文档推断“持久 qf 永久禁止休眠”：本次 `0.5` override 的运行时读回同时为 `sleeping=true` 和两路 `qf≈−7.400000095 N`。

#### 每帧外力积分进入 TGS；睡眠速度并非最终 qvel

SAPIEN `src/physx/physx_system.cpp:66-87` 创建 CPU scene 时没有启用 `eENABLE_EXTERNAL_FORCES_EVERY_ITERATION_TGS`；该 flag 的 PhysX [定义及默认值为 false，PxSceneDesc.h L280-L294](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include/PxSceneDesc.h#L280-L294)。在这个全步外力模式下：

1. [DyFeatherstoneForwardDynamic.cpp L1658-L1688](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneForwardDynamic.cpp#L1658-L1688) 读取持久 qf；[L183-L188](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneForwardDynamic.cpp#L183-L188) 将 `qf − SᵀZ_internal` 写入关节广义动力学项；[L1283-L1311](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneForwardDynamic.cpp#L1283-L1311) 求加速度并积分到关节和 link 空间速度。
2. 每帧 `ArticulationData::init` 先清 `posIterMotionVelocities`，见 [DyFeatherstoneArticulation.h L469-L474](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/include/DyFeatherstoneArticulation.h#L469-L474)。它不是直接留存 unconstrained velocity 的缓冲区。
3. TGS 每个位置子步先解内部约束，再更新运动；位置循环后保存速度，之后才解 velocity iterations，见 [DyTGSDynamics.cpp L2525-L2554](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyTGSDynamics.cpp#L2525-L2554)。有接触的路径也在保存后才转入 velocity iterations，见 [L2617-L2639](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyTGSDynamics.cpp#L2617-L2639)。
4. 每个位置子步将 link 速度乘子步长累加，见 [DyFeatherstoneArticulation.cpp L1196-L1203](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L1196-L1203)；`saveVelocityTGS` 在 [L1888-L1899](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L1888-L1899) 除以总步长。因此睡眠使用的位置阶段平均速度为 `v_sleep = Σ(v_k·h)/dt`；它不是后续速度迭代结束的 qvel。

#### 计数器取各 link 的滤波能量；所有 link 都准备好才能休眠

[ScArticulationSim.cpp L462-L493](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/simulationcontroller/src/ScArticulationSim.cpp#L462-L493) 遍历全部 link，以 `getMotionVelocity` 更新各自 wake counter，并取最大值；只有最大值为零才让整个 articulation 准备休眠。这里 `getMotionVelocity` 取上述 `posIterMotionVelocities`，见 [DyFeatherstoneArticulation.cpp L936-L941](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L936-L941)。

[ScBodySim.cpp L581-L641](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/simulationcontroller/src/ScBodySim.cpp#L581-L641) 在计数器进入检查区间时，将本帧线速度、转到 body 坐标的角速度加到睡眠滤波累计量，计算 `E = 0.5·(|v_acc|² + ω_accᵀIω_acc/m)`。阈值再乘 `1 + counted_interactions`。超阈值时重置滤波、延长 counter；否则 counter 每帧减 `dt`。因此 `sleep_threshold` 的单位为质量归一能量 **J/kg = m²/s²**；它不是简单的“瞬时关节速度阈值”。

SAPIEN 工厂默认值为 `0.005f`，见 `include/sapien/physx/physx_default.h:43-47`；`src/physx/articulation.cpp:34-42` 在 articulation 创建时写入。现成 Python 接口在 `python/pybind/physx.cpp:1093-1096`，底层 setter/getter 在 `src/physx/articulation.cpp:51-52,65-66`。本次只对已创建的手柄实例调用 `art.set_sleep_threshold(0.5)`，并读取 `art.get_sleep_threshold()`、root link 的 `sleeping` 和 qf；未改全局工厂值。

### 已确认的残差机制与尚未 trace 的细节

源码允许“位置贴住限位，但位置阶段睡眠速度仍有残差”。[DyFeatherstoneArticulation.cpp L1606-L1618](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L1606-L1618) 直接夹紧 prismatic 的位置，却没有在该分支夹速度；位置阶段的睡眠累计仍用 `motionVelocities·h`。内部限位约束使用 `1/(R+cfm)`，见 [L2468](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L2468) 和 [L2658-L2668](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L2658-L2668)。对目标速度为零且单边冲量裁剪未改变结果的限位更新，[DyCpuGpuArticulation.h L399-L401 与 L446](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/shared/DyCpuGpuArticulation.h#L399-L446) 给出 `Δλ=−v/(R+cfm)`，从而 `v'=v·cfm/(R+cfm)`；非零 CFM 时不保证一次消为零。CFM 来源见 [DyFeatherstoneArticulation.cpp L4040-L4042](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L4040-L4042)。

**已确认的是上述力积分、位置/速度阶段分离、滤波与休眠判定链；未取得本次 native 子步速度、每个 link 的滤波能量和内部 counter trace。** 因此不把 CFM、某一个关节或某种微振动写成唯一根因，也不声称已数值证明某个残差恰好超过 `0.005/0.05`。提高阈值后保留 qf 仍能休眠的对照，支持“原阈值下求解运动量无法满足休眠条件”这一解释，推翻“持久非零 qf 本身构成永远无法绕过的硬性休眠禁令”。


### 本轮对照结果

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `sleep-0.05-static-r1` | 1472.8 / 1494.6 [1472.0, 1474.6] | 1511.5 / 1535.0 [1510.8, 1513.4] | [1526.8, 1553.7] | [False, False, False] | [0.0, 0.0, 0.0] |
| `sleep-0.5-static-r1` | 229.5 / 242.6 [229.3, 229.6] | 262.7 / 279.3 [262.5, 262.9] | [276.5, 281.0] | [True, True, True] | [0.0, 0.0, 0.0] |
| `sleep-0.5-active` | 247.6 / 267.4 [247.6, 250.8] | 454.9 / 581.2 [453.6, 458.1] | [569.6, 584.0] | [True, True, True] | [0.0, 0.0, 0.0] |
| `sleep-0.5-contact` | 1674.5 / 1691.3 [1673.0, 1677.1] | 1748.0 / 1768.6 [1729.7, 1751.8] | [1764.4, 1770.9] | [False, False, False] | [3.0, 3.0, 3.0] |


阈值 0.05 的 T1 为 6/6，但没有休眠及加速，未升级为完整候选。0.5 先单独 T1 6/6，再完整验收 6/12/6/10/23，T4 原通过项无新增退化；静态与 100 Hz 组均三次休眠且 qf 保留，L3 接触组三次保持唤醒。没有用强制休眠清掉 preload。

阈值 0.5 不改变清醒时的 qf、驱动或限位，但把休眠能量门提高到工厂值的 100 倍，可能提前冻结小能量运动。已测协议未退化不等于所有未覆盖的小扰动都相同。这一数值设置属于待批准候选，不是新的实测硬件参数。接触完整步仍约 1748 µs，故按顺序进入迭代扫描。

## 迭代扫描

全部 12 组均叠加手柄实例 `sleep_threshold=0.5 J/kg`，其余参数不动。逐组串行执行完整上游验收和三种基准，没有只凭总通过数掩盖旧通过项退化。较少迭代时阈值 0.5 不一定足以休眠，表中列出实际末态。

### 上游验收

沿用 `tests/acceptance/robotwin/` 现有 T1、T2、圆锥、T3v2 和 T4 入口、输入、步长与判据；验收协议中的 4 ms 保持原样，性能基准是 1 ms，二者不混淆。新增 runner 只编排和施加 override。T4 原通过集合按本轮默认 23 项逐项比较；Pair、L3、R3 是原有失败，继续保留。

| 条件 | T1 | T2 | 圆锥 | T3v2 | T4 | T4 原通过项退化 | 验收墙钟 s |
|---|---:|---:|---:|---:|---:|---|---:|
| `acceptance-default` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 32.08 |
| `sleep-0.05-t1` | 6/6 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 8.32 |
| `sleep-0.5-t1` | 6/6 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 8.36 |
| `sleep-0.5-full` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 32.04 |
| `grid-24-1-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 23.61 |
| `grid-24-2-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 23.69 |
| `grid-24-4-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 24.09 |
| `grid-32-1-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 25.13 |
| `grid-32-2-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 24.72 |
| `grid-32-4-acceptance` | 6/6 | 12/12 | 2/6 | 2/10 | 22/26 | Guide | 25.43 |
| `grid-48-1-acceptance` | 6/6 | 12/12 | 3/6 | 4/10 | 23/26 | 无 | 28.21 |
| `grid-48-2-acceptance` | 6/6 | 12/12 | 3/6 | 4/10 | 23/26 | 无 | 28.31 |
| `grid-48-4-acceptance` | 6/6 | 12/12 | 3/6 | 4/10 | 23/26 | 无 | 28.49 |
| `grid-64-1-acceptance` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 30.47 |
| `grid-64-2-acceptance` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 30.69 |
| `grid-64-4-acceptance` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 30.94 |
| `batch-1-acceptance` | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 30.43 |


### 无接触：静态

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `grid-24-1-static` | 559.8 / 572.6 [558.7, 560.1] | 595.7 / 611.1 [594.7, 595.8] | [610.3, 611.8] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-24-2-static` | 570.2 / 586.9 [569.5, 570.7] | 605.5 / 630.1 [604.9, 606.6] | [624.0, 630.3] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-24-4-static` | 590.4 / 606.2 [589.1, 590.7] | 627.2 / 646.7 [625.6, 627.3] | [646.0, 648.0] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-1-static` | 710.5 / 724.3 [710.3, 712.7] | 747.5 / 764.6 [747.2, 749.6] | [763.9, 764.8] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-2-static` | 719.4 / 733.4 [718.4, 724.7] | 755.9 / 774.1 [754.8, 762.2] | [770.7, 784.6] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-4-static` | 743.8 / 758.0 [740.6, 744.7] | 779.9 / 799.4 [776.3, 781.6] | [793.7, 799.9] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-48-1-static` | 229.4 / 241.0 [229.0, 229.5] | 263.6 / 277.9 [263.1, 263.7] | [276.8, 279.5] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-48-2-static` | 229.4 / 243.1 [228.7, 229.5] | 262.0 / 281.1 [261.0, 262.5] | [280.2, 281.7] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-48-4-static` | 228.9 / 241.7 [227.8, 229.2] | 261.5 / 278.8 [260.6, 262.8] | [275.1, 279.5] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-1-static` | 228.9 / 240.2 [228.5, 229.5] | 261.9 / 275.7 [261.4, 262.2] | [275.3, 280.2] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-2-static` | 229.3 / 242.3 [228.4, 229.7] | 262.4 / 278.5 [261.0, 262.8] | [278.4, 280.9] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-4-static` | 229.3 / 241.0 [229.2, 230.3] | 262.4 / 276.8 [262.0, 263.7] | [276.5, 278.2] | [True, True, True] | [0.0, 0.0, 0.0] |


### 无接触：双臂 100 Hz

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `grid-24-1-active` | 584.8 / 607.8 [584.0, 587.5] | 795.6 / 968.0 [794.5, 803.2] | [958.3, 977.3] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-24-2-active` | 592.7 / 614.3 [592.6, 596.6] | 800.6 / 967.2 [799.8, 806.8] | [961.3, 972.8] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-24-4-active` | 612.4 / 633.5 [610.5, 615.0] | 820.8 / 988.6 [819.7, 824.5] | [982.5, 992.4] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-1-active` | 735.4 / 766.4 [735.0, 738.5] | 947.7 / 1116.9 [945.3, 952.8] | [1107.6, 1123.8] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-2-active` | 745.8 / 773.7 [743.0, 748.5] | 954.3 / 1120.9 [948.2, 963.0] | [1117.6, 1131.6] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-32-4-active` | 763.1 / 793.8 [761.0, 764.6] | 976.5 / 1142.9 [975.4, 977.9] | [1141.4, 1147.0] | [False, False, False] | [0.0, 0.0, 0.0] |
| `grid-48-1-active` | 253.1 / 268.2 [252.7, 254.1] | 453.0 / 578.8 [452.7, 454.7] | [574.3, 590.0] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-48-2-active` | 252.8 / 267.2 [249.1, 254.1] | 452.2 / 566.7 [449.2, 453.0] | [565.6, 577.5] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-48-4-active` | 253.7 / 269.4 [252.4, 254.6] | 453.9 / 572.0 [452.6, 454.8] | [570.8, 574.3] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-1-active` | 253.1 / 270.5 [250.3, 254.2] | 455.1 / 578.1 [450.1, 455.6] | [574.3, 590.3] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-2-active` | 253.1 / 268.4 [251.0, 254.7] | 452.0 / 582.7 [451.0, 456.7] | [582.0, 590.6] | [True, True, True] | [0.0, 0.0, 0.0] |
| `grid-64-4-active` | 247.4 / 264.0 [247.3, 248.1] | 454.2 / 571.9 [452.9, 454.4] | [561.4, 575.3] | [True, True, True] | [0.0, 0.0, 0.0] |


### 有接触：冻结 L3

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `grid-24-1-contact` | 642.3 / 657.0 [640.8, 644.7] | 705.2 / 725.7 [703.8, 708.6] | [723.0, 726.5] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-24-2-contact` | 646.7 / 661.7 [642.3, 647.7] | 700.5 / 719.8 [694.8, 701.4] | [714.2, 728.5] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-24-4-contact` | 683.5 / 697.6 [683.1, 683.8] | 736.4 / 753.6 [735.9, 747.9] | [753.2, 771.1] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-32-1-contact` | 808.8 / 824.6 [808.3, 810.6] | 860.6 / 878.7 [859.4, 861.0] | [877.2, 884.1] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-32-2-contact` | 819.2 / 838.3 [817.7, 820.7] | 876.3 / 895.6 [872.7, 877.8] | [894.5, 901.2] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-32-4-contact` | 844.5 / 859.9 [843.2, 846.0] | 896.5 / 914.5 [893.7, 908.6] | [912.1, 937.0] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-48-1-contact` | 1149.5 / 1166.7 [1143.2, 1153.4] | 1205.9 / 1227.5 [1198.3, 1208.7] | [1223.1, 1240.6] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-48-2-contact` | 1161.4 / 1180.7 [1160.2, 1167.7] | 1229.1 / 1248.2 [1216.9, 1238.9] | [1244.3, 1270.6] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-48-4-contact` | 1192.8 / 1210.4 [1191.8, 1195.5] | 1256.1 / 1277.0 [1250.1, 1256.8] | [1267.9, 1283.1] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-64-1-contact` | 1492.8 / 1513.5 [1488.5, 1495.5] | 1562.1 / 1577.2 [1549.7, 1567.5] | [1575.9, 1601.1] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-64-2-contact` | 1503.7 / 1518.3 [1502.8, 1507.4] | 1575.2 / 1594.9 [1561.2, 1576.3] | [1577.5, 1596.9] | [False, False, False] | [3.0, 3.0, 3.0] |
| `grid-64-4-contact` | 1525.2 / 1544.1 [1518.6, 1527.1] | 1581.9 / 1608.1 [1572.8, 1599.8] | [1598.3, 1630.0] | [False, False, False] | [3.0, 3.0, 3.0] |


24/32 次位置迭代的六组均为圆锥 2/6、T3v2 2/10、T4 22/26，并新增 Guide 退化；48 次的三组恢复 T4 23/26，但圆锥只有 3/6、T3v2 4/10。这里 T3v2 的未通过项均为实际 `failed`，没有把夹具无效计成通过。只有 64 次的三组保住全部门，而接触完整步分别约 1562、1575、1582 µs。故在指定网格内，物理通过区域与性能通过区域不相交。

较少迭代还会改变休眠状态：24/32 组虽叠加 0.5，静态仍醒；48/64 组静态能睡。这个变化已读取，不能把 64/16 的休眠收益直接套到所有迭代配置。

## batch size 诊断

Python 运行时检查 `PhysxCpuSystem`、`PhysxSceneConfig` 未发现 batch setter；`PhysxArticulationLinkComponent` 已有 `_physx_pointer`。绑定来源是 SAPIEN `python/pybind/physx.cpp:732-734`。PhysX [PxScene.h:1651-1668](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include/PxScene.h#L1651-L1668) 已公开 set/get；本轮用同版本官方头文件编译一个独立 C ABI 适配库，从 `PxActor* -> getScene()` 调用它。所有调用都发生在 scene 未进行 step 时。

**不需要改 SAPIEN fork 或构建 a4。** 适配库未链接新的 SAPIEN/PhysX 动态库，只调用原对象的公开虚函数；`nm -u` 没有 SAPIEN/PhysX 未解析符号。GCC 11.4.0 首次编译成功，实际全部读回 **16 → 1**。这仅是固定版本诊断接口，不是已发布的新 Python API。

叠加 `64/1 + threshold 0.5` 后，完整上游验收仍为 6/12/6/10/23，无原通过项退化。基准如下：

| 条件 | 原生中位数 / p95 [中位数重复范围] | 完整步中位数 / p95 [中位数重复范围] | 完整步 p95 重复范围 | 末态休眠 | 接触对 |
|---|---:|---:|---:|---|---|
| `batch-1-static` | 230.1 / 241.8 [229.8, 230.4] | 263.2 / 276.8 [262.8, 263.4] | [276.4, 276.9] | [True, True, True] | [0.0, 0.0, 0.0] |
| `batch-1-active` | 249.9 / 270.0 [248.9, 250.4] | 452.9 / 569.8 [450.1, 454.1] | [564.5, 580.2] | [True, True, True] | [0.0, 0.0, 0.0] |
| `batch-1-contact` | 1056.9 / 1070.5 [1054.0, 1058.2] | 1126.7 / 1142.5 [1109.6, 1130.1] | [1124.9, 1147.4] | [False, False, False] | [3.0, 3.0, 3.0] |
| `batch-1-awake-static` | 471.2 / 486.4 [471.1, 472.2] | 507.9 / 525.0 [507.4, 509.0] | [524.6, 525.1] | [False, False, False] | [0.0, 0.0, 0.0] |

`batch-1-awake-static` 是保留工厂休眠阈值、保持唤醒的 64/1 补充诊断；它不是与 64/16 默认值只差 batch 的对照。正式 batch 效应对照是同为 64/1、threshold 0.5 的 `grid-64-1-*` 与 `batch-1-*`。

接触完整步由 1562.1 降到 1126.7 µs，降幅约 28%，但仍不合格。这不表示 batch 把接触岛拆开：[DyTGSDynamics.cpp:688-729](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyTGSDynamics.cpp#L688-L729) 按完整岛累加，批内最大迭代在 [1671-1707](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/source/lowleveldynamics/src/DyTGSDynamics.cpp#L1671-L1707) 取得。

为区分“接触岛不可拆”和“接触时整个场景完全不能受益”，另做了一次 **1 次重复、100 步**的接触归属诊断，**不作为性能统计组**。三个接触对均读回左手—手柄（ring/pinky—body、thumb—left_stick），右侧无接触。结合上述源码，右侧独立岛避免被合批带上高迭代，可解释部分下降；左手与手柄组成的接触岛仍完整保留。我们没有内部 batch trace，不把解释写成逐批原生实测。双手同时接触不是本次 AQ L3 姿态，不能外推它也有同等降幅。

## 推荐及物理代价

不建议为本任务修改默认 profile。可提交负责人考虑的辅助候选是保留 preload 的实例休眠阈值 0.5：本套协议无新增退化，无接触收益明确，但它改变小能量运动何时被冻结，且单独不能解决接触实时性。

64/1 减少速度迭代，本套验收未退化，但仍可能改变未覆盖的接触瞬态；batch size 1 避免不相关岛承担批内高迭代，也可能改变原来因合批而获得的额外机器人求解精度。三者叠加后接触仍不满足目标，因此本轮没有推荐切换方案，也没有以物理退化换取速度。后续若继续研究，需要另行确定方向；本任务未扩展到改引擎、改物理模型或换硬件。

## 我自行决定的选择

- 用 AQ 已维护的完整采集后端、资源副本与旧隔离环境，避免新建近似机械场景；源代码从本地镜像，节点仅运行镜像。
- 用一个只读子助手核查休眠源码，主线程串行运行所有物理和计时；没有并发跑候选影响彼此计时。
- 首选保留持久 qf、仅提高实例休眠阈值，规避 ruling5 已知的远限位外 drive 交互。0.05 不眠后测试 0.5；阈值不作为硬件物性。
- 不用物理性能总分替代逐项回归，12 组均执行完整套件；不改默认值、不移除碰撞/手部、不换 PGS。
- 计时采用固定线程/亲和性和三次独立重复，同时报告 native 与完整后端步；不把无接触休眠收益外推为有接触收益。
- 首次阈值计时因启动目录找不到场景配置退出，保留失败日志后修正工作目录，重跑使用 `-r1` 新目录；这次是启动脚本自修 1 次，没有改物理代码或判据。一次 rsync 指向不存在的本地 `build_data/` 返回 23，后续仅同步实际存在的文件；默认数据没有修改。

## 复现句柄与原始证据

- [小摘要 JSON](summary.json)：每组中位数/p95/重复范围、验收结果、T4 原通过集合、环境版本和每个原始 summary/step-times 的 SHA256。共有 50 个正式/补充性能条件（均 3×3000 步），另有一个单次接触归属诊断。
- 原始逐步轨迹完整保留在指定计算节点的运行镜像 **`build/experiments/station_rtf/raw/`**，共 2241 个证据文件；本机 `build/experiments/station_rtf/raw/` 保留小型逐步计时 NPZ、摘要、日志及 receipts。大型验收 JSONL 留在节点，不提交。
- 本机 `build/experiments/station_rtf/handles.json` 保存实际连接 profile、节点根目录、资源、两套 Python 和镜像句柄；`raw-sha256.json` 给出全部原始文件的逐文件 SHA256，`experiment-input-sha256.json` 和 `local-source-sha256.json` 保存实验脚本与只读源输入校验。
- 输入/脚本快照在 `build/experiments/station_rtf/input/`。基线使用 `benchmark-baseline.py` 的归档字节版本；休眠/网格使用 `benchmark-sleep-grid.py`、`overrides-sleep-grid.py`、`station_rtf-sleep-grid.py`；batch/归属诊断有各自脚本 SHA。运行时源码变化只增加计时/读回和实验 override，没有改资源或判据。
- 本次实现的提交由分支 `perf/station-rtf` 的 `git log -1` 定位；数据产生时的基线提交为 d05786c，采集后端为 8550818，SAPIEN/PhysX 版本见上文及摘要。最终代码的 SHA256 也写入摘要，避免把当前源码误当成历史每一轮的同字节脚本。

| 原始证据 | SHA256 |
|---|---|
| 全部原始文件校验目录 `raw-sha256.json` | `38af35ab14a118f3b6011df87dc9c556d6b00e497244fe5c0769fd12a65c11e5` |
| 最优候选接触逐步 `batch-1-contact/step_times.npz` | `509d1db143da3caa639fc49ff547d613100ff99fadbaa441c81d5129b0706e70` |
| 冻结 L3 输入 | `490fcd588c543419215e3331f93c614b8688e6f8bdbdb7c47763870ff594c283` |
| 官方 PhysX SDK 源码 archive | `1150b3a8430907632eaa7ac410b783be12f72dcee1b3287da974294104710234` |
| 独立 batch adapter `.so` | `69e62b3f3591fd5e5abb3450bc23b212fc94ea2af9dc93a99f6c2ef4c116d2ce` |

新环境：Python 3.10.12，SAPIEN `3.0.3+concon.physx5.6.1.a3`，xbox-gamepad-physics 0.4.2；环境名 `sapien-3.0.3concon-xgp0.4.2-py310`。旧环境名 `am-baseline-sapien303-xgp041`，Python 3.10.12 / SAPIEN 3.0.3 / 0.4.1。只使用已有环境，没有覆盖或安装共享包。

节点执行示例（变量的实际值见本机 handles；每次用新的输出目录）：

```bash
export DISPLAY='' CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export GAMEPAD_VLA_WORKSPACE="$VALIDATION_WORKSPACE"
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$VALIDATION_RESOURCES"
export PYTHONPATH="$XGP_CHECKOUT:$XGP_CHECKOUT/src:$STATION_CHECKOUT/src"
cd "$STATION_CHECKOUT"

taskset -c 8 "$VALIDATION_PYTHON" -m tests.acceptance.robotwin.station_rtf   --suite full --iterations 64 1 --sleep-threshold 0.5   --batch-size 1 --batch-library "$BATCH_SO" --output "$NEW_ACCEPTANCE_OUTPUT"

taskset -c 8 "$VALIDATION_PYTHON"   "$XGP_CHECKOUT/experiments/robotwin/station_rtf/benchmark.py"   --aq-probe "$AQ_PROBE" --condition contact --iterations 64 1   --sleep-threshold 0.5 --batch-size 1 --batch-library "$BATCH_SO"   --steps 3000 --repetitions 3 --output "$NEW_BENCH_OUTPUT"
```

将 `--condition` 换成 `static` / `active` 可复跑无接触两组；省去 batch 参数复跑步骤 2，省去 iterations 复跑步骤 1。网格执行及逐项回归比较入口为 `tests/acceptance/robotwin/station_rtf_scan.py`（运行时归档名 `grid.py`，源码相同）。准确的批量启动命令还保存在原始 `run-*.sh`，它们不触发硬件或输入链。

复跑旧基线时只将采集后端 `src` 放入 PYTHONPATH，使用旧 Python/0.4.1 资源和归档的 `benchmark-baseline.py`，避免本仓库 `src` 遮蔽旧安装包。AQ probe 本身也须使用归档 SHA 对应版本及相邻 L3 输入目录布局。

独立适配库的构建命令（计算节点，先直连下载固定 SDK；本轮首轮直连成功，无代理）：

```bash
curl --noproxy '*' -fL --connect-timeout 15 --max-time 60   https://codeload.github.com/NVIDIA-Omniverse/PhysX/tar.gz/5ca9f472105a90d70d957c243cb0ef36fe251a9f   -o physx-5ca9f472.tar.gz
tar -xzf physx-5ca9f472.tar.gz --wildcards '*/physx/include/*'
g++ -std=c++17 -O2 -fPIC -shared -DNDEBUG   -I PhysX-5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include   "$XGP_CHECKOUT/experiments/robotwin/station_rtf/batch_adapter.cpp"   -o "$BATCH_SO"
```

该库仅用于这套固定 SDK/引擎的诊断；没有修改、重编或发布 SAPIEN。

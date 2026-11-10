# RoboTwin click 受力切换限位原型

**裁定 2 结论：在 1 ms × 10/1 下，A（持续 preload）和 B（混合状态机）均通过全部既有验收门，结果都是 T1 6/6、T2 12/12、圆锥 6/6、T3v2 10/10、T4 25/26，原通过项没有退化。** Pair 仍为已知失败，不能称作 26/26。A 的 1 ms × 64/16 对照也得到相同结果，未发现改成 1 ms 本身引入新失败。

**始终唤醒时，三类完整步的中位数和 p95，A/B 全部低于 800 µs。** A 的静态/100 Hz 双臂/冻结接触中位数为 **327.0 / 520.0 / 389.1 µs**，p95 为 **342.0 / 681.4 / 411.1 µs**；B 为 **339.3 / 530.9 / 403.8 µs**，p95 **355.3 / 686.0 / 423.9 µs**。但若“≤800 µs”要求每一个采样步都满足，**两者均未达成**：每组 9000 步仍有 2–20 个超时尖峰，最大值见表。

**在本轮证据范围，B 没有正式化的必要。** A 已满足相同验收门和所报分位数性能门；B 未增加通过项，完整步中位数反而多约 10.9–14.7 µs，还需逐步 hook 和 qf 状态管理。B 仅消除锁定期 preload，解锁期仍保留原力律及可能的倾斜摩擦耦合。休眠不再参与方案判断。当前证据支持采用 A 的部署步长/迭代诊断结论，不支持为此加入混合状态机；**本轮没有修改生产默认值**。

## 裁定 2：执行范围与停止记录

收到裁定后向本会话自己的纯方案休眠进程 PID 778308 发送 SIGTERM，并确认该进程及父批次均退出；纯 64/16 的 30 s 补测只完成 8/12，纯 10/1 的 30 s 补测未启动。没有再启动休眠观察。既有混合 64/16 的约 **10.146 s 自然入睡、睡后 q=0** 只作为历史记录。

A 使用原 0.4.2 preload，仅覆盖指定迭代；B 使用本原型。只在指定节点 CPU 10 串行执行离线仿真，既有 a3 环境、资源、AQ probe 及全部机器人不变。没有连接采集台/硬件，没有修改 MuJoCo、Isaac、`src/`、`references/`、`build_data/` 或默认 profile，没有覆盖共享环境，没有 push。P/K 报告仅提供部署步长线索，本轮独立重跑完整套件，没有写它们的路径。

## 1 ms 部署诊断：逐项时间换算

适配在 `experiments/robotwin/click_switch/deployment.py` 进程内完成。读取既有函数源码，只替换时间常量/采样数，并在退出后恢复原函数。每组 `deployment.json` 保存实际转换源码、替换项、原/转换后函数 SHA256 和有效协议。原冻结 JSON 与测试源码未改；这是 **1 ms 部署诊断，不替代原 4 ms 验收**。

| 项目 | 4 ms → 1 ms 的处理 | 保持的物理意义 |
|---|---|---|
| T1/T2 及 setup | 运行时 `P.dt_s=.001`；settle 250→1000；T1 每半程 750→3000；T2 250→1000，末窗 125→500 | settle 1 s、上/下 ramp 各 3 s、T2 保持 1 s/末窗 0.5 s |
| T1 端点样本 | 沿用 `2*round(3/dt)+1`，1501→6001 样本 | 原 ramp 公式和两端点保留；受载采样序列 6.004→6.001 s，额外一个积分样本随 dt 缩小，不缩短名义 3 s ramp |
| 圆锥 | 总步数 500→2000，加载边界两处 250→1000，记录时钟 `.004→.001` | 加载/释放各 1 s；steady 0.8–1.0 s、release 1.8–2.0 s 仍按原秒窗口 |
| T3v2 | settle/ramp_up/hold/ramp_down/observe 从 250/125/250/125/125→1000/500/1000/500/500；末 hold 窗口 125→500 | 各 1/0.5/1/0.5/0.5 s，阳性控制末窗 0.5 s |
| T4 轨迹和物理步 | fixture dt、`PressTrajectory.dt`、`executor.step`、phase age 时钟均为 1 ms | 接近 1 s、5 mm/s 推进、0.5 s hold、0.5 s 抬起/observe、原终止逻辑 |
| T4 阻塞与预算 | `PressStop` 接收实际 dt，0.1 s 窗口 25→100 个步间隔；预算 10000→40000 | 阻塞 0.1 s、总预算 40 s；不延长允许物理时间 |
| T4 评分 | 最后 125→500 个有效 hold 样本；长度检查、返回计时、hold 时长同步换算 | 0.5 s 稳态窗、返中 ≤0.5 s、原所有信号/误触/内部接触阈值 |

球体半径仍 **4 mm**，质量仍 **50 g**；没有把半径 `.004 m` 当成步长改掉。PD、16 N 限幅、碰撞、材料、力、作用点和手柄参数均不变。旧 timeline 只作来源保留，本调用链使用原轨迹状态机重新执行，不回放旧步号。T4 的导入别名、scorer 相对导入及 load_suite 别名已按实际调用链覆盖。

抽读三组实际轨迹均确认 T1 为 6001 样本/末时刻 6.001 s，T2 为 1000/1 s，圆锥为 2000/2 s 且加载 1000 步，T3v2 各阶段为 1000/500/1000/500/500，View 的有效 hold 恰为 500 样本。三组各 26 个 T4 病例的 native dt 均读回约 1 ms（单精度），球体迭代仍为原 10/1，半径/质量为 4 mm/50 g；见 `trace-observations.json`。

### 完整结果

| 方案/迭代（均 1 ms） | T1 | T2 | 圆锥 | T3v2 | T4 | 原通过项退化 | 墙钟 s |
|---|---:|---:|---:|---:|---:|---|---:|
| A-64-16 | 6/6 | 12/12 | 6/6 | 10/10 | 25/26 | 无 | 111.93 |
| A-10-1 | 6/6 | 12/12 | 6/6 | 10/10 | 25/26 | 无 | 65.72 |
| B-10-1 | 6/6 | 12/12 | 6/6 | 10/10 | 25/26 | 无 | 67.55 |

三组 T4 都只失败 Pair，原 23 个通过项全部保留，L3/R3 两项新增通过。完整保存每个病例与原通过集合，未用总数抵消退化。A 的 64/16 对照确认了 1 ms 下的门；A/B 的 10/1 结果表明旧 4 ms 的圆锥及 View/Menu/Guide 失败不能直接外推为部署步长下必须使用 64/16。

## 始终唤醒的采集台性能

`awake.py` 在每个 1 ms `backend.step` 前调用一次 root `wake_up()`，没有改 sleep threshold。AQ 调用链每次 backend call 恰为一个物理步。每次都在唤醒后及物理步后读取 `sleeping`；六组各三次读回全部为 **False**，不是只检查末态。静态/active 每重复 3500 次、接触 5200 次（含准备/暖机），对应读回中睡眠次数均为 **0**。

三类场景沿用 AQ 原入口，CPU affinity `[10]`、TGS、`cpu_workers=0`，OMP/OpenBLAS/MKL 均 1；每组 3×3000 个测量步。静态/active 无接触，冻结 L3 接触三次均 3 对。完整步包含逐步唤醒、状态读回和记录；B 还包括切换函数及其计时。native 为内层实际 `scene.step()`；B 另保留 `native_with_callback`，没有把 callback 排除出完整步。完整步不含循环外稀疏诊断、渲染或录制，不能当成采集台端到端硬实时保证。

单位 **µs/步**。中位数/p95 是三次统计量的中位数；范围为三次各自统计量的最小最大值。

| 方案/条件（10/1） | native 中位数 / p95 | 完整步中位数 / p95 | 完整步中位数重复范围 | 完整步 p95 重复范围 | 墙钟 s |
|---|---:|---:|---:|---:|---:|
| A / static | 288.6 / 301.2 | 327.0 / 342.0 | [326.6, 327.2] | [341.4, 342.4] | 10.63 |
| A / active | 313.1 / 334.5 | 520.0 / 681.4 | [518.5, 523.0] | [676.5, 686.4] | 12.49 |
| A / contact | 334.6 / 352.4 | 389.1 / 411.1 | [389.0, 398.1] | [409.9, 418.0] | 13.46 |
| B / static | 291.1 / 304.2 | 339.3 / 355.3 | [339.0, 341.1] | [354.1, 356.5] | 10.80 |
| B / active | 312.2 / 332.3 | 530.9 / 686.0 | [527.6, 533.4] | [677.8, 698.1] | 12.77 |
| B / contact | 338.3 / 356.9 | 403.8 / 423.9 | [400.5, 410.9] | [422.8, 434.2] | 13.77 |

每个重复的完整步 p95 也都低于 800 µs，最高为 B-active 的 **698.1 µs**。每组原始 9000 步中的越限数如下；尖峰根因未定位，没有重测并丢弃这些样本。

| 方案/条件 | 完整步 >800 µs | 最大完整步 µs |
|---|---:|---:|
| A / static | 2/9000 | 1215.6 |
| A / active | 12/9000 | 5862.0 |
| A / contact | 2/9000 | 1213.8 |
| B / static | 2/9000 | 1171.8 |
| B / active | 20/9000 | 1345.4 |
| B / contact | 2/9000 | 1243.1 |

因此，问题“完整步是否都 ≤800 µs”的答案应区分统计门和逐步硬截止时间：**三类中位数/p95 都满足；每一步都满足则 A、B 都不成立。** 本轮没有继续改调度、删功能或调物理来追逐尖峰。

## B 相对 A 的价值判断

两者在部署步长下验收结果一致。B 本轮完整步中位数比 A 的静态/active/contact 分别多 **12.3/10.9/14.7 µs**，其 callback 自身中位数约 **5.9–7.3 µs**；不把全部差额都归因于该函数。没有观察到 B 的验收或性能收益，且两者都有逐步超时样本。

B 可撤去锁定期的人工预压力，但这个变化没有在本套 1 ms 验收中产生 A 无法达到的结果，也没有识别出新的硬件保持力或迟滞。解锁期仍使用原 preload，不能宣称完全解耦倾斜摩擦。休眠已被排除为收益来源后，目前不足以支持增加此状态机及下游调用责任；本轮保留原型作诊断，不改默认值。

## 裁定 2 的复现入口

已有节点镜像中，`run_deployment.sh` 记录三个完整诊断及六个始终唤醒基准的串行调用。单独复现时使用新的输出目录：

```bash
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"

bash "$CLICK_LAUNCH" -m experiments.robotwin.click_switch.run \
  --mode preload --entry acceptance --deployment-1ms \
  --suite full --iterations 10 1 --output /path/to/new-dt1-acceptance

bash "$CLICK_LAUNCH" -m experiments.robotwin.click_switch.run \
  --mode preload --entry benchmark --always-awake \
  --aq-probe "$CLICK_ROOT/support/reports/2026-11-09-realtime-input-lag/engine_probe.py" \
  --condition active --iterations 10 1 --steps 3000 --repetitions 3 \
  --output /path/to/new-awake-benchmark
```

B 将 `--mode preload` 换成 `hybrid`；A 对照使用 `--iterations 64 16`；其他性能场景用 static/contact。`run_remote.sh` 固定 CPU 10、既有解释器、环境和资源路径。

本机总句柄为 `build/experiments/station_rtf/click_switch/handles.json`；该目录的 `summary.json`、`trace-observations.json`、`source-sha256.json`、`raw-sha256.json` 保存逐组数据与校验。正式新结果以 `deployment-*`、`awake-*` 命名，和早期休眠/4 ms 结果分开。

---

以下为原型机制、裁定 1 和裁定 2 前的过程记录。**早期休眠及允许自然休眠的计时不作为最终方案依据。**

## 原型设计与测力

实现位于 `experiments/robotwin/click_switch/override.py`，以进程内 override 替换加载时的 preload 写入，并为返回 handle 添加 `pre_step()`。每个物理步前读一次前一步的传递力，再按状态边沿更新限位。没有写 qpos/qvel，没有修改信号编码器；T1/T2 的信号与 raw fraction 继续来自实际 q/0.4 mm。

| 状态/边沿 | 纯方案 | 混合方案（裁定 1） |
|---|---|---|
| 锁定 | click 限位 `[0,0]`；本原型的 qf 贡献为 0 | 相同 |
| 解锁条件 | 测得轴向载荷 ≥ `references/full_controls.json` 的 `control_groups.sticks.click_force_n`，当前 7.4 N | 相同 |
| 解锁动作 | 限位 `[0,0.0004] m` | 放开相同限位，并用原 `mappings.apply_preload` 叠加 manifest 的 −7.4 N |
| 解锁回复力 | 原零目标弹簧 `1000q N` | 原 0.4.2 力律 `7.4+1000q N` |
| 重新锁定 | `q ≤ 1 µm` 且测得载荷 < 7.4 N，再把限位设回 `[0,0]` | 同条件锁回，并在当前 qf 上加回自己先前叠加的 7.4 N |

两方案均保留 native drive 的 k=1000 N/m、目标 0、阻尼约 2.8 N·s/m、spring drive cap 10.4 N。混合方案只在两个边沿写 qf，不每步重写；读取调用方当前 qf 后增减自己的 click 分量。调用方整体 `set_qf` 覆盖仍须遵守原有 compose 约定。本原型没有实现独立的 qf 所有权通道。

选择零宽限位的依据是 SAPIEN `src/physx/articulation_link_component.cpp:190–216`：有限区间映射为 PhysX `eLIMITED`，`[0,0]` 不移除 DOF；固定 PhysX `NpArticulationJointReducedCoordinate.cpp:289–298` 接受 `low <= high`。实际读回仍为 20 DOF、限位 `[0,0]`。1 µm 是重新锁定的数值容差，不是新的机械行程；只有自然回位已进入该范围才允许锁回。混合释放轨迹在锁回前均已进入 1 µm 容差，已核对的最大余量约 0.51 µm；零宽限位可消除这段亚微米余量，未在明显中途行程锁定。

### 原生传递力接口

实际 a3 wheel 已确认存在 `art.get_link_incoming_joint_forces()`。SAPIEN 绑定在 `python/pybind/physx.cpp:1057–1059`，实现位于 `src/physx/articulation.cpp:350–358`：内部调用 `copyInternalStateToCache(eLINK_INCOMING_JOINT_FORCE)`，返回每 link 的 `[Fx,Fy,Fz,Tx,Ty,Tz]`。无需另外打开旧版的 `eCOMPUTE_JOINT_FORCES`。本轮没有编译适配库，也没有退回接触冲量求和。

该接口返回父 link 传给 child 的上一步平均关节传递力，坐标为 child incoming joint frame，线力单位 N、力矩 N·m，包含 drive、限位、摩擦及用户 qf。参见 [PhysX 5.6.1 官方说明](https://nvidia-omniverse.github.io/PhysX/physx/5.6.1/docs/Articulations.html#link-incoming-joint-force) 与[固定版本头文件](https://github.com/NVIDIA-Omniverse/PhysX/blob/5ca9f472105a90d70d957c243cb0ef36fe251a9f/physx/include/PxArticulationReducedCoordinate.h#L287-L296)。SAPIEN `get_links()` 按 PhysX link index 排序；原型用 click child 对应行的 `max(0,-Fx)`，无需除 dt。

运行时校验：锁定 L3，无手指外力时读到约 0.0492 N，沿杆施加 7 N、0° 时约 7.0478 N，8 N、20° 时约 7.5652 N。当前结构是 **body → click → tilt x → tilt y → cap**，click 轴为壳体固定的 −Z；沿倾斜杆施力自然成为 `F cosθ` 的 click 载荷，不额外乘一次 cosθ。不要套用历史报告旧结构的轴关系。

没有额外低通、去抖或噪声阈值。CPU 恒载末态读回可检验符号及投影，未测随机噪声谱；接触冲击、重力、惯性和驱动都会进入读数。`pre_step()` 使用前一步结果，检测延迟至少一个物理步，即现有验收约 4 ms、释放/基准约 1 ms。解锁后它不是独立手指力计，重新锁定仍必须同时检查 q。完整 T3v2/T4 只验证既有工况下的行为，不代表任意冲击均无误触发。

## 裁定 1：37 µm 的重力核实

实测 L click 下游树：x/y frame 各 0.5000 g，cap 4.014851 g，总 **5.014851 g**。按压正轴世界方向约 `[0,0,-1]`；k=1000 N/m，因此连续静力预测 `mg cosα/k = 49.1957 µm`。当前 R 树资源质量为 **4.547936 g**，对应 **44.6152 µm**。这些是资源中的仿真质量：cap 来自体积、密度和填充率假设，frame 是数值正则质量，不是硬件称重。

`diagnose_gravity.py` 在同一模型/姿态下做重力开/关及自然休眠/逐步唤醒对照；未修改休眠阈值。逐步唤醒只用于区分原因，未进入原型或正式性能组。

| dt | 重力 | 自然休眠末态 q | 持续唤醒末态 q | 自然首睡时刻 | 睡前 click qvel | 睡前子树瞬时动能/质量 |
|---|---|---:|---:|---:|---:|---:|
| 4 ms | 9.81 m/s² | 36.8712 µm | 36.8712 µm | 0.400 s | −0.01194 m/s | 7.13e−5 J/kg |
| 1 ms | 9.81 m/s² | 48.3995 µm | 48.3995 µm | 0.401 s | −0.004372 m/s | 9.56e−6 J/kg |
| 4 ms | 0 | 约 7e−6 µm | 0 | 0.400 s | 约 0 | 1.08e−14 J/kg |
| 1 ms | 0 | 约 3e−6 µm | 约 3e−6 µm | 0.401 s | 约 1.1e−8 m/s | 9.64e−13 J/kg |

**重力导致非零回复位置已确认；“提前休眠截断导致 37 µm”被持续唤醒对照推翻。** 37 µm 也不是精确 `mg/k` 平衡：4 ms、1 ms 的未平衡力分别约 12.32 mN、0.796 mN，getter 速度仍非零。这是重力相关、步长相关的离散稳态残差；未取得内部位置/速度迭代 trace，不能把具体 CFM 或某个内部阶段写成唯一原因。它已足以解释纯方案为什么达不到 1 µm 的锁回条件，并支持裁定 1 的混合方案尝试。

表中能量由 getter 的 link 速度、质量和惯量计算，**不是 PhysX 内部睡眠累计能量**。后者使用位置求解阶段 motion velocity 的跨步累计量，且全 articulation 的 link 都要就绪才睡。睡后速度为零也不能倒推睡前精确静力平衡。

## 验收及回归

复用 `tests/acceptance/robotwin/station_rtf.py`，以及其调用的原 T1、T2、圆锥、T3v2、T4 入口。协议、评分、球探针、材料和输入均未修改。这里的迭代数指手柄；采集场景双臂/双手继续使用原 10/1。验收 dt 仍为协议的 4 ms。

| 方案/手柄迭代 | T1 | T2 | 圆锥 | T3v2 | T4 | 原 T4 通过项退化 | 验收墙钟 s |
|---|---:|---:|---:|---:|---:|---|---:|
| 纯方案 64/16，仅 T1 | 0/6 | — | — | — | — | 未运行 | 8.19 |
| 纯方案 10/1，仅 T1 | 0/6 | — | — | — | — | 未运行 | 6.22 |
| 混合 64/16，独立 T1 门 | 6/6 | — | — | — | — | 未运行 | 8.19 |
| 混合 10/1，独立 T1 门 | 6/6 | — | — | — | — | 未运行 | 6.23 |
| 混合 64/16，完整 | 6/6 | 12/12 | 6/6 | 10/10 | 23/26 | 无 | 27.31 |
| 混合 10/1，完整 | 6/6 | 12/12 | 2/6 | 10/10 | 22/26 | View、Menu、Guide | 21.12 |

纯方案加载段可以检测到约 7.4 N 的解锁，但解锁后仅剩最多 0.4 N 的弹簧回复力，卸载到低载时仍接近满行程；T1 的低力最大信号/行程约 0.988–0.989，零外载末态还残留约 32–36 µm，故判失败。没有通过调信号或放宽低力判据“修复”。裁定 1 提供了新的合法物理方案，混合 64/16 首次 T1 即通过，没有触发三次失败后停机条件。

64/16 的 T4 失败仍为 Pair/L3/R3。10/1 新通过 L3/R3，但新增 View/Menu/Guide 退化；新增通过不抵消旧通过项丢失。10/1 的圆锥四个失败为左右 positive_x/positive_y，保持角约 22°，未满足原边界要求。这里报告测量结果，不依赖 P/K 会话的原因结论。

## 1 kHz 释放回位

每方案、每种迭代、每侧分别测试 0°/2°/23° × 满行程/刚过解锁阈值，共 **12 工况/组**。满行程用轴向外力压到约 0.399 mm；“刚过阈值”定义为外力轴向分量 `1.01×7.4 N`，检测到首次解锁且 q>0 后立即释放。混合方案此时 q 约 **17.6–18.6 µm**，确实覆盖很浅的释放；纯方案因缺少解锁保持力，首步已接近满行程，原样记录。

释放时同时停止施力、恢复倾斜原被动驱动；不保留角度夹具，不重置 q/速度，不强制睡眠。空间判据明确取 click **3 µm**、杆轴倾斜 **0.1°**；记录首次 click 回位、此后持续满足两项的完成时刻、首次睡眠以及睡后位置。原型锁回容差仍为 1 µm，没有拿 3 µm 诊断容差改变状态机。

混合方案两种迭代、满行程和浅行程的空间结果一致：

| 释放角度 | L3 click 回位 / 完整回位 | R3 click 回位 / 完整回位 | 锁回 |
|---|---:|---:|---:|
| 0° | 1 / 1 ms | 1 / 1 ms | 约 2 ms |
| 2° | 1 / 182 ms | 1 / 183 ms | 约 2 ms |
| 23° | 1 / 330 ms | 1 / 331 ms | 约 2 ms |

时间分辨率为 1 ms。混合方案所有空间末态读回 click q=0；不能由此推断亚毫秒峰值或硬件回弹。已取得的 30 s 对照及耗时如下；裁定 2 后未完成的组明确标为停止，不再以休眠作为方案依据：

| 方案/迭代 | 观察窗 | 空间末态合格 | 自然睡眠 | 首睡时刻 | 墙钟 s |
|---|---:|---:|---:|---:|---:|
| 纯-64-16 | 5 s | 0/12 | 0/12 | 窗口内未观察到 | 39.37 |
| 纯-10-1 | 5 s | 0/12 | 0/12 | 窗口内未观察到 | 25.24 |
| 混合-64-16 | 5 s | 12/12 | 0/12 | 窗口内未观察到 | 39.71 |
| 混合-10-1 | 5 s | 12/12 | 0/12 | 窗口内未观察到 | 25.13 |
| 混合-64-16（30 s） | 30 s | 12/12 | 12/12 | 10.146–10.146 s | 99.28 |
| 混合-10-1（30 s） | 30 s | 12/12 | 0/12 | 窗口内未观察到 | 123.40 |

纯方案 64/16 的 30 s 补测在裁定 2 后停止，summary 已完成 **8/12** 工况；该组不计作完整验收。纯 10/1 的 30 s 补测未启动。停止凭据为 `stop-receipt.json`。

64/16 混合方案睡前选中 click 的 qvel 约 `0.8–2.1e−10 m/s`，子树 getter 动能/质量约 `1.3e−13–7.0e−12 J/kg`，睡后 click q=0、倾斜读数为 0°。回位已完成后仍需等待全 articulation 自然休眠；没有内部 counter trace，不能解释为何该套工况首睡时刻如此一致。

额外的 `sleep_probe.py` 比较无锁/零宽限位/1 µm 限位、每步读取/不读取传递力。一次唤醒后，64/16 六组均在 0.402 s 入睡，零宽限位下两路 q=0；10/1 六组在 5 s 内未睡。该对照推翻了“力查询必然阻止休眠”与“零宽限位必然不能休眠”。它不是完整释放场景，不能把 0.402 s 套到释放结果。

## 裁定 2 之前的采集台性能（仅记录）

仅使用指定节点 `the designated compute node` 的 **CPU 10**，已有 a3 / 0.4.2 环境；不使用 GPU。OMP/OpenBLAS/MKL 均 1，PhysX `cpu_workers=0`，DISPLAY/CUDA 为空。每组独立建场景，暖机 500 步，**3×3000 步、dt=1 ms**。100 Hz 输入为 AQ 原有墙钟合成双臂路径；冻结接触沿用原 L3 hold/push、1700 步准备及全部机器人/手柄资源。

先在同一时间段复跑 preload `baseline-new-static`：native 中位数 **1480.3 µs**、完整步 **1517.2 µs**，完整步三次范围 **1515.0–1521.9 µs**，与历史 1518.6 µs 接近，未见明显并行会话干扰。该结果不证明节点独占或没有任何调频/抖动。

`native` 用内层计时器测真实 `scene.step()`；完整步仍为原 `backend.step(0.001)`，**包含本原型每步函数、控制、目标写入、被动力和接触查询**。保留上游包围 callback 的 `native_with_callback`，不把它冒充纯 native。原型稳态 callback 中位数约 **5.4–7.6 µs**。静态/active 每重复实际调用 3500 次，接触每重复 5200 次；统计数组各保留最后 3000 步，准备和暖机不计入分位数。

下表单位均为 **µs/步**；分位数取三次统计量的中位数，范围为三次完整步中位数/三次完整步 p95 的最小最大值。

| 条件 | native 中位数 / p95 | 完整步中位数 / p95 | 完整步中位数重复范围 | 完整步 p95 重复范围 | 末态睡眠（三次） | 墙钟 s |
|---|---:|---:|---:|---:|---|---:|
| `baseline-new-static-r1` | 1480.3 / 1493.3 | 1517.2 / 1534.4 | [1515.0, 1521.9] | [1532.0, 1537.9] | [False, False, False] | 23.23 |
| `hybrid-64-16-static-r1` | 232.0 / 246.3 | 274.0 / 292.8 | [272.9, 275.2] | [289.0, 294.4] | [True, True, True] | 11.62 |
| `hybrid-64-16-active-r1` | 251.1 / 266.0 | 460.9 / 589.3 | [457.7, 464.6] | [588.4, 608.8] | [True, True, True] | 13.66 |
| `hybrid-64-16-contact-r1` | 1671.8 / 1683.5 | 1749.2 / 1762.7 | [1726.0, 1751.0] | [1744.7, 1777.2] | [False, False, False] | 34.49 |
| `hybrid-10-1-static-r1` | 291.4 / 303.8 | 337.6 / 352.1 | [336.3, 338.2] | [351.1, 352.2] | [False, False, False] | 10.74 |
| `hybrid-10-1-active-r1` | 312.9 / 336.5 | 524.3 / 678.5 | [524.1, 527.7] | [678.1, 691.1] | [False, False, False] | 12.67 |
| `hybrid-10-1-contact-r1` | 337.6 / 355.0 | 401.5 / 420.2 | [399.2, 410.4] | [420.1, 427.8] | [False, False, False] | 13.71 |

所有静态/active 组无接触，所有冻结组恰为 3 对接触。冻结接触的混合状态均为左 click 解锁、右 click 锁定，左 qf 读回 −7.400000095 N、右贡献为 0；不是 callback 漏执行造成的“无 preload 加速”。64/16 接触的 native 本身已超过 800 µs，完整步容量约 **0.57 RTF**。10/1 各组完整步均低于 800 µs，但物理门没有通过。

## 历史 preload 对比及 sim-to-real 选择

64/16 静态完整步从同窗 preload 的 1517.2 降到 274.0 µs，约下降 **82%**，工厂阈值 `0.005 J/kg` 下三次都自然休眠。历史持续 preload 的 active/contact 完整步约 1720.7/1739.7 µs；本轮混合为 460.9/1749.2 µs。后两项是历史、不同 CPU 亲和性时段的对照，只支持无接触收益与接触仍约 1.75 ms 的量级结论，不把很小差值当成回归或收益。

混合方案撤除了**锁定空闲期**的 preload，解锁期继续保留已批准力律及其倾斜摩擦耦合；不能宣称完全消除了所有状态下的耦合。

7.4±3 N、0.4 mm 的适用性仍是 [ALPS RKJXV122400R 代表性模块资料](https://tech.alpsalpine.com/e/products/detail/RKJXV122400R/)，未建立为 Xbox 1708 实测。历史 `build/experiments/stick_click_research_20261105/REPORT.md:8,83` 将回落力、回弹力保留 null；其中旧刚度快照不是本轮 k=1000 的依据。

纯方案以原弹簧的 0–0.4 N 作为解锁保持力，导致不符合现有卸载两态判据。混合方案按裁定恢复原 preload，解锁期保持/回复力随 q 为 7.4–7.8 N（静态、未计阻尼），**这是复用已批准仿真力律，不是填补硬件 null**。释放 guard 暂用同一 7.4 N，只有 q 近零后才生效；真实释放阈值、迟滞、回落力及回弹力仍未知，交负责人决定是否采纳/测量。没有再调弹簧、阻尼、摩擦、睡眠阈值或求解器 batch。

## 正式化时调用方的接入代价

资产文件本身无法运行条件状态机。调用方必须保存 handle，在每个物理子步、完成施力之后且 `scene.step()` 之前调用一次 `handle.pre_step()`，同时处理新 scene/reset 时的状态初始化及现有 qf compose 约定；仅在 100 Hz 控制更新时调用不够。本原型使用 scene hook 让原验收入口无需修改，尚未成为公开生产 API。

只读检查的本地 RoboTwin fork HEAD 为 `57d8e9512981f4bd268f167647a4515d376e0b17`。`envs/_base_task.py` 中 `together_move_to_pose`（944）、`take_dense_action`（1537）、`take_action`（1727）的内循环均直接 `scene.step()`；稳定性检查（175/189）、相机初始化（415）及 `envs/utils/transforms.py:19` 也有物理步。正式化需统一这些已加载手柄时的步进入口，或提供等价的可靠 scene 回调。没有修改该 fork，也未实跑其任务。本轮实际采集后端接入点为源码镜像 `collection_sapien.py:288` 的内层物理循环。

因此它增加调用方的逐步接入责任，不能继续声称只导入 URDF 就具有条件 click 行为。几何/信号导入、接触动力学验收及采集实时性分别保留其证据边界。

## 我自行决定的选择

- 使用已有原生传递力 API；不新增 cache 适配库、滤波器或接触求和实现。
- 锁定采用合法 `[0,0]`，回锁 ε=1 µm；另测 1 µm 区间以检查数值行为，未将其采用为新行程。
- 释放 guard 复用 7.4 N；保留 q 条件与原弹簧/阻尼。混合 preload 来自裁定 1，不是自行加入的新物性。
- 释放角度、浅行程和 3 µm 诊断容差采用上文明确定义；最初 5 s 不足后扩至 30 s；裁定 2 后立即停止纯方案补测，只保留已完成数据。
- 主线程串行跑物理/计时，第二 agent 只读查源码及一手资料；两者没有并行争用 CPU 10。
- 复用已有 AQ probe、普通文件 support 镜像及准备资源，不启动采集链，不改变其他会话。

启动/执行修复均保留日志：测力探针最初两次在默认 scene 构造处崩溃，改用既有 CPU-only `run_suite.cpu_scene` 后成功；基线首次缺少源码包资源锁，改用和验收相同的已准备资源解析 override；释放首次字典合并重名修复一次。首次采集台计时把 hook 安在 `_PhysicsScene` 代理上，callback 数组为空，整轮作废，改挂实际底层 scene 后六组全部重跑。休眠小对照第一次沿用了已睡场景的初态，补一次唤醒后重跑，以 `sleep-probe-r1` 为准。这些修复没有调物理判据。

## 复现句柄与证据

- 分支 `perf/click-switch-limit`，基于 `9e00dd65bf5dc0597d64b221f383ece29b082eaf`；最终提交由本分支 `git log -1` 定位。
- 本机输出：主仓库 `build/experiments/station_rtf/click_switch/`；其 `handles.json`、`summary.json`、`source-sha256.json`、`raw-sha256.json` 记录路径、逐组数据及校验。大型验收 JSONL 留在节点。
- 节点运行镜像：`$NODE_WORK/station-rtf-20261110-s`，输出位于其 `code/build/experiments/station_rtf/click_switch/`。裁定 1 的历史性能结果是六个 `hybrid-*-r1` 目录；裁定 2 的最终正式性能结果为 `awake-*`。无后缀的首次 static 结果已作废。
- 共享环境只读使用 `$NODE_ENVS/sapien-3.0.3concon-xgp0.4.2-py310`；Python 3.10.12、SAPIEN `3.0.3+concon.physx5.6.1.a3`、xbox-gamepad-physics 0.4.2。
- AQ probe SHA256：`a359b8e163deaa70b1cd91732b2843808dbe8e8ad4922ebf92fb3cf09241932b`；resource manifest SHA256：`504a9cbcf33a69de73512823f6ff85aeda12ba53fa6252fb629d74dbe5e2d33b`。原接受测试所用 override 与 5 s release 字节另保存在输出的 `input/`，最终 proxy 适配仅影响采集台 hook 的实际接入。

以下为历史原型/4 ms 结果的复现入口（`run_remote.sh` 已固定 CPU 10、已有解释器、资源与 source/support 路径）：

```bash
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"

bash "$CLICK_LAUNCH" -m experiments.robotwin.click_switch.run \
  --mode hybrid --entry acceptance --suite full --iterations 64 16 \
  --output /path/to/new-acceptance-output

bash "$CLICK_LAUNCH" -m experiments.robotwin.click_switch.release \
  --mode hybrid --iterations 64 16 --duration-s 30 \
  --output /path/to/new-release-output

bash "$CLICK_LAUNCH" -m experiments.robotwin.click_switch.run \
  --mode hybrid --entry benchmark \
  --aq-probe "$CLICK_ROOT/support/reports/2026-11-09-realtime-input-lag/engine_probe.py" \
  --condition contact --iterations 64 16 --steps 3000 --repetitions 3 \
  --output /path/to/new-benchmark-output
```

替换为 10 1、static/active 或 pure 可复现相应组。原运行批次见 `run_diagnostics.sh`、`run_performance.sh`、`run_release_extended.sh` 及保留的日志；每次输出须使用新目录。模型/资料/测试文件没有写入默认生产路径，联网未使用本机代理。

# 10/1 下 View/Menu/Guide 的版本归因

**无法归因于 0.4.1 → 0.4.2：C1 对照不成立，已按原任务停止条件停止单因素实验。** 0.4.2 在 a3 的 10/1 下复现三个失败；严格 v0.4.1 源码与旧资源在 a3、官方 3.0.3 的 10/1 下也全部失败。因此目前没有确认 preload、链序、圆锥或摩擦是这些失败的原因。

## 固定条件与结果

在 the designated compute node 上，仅 CPU PhysX、TGS、cpu_workers=0、CPU affinity=[8]；CUDA_VISIBLE_DEVICES 与 DISPLAY 均为空；OMP/OpenBLAS/MKL 均1。沿用冻结 T4 executor、runner、scorer、协议及 4 ms dt。每项重新建场景，手柄和原小球读回均为10/1，未增加idle。数字阈值0.95，回位和误触发条件原样。

| 组 | 模型 / 引擎 | View min–max / 通过 | Menu min–max / 通过 | Guide min–max / 通过 | A min–max / 通过 |
|---|---|---|---|---|---|
| C0 | 0.4.2 / a3 | .777195928–.777200432 / 否 | .841431005–.999999981 / 否 | .306491186–.306499654 / 否 | .983085502–.983330643 / 是 |
| C1-a3 | v0.4.1 / a3 | .776893636–.776896301 / 否 | .841420895–.999999981 / 否 | .306490705–.306500879 / 否 | .981848372–.982132025 / 是 |
| C1-stock | v0.4.1 / 官方3.0.3 | .789275945–1 / 否 | .775338134–.775343005 / 否 | .306183966–.306191190 / 否 | .981848047–.982130857 / 是 |

12项均无误触发、internal_pairs=0、撤回后的回位时间=0。C0 View/Guide 的 termination 为 blocked，Menu 为 signal_goal；C1-a3 同样；C1-stock 的 View 为 signal_goal、Menu/Guide 为 blocked。Menu/stock View 瞬时达到目标也不能代替保持段最小值判据。

C1 的旧 click 实际读回 K=18500 N/m、D≈12.043255806 N·s/m、target≈−6 µm、全部qf=0；C0 为 K=1000、D≈2.8、target=0、两个click qf≈−7.4 N。旧源码由 v0.4.1 tag 的跟踪Python文件导出，未从新loader模拟旧版本。实际manifest、URDF、motion contract已存档；新旧全部link inertial和contact material逐字相等。C0六个关键模块的SHA与d05786c一致，C1五个关键模块与v0.4.1一致；冻结测试五个文件与本地checkout一致。

已有 `docs/reports/v0.4.2/robotwin_validation.json#view_same_input` 的官方3.0.3默认View也是 .789275945–1、a1也是 .776893636–.776896301，均失败；本轮旧模型分别重现这两个数值。`robotwin.md` 已注明历史gripper64/16有记录、历史gamepad有效求解组次数未知。因此历史23/26不能直接证明独立小球测试在明确10/1时通过。本轮未改变迭代数复跑历史完整场景，也未确认其差异原因。

## v0.4.1 → d05786c 完整模型差异及恢复方法

以 `git diff v0.4.1..d05786c -- src references` 及实际资源为依据，差异原文见原始数据 `input/model.diff`。下表的恢复方法是尚未运行的单因素定义。

| 因素 | 旧 → 新 | 恢复旧做法 |
|---|---|---|
| click持续外力 | 无 → 两个click各−7.4 N qf | 仅取消这两个qf，保留新K、D、target0；独立于完整旧click组 |
| click弹簧 | K18500 →1000 N/m；drive D12.043255373859676→2.8 N·s/m；URDF passive D .6021627686929838→.14；target−6 µm→0（manifest运行值） | 去qf，并恢复旧manifest drive及URDF派生值；cap10.4 N、travel .4 mm未变 |
| 链序 | body→x→y→click→stick → body→click→x→y→stick | 重挂接三个关节；首关节保留公共pivot，其余原点0；保留历史frame与最终stick的身份/惯性 |
| 原生圆锥 | 旧loader没有创建原生圆锥 → 两个D6 swing cone | 不创建D6。严格tag差异不是distance→D6；distance是过渡候选，只能另列诊断 |
| tilt摩擦族 | coefficient .1、drive D .00023384842283830882 → coefficient0、native params(0,0,0)、drive D加b=.0018707873827064705，合计 .0021046358055447794 N·m·s/rad | 取消native params，D恢复旧值，set_friction(.1)；K=.03487569187752837 N·m/rad和cap .024 N·m未变 |
| ABXY行程及派生动力学 | 四个artist行程 → 统一1.22 mm；连带K、D、passive D、target和信号归一化上限变化 | 每键一起恢复旧travel、K=1.57/travel、D=1.4√(K·.001)、passive=.05D、target=−.015travel及motion上下限/归一化 |
| solver策略 | loader不指定 → 明确64/16 | 本任务各组明确10/1，作为控制变量；没有实验改变它 |

ABXY精确旧值及新值：

| 键 | 旧travel m | 旧K N/m | 旧drive D N·s/m | 旧passive D | 旧target m |
|---|---:|---:|---:|---:|---:|
| A | .0008967542780293029 | 1750.7583052184757 | 1.8524271316918817 | .09262135658459408 | −.000013451314170439542 |
| B | .0013767679701224785 | 1140.3519213628506 | 1.4950216606695659 | .0747510830334783 | −.000020651519551837177 |
| X | .0007809609139585009 | 2010.3438878164234 | 1.9850123475989232 | .09925061737994617 | −.000011714413709377513 |
| Y | .001228400054203025 | 1278.0852578345107 | 1.5827340602121511 | .07913670301060756 | −.000018426000813045374 |

新四键均 travel=.00122 m、K=1286.8852459016396、drive D=1.5881735049947199、passive D=.079408675249736、target=−.0000183 m。

没有遗漏成独立数值因素的项目：

- 全部link的质量、COM、惯量及质量推导政策未变；总质量 .28 kg。链序改变让click平移子树额外包含两个frame，各 .0005 kg、对角惯量2e−8 kg·m²，这是链序后果。
- 源几何、碰撞输入、SDF构建路径未变；contact静摩擦.5、动摩擦.4、restitution .05、contact offset .0002 m、rest offset0未变。
- View/Menu/Guide自己的行程、轴、K、D、target、cap3.14 N未变；K分别1239.5174286111217 /1239.5168156383263 /2164.9840890905616 N/m，D分别1.1021465782911541 /1.102146305771407 /1.456600290851526 N·s/m。
- 公共motion由新拓扑派生的parent/child/origin、圆锥reference_link和moving_link随链序变；信号算法、deadzone和判据未改，ABXY归一化分母随travel变。
- 新增引擎版本约束、GPU preload拒绝、diagnostics的qf记录、构建依赖和文案属于兼容/证据语义；不能当作成功进入CPU仿真后的独立物理因素。

代码定位：`builders/build_kinematics.py:274,527`；`builders/build_common_motion.py:53,117`；`backends/common/physical.py:114`；`builders/build_robotwin_full_controls.py:348`；`robotwin/loader.py:218,508,548`；`robotwin/mappings.py:7,30,47`（均相对 `src/xbox_gamepad_physics/`）。

## 原因因素、机制及执行边界

**没有确认的原因因素。** 没有执行单因素、两两组合或T3v2；没有把preload休眠机制当成这些按键失败的证据。轨迹中blocked和保持段信号不足是观测结果，不能单凭它们判定求解器、壳体或驱动哪个造成失败。未做PhysX源码机制归因。

## 我自行决定的选择

1. 用严格v0.4.1 tag源码加实际旧资源做C1，避免新loader残留新行为；新旧环境均未安装或覆盖包。
2. 加A键作正常对照；官方3.0.3复查随对照批次执行。确认C1失败后，不启动后续实验。
3. 只使用一个CPU核、无渲染；没有连接采集台或硬件。
4. 首次rsync错误把占位host传入SSH wrapper，退出12，没有传输成功；改用tar流完成传输，属于传输自修1次，物理实验没有重试。
5. 删除交付脚本中未执行的因素分支；实际运行字节保存在 `input/run-controls-initial.py`。交付 `run.py` 仅保留相同的对照行为，未把未完成的单因素实现作为结果。

## 复现句柄

本地原始数据：`build/experiments/station_rtf/view_attribution/`，含三组完整JSONL、results、runtime、input_receipt、summary、日志、输入快照和 `sha256.json`。完整相对路径及环境句柄在 `handles.json`；原始数据不加入Git。

远端根：`$NODE_WORK/station-rtf-20261110/code`；原始数据在其 `build/experiments/station_rtf/view_attribution/`。环境和资源沿用上一报告 `handles.json` 指定的两套现有环境及regular-file资源副本。

对照入口：`experiments/robotwin/view_attribution/controls.sh`。它依次调用 `python -m experiments.robotwin.view_attribution.run`；输出目录必须未存在，复跑时先选新的输出句柄。旧源码快照由 `git show v0.4.1:<path>` 导出所有跟踪的package Python文件并解压到 `input/baseline041/src/`；没有修改生产路径。模型输入存档入口：`capture_inputs.py`。

源基线：v0.4.1=`3dc5734f2b04f6bae114103b7dfd4d0bab00d6c7`；0.4.2=`d05786cef6b15c4127b106622d45e6301a2c2d3f`；工作分支 `perf/station-rtf`，起点 `9e00dd65bf5dc0597d64b221f383ece29b082eaf`。负责人随后裁定改查探针；后续结果单独见 `view_probe.md`，不改写本轮停止结论。

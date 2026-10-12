# 完整控件物理资产

`full_controls` 是 Xbox One S 的首版完整物理 profile，同时提供
RoboTwin/SAPIEN 和 MuJoCo 资源。它覆盖 20 个活动关节、21 个游戏通道和一个 Pair
物理事件。当前数值用于仿真与训练启动，尚未替代真实手柄测量。

## 机构

- 左右摇杆：每侧两个倾斜转轴和一个沿杆轴的按压关节；
- D-pad：共享帽体的水平、垂直两级摇摆关节；
- LT/RT：独立转轴；
- ABXY、LB/RB、View、Menu、Guide、Pair：独立直线关节；
- 手柄机身：固定根节点；
- Pair：输出 `pair_bind_connect`，不占游戏张量通道。

运动方向、轴心和行程来自已归档 artist animation profile。摇杆参考扭矩、摇杆点击、
正面按钮和肩键参考值来自 `references/catalog.json`。扳机、D-pad、质量分配、接触材料和
1.5% 单向控件预紧均在 `references/full_controls.json` 中标明适用范围和
替换条件。真实测量与统一人工检查项目记录在 `docs/pending_user_review.md`。

双摇杆使用 `0.02` 的二维径向死区（2026-10-12 负责人选定的仿真设置，不是实测值）；
死区以内归零，死区以外保持原值，不重新缩放。摩擦系数仍为 `0.1`：
回中后可能停在归一化约 `0.005–0.0101` 处，`0.02` 为这类残留留出余量。
此前 `0.01` 设置和2026-10-09晃动实验依据保留在参考记录及历史报告中。
双扳机、按钮和 D-pad 继续使用 `1e-4` 清理求解器残差。Microsoft XInput
把实际 dead-zone 交给应用处理，并把死区外归一化列为可选；SDL3 返回轴状态，W3C
Gamepad 对轴做线性归一化。因此游戏侧 dead-zone 将作为独立策略配置，不写进原始设备层。

十字键信号在 `GamepadSignalController.encode` 完成拆分、死区和径向处理后，
对上、下、左、右四个通道分别模拟触点闭合：归一化幅值低于触发阈值就输出0，
达到或超过时保留原有连续值，不放大到1。四个方向独立判断，真正的斜向按压
可以同时输出两个方向。
阈值从 `references/full_controls.json` 的
`signal_policy.dpad_contact_closure.threshold` 读取，当前为满行程的30%（0.3，无量纲），
是**未实测的测试值**，用于区分微小正交运动与有意触发；不是实物开关参数。
未来需同步测量翻转角和每个方向的电触点通断，重复按下/释放及斜向动作，
分别标定闭合、断开阈值和滞回，再替换测试值。
仅关节状态到32维信号的encode有这一处理；decode_joint_targets和其他通道不变。
RoboTwin和MuJoCo共用控制器，所以信号行为同时作用于两后端；
MuJoCo冻结文件不改。代码独立安装时应在其运动资源中提供同一signal_policy记录；
缺少阈值会明确报错，不静默写死0.3。

RoboTwin 中四个摇杆倾斜关节的无量纲 PhysX 摩擦系数设为 `0.1`。这是用户指定的
仿真参数，尚未由实物测量确认。

关节拓扑、每轴运动范围、二维径向约束和信号绑定统一发布在
资源根目录下的 `common/xbox_one_s/motion/full_controls.json`。RoboTwin 运行时直接读取该
公共契约，并在 URDF 加载后应用其中的关节限位；backend manifest 不再复制运动约束。
MuJoCo 构建器和运行时信号控制器也读取同一份契约。

## 生成

```sh
python -m xbox_gamepad_physics build-resources
python -m xbox_gamepad_physics verify \
  --backend all --profile full_controls
```

依赖图见 `scripts/build_resources.py`。MuJoCo 资源目前冻结在
`src/xbox_gamepad_physics/resource_data/mujoco/`，构建时原样复制，不重新生成。

## RoboTwin / SAPIEN

`full_controls` 默认使用闭合meshbase的SDF碰撞体，RoboTwin extra固定为SAPIEN 3.0.3。
CoACD作为显式变体保留：`load_into_scene(..., collision="coacd")` 或实验配置
`gamepad.collision: coacd`，支持3.0.0b1和3.0.3。低版本默认调用报错，
给出升级到3.0.3或显式选择CoACD两条出路，不静默回退。
CoACD 固定为 1.0.14、seed 0、单线程；参数和实测误差见
`references/full_controls.json`。SDF spacing 为 1 mm，需要 SAPIEN ≥3.0.3，不能与
`add_ground` 平面或另一个 SDF 物体碰撞，支撑桌面应使用静态盒子。

两种变体均保留碰撞组 g0/g1，将 g2 加上 `0x80000000` 并设置 g3 为 `0x5842`。
共享忽略位且 ID 相同的手柄内部形状不产生碰撞；手、桌面等外部形状仍按原有
接触类型和亲和组碰撞。十字键、摇杆孔口可触区域约 1–1.5 mm 的外胀已由负责人
于2026-10-11暂时接受；Guide开口覆盖现已由SDF对照确认，CoACD优化留待下一阶段。

运动部件质量来自 meshbase 闭合体积、密度和填充系数；摇杆两层壳先求并集，
完整惯量张量以连杆局部坐标系中的质心为参考点。总质量仍为 0.28 kg。
本次碰撞与质量改动只作用于 RoboTwin `full_controls`。

```python
from xbox_gamepad_physics import load_motion_contract
from xbox_gamepad_physics.robotwin import load_into_scene

motion = load_motion_contract("full_controls")
left_stick_x = motion.joint_by_name["left_stick_x"]

gamepad = load_into_scene(
    scene,
    pose=sapien.Pose(),
    fixed_root=True,
    profile="full_controls",
)

state = gamepad.gamepad_state()
events = gamepad.physical_events()

# 真实手柄或鼠标状态同步到仿真姿态
gamepad.set_gamepad_state(state)
gamepad.set_physical_events({"pair_bind_connect": 0.0})

# 需要由 SAPIEN drive 追踪时
gamepad.set_gamepad_targets(state)
```

非视觉运行脚本：

```sh
python run_robotwin.py configs/smoke_full_controls.yaml \
  --set params.steps=2000 --output /tmp/robotwin-full-controls
```

## MuJoCo

```python
from xbox_gamepad_physics.mujoco import load_scene

loaded = load_scene(profile="full_controls", scene="fixed")
state = loaded.gamepad.gamepad_state()
loaded.gamepad.set_gamepad_state(state)
loaded.gamepad.set_physical_events({"pair_bind_connect": 0.0})
```

非视觉运行脚本：

```sh
python examples/mujoco_full_controls_smoke.py \
  --steps 2000 --output /tmp/mujoco-full-controls.json
```

自编译 MuJoCo 3.15 使用 Conda 环境内的新版 `libstdc++`。将仓库中的激活脚本安装到
对应环境后，普通 `conda activate` 即可加载：

```sh
cp requirements/conda/activate.d/concon-mujoco-libstdcxx.sh \
  "$CONDA_PREFIX/etc/conda/activate.d/"
cp requirements/conda/deactivate.d/concon-mujoco-libstdcxx.sh \
  "$CONDA_PREFIX/etc/conda/deactivate.d/"
```

构建产物的 `_specs.so` 需要 `CXXABI_1.3.15` 和 `GLIBCXX_3.4.32`；Ubuntu 22.04
系统库不满足，环境内 `libstdc++.so.6.0.36` 满足。该问题已经定位为动态链接路径，
不属于 MJCF 编译错误。

## 自动运行记录

- SAPIEN 3.0.0b1：20 关节、21 通道、Pair 事件、2000 步有限；并发命令回读最大误差
  `2.02e-8`；
- MuJoCo 3.15.0：20 关节、20 传感器、21 通道、Pair 事件、2000 步有限；并发命令
  回读最大误差 `1.11e-16`；
- MuJoCo 使用 `discrete` 积分器处理高刚度小质量按钮；只排除了实际诊断到的
  `controller_body` 与 LT/RT 粗略碰撞 proxy 的内部重叠。

这些记录证明资源可以加载、步进和读写信号，不代替用户视觉检查或真实手柄标定。

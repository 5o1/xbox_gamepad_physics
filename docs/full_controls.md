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

双摇杆使用 `0.01` 的二维径向死区；死区以内归零，死区以外保持原值，不重新缩放。
双扳机、按钮和 D-pad 继续使用 `1e-4` 清理求解器残差。Microsoft XInput
把实际 dead-zone 交给应用处理，并把死区外归一化列为可选；SDL3 返回轴状态，W3C
Gamepad 对轴做线性归一化。因此游戏侧 dead-zone 将作为独立策略配置，不写进原始设备层。

RoboTwin 中四个摇杆倾斜关节的无量纲 PhysX 摩擦系数设为 `0.1`。这是用户指定的
仿真参数，尚未由实物测量确认。

关节拓扑、每轴运动范围、二维径向约束和信号绑定统一发布在
`resource_data/common/xbox_one_s/motion/full_controls.json`。RoboTwin 运行时直接读取该
公共契约，并在 URDF 加载后应用其中的关节限位；backend manifest 不再复制运动约束。
MuJoCo 构建器和运行时信号控制器也读取同一份契约。

## 生成

```sh
python scripts/build_common_motion.py
python scripts/build_robotwin_full_controls.py
python scripts/build_mujoco_full_controls.py
python -m xbox_gamepad_physics verify \
  --backend all --profile full_controls
```

## RoboTwin / SAPIEN

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
python examples/robotwin_full_controls_smoke.py \
  --steps 2000 --output /tmp/robotwin-full-controls.json
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

# RoboTwin backend 接入

## 接口边界

RoboTwin backend 的正式入口是：

```python
from xbox_gamepad_physics.robotwin import load_into_scene

gamepad = load_into_scene(
    scene=task.scene,
    pose=gamepad_pose,
    fixed_root=True,
    profile="full_controls",
)
```

包内代码不导入 RoboTwin 的任务模块，也不修改任务注册表。它只依赖调用时传入的
SAPIEN scene。`GamepadState`、通道 mask 和信号映射位于后端无关的公共层；返回的
`XboxOneSArticulation` 提供具名关节访问、状态读写和 drive target 接口。

## 位姿所有权

`pose` 完全由调用者决定，表示 `controller_body` 根 link 在调用者场景坐标系中的位姿。
可以传入 `sapien.Pose`，也可以传入米制的
`[x, y, z, qw, qx, qy, qz]`。包内不提供桌面位置、治具变换或机械臂基座变换的默认值。
`fixed_root` 同样由任务选择。

## RoboTwin 生命周期

RoboTwin `ea8b21121ebb3cd201ff5b3fe361944ac94eda3f` 的 `Base_Task._init_task_env_()`
依次创建 scene、桌面、机器人和相机，然后调用任务的 `load_actors()`。因此任务应在
`load_actors()` 中加载手柄，并把返回 handle 保存为实例成员。每次 `setup_demo()` 创建
新 scene 时会得到新的 handle。

可复制的最小任务模块见
[`examples/robotwin_gamepad_asset_probe.py`](../examples/robotwin_gamepad_asset_probe.py)。
它只展示消费端接入，不定义机械臂动作、奖励或训练逻辑。

## 原生目录复制

`install-robotwin` 仅用于需要 `assets/objects/xbox_one_s` 文件布局的工具。复制资源不会
注册 RoboTwin 任务，也不会建立 `GamepadState` 映射。常规任务接入直接使用 Python
公共接口即可。

## 当前验收边界

仓库测试覆盖直接 SAPIEN scene、带 `.scene` 的任务对象、具名关节绑定、数值位姿格式、
drive 配置以及状态往返。固定 RoboTwin 源码上的消费端检查入口是：

```sh
python scripts/validate_robotwin_task_integration.py \
  --robotwin-root /path/to/RoboTwin \
  --pose 0 0 0.8 1 0 0 0 \
  --output /tmp/xbox-robotwin-task.json
```

该检查按正常 `Base_Task` 初始化顺序创建桌面、机器人、相机和手柄，只执行状态往返与十个
仿真步。2026-10-09 在 RoboTwin
`ea8b21121ebb3cd201ff5b3fe361944ac94eda3f` 上执行通过：20 个活动关节、21 个可用游戏通道，
四个并发输入的最大往返误差低于 `1.3e-8`。场景同时包含 ALOHA 双臂 articulation 和手柄
articulation；第二次 `setup_demo()` 会重建 scene/handle，并从中立手柄状态开始。记录见
[`references/robotwin_backend_validation.json`](../references/robotwin_backend_validation.json)。

相机画面、机械臂接触和完整控件运动仍由用户逐项验收。

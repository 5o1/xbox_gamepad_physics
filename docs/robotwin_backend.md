# RoboTwin backend 接入

## 安装与构建

首发面向 Linux x86_64 + NVIDIA、Python 3.10、RoboTwin fork + SAPIEN 3.0.3。
从 Release 取得 wheel、输入 zip 和 `SHA256SUMS`，安装 wheel 的 `[build,robotwin]`
依赖；不通过 PyPI 分发。

```sh
python -m pip install "./xbox_gamepad_physics-0.4.0-py3-none-any.whl[build,robotwin]"
python -m xbox_gamepad_physics build-resources \
  --archive ./xbox_gamepad_physics-resources-0.4.0.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
python -m xbox_gamepad_physics verify --backend robotwin --profile full_controls
```

wheel 自带 DAG、生成器与小证据；输入 zip 保存原 GLB、冻结 static visual、visual_meshbase、collision meshbase、
v0.2.0 CoACD 和批准的 Cycles 场景及其必要归属。首次使用在用户资源目录生成运动学、
运动契约、视觉、URDF/manifest 与 SDF 网格，基础构建不需要 Blender，不运行 CoACD。
第二次检查缓存，缺失或过期时只重建相关下游。环境变量目录同样执行 prepare。
完整导入和维护者说明见 [`importing.md`](importing.md)。

MuJoCo 不在 v0.3+ 发布范围内。B1+B2 验证资源构建；新 wheel 的真实 SAPIEN 加载、
交互与原生渲染在 B4 的 GPU 环境单独验收。

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

资源目录中的网格和 URDF 是内部构建产物。直接导入会绕过外观材质、SDF 配置与信号映射；
应使用 `load_into_scene`。英文完整接入指引见 `xbox-gamepad-physics guide`，环境、资源与
可选 extras 检查见 `xbox-gamepad-physics doctor`；场景建好后可调用公开的
`diagnose_scene(scene)`，它只报告、不修改场景，并识别直接导入和 SDF 配平面等常见错误。

新建实验台使用公开的 `xbox_gamepad_physics.robotwin.create_scene`；下游不要导入内部
`examples` 模块。默认光栅渲染即可显示 ABXY 字样。复现审查图时才显式调用公开的
`apply_review_rendering`：它修改 SAPIEN **全局**相机着色器和光追设置，会影响所有相机，
不适合作为向已有实验台注入手柄的隐式步骤。`load_into_scene` 不选择全局渲染设置。

加载器保留碰撞 `groups[0]`、`groups[1]`，占用 `groups[2]` 的 bit31
（`0x80000000`）并设置 `groups[3]=0x5842`，用于屏蔽手柄内部碰撞。
调用方若给其他对象复用同一 bit 和标识，会产生接触过滤冲突，须检查自己的分组分配。

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

## 安装包中的 example、viewer 与 overlay（B3a）

这些入口直接使用 wheel 内实现和静态模块，不需要本项目检出、CDN 或首次 npm 下载。

```sh
python3.10 -m pip install "./xbox_gamepad_physics-0.4.0-py3-none-any.whl[example]"
xbox-gamepad-physics example export ./gamepad_example
python3.10 ./gamepad_example/run_robotwin.py --help
```

导出目录含一个薄入口和 `smoke_full_controls.yaml`、`render_review.yaml`。实际运行需用户自己的
SAPIEN 3.0.3/RoboTwin fork 环境及已准备资源；可加装 `[build,robotwin,example]`，先按资源导入
说明离线构建，再执行：

```sh
python3.10 ./gamepad_example/run_robotwin.py ./gamepad_example/smoke_full_controls.yaml --resources ./gamepad_resources
python3.10 ./gamepad_example/run_robotwin.py ./gamepad_example/render_review.yaml --resources ./gamepad_resources --output ./review_output
```

默认输出在用户 cwd 的 `build/runs/`，`--output` 可指定位置；记录包、SAPIEN 和资源版本。
Git 仅在代码来自检出且 Git 可用时记录，缺 Git 不阻塞。渲染 example 沿用共享 RT 配置，
原生 SAPIEN 场景不强制提供 RoboTwin 根；已有平台调用可继续显式传 `scene.robotwin_root`。
真实加载、外观与交互验收留 B4。

```sh
xbox-gamepad-physics viewer --resources ./gamepad_resources --offline --blender /path/to/blender
xbox-gamepad-physics overlay
xbox-gamepad-physics overlay --trace-dir ./my_traces --port 8770
```

viewer 使用输入包的已审 `.blend`，Blender 4.5 可执行文件由用户通过 `--blender` 提供。
未提供 Blender 时，静态页面仍可打开，Cycles 请求明确返回 503 并说明缺少 Blender；
这不代表已有渲染画面。viewer 只准备同一 DAG 的运动学节点，基础静态服务不要求 SAPIEN。
UI、overlay、Three.js 所需模块及其 MIT/Unlicense 许可随 wheel 分发。参考 PNG 是模型派生资产，随输入 zip 分发并附 CC BY 4.0 归属；viewer 从资源根的 `inputs/assets/xbox_one_s/render/` 读取，缺图时原位置显示“缺少输入资源”，页面仍可使用。

overlay 默认打印带小型 canonical demo trace 的本地地址；demo 是合成示例，不冒充物理读回。
自有 trace 放到 `--trace-dir` 后，在打印地址中改成 `trace=/traces/<文件>.json&autoplay=1`。
显示阈值、连续幅值和上游信号映射均不改。

检出中的 `python3 run_robotwin.py ...`、`npm run viewer`、`npm run gamepad-overlay` 保留薄入口。
### 遥操作：默认单机，远程可选

首发目标是 Linux x86_64 + NVIDIA、Python 3.10、SAPIEN 3.0.3。安装本地 Release wheel 的
`[robotwin,teleop]` extras；teleop extra 同时包含离线资源构建所需的依赖。FFmpeg、NVIDIA
驱动和 Vulkan 是系统前置条件：FFmpeg 必须带 `h264_nvenc` 并能在所选 GPU 实际编码；
浏览器需要支持 H.264 WebCodecs 和 Pointer Lock。Node、Blender、SSH、WSL 都不是单机依赖。
夹爪使用**用户自己的 RoboTwin aloha-agilex** URDF、其引用的 mesh 和根 `LICENSE`，
路径为 `assets/embodiments/aloha-agilex/urdf/arx5_description_isaac.urdf`；这些外部资产不放入本包的 zip。

```sh
python3.10 -m pip install './xbox_gamepad_physics-0.4.0-py3-none-any.whl[robotwin,teleop]'
xbox-gamepad-physics build-resources --archive ./xbox_gamepad_physics-resources-0.4.0.zip --resources ./gamepad_resources --offline
xbox-gamepad-physics teleop --robotwin-root /path/to/RoboTwin --gpu 0 --resources ./gamepad_resources --output ./teleop_session --port 8775
```

默认 `--mode local`、仅监听 `127.0.0.1`，三个进程均使用当前 Python。
`--output` 为本次新目录；已有目录和端口冲突会明确拒绝，不结束占用者。等物理、渲染和首个编码帧
使 health 就绪后才打印 URL；`--open-browser` 可选。`--stream-python` 可选择已安装本 wheel 的
推流解释器，`--simulation-python` 可显式选择物理/渲染解释器；未覆盖的解释器保持当前 Python。
单机入口不读取 `configs/local/`。`--render-candidate rt|raster` 和 `--collision sdf|coacd` 可选，默认沿用 rt/SDF。

远程机器应预装同一个 wheel 和资源。用用户自己的 OpenSSH alias 即可创建 localhost 隧道，
不需要同步仓库；下列远程路径须替换为该机器上的真实路径：

```sh
xbox-gamepad-physics teleop --mode remote --ssh '<ssh-alias>' --remote-python /path/to/venv/bin/python --robotwin-root /path/to/RoboTwin --gpu 0 --resources /path/to/resources --output /path/to/new-session --port 8775 --local-port 8775
# 也可用 user@host 加 --identity /path/to/key --ssh-port <port>。
# 占位符模板：configs/teleop_remote.example.env；显式 --site <file> 才读取。
```

Windows relay 只用于 GPU + WSL + Windows 拓扑：remote 下显式加 `--windows-relay --wsl-interface <interface> --relay-port <port>`。
负责人现有 `bash scripts/teleop_session.sh` 继续读取忽略的站点配置，作为 remote 薄入口；GPU 上需要预装本 wheel，
不再 rsync 整个仓库。它保留 G 的端口身份检查、仅显式 `--stop-existing` 关闭确认的旧会话/隧道、FIFO EOF 清理和超时 watchdog。
该站点适配器的 WSL/Windows 字段继续兼容原配置；可用 `--port`、`--local-port`、`--relay-port` 覆盖测试端口。
local 不调用 G 的远程端口识别或清理。remote 的网关脱离 SSH 会话运行，输出写入远端会话目录的 `gateway.log`；HTTP shutdown、信号和隧道空闲超时共用退出路径。清理会检查本会话进程身份并明确报告失败。Linux/WSL 的正常起停、断开 SSH 后 watchdog 退出，以及主助手沙箱外执行的完整 Windows relay 起停均已通过；K3b 证据见 `build/experiments/release_v030_b3b/ruling1/K3B_RESULT.md`。证据与操作步骤见 `build/experiments/release_v030_b3b/ruling1/REPORT.md`。`--skip-windows-relay` 仅用于 K3a 验证，正常工作流不需要它。

新 live 记录为 **schema 6**：G 的 held 速度/牵引逻辑和 H 的逐指速度驱动保持，网页显示实际关节行程，
overlay 忠实呈现上游信号、阈值不变。schema 3/4 保留即时位置目标，schema 5 保留推进位置目标。
回放在新场景执行记录命令，不把记录的位姿强灌回场景：

```sh
xbox-gamepad-physics teleop-replay ./record.xgpr --resources ./gamepad_resources --robotwin-root /path/to/RoboTwin --output ./replay --steps 300
```

去掉 `--steps` 则回放全部可读记录；JSONL 和二进制 xgpr 均支持。资源和 SAPIEN 版本须与源记录匹配；
记录内的外部资产路径可由 `--robotwin-root` 重定位。`experiments/teleop_replay.py` 和旧 `teleop.*` 检出入口保留兼容包装。

## 运行时固定或释放手柄根部

`load_into_scene(..., fixed_root=...)` 的参数仍决定初始状态。返回的手柄对象提供只读 `root_fixed` 和 `set_root_fixed(fixed: bool)`：只能在前一次 `scene.step()` 完成后、下一次开始前调用，不能与物理步并发。同一棵 articulation 的根关节原地切换，保留根部位姿、关节角/速度及驱动目标，不重新加载资源。

```python
import sapien
from xbox_gamepad_physics.robotwin import load_into_scene

scene = sapien.Scene()  # CPU PhysX；渲染可以使用 GPU
scene.set_timestep(1 / 250)
table = scene.create_actor_builder()
table.add_box_collision(half_size=[0.5, 0.5, 0.025])
table.add_box_visual(half_size=[0.5, 0.5, 0.025])
support = table.build_static(name="support_table")
support.set_pose(sapien.Pose([0, 0, -0.025]))
pad = load_into_scene(scene, sapien.Pose([0, 0, 0.4]), fixed_root=False,
                      collision="sdf")
transition = pad.set_root_fixed(True)
assert pad.root_fixed
signals = pad.gamepad_state()
print(signals.channel("left_x"), transition["signal_delta"])
for _ in range(100):
    scene.step()
pad.set_root_fixed(False)
for _ in range(100):
    scene.step()  # 自由根部恢复重力运动
```

参数必须是 Python `bool`，其他类型报 TypeError。目标状态相同时返回 `None`，不写状态、不唤醒；发生切换时返回字典：`from`/`to` 为 `moving` 或 `fixed`，`pose` 是切换前 `[x,y,z,qw,qx,qy,qz]`（米及四元数），`joint_positions` 和 `drive_targets` 按关节名记录切换前快照，`signal_delta` 是全部标准通道的切换后减切换前差。遥操作 G 直接调用该接口，记录字段和 schema 3–6 的行为保持原样，schema 不升级。

速度语义保持已批准的遥操作实现：**释放时显式清零根部线速度和角速度，再 wake_up；固定时设置 eFIX_BASE，由下一次物理步的求解器使用零根速度，不额外写速度。** 因而固定调用刚返回、尚未 step 时，速度 getter 可能保留旧值，不能将它误解为固定根还会运动。依据是 [SAPIEN 3.0.3 根关节实现](https://github.com/haosulab/SAPIEN/blob/3.0.3/src/physx/articulation_link_component.cpp#L36)：根分支设置 `PxArticulationFlag::eFIX_BASE`；[PhysX 5.3.1 的固定基求解分支](https://github.com/NVIDIA-Omniverse/PhysX/blob/105.1-physx-5.3.1/physx/source/lowleveldynamics/src/DyFeatherstoneArticulation.cpp#L4443) 将根运动速度与加速度设为零。没有为了统一接口而改变既有回放的即时速度字段。

适用范围是 **SAPIEN 3.0.3 的 CPU PhysX**。根类型切换走 eFIX_BASE，不是内部关节的 `setJointType`；[PhysX API 实现](https://github.com/NVIDIA-Omniverse/PhysX/blob/105.1-physx-5.3.1/physx/source/physx/src/NpArticulationReducedCoordinate.cpp#L94) 允许在物理步之外设置 articulation flag。[SAPIEN 构建配置](https://github.com/haosulab/SAPIEN/blob/3.0.3/cmake/physx5.cmake#L5) 指定 PhysX 5.3.1。

本接口的实际切换在 `PhysxGpuSystem` 下明确抛出 `SceneCompatibilityError`，包括 GPU/批量 PhysX。原因是完整的释放/记录契约需要逐对象 CPU 速度和状态访问，而 [PhysX 5.3.1 的根速度写入](https://github.com/NVIDIA-Omniverse/PhysX/blob/105.1-physx-5.3.1/physx/source/physx/src/NpArticulationReducedCoordinate.cpp#L448) 在 Direct GPU API 初始化后非法；[SAPIEN 的 GPU 状态接口](https://github.com/haosulab/SAPIEN/blob/3.0.3/src/physx/articulation.cpp#L239) 也限制逐对象 qvel。不能仅凭 flag getter 改变就声称 GPU 整套语义成立。本接口不提供重建 GPU batch 或缓存重初始化方案。GPU 机器上的 CPU 物理配合 GPU 渲染属于支持路径；多个 CPU 场景也不等同于 GPU 批量物理。重复请求相同状态仍为无操作。

已知问题：手柄倾斜冻结后，摇杆信号会偏约 **0.03**。负责人决定暂不处理；观察和证据见 [倾斜摇杆偏移报告](reports/stick_tilt_deflection_20261013/REPORT.md)。本接口不补偿该偏移。

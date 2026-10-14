# Xbox 手柄物理资产

这个仓库维护 Xbox 手柄的视觉候选、交互预览、物理规格和来源记录。
游戏强化学习、VLA 和机械臂控制不在这里实现。

当前只分发 Xbox One S 的模型资产。Switch Pro 和旧 Xbox Series X|S 候选模型保存在
GPU 节点，存档位置见 `references/archive/switch_pro_candidates.json` 和 `assets/asset_index.json`。
仓库保留相关历史报告、图片和来源记录；旧型号已退出查看器可选入口。

RoboTwin完整控件默认使用 **SDF碰撞体、SAPIEN 3.0.3**；v0.3.0 使用 Release wheel 的 `[build,robotwin]` 安装方式，见下文。
CoACD仍可显式选择`collision="coacd"`，包括旧3.0.0b1环境；默认SDF在低版本会明确报错。
SDF手柄的支撑桌面使用静态盒子，不能使用`add_ground`平面。

## 当前状态

运行状态以 [资产索引](assets/asset_index.json) 为准；README 只提供入口和边界说明。

| 项目 | 状态 |
|---|---|
| 目标实物 | Xbox One S；由持有者明确确认 |
| 目标外观资产 | BatonyRobson 的 Xbox One S 模型；已选定 |
| 物理几何标定 | 局部尺寸、内部结构和关节位置尚未实测 |
| Viewer kinematics | 可交互的运动学预览，不是可训练物理资产 |
| 旧 Casper 候选 | 外观特征更接近 1914；模型在 GPU 节点存档，不分发 |
| 动力学 | `full_controls` 已覆盖 20 个关节；参数仍待实测替换 |
| v0.3.0 发布后端 | Linux x86_64 + NVIDIA、Python 3.10、RoboTwin fork + SAPIEN 3.0.3；MuJoCo 历史基线留在 Git |
| 真实手柄验收 | 尚未执行 |

主候选的来源、许可和文件身份记录在
[候选清单](references/xbox_replacement_candidates.json)。它使用 16 个视觉节点和作者动画信息
生成 Viewer 运动学；统一尺度来自候选整体宽度与微软公布宽度之比。
目标产品与外观资产已确认。尺度拟合用于交互预览；真实轴心、行程和受力保持待标定状态。

旧 Casper 资产的型号判断见 [几何复核](references/geometry_review.json)。它的 Share 键、圆盘方向键
和接口外形与目标 Xbox One S 不符；宽度缩放派生物只用于历史 viewer 回归。

## 第一阶段验收

[交互验收规格](specs/interactive_acceptance.json)规定了两个必须同时通过的方向：

1. 用鼠标拖动可见的摇杆、按钮、扳机或方向键，产生对应的虚拟手柄状态。
2. 读取用户电脑上的真实手柄状态，驱动同一组可见部件运动。

验收还要求：

- 中立位、端点、对角和多控件并发输入均可检查；
- 失焦、断开、取消拖动和模式切换后不能残留输入；
- 未识别的设备布局必须拒绝，不能猜测轴或按钮顺序；
- 演示结果需要人工查看错误轴向、错误轴心、脱离和穿插；
- 交互通过不等于碰撞、摩擦、回弹或手指接触已经通过。

浏览器检查器仍按 Web Gamepad API 传输 21 个浮点数：4 个标准轴，随后是 17 个
标准按钮值。这只是一种浏览器边界格式。

Python 公共状态接口采用版本化的 `sdl3-gamepad-core-v1`：先放 SDL3 的 6 个标准轴，
再放 26 个标准按钮，共 32 维。每个状态同时携带 `available_mask`、`task_mask` 和
`device_id`；不可用通道必须补零，动作损失和执行使用两个 mask 的交集。Xbox One S
设备能力占其中 21 个通道，Pair 键不属于游戏控制。左摇杆局部 profile 只把
`left_x/left_y` 标为可用；完整 profile 提供全部 21 个设备通道。浏览器、游戏或训练
代码接入时必须按名称适配，不能按下标直连。

`GamepadSignalController` 是仿真后端之外的公共信号层。两个后端都向它提供具名关节
位置；归一化、饱和、双摇杆圆形约束、D-pad 拆分和状态 mask 都由该层生成。反向接口把
真实手柄或鼠标状态转换为同名关节目标。

## 虚拟手柄信号预览

仓库内置了基于开源 `gamepad-overlay` SVG 渲染器的 32 维状态适配器。启动静态服务：

```sh
npm run gamepad-overlay
```

打开以下地址可循环播放左摇杆单位圆轨迹：

```text
http://127.0.0.1:8770/viewer/gamepad_overlay/index.html?source=canonical&trace=/build/experiments/gamepad_overlay_left_stick_circle/trace.json&autoplay=1
```

页面同时显示关节角、`left_x/left_y`、信号半径和虚拟摇杆位置。项目适配器只接受
`sdl3-gamepad-core-v1` 的 32 维值、两个 mask 和 `device_id`，不会按 W3C 下标猜测输入。
正式演示视频以 RoboTwin/SAPIEN 手柄为主画面，并把透明虚拟手柄叠加在右下角。
视频生成到 `build/experiments/gamepad_overlay_left_stick_circle/`，不进入 Git。
圆周轨迹作为运动学测试输入写入 articulation；渲染循环随后读回实际 `qpos`，调用
`GamepadSignalController` 生成 `observed_trace.json`，overlay 只消费该读回记录。该演示
验证关节状态到信号的链路，不包含手指接触或动力学驱动声明。

## 关键入口

- [资产索引](assets/asset_index.json)：候选、派生版本和准入状态。
- [目标物理规格](specs/xbox_v1.json)：部件、物理字段和未决项。
- [交互验收规格](specs/interactive_acceptance.json)：浏览器双向交互的验收门禁。
- [32 维张量契约来源](references/gamepad_tensor_contract_v1.json)：通道顺序、mask 与设备标识的依据和项目选择。
- [虚拟手柄适配器](viewer/gamepad_overlay/index.html)：将 canonical 状态交给现成 SVG 手柄渲染器。
- [完整控件使用说明](docs/full_controls.md)：20-DOF 双后端资产、信号接口和运行记录。
- [RoboTwin backend 接入](docs/robotwin_backend.md)：公共接口、位姿所有权和真实任务生命周期接入点。
- [MuBlE 适配器](src/xbox_gamepad_physics/muble/)：从公共 MuJoCo 接口导出 body pose，并驱动已验收 Blender 对象。
- [待统一确认与实测清单](docs/pending_user_review.md)：延后处理的视觉确认和硬件测量。
- 完整控件逐项验收材料：生成到 `build/experiments/full_controls_user_review/`，不进入 Git。
- Viewer 运动学与参数依据：由包内同一 DAG 生成到资源根的 `kinematics/`。
- [官方尺寸记录](references/1708_dimensions.json)：整体尺寸及其适用边界。
- [方向键记录](references/1708_dpad_assembly.json)：十字键整体结构证据。
- [扳机记录](references/1708_trigger_mechanism.json)：外帽、内部组件和缓冲接触证据。
- [FCC 照片记录](references/1708_fcc_internal.json)：内部照片来源与限制。
- [第三方声明](THIRD_PARTY_NOTICES.md)：进入 Git 的第三方内容及许可证。

目录分工：

- `assets/` 保存轻量运行描述；
- `src/xbox_gamepad_physics/` 保存公共状态接口和双后端运行时；
- `schemas/` 保存可发布资源的 manifest 格式；
- `docs/` 保存导入与维护约定；
- `references/` 保存来源、推导和适用范围；
- `specs/` 保存当前规格和明确的未知项；
- `viewer/` 保存浏览器检查器；
- `scripts/` 保存构建、转换和审计程序；
- `tests/` 保存当前行为的回归测试；
- `build/experiments/` 保存本地实验构建产物，不进入 Git。

`build/experiments/` 中的材料只代表对应运行，不自动代表当前 HEAD 已通过。

## 快速检查

Python 环境使用 3.10。完整依赖快照位于
[gpu-tested.freeze.txt](requirements/gpu-tested.freeze.txt)，直接依赖约束位于
[gpu-tested.constraints.txt](requirements/gpu-tested.constraints.txt)。JavaScript 测试使用
[`.node-version`](.node-version) 所列 Node 版本。

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements/gpu-tested.freeze.txt
npm ci
```

检查 Viewer 运动学生成逻辑与来源：

```sh
python3 scripts/build_kinematics.py --check
```

运行默认回归：

```sh
python3 scripts/run_regression.py fast
```

安装 Release v0.3.0 的 wheel 并离线导入输入包（不上 PyPI）：

```sh
python3 -m pip install "./xbox_gamepad_physics-0.3.0-py3-none-any.whl[build,robotwin]"
python3 -m xbox_gamepad_physics build-resources \
  --archive ./xbox_gamepad_physics-resources-0.3.0.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
python3 -m xbox_gamepad_physics verify --backend robotwin --profile full_controls
```

wheel 包含构建器、小证据与规则；输入 zip 只含作者原 GLB、已批准静态 visual、meshbase、
冻结的 v0.2.0 CoACD、批准的 Cycles 场景及其必要来源与许可。运动学、运动契约、
sim_visual、URDF/manifest 和 SDF 网格在用户机器上首次构建，输入不变时命中缓存。
静态 visual 与 meshbase 都是冻结快照，基础构建不需要 Blender，也不调用 CoACD。
环境变量指定的资源目录同样会检查和准备，目录存在不会跳过构建。
解析顺序、共享缓存和维护者打包方式见 [导入约定](docs/importing.md)。

仓库开发可用 `python3 -m pip install -e ".[build]"`；既有 setuptools 59 环境可加
`--no-build-isolation`，`setup.py` 与 pyproject 元数据同步。用户 `[build]` 不含 CoACD，
维护者显式重新分解时另装 `[build,maintainer]`，并先归档旧快照。

v0.3.0 提供 RoboTwin `full_controls` 与局部 `left_stick`。MuJoCo 不在 v0.3.0 发布范围内；
其冻结树只作 Git 历史基线，不进入运行时 DAG 或发布资源。真实 SAPIEN 加载、交互与渲染
在 B4 GPU 验收，资源构建检查不替代该验收。

需要定位失败时，可直接运行底层测试：

```sh
python3 -m unittest discover -s tests
node --test tests/test_*.mjs
```

## example、viewer 与 overlay

安装包的公开命令与离线资源准备见下文“安装包中的 example、viewer 与 overlay”。
smoke/render_review 的唯一实现、共享场景与配置已在 wheel 内；根入口是薄包装，默认输出在用户 cwd。
原生 render_review 不强制 RoboTwin 根，旧的平台调用仍可显式提供。

检出可运行 `npm run viewer -- --blender /path/to/blender` 和 `npm run gamepad-overlay`；
UI、Three 模块闭包与许可都在包内，不需要先 npm ci。viewer 的输入 zip 使用已审场景，
缺少 Blender 时显示明确的 Cycles 不可用错误；真实外观与交互由 B4 验证。
旧的 --assets/--vendor/--cycles-command 检出入口由显式 --resources/--blender 的安装包入口替代。

## 建模原则

- 正式采用的物理参数必须记录来源、单位、适用范围、推导和不确定性。
- 可以在实测前使用有来源的估计值，但必须标记为 estimated，并说明如何被后续测量推翻或修正。
- 无法从资料推断的值保持 `null/unknown`，不能静默使用仿真器默认值。
- 外观确认、整体尺度、作者动画和软件夹具不能替代机械结构证据。
- visual mesh、collision mesh、刚体/关节和输入映射分别验收。
- 原始第三方文件保持不变；派生物记录上游版本、许可证、哈希和处理方法。
- 大型源网格、数据集、权重和可重建中间产物保存在 GPU 节点，不提交到 Git。

现有参考元件和拆解资料只能支持其明确给出的范围。例如，开关操作力和行程不能唯一确定
回弹曲线，整体重量不能分配为各部件质量，二维照片中的刻度也不能直接给出三维轴心。

## 下一步

当前计划和待办见 [计划](docs/plan.md)，完整过程与证据见[阶段报告](docs/reports/xbox_one_s_physics_asset_report.html)。

## 安装包中的 example、viewer 与 overlay（B3a）

这些入口直接使用 wheel 内实现和静态模块，不需要本项目检出、CDN 或首次 npm 下载。

```sh
python3.10 -m pip install "./xbox_gamepad_physics-0.3.0-py3-none-any.whl[example]"
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
python3.10 -m pip install './xbox_gamepad_physics-0.3.0-py3-none-any.whl[robotwin,teleop]'
xbox-gamepad-physics build-resources --archive ./xbox_gamepad_physics-resources-0.3.0.zip --resources ./gamepad_resources --offline
xbox-gamepad-physics teleop --robotwin-root /path/to/RoboTwin --gpu 0 --resources ./gamepad_resources --output ./teleop_session --port 8775
```

`--gpu` 是**调用者可见设备列表中的序号**。未设置 `CUDA_VISIBLE_DEVICES` 时等于物理编号；
例如外层 `CUDA_VISIBLE_DEVICES=3,1` 配合 `--gpu 0` 选择物理卡3，`--gpu 1` 选择物理卡1。
UUID/MIG 遮罩项原样保留，越界明确报错。物理、渲染和FFmpeg子进程只暴露选中的设备，
在子进程中统一编号为0（FFmpeg使用 `-gpu 0`）。viewer 的 `--gpu` 使用同一语义，默认0。
这遵从 [NVIDIA 的设备遮罩及重编号规则](https://docs.nvidia.com/deploy/topics/topic_5_2_1.html)。

SAPIEN 的 Vulkan 即使选择其他 GPU，仍会在 GPU 0 留下约 6 MiB 的纯图形记录；
计算和实际渲染仍在选定的 GPU 上，核对时应区分图形初始化记录和 compute 记录。
视频客户端停止读取、断网或重新连接时，只断开该客户端；重连从下一个关键帧开始，
不会把差分帧直接交给新解码器。客户端发送和关闭各有期限，gateway 自身的停止取消照常传播。

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

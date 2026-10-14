# v0.3 安装与资源导入

首发支持 Linux x86_64 + NVIDIA、Python 3.10、RoboTwin fork + SAPIEN 3.0.3。
Release 附件为 wheel、输入 zip 和 `SHA256SUMS`，不上 PyPI。自有代码为 MIT，资产沿用
第三方许可；CC BY 4.0 正文规范链接与署名见 `THIRD_PARTY_NOTICES.md`。

wheel 包含包内 DAG、生成器与版本化的小证据（references、specs 和 One S 资产索引切片）。
输入 zip 只含审定输入：作者原 GLB、已批准静态 visual 快照及实际读取文件、meshbase、
v0.2.0 冻结 CoACD 凸包、批准的 Cycles 场景及所需文件，以及这些输入的来源、署名和许可。
静态 visual 和 meshbase 一样不在用户机器上重新导出，基础构建不需要 Blender。
运动学、运动契约、sim_visual、URDF/manifest 和 SDF 网格均在本地生成；用户端不运行 CoACD。

## 安装与离线导入

```sh
python3.10 -m pip install "./xbox_gamepad_physics-0.3.1-py3-none-any.whl[build,robotwin]"
python3.10 -m xbox_gamepad_physics build-resources \
  --archive ./xbox_gamepad_physics-resources-0.3.1.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
python3.10 -m xbox_gamepad_physics status --backend robotwin
python3.10 -m xbox_gamepad_physics verify --backend robotwin --profile full_controls
```

`[build]` 声明 numpy、trimesh、Pillow 和 manifold3d；不含 CoACD。已有依赖的离线安装
需要预备这些依赖 wheel。`--offline` 限制资源导入/构建联网，不代替 pip 的离线依赖准备。
`verify` 检查 readiness 与必需文件，缺失时返回非零；它不执行真实仿真。

## 资源根目录与缓存

加载器依次使用：

1. `XBOX_GAMEPAD_PHYSICS_RESOURCES` 指定目录，或命令显式的 `--resources`。
2. 仓库检出的 `build/resources/`。
3. 当前下游工程的 `.xbox_gamepad_physics/resources/`；独立目录请显式指定资源根。

环境变量指定的根目录也会导入输入、检查缺失或过期节点并构建。输入保存在资源根的
`inputs/`，构建器使用 wheel 内证据和冻结输入生成 runtime 输出；不会写入 site-packages。
输入不变时第二次命中缓存；删除产物或改变证据只重建受影响节点及其下游。
`--force` 可显式重建全部运行时产物，不会重新分解 CoACD。

在线首次准备可下载 `_resource_lock.json` 指向的版本化输入 zip，然后本地构建。
离线机器应提前取得本地 zip 并用上面的 `--archive ... --offline` 导入。在线入口关闭环境
代理后先直连，确认失败且显式设置 `FALLBACK_PROXY_PORT` 时才回退。使用 fake-IP DNS 的
站点应先提供真实解析或采用离线导入；本阶段没有访问尚未发布的 v0.3.0 在线附件。

## 维护者打包

`python scripts/package_release_resources.py` 仅按白名单封装输入，生成输入 zip、
`SHA256SUMS` 与 `_resource_lock.json`；不调用完整构建，也不调用 CoACD。
随后构建 wheel，并让 `SHA256SUMS` 同时覆盖最终 wheel 和输入 zip，作为 Release 附件。
发布前检查 wheel 中的小证据和生成器齐全、zip 中无运行时产物或其他型号。
B1+B2 只产出待审文件，不上传、打 tag 或发布。

仓库开发仍可 `python -m pip install -e ".[build]"`；setuptools 59 环境使用
`--no-build-isolation`，`setup.py` 镜像保持版本、extras、package_data、入口与 MIT 同步。
维护者只有在明确更新凸包时才使用 `[build,maintainer]` 和显式重生成命令，先归档旧快照。
冻结 CoACD 来源为 v0.2.0 发布 zip、coacd 1.0.14；对应 meshbase 与参数随快照记录。

## RoboTwin / SAPIEN

完整控件 profile 默认使用 `collision="sdf"`，RoboTwin extra 固定为 SAPIEN 3.0.3。
默认加载1 mm SDF；显式传 `collision="coacd"` 或在实验 YAML 下设置
`gamepad.collision: coacd` 可保留CoACD变体（支持3.0.0b1和3.0.3）。
SDF 要求 SAPIEN ≥3.0.3，不支持与 `add_ground` 平面、另一个 SDF 物体碰撞；
桌面用静态盒子。低版本默认调用会明确报错，要求升级到3.0.3或显式选择CoACD，不静默回退。
历史的 `left_stick` 局部profile没有SDF声明，使用时显式选择 `collision="coacd"`。

两种选项均过滤手柄内部碰撞：全部形状保留 g0/g1，设置
`g2 |= 0x80000000`、`g3 = 0x5842`，外部物体的接触仍按 g0/g1 判断。
十字键、摇杆孔口可触区域约 1–1.5 mm 的 CoACD 外胀已于 2026-10-11 暂时接受；
Guide开口覆盖已由SDF对照确认；CoACD孔口优化留待下一阶段，本轮不修改几何。
具体参数和按组件误差见 `references/full_controls.json`。

RoboTwin 的公共接入约定与任务模板见 [`robotwin_backend.md`](robotwin_backend.md)。
调用者持有场景和安装位姿；资产包只把 `pose` 应用到 `controller_body` 根 link。

视觉阶段可以在物理 URDF 就绪前加载 16 个 render-only 部件：

```python
from xbox_gamepad_physics.robotwin import load_visual_into_scene

visual = load_visual_into_scene(self, pose=sapien.Pose([0, 0, 0.8]))
assert visual.physics_ready is False
```

该入口保留 UV、法线和 2K PBR 贴图，不创建碰撞或惯量。完整实验台示例见
`examples/robotwin_visual.py`。

主入口把 URDF articulation 直接加入调用者提供的 SAPIEN scene：

```python
from xbox_gamepad_physics.robotwin import load_into_scene

gamepad = load_into_scene(
    scene=self,  # RoboTwin task，或直接传 sapien.Scene
    pose=[0.0, 0.0, 0.8, 1.0, 0.0, 0.0, 0.0],
    fixed_root=True,
    profile="left_stick",
    collision="coacd",
)

state = gamepad.gamepad_state()
print(state.channel("left_x"), state.channel("left_y"))
print(state.available_mask, state.task_mask, state.device_id)
```

加载器执行以下门禁：

- backend manifest 已通过 readiness 检查；
- URDF、视觉网格、碰撞网格和声明文件全部存在；
- 每个 link 都有显式 COM、质量和正定惯量；
- 每个活动 joint 都有显式类型、轴和 limit；
- manifest 的 joint dynamics 与 articulation 的活动 joint 名称完全一致。

加载过程保留 URDF inertial，并按 joint name 设置 drive、摩擦与中立目标。返回的
`XboxOneSArticulation` 也只接受 joint name；qpos 数组顺序不会成为公共接口。左摇杆
profile 将两轴 qpos 归一化到 `[-1, 1]`，并在对角超出单位圆时做径向投影。完整接触
验证示例见 `examples/robotwin_left_stick.py`。

需要把数据文件复制进 RoboTwin 原生资产目录时，可以先查看 copy plan：

```sh
xbox-gamepad-physics install-robotwin --root /path/to/RoboTwin
```

确认目标后显式执行：

```sh
xbox-gamepad-physics install-robotwin \
  --root /path/to/RoboTwin \
  --apply
```

这个命令只复制已审核的资源文件，不修改 RoboTwin Python 源码或任务注册。公共 backend
接口不要求执行复制；任务代码可以直接调用 `load_into_scene(task.scene, ...)`。

## MuJoCo 历史基线

MuJoCo 不在 v0.3 发布范围内。冻结树保留在 Git 原地供历史比对，不进运行时 DAG、
wheel 资源数据或输入 zip，也不恢复其生成器。`status` / `verify --backend mujoco` 与
MuJoCo 加载入口会明确提示此范围；相关运行时、资产与 MuBlE 真实集成测试注明原因后跳过。
旧示例与历史实验记录保留，不作为 v0.3 安装或验收入口。

## Backend manifest

每个 profile 都必须包含：

```text
schema_version
asset_id
backend
profile
available
dynamics_ready
entrypoint
required_files
reason
```

RoboTwin ready profile 还需要逐关节 `joint_dynamics`。完整控件的 backend manifest
通过 `motion_contract` 指向公共运动
契约，关节范围和信号约束不在 backend manifest 中重复维护。格式说明见
`schemas/backend_manifest.schema.json`（文档，运行时不校验）。RoboTwin 的字段取值范围与有限性、URDF 显式惯量与限位等由生成器保证，
并在资产测试中对构建结果检查一次；RoboTwin 加载器运行时只检查就绪状态、必需文件和关节名一致。
公共运动契约和信号控制器仍校验各自的输入。

## 验证

基础设施测试检查资源完整性、具名关节绑定、调用边界和 MuJoCo 排除提示。发行前另从
不含本仓库的临时工作目录，使用非 editable wheel、声明的 `[build]` 依赖和本地输入 zip
完成离线构建，检查必需文件与缓存失效传播。wheel 应包含构建器及小证据，不含生成资源、
历史 MuJoCo 树或其他型号档案。

这些检查不等于真实 SAPIEN 加载或渲染通过；Linux/NVIDIA + RoboTwin fork + SAPIEN 3.0.3
的加载、交互、原生渲染留到 B4，用户视觉确认、真实手柄标定与接触实验分别验收。

## 安装包中的 example、viewer 与 overlay（B3a）

这些入口直接使用 wheel 内实现和静态模块，不需要本项目检出、CDN 或首次 npm 下载。

```sh
python3.10 -m pip install "./xbox_gamepad_physics-0.3.1-py3-none-any.whl[example]"
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
python3.10 -m pip install './xbox_gamepad_physics-0.3.1-py3-none-any.whl[robotwin,teleop]'
xbox-gamepad-physics build-resources --archive ./xbox_gamepad_physics-resources-0.3.1.zip --resources ./gamepad_resources --offline
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

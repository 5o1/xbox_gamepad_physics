# RoboTwin 与 MuJoCo 导入约定

本仓库以 Python 包形式提供 Xbox One S 资产。wheel 只包含代码；运行时资源（运动契约、
视觉、RoboTwin 与 MuJoCo profile）在构建时生成，或从 GitHub Release 的资源 zip 下载，
统一缓存在资源根目录下的 `<backend>/<profile>/`。

## 资源根目录

加载器按以下顺序确定资源根目录：

1. 环境变量 `XBOX_GAMEPAD_PHYSICS_RESOURCES` 指定的目录。
2. 在仓库检出中运行时：`<仓库>/build/resources/`。
3. 作为依赖安装时：从当前目录向上找到含 `pyproject.toml` 或 `.git` 的工程根，使用
   `<工程根>/.xbox_gamepad_physics/resources/`（请加入该工程的 `.gitignore`）。找不到工程根时报错。

资源缺失或过期时自动处理：仓库检出中在本地按依赖图构建（需要 `[build]` extra），
否则下载与包版本对应的 Release zip，校验 SHA-256 后解压。下载使用标准库默认的网络
设置，遵循 `HTTPS_PROXY`、`NO_PROXY` 等标准代理变量。结果写入后不再重复构建：
各构建节点记录输入内容，输入不变时直接跳过（本地实测第二次构建约 0.03 秒）。
缓存不会写入用户主目录或 site-packages。

多个实验共用同一台机器（例如 GPU 节点）时，可让它们指向同一缓存，只构建一次：

```sh
export XBOX_GAMEPAD_PHYSICS_RESOURCES=/path/to/shared/xbox_gamepad_physics_resources
```

## 发布资源包

1. `python scripts/package_release_resources.py`：完整构建资源，在 `dist/` 生成
   `xbox_gamepad_physics-resources-<版本>.zip`、`SHA256SUMS`，并把下载锁写入
   `src/xbox_gamepad_physics/_resource_lock.json`（该文件不进 Git）。版本号取自 `pyproject.toml`。
2. 用 `python -m build` 生成 sdist 与 wheel。它先打 sdist，再从 sdist 构建 wheel，不受仓库里残留的
   `build/lib`、`*.egg-info` 影响；不要在有旧构建产物的工作区直接用 `pip wheel .` 发布。
3. 把 zip 上传到 GitHub Release `v<版本>`，与 wheel 一起发布。

## 安装与状态检查

基础包不强制安装仿真器：

```sh
python -m pip install -e ".[build]"
python -m xbox_gamepad_physics build-resources
python -m xbox_gamepad_physics status
```

`build-resources` 也会在首次加载资源时自动执行；手动运行便于提前构建和查看进度，
`--force` 强制全部重建。

已有 RoboTwin 环境需要保持离线安装时，可以复用环境中的 setuptools：

```sh
python -m pip install -e . --no-build-isolation
```

可选依赖：

```sh
python -m pip install -e ".[mujoco]"
python -m pip install -e ".[robotwin]"
```

MuJoCo/Filament 开发使用独立 Python 3.12 环境。GPU 节点当前验证路径为：

```text
/path/to/gpu-data/<gpu-project>/envs/concon-xbox-py312
```

该环境不继承 RoboTwin/SAPIEN 环境。Python 3.12 是低层
`mujoco.rendering.filament` 的最低实际可用版本，因为它使用 Python 3.12 新增的
`collections.abc.Buffer`。已验证版本见
`requirements/mujoco-filament-py312.freeze.txt`。官方 MuJoCo 3.15.0 wheel 的基础依赖
元数据遗漏了 `typing_extensions`，本项目的 `mujoco` extra 显式补充该运行时依赖。

`status` 只报告 manifest。`verify` 会检查 readiness 标志和所有必需文件，并在任何物理资源
缺失时返回非零状态：

```sh
python -m xbox_gamepad_physics verify --backend mujoco
python -m xbox_gamepad_physics verify --backend robotwin
python -m xbox_gamepad_physics verify --backend robotwin --profile left_stick
```

完整仿真资产使用可运行的 `full_controls`；其结构已满足仿真加载要求，但物理参数仍是未完成硬件校准的
估计值。RoboTwin 另有 `left_stick`，只覆盖左摇杆物理闭环。

## RoboTwin / SAPIEN

完整控件 profile 的默认碰撞选项为 `collision="coacd"`；使用
`load_into_scene(scene, pose, fixed_root, profile="full_controls", collision="sdf")`
或在实验 YAML 的 `gamepad` 下设置 `collision: sdf` 可选择 1 mm SDF。
SDF 要求 SAPIEN ≥3.0.3，不支持与 `add_ground` 平面、另一个 SDF 物体碰撞；
桌面用静态盒子。低版本选择 SDF 会明确报错。

两种选项均过滤手柄内部碰撞：全部形状保留 g0/g1，设置
`g2 |= 0x80000000`、`g3 = 0x5842`，外部物体的接触仍按 g0/g1 判断。
十字键、摇杆孔口可触区域约 1–1.5 mm 的 CoACD 外胀已于 2026-10-11 暂时接受；
后续仿真实验确认影响结果后再修。具体参数和按组件误差见 `references/full_controls.json`。

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

## MuJoCo 独立场景

视觉阶段可以直接加载实验台场景；返回前已经执行 `mj_forward`，因此固定相机和所有
visual geom 的世界位姿可立即用于首帧渲染：

```python
from xbox_gamepad_physics.mujoco import load_visual_scene

visual = load_visual_scene(scene="table")
assert visual.physics_ready is False
```

完整原生渲染与交互示例见 `examples/mujoco_visual.py`。当前 MuJoCo 原生渲染器使用
2K base-color 纹理和标量 specular/shininess；normal、occlusion、roughness、metallic、
emissive 贴图保留在共用视觉资源中，原生渲染器不会解释这些 PBR 纹理角色。

Filament PBR 入口使用原 GLB 的 RGB、alpha、normal、occlusion、roughness、metallic 和
emissive 语义：

```python
from xbox_gamepad_physics.mujoco import load_visual_scene

reference = load_visual_scene(scene="reference", renderer="filament")
table = load_visual_scene(scene="table", renderer="filament")
```

MuJoCo 3.15.0 的 `ModelRenderables` 没有把 `mjTEXROLE_OPACITY` 传给 Filament material，
因此官方 wheel 会把 Xbox One S 的透明 ABXY 外壳画成不透明白色。当前 Filament 入口要求
使用 [5o1/mujoco 的 `concon/filament-opacity-texture` 分支](https://github.com/5o1/mujoco/tree/concon/filament-opacity-texture)，
修复提交为 `fbeb31381564ae71e9efcdf3189d1ffbf5033269`。该补丁只补齐通用 opacity role
映射，不包含 Xbox 专用材质或颜色。

离屏示例见 `examples/mujoco_filament_visual.py`：

```sh
python examples/mujoco_filament_visual.py \
  --scene reference \
  --output /tmp/xbox-filament
```

将纯视觉资产加入调用者自己的 `MjSpec`：

```python
import mujoco
from xbox_gamepad_physics.mujoco import attach_visual_to_spec

parent = mujoco.MjSpec.from_file("dual_hand_scene.xml")
attachment = attach_visual_to_spec(
    parent,
    frame=parent.frame("gamepad_mount"),
    prefix="xbox_visual_",
)
model, data = attachment.compile()
```

该入口只加入 16 个 `contype=0`、`conaffinity=0` 的视觉 geom。碰撞、质量、惯量、
关节和接触参数将在物理资产阶段接入。

### 物理场景接口

`load_scene` 负责完整的 parse、compile、`MjData` 分配和命名绑定：

```python
from xbox_gamepad_physics.mujoco import load_scene

loaded = load_scene(profile="full_controls", scene="fixed")
model = loaded.model
data = loaded.data
gamepad = loaded.gamepad
```

standalone scene 可以是 XML 或自包含 MJZ。manifest 通过 `scenes` 映射声明 `fixed`、`free`
等公开场景名。

## MuJoCo 加入已有场景

MuJoCo 在 `MjSpec` 阶段组合子模型：

```python
import mujoco
from xbox_gamepad_physics.mujoco import attach_to_spec

parent = mujoco.MjSpec.from_file("dual_hand_scene.xml")
attachment = attach_to_spec(
    parent,
    frame="gamepad_mount",
    prefix="xbox_",
    profile="full_controls",
)

compiled = attachment.compile()
model = compiled.model
data = compiled.data
gamepad = compiled.gamepad
```

调用者也可以自行编译 parent，再执行：

```python
model = parent.compile()
data = mujoco.MjData(model)
gamepad = attachment.bind(model, data)
```

`prefix` 使同一场景可以附加多个实例。joint 与 sensor 都通过编译后的名称绑定，父场景中
body 的排列变化不会改变公共访问方式。

## MuBlE

MuBlE 是 MuJoCo 资产的消费者，不维护第三份 Xbox 物理资产。适配代码位于
`xbox_gamepad_physics.muble`：它通过公开的 `MujocoGamepadHandle` 写入标准
`GamepadState`，从编译后的 visual geom/body 名称推导 16 个部件的所属关系，并输出
`muble/body-pose-trace-v1`。

生成一个最小 pose probe：

```sh
python examples/muble_pose_probe.py --output /tmp/xbox_muble_trace.json
```

Blender 端直接打开已经验收的场景，并从包内共用视觉 manifest 读取原 Blender 对象名称、
初始矩阵、尺度和坐标变换：

```sh
PYTHONPATH="$PWD/src" blender --background --python-use-system-env \
  --python examples/muble_visual.py -- \
  --approved-blend assets/xbox_one_s/render/Xbox_One_S_approved_cycles.blend \
  --trace /tmp/xbox_muble_trace.json \
  --frame 1 \
  --save /tmp/xbox_muble_frame.blend
```

MuBlE 的桌面、机器人和灯光仍由 MuBlE 自己提供。调用者先打开 approved Xbox scene，
再使用 MuBlE 的通用场景组合能力追加或链接所需环境；本仓库不复制
`base_scene_panda.blend`，也不维护额外的 Xbox `blender_binding.json`。

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

MuJoCo ready profile 还需要 `scenes` 和 `bindings`。RoboTwin ready profile 还需要逐关节
`joint_dynamics`。完整控件的两个 backend manifest 通过 `motion_contract` 指向公共运动
契约，关节范围和信号约束不在 backend manifest 中重复维护。格式说明见
`schemas/backend_manifest.schema.json`（文档，运行时不校验）。RoboTwin 的字段取值范围与有限性、URDF 显式惯量与限位等由生成器保证，
并在资产测试中对构建结果检查一次；RoboTwin 加载器运行时只检查就绪状态、必需文件和关节名一致。
公共运动契约和信号控制器仍校验各自的输入，冻结的 MuJoCo 层保留原有检查。

## 验证

基础设施通过以下实验验证：

1. 在未安装 SAPIEN 或 MuJoCo 时导入基础包，确认没有隐式后端依赖。
2. 使用 fake scene/spec 记录调用，确认 readiness 失败发生在 scene 修改之前。
3. 使用临时绝对资源路径，确认 RoboTwin loader 不读取当前工作目录。
4. 改变活动 joint 顺序，确认名称化访问仍返回正确 qpos。
5. 构造缺失 inertial、joint limit、binding 和资源文件的 profile，确认全部 fail closed。
6. 构造 MuJoCo parent spec attachment，确认 prefix 后的 joint/sensor 名称能够绑定。
7. 构建 wheel，确认其中只有代码（以及发布时生成的 `_resource_lock.json`），不含资产或构建好的资源。

自动测试覆盖资源完整性、命名绑定和调用边界。各后端的用户视觉检查、真实手柄标定和
机械臂接触实验继续按独立验收项推进。

# RoboTwin 与 MuJoCo 导入约定

本仓库以 Python 包形式提供 Xbox One S 资产。运行时资源位于
`xbox_gamepad_physics/resource_data/<backend>/<profile>/`，加载器通过包内绝对路径访问，
调用者的当前工作目录不参与资源解析。

共用视觉资源位于包内 `resource_data/xbox_one_s/visual/`，包含静态 GLB、16 个 OBJ
和部件清单；查看器与安装包使用同一组文件。资产索引和预览配置也在 `resource_data/`。
原始 GLB 单独保存在仓库的 `archive/xbox_one_s/`，不进入 wheel。
索引中的历史报告和来源链接用于仓库内查阅；它们指向的研究记录不属于安装包运行资源。

## 安装与状态检查

基础包不强制安装仿真器：

```sh
python -m pip install -e .
python -m xbox_gamepad_physics status
```

已有 RoboTwin 环境需要保持离线安装时，可以复用环境中的 setuptools：

```sh
python -m pip install -e . --no-build-isolation
```

可选依赖：

```sh
python -m pip install -e ".[mujoco]"
python -m pip install -e ".[robotwin]"
```

`status` 只报告 manifest。`verify` 会检查 readiness 标志和所有必需文件，并在任何物理资源
缺失时返回非零状态：

```sh
python -m xbox_gamepad_physics verify --backend mujoco
python -m xbox_gamepad_physics verify --backend robotwin
```

当前 `estimated_v0` 的两个后端都处于 blocked 状态。视觉资产、碰撞体、惯量和被动力学
通过审核后，才会把对应 manifest 的 `available` 与 `dynamics_ready` 置为 `true`。

## RoboTwin / SAPIEN

主入口把 URDF articulation 直接加入调用者提供的 SAPIEN scene：

```python
from xbox_gamepad_physics.robotwin import load_into_scene

gamepad = load_into_scene(
    scene=self,  # RoboTwin task，或直接传 sapien.Scene
    pose=[0.0, 0.0, 0.8, 1.0, 0.0, 0.0, 0.0],
    fixed_root=True,
    profile="estimated_v0",
)
```

加载器执行以下门禁：

- backend manifest 已通过 readiness 检查；
- URDF、视觉网格、碰撞网格和声明文件全部存在；
- 每个 link 都有显式 COM、质量和正定惯量；
- 每个活动 joint 都有显式类型、轴和 limit；
- manifest 的 joint dynamics 与 articulation 的活动 joint 名称完全一致。

加载过程保留 URDF inertial，并按 joint name 设置 drive、摩擦与中立目标。返回的
`XboxOneSArticulation` 也只接受 joint name；qpos 数组顺序不会成为公共接口。

需要使用 RoboTwin 原生目录时，可以先查看 copy plan：

```sh
xbox-gamepad-physics install-robotwin --root /path/to/RoboTwin
```

确认目标后显式执行：

```sh
xbox-gamepad-physics install-robotwin \
  --root /path/to/RoboTwin \
  --apply
```

这个命令只复制已审核的资源文件，不修改 RoboTwin Python 源码或任务注册。

## MuJoCo 独立场景

`load_scene` 负责完整的 parse、compile、`MjData` 分配和命名绑定：

```python
from xbox_gamepad_physics.mujoco import load_scene

loaded = load_scene(profile="estimated_v0", scene="fixed")
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
    profile="estimated_v0",
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
`joint_dynamics`。格式约束见 `schemas/backend_manifest.schema.json`。

## 验证

基础设施通过以下实验验证：

1. 在未安装 SAPIEN 或 MuJoCo 时导入基础包，确认没有隐式后端依赖。
2. 使用 fake scene/spec 记录调用，确认 readiness 失败发生在 scene 修改之前。
3. 使用临时绝对资源路径，确认 RoboTwin loader 不读取当前工作目录。
4. 改变活动 joint 顺序，确认名称化访问仍返回正确 qpos。
5. 构造缺失 inertial、joint limit、binding 和资源文件的 profile，确认全部 fail closed。
6. 构造 MuJoCo parent spec attachment，确认 prefix 后的 joint/sensor 名称能够绑定。
7. 构建 wheel，确认两个 backend manifest 被包含在安装包中。

物理资源完成后还需要在真实 SAPIEN 与 MuJoCo 版本中执行编译、接触和跨后端响应测试。
当前基础设施测试不构成动力学验收。

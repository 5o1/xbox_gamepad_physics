# Isaac Lab 预览（v0.4.2 组件）

本版随包交付 Isaac **预览**。外部前置为 Python 3.11、Isaac Lab 2.3.2、Isaac Sim 5.1
及其兼容 torch；本项目不安装或升级这些平台依赖。默认 SDF 0.5 mm，CoACD 只作对照。

## 安装与公共输入

在已选平台解释器中安装，或创建继承该环境的临时 venv：

```sh
/path/to/isaac-python -m venv --system-site-packages ./isaac_preview_env
./isaac_preview_env/bin/python -m pip install \
  "./xbox_gamepad_physics-0.4.2-py3-none-any.whl[build,isaac]"
```

`[isaac]` 为空；`[build]` 只提供公共构建依赖。不要用 pip 替换平台自带 torch/Isaac。
平台解释器、动态库目录、GPU选择来自调用者自己的现有环境或私有 site 配置，不写入源码。

普通环境执行 `build-resources --backend isaac` 会明确报需要 `isaac_app` / AppLauncher。
通用入口不会自动启动平台。原生构建入口是
`xbox_gamepad_physics.isaac.build_usd`，必须先由调用者启动 AppLauncher，再导入 pxr/原生模块。

## 在平台进程中构建并加载

下面展示专用 API 路径。输入 zip 是普通发布附件；公共描述仍由同一份包内生成器产生。
根部 `fixed` / `free` 在生成时选择，不提供运行中固定/释放。

```python
import json
from pathlib import Path
from isaaclab.app import AppLauncher

app = AppLauncher(headless=True).app
try:
    from isaaclab.sim import SimulationCfg, SimulationContext
    from xbox_gamepad_physics import prepare_resources
    from xbox_gamepad_physics.backends.common.appearance import (
        bind_appearance_to_motion, load_appearance,
    )
    from xbox_gamepad_physics.backends.common.collision import load_collision_sources
    from xbox_gamepad_physics.backends.common.physical import load_physical
    from xbox_gamepad_physics.isaac import (
        bind_articulation, build_usd, make_articulation_cfg,
    )
    from xbox_gamepad_physics.motion import motion_from_dict

    resources = Path("./gamepad_resources").resolve()
    prepare_resources(
        backends=("robotwin",), targets=("common_physical", "sim_visual"),
        resources=resources,
        archive=Path("./xbox_gamepad_physics-resources-0.4.2.zip"), offline=True,
    )
    common = resources / "common/xbox_one_s"
    motion = motion_from_dict(json.loads((common / "motion/full_controls.json").read_text()))
    physical = load_physical(resource_directory=common / "physical")
    kinematics = json.loads((resources / "kinematics/xbox_one_s.json").read_text())
    appearance = bind_appearance_to_motion(
        load_appearance(directory=common / "visual"), kinematics, motion,
    )
    artifact = build_usd(
        resources / "usd/fixed.usda", motion=motion, physical=physical,
        appearance=appearance,
        collision_sources=load_collision_sources(directory=common / "collision"),
        visual_directory=common / "visual", root_mode="fixed",
    )
    sim = SimulationContext(SimulationCfg(dt=0.004, device="cuda:0"))
    cfg = make_articulation_cfg(
        artifact.usd_path, motion=motion, physical=physical,
    )
    native = cfg.class_type(cfg)
    sim.reset()
    native.update(sim.get_physics_dt())
    pad = bind_articulation(native, motion=motion, physical=physical)
    print(pad.gamepad_state().channel("south"))
finally:
    app.close()
```

调用者持有应用、scene、reset和步进生命周期。已有场景用同一 `make_articulation_cfg`，reset后绑定。
不要把状态同步当接触按压；`isaac.step` 是原生 flush/step/update 的便利包装，没有步后关节修正。
源码检出的 `examples/isaac/` 提供用户加载和具名驱动示例；诊断、探针和审查脚本在 `experiments/isaac/`，冻结用例及评分在 `tests/acceptance/`。这些 checkout 工具不随 wheel 分发，上述运行时 API 随包提供。

## click 运行时预压及生命周期

公共链为`controller_body → click（壳体系−Z）→ x → y → stick`。圆锥闭环接在随click平移的框架和杆端之间，只限制倾角，不锁住前置click平移。

原生force drive的click目标为0，刚度/阻尼沿用公共输入；另由公共`k × neutral_target`得到−7.4 N原生关节力。因此静态恢复律为`−7.4−1000q N`，click行程0–.4 mm，ABXY行程1.22 mm。10.4 N是弹簧drive的原生力限，额外预压不属于同一drive限幅；不声称任意高速下与单一总力限完全等价。硬件未知干摩擦/armature仍为null。

`make_articulation_cfg`返回带专用`class_type`的配置。直接创建用`cfg.class_type(cfg)`；`InteractiveScene`会自动使用此类型。资产的物理初始化回调在原生缓冲区/actuator可用后，一次设置Lab effort buffer并提交native effort。普通循环继续`write_data_to_sim()`；该函数每步覆盖原生effort，但使用持久buffer，所以预压不会丢失。调用方若为click覆盖新的effort target，须在新命令中保留−7.4 N偏置。

**裸USD只包含零目标弹簧，不包含运行时预压。** 不要用`Articulation(cfg)`绕开`class_type`；旧代码绑定handle时会补齐，但新示例在资产初始化时就安装预压。绑定handle同时恢复全部被动位置目标。已实测Lab2.3.2普通asset reset保留buffer；完整stop/play重建自动重装来自初始化源码推导，尚未单独实测。

`examples/isaac/load_and_read.py --build`从本版公共motion/physical/kinematics/visual资源重新生成USD，不需要历史`review_binding.json`或旧预制USD。AppLauncher必须先于pxr/native模块和USD authoring；示例记录实际package路径与版本供检查wheel是否被源码遮蔽。

## 历史证据与未完成边界

以下是2026-11-07原源码工作区及冻结公共输入的实测，**不是即将集成的v0.4.2 wheel实测**。版本化标量证据在[Isaac验收摘要](../tests/acceptance/isaac/data/source_native_20261107.json)。最终集成wheel须重新完成构建/加载/预压及所需验收边界，不能继承旧工作区“已通过”身份。

- 原登记T1为6/6、T2为12/12；T3单点外力v2新模型10/10。旧小球版夹具无效，不作物理结论。
- T4完整26项为23通过：历史22项全部保持，L3新增通过（保持最小值约.972153）；Guide=.931170、Pair=0、R3=.949565874仍失败。R3不足.95，未四舍五入或放宽阈值。
- 单点v2旧模型没有出现预期低档误按；两侧正对照均失败。右侧正对照末半秒最小值约.332497，并非零；旧低档零信号不能证明其物理正确。
- 数值沿用4 ms、TGS、原生articulation32/1读回、SDF .5 mm；.998余量对应22.954°，公共上限仍23°。没有采用其他后端的数值设置。
- 旧补偿链曾有23.001294°瞬态；新click前置链没有任意负载下严格逐子步23°保证。以前的稳态加载结果不能自动算作新链的完整限位资格。
- 旧free/N=1024行排列根位置差4.2915 µm超过原3 µm；新配置完整批量/扩展曲线未复验。单实例预压与fixed/free读回不能替代大批量资格。
- RTX实时ABXY可能较模糊，路径追踪更清楚；PreviewSurface不完全等价于源glTF全部高光语义。

可加载、信号读回、点力检测与接触就绪分开；本后端继续preview，不声称硬件标定或RL性能。验收入口和原协议见[Isaac检测说明](../tests/acceptance/isaac/README.md)；公共资源导入见[importing.md](importing.md)。

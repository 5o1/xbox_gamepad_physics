# Isaac Lab 预览（0.4.1）

本版随包交付 Isaac **预览**。外部前置为 Python 3.11、Isaac Lab 2.3.2、Isaac Sim 5.1
及其兼容 torch；本项目不安装或升级这些平台依赖。默认 SDF 0.5 mm，CoACD 只作对照。

## 安装与公共输入

在已选平台解释器中安装，或创建继承该环境的临时 venv：

```sh
/path/to/isaac-python -m venv --system-site-packages ./isaac_preview_env
./isaac_preview_env/bin/python -m pip install \
  "./xbox_gamepad_physics-0.4.1-py3-none-any.whl[build,isaac]"
```

`[isaac]` 为空；`[build]` 只提供公共构建依赖。不要用 pip 替换平台自带 torch/Isaac。
平台解释器、动态库目录、GPU选择来自调用者自己的现有环境或私有 site 配置，不写入源码。

普通环境执行 `build-resources --backend isaac` 会明确报需要 `isaac_app` / AppLauncher。
预览的通用 registry readiness 尚未开启，该命令不会自动启动平台。原生构建入口是
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
    from isaaclab.assets import Articulation
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
        archive=Path("./xbox_gamepad_physics-resources-0.4.1.zip"), offline=True,
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
    native = Articulation(make_articulation_cfg(
        artifact.usd_path, motion=motion, physical=physical,
    ))
    sim.reset()
    native.update(sim.get_physics_dt())
    pad = bind_articulation(native, motion=motion, physical=physical)
    print(pad.gamepad_state().channel("south"))
finally:
    app.close()
```

调用者持有应用、scene、reset和步进生命周期。已有场景用同一 `make_articulation_cfg`，reset后绑定。
不要把状态同步当接触按压；`isaac.step` 是原生 flush/step/update 的便利包装，没有步后关节修正。
源码检出里的 `examples/isaac/` 提供完整审查脚本；这些 checkout 脚本不随 wheel 分发，上述 API 随包提供。

## 已知问题与负责人决定

- 当前26项为22通过：Guide最低保持信号约0.931，低于0.95且相对基线退化；Pair、L3、R3也失败。
  负责人2026-10-21决定 Guide 暂不诊断、L3/R3暂不调查，本版没有修复或调低阈值。
- 原生半角按已批准0.998数值补偿为22.954°，公共定义与信号归一化仍为23°。
  这不是实测尺寸或严格瞬态保证；曾有23.001294°瞬态样本，严格逐子步门槛未通过。
- free / N=1024行排列的根位置差4.2915 µm超过原3 µm门槛；不能声称完整大批量隔离通过。
- 最终补偿模型的完整扩展曲线没有重跑；历史性能曲线不能代替当前模型的资格验证。
- RTX实时 `RaytracedLighting` 下ABXY偏模糊，路径追踪更清楚，高质量出图用后者。
  PreviewSurface不是源glTF全部高光语义的无损实现。
- 可加载、读回和软件接口不等于完整接触就绪；以上分数也不代表硬件标定。

负责人决定、其他后端分母见 [plan.md](plan.md)；公共资源导入见 [importing.md](importing.md)。

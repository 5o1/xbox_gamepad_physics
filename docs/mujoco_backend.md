# MuJoCo 后端（0.4.1）

支持 Linux x86_64、Python 3.10/3.11。默认 SDF，CoACD 为显式对照；外观使用经典渲染器。
负责人于2026-10-21确认 K5 外观。按压结果、原生限位与硬件标定是独立结论。

## 安装与资源

```sh
python -m pip install "./xbox_gamepad_physics-0.4.1-py3-none-any.whl[build,mujoco]"
python -m xbox_gamepad_physics build-resources --backend mujoco \
  --archive ./xbox_gamepad_physics-resources-0.4.1.zip \
  --resources ./gamepad_resources --offline
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
python -m xbox_gamepad_physics status --backend mujoco
```

`[mujoco]` 根据解释器选择负责人 [fork Release](https://github.com/5o1/mujoco/releases/tag/v3.16.0-concon.sdf3689.2)
的 cp310/cp311 wheel，直链含 SHA256。发行版本是 `3.16.0+concon.sdf3689.2`，原生
`mujoco.__version__` 仍为 `3.16.0`。fork 使用上游 PR #3689 修正3.16.0网格 SDF 的符号错误；
普通官方3.16.0不是这一采用版本。pip安装可能联网，资源的 `--offline` 不限制 pip。

## 加载与按名字驱动

```python
import mujoco
from xbox_gamepad_physics import GamepadState
from xbox_gamepad_physics.mujoco import load_standalone

scene = load_standalone(fixed_root=True, collision="sdf")
pad = scene.gamepad
print(pad.gamepad_state().channel("south"))
pad.set_gamepad_targets(GamepadState.xbox_one_s({"south": 0.65}))
for _ in range(100):
    mujoco.mj_step(scene.model, scene.data)
print(pad.joint_positions())
```

`set_gamepad_state` 是状态同步；`set_gamepad_targets` 设置持续目标，由调用者步进。
Pair 是 `physical_events()` 中的独立事件，不在32维游戏张量内。挂入既有模型时使用
`make_spec` / `attach_to_spec`，由调用者编译后 `binding.bind(model, data)`；固定/自由根在编译前选择。
片段不覆盖调用者全局 options、灯光或相机。默认 SDF 的 depth 与数值政策通过正式入口落实，
直接编译内部 XML 不等于完整加载。详细原生边界见源码 `mujoco/HARD_LIMITS.md`。

## 已知边界

- 冻结26项按压为25通过，只有 Pair 失败；不代表26项全通过或硬件已标定。
- 23°圆形限位首次峰值约23.35°，负责人2026-10-20暂时接受；严格逐子步硬上限尚未成立，
  `hard_shaft_limits` 不能写成通过。没有步后手动投影或额外修正冲量。
- 记录的每验收步耗时10.45 ms，对应4 ms仿真时间，不是实时性能。
- 经典 Phong 是源 PBR 外观的近似；源贴图与材质证据保留，不能把视觉近似说成物理材质实测。
- 资源可构建/可加载与 `dynamics_ready` 是不同声明；`verify` 仍可能按显式 readiness 返回非零。

当前分母和负责人决定见 [计划与已知问题](plan.md)，安装资源通则见 [importing.md](importing.md)。

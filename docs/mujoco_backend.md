# MuJoCo 后端（0.4.2）

支持 Linux x86_64、Python 3.10/3.11。默认 SDF，CoACD 为显式对照；外观使用经典渲染器。
负责人于2026-10-21确认 K5 外观。按压结果、原生限位与硬件标定是独立结论。

## 安装与资源

```sh
python -m pip install "./xbox_gamepad_physics-0.4.2-py3-none-any.whl[build,mujoco]"
python -m xbox_gamepad_physics build-resources --backend mujoco \
  --archive ./xbox_gamepad_physics-resources-0.4.2.zip \
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
from xbox_gamepad_physics.mujoco import load_standalone

scene = load_standalone(fixed_root=True, collision="sdf")
pad = scene.gamepad
print(pad.gamepad_state().channel("south"))
lower, upper = pad.joint("a_press").range
pad.set_joint_target("a_press", lower + 0.65 * (upper - lower))
for _ in range(100):
    mujoco.mj_step(scene.model, scene.data)
print(pad.joint_positions())
```

`set_gamepad_state` 是状态同步，不是物理按压。上例只设置面键的命名关节目标，保留其余关节的公共回复目标。Pair 是 `physical_events()` 中的独立事件，不在32维游戏张量内。挂入既有模型时使用 `make_spec` / `attach_to_spec`，由调用者编译后 `binding.bind(model, data)`；固定/自由根在编译前选择。片段不覆盖调用者全局 options、灯光或相机。默认SDF的depth与数值政策通过正式入口落实，直接编译内部XML不等于完整加载。

## 被动click与壳体系按压轴

公共运动链为 `controller_body → click → x → y → stick`，click轴固定在壳体系。MuJoCo使用原生被动关节弹簧，`K=1000 N/m`、`springref=-0.0074 m`，静止回复力为 `-(7.4+1000q) N`；公共drive/passive阻尼各映射一次到joint damping，总计2.94 N·s/m。两个click没有回复actuator，没有回调恢复力。被动弹簧不能映射原drive的10.4 N限幅，该值保留为明确未映射的公共元数据；未知摩擦/armature仍保留null及原因。

真实按压应当施加外力，由引擎计算位移和信号。下游例子：

```sh
python examples/mujoco/press_stick.py --resource-root ./gamepad_resources \
  --side left --force-n 8.14 --hold-s 0.5 --release-s 0.5
```

脚本在moving stick COM使用原生 `mj_applyFT`，加载后卸载并打印读数，不写click位置/目标，不评分验收。`set_joint_target` 对被动click会修改 `model.qpos_spring`；全量 `set_gamepad_targets` 也会对省略通道写中性目标，因此会覆盖click预压。离开软件目标驱动模式时用 `restore_passive_targets()` 恢复全部公共回复目标。相同compiled model的多个MjData共用spring reference；不同前缀实例使用各自坐标。

## 批准的click止挡数值政策

`backend_options.mujoco.click_limit_response` 于2026-11-07经负责人裁定4批准，属于**数值政策，不是硬件物性**：

| 参数 | 值 | 单位与适用范围 |
|---|---|---|
| margin | 1e-8 | m，只用于左右click scalar stop |
| solreflimit | [1e-6, 5] | s、无量纲阻尼比 |
| solimplimit | [.9999, .9999, .001, .5, 2] | 无量纲、无量纲、m、无量纲、无量纲 |

保持既有discrete/Newton100、tolerance1e-8、refsafe关闭、diagexact关闭，0.5 ms原生步长、4 ms外层8子步；contact solref=(.002 s,1)、solmix=1e6不变。该设置为MuJoCo自己的原生数值政策，其他后端独立配置。

正margin让q=0时第一子步已有原生止挡行；margin=0时第一子步没有该行，预压先产生较大自由位移。d0=dw=.9999使阻抗为常数，第三项width=.001m在此配置下不决定阻抗过渡。来源为实际fork提交[原生约束实现](https://github.com/5o1/mujoco/blob/ac1bfe32700667d98b0eea412900beef5d98cbc2/src/engine/engine_core_constraint.c)，及2026-11-07完整模型、仅margin变化的1s原生对照：

| margin nm | 左/右首步q nm | 左/右1s最低q nm | 左/右稳态公共signal | 裁定3判据 |
|---:|---|---|---|---|
| 100 | +63.6053 / +61.5542 | 0 / 0 | .000174947 / .000169306 | 信号超限 |
| 30 | -.0189204 / -2.06997 | -.0208163 / -2.27739 | 0 / 0 | 满足 |
| 10 | -18.1973 / -20.2483 | -20.0207 / -22.2773 | 0 / 0 | 满足 |
| 3 | -24.5597 / -26.6107 | -27.0207 / -29.2773 | 0 / 0 | 满足 |
| 1 | -26.3775 / -28.4286 | -29.0207 / -31.2773 | 0 / 0 | 满足 |
| 0 | -272864.409 / -293374.269 | 同首步 | 0 / 0 | 初步穿透超限 |

六档均无native warning。判据为首步与全1s最低q≥−4µm、稳态公共signal<1e-4；裁定4的K2b另保留所有公共通道全为0。选10nm是在已测1–30nm合格集合内部保留两侧余量；没有把纳米级负q改写成0。有限柔顺残差仍存在，数值不确定性没有硬件辨识置信区间，不能当成实物公差或任意负载的严格误差上界。

圆锥仍使用随click平移的原生spatial tendon方向坐标，保持壳系参考轴及click零Jacobian，没有额外质量/自由度或状态投影。详细原生边界见源码 `mujoco/HARD_LIMITS.md`。

## 历史组件验证（2026-11-07）

原会话ruling4在当时完整SDF产物上得到：K2b通过；T1六组、T2十二组通过；T3 v2新模型10/10通过，旧73c8676模型10组夹具有效、低档有误触发；冻结T4完整执行26项，25通过、仅Pair失败，与历史通过集合一致。T3点来自最高上帽shell自己的中心/半径，偏移0.5半径，使用原生随动点力，无小球。v1球夹具保留为无效历史。冻结协议与执行/评分位于 `tests/acceptance/mujoco/`。

这些是历史native组件结果，**不是新构建0.4.2 wheel已经完成集成验收的结论**。新wheel还需独立安装、离线资源重建和加载检查。历史分数及控制对照不代表硬件标定或RL结果。

## 已知边界

- 历史冻结26项按压为25通过，只有Pair失败；不代表新wheel集成测试或26项全通过。
- 23°圆形限位首次峰值约23.35°，负责人2026-10-20暂时接受；严格逐子步硬上限尚未成立，
  `hard_shaft_limits` 不能写成通过。没有步后手动投影或额外修正冲量。
- 历史记录每4ms验收步约10.45ms墙钟时间，该记录不是当前机器的实时性能测量。
- 经典 Phong 是源 PBR 外观的近似；源贴图与材质证据保留，不能把视觉近似说成物理材质实测。
- 加载器直接报告资源缺失和输入错误，不以状态布尔值阻止加载；加载成功不替代接触实验。

当前分母和负责人决定见 [计划与已知问题](plan.md)，安装资源通则见 [importing.md](importing.md)。

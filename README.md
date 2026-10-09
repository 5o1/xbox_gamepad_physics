# Xbox 手柄物理资产

这个仓库维护 Xbox 手柄的视觉候选、交互预览、物理规格和来源记录。
游戏强化学习、VLA 和机械臂控制不在这里实现。

当前只分发 Xbox One S 的模型资产。Switch Pro 和旧 Xbox Series X|S 候选模型保存在
GPU 节点，存档位置见 `sources/switch_pro_candidates.json` 和 `assets/asset_index.json`。
仓库保留相关历史报告、图片和来源记录；旧型号已退出查看器可选入口。

## 当前状态

运行状态以 [资产索引](assets/asset_index.json) 为准；README 只提供入口和边界说明。

| 项目 | 状态 |
|---|---|
| 目标实物 | Xbox One S；由持有者明确确认 |
| 目标外观资产 | BatonyRobson 的 Xbox One S 模型；已选定 |
| 物理几何标定 | 局部尺寸、内部结构和关节位置尚未实测 |
| estimated-v0 | 可交互的估计运动学预览，不是可训练物理资产 |
| 旧 Casper 候选 | 外观特征更接近 1914；模型在 GPU 节点存档，不分发 |
| 动力学 | `full_controls_estimated_v0` 已覆盖 20 个关节；参数仍待实测替换 |
| 双后端基础设施 | RoboTwin/SAPIEN 与 MuJoCo 完整 profile 均可加载、步进和读写 21 个游戏通道 |
| 真实手柄验收 | 尚未执行 |

主候选的来源、许可和文件身份记录在
[候选清单](sources/xbox_replacement_candidates.json)。它使用 16 个视觉节点和作者动画信息
生成 estimated-v0；统一尺度来自候选整体宽度与微软公布宽度之比。
目标产品与外观资产已确认。尺度拟合用于交互预览；真实轴心、行程和受力保持待标定状态。

旧 Casper 资产的型号判断见 [几何复核](sources/geometry_review.json)。它的 Share 键、圆盘方向键
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
http://127.0.0.1:8770/viewer/gamepad_overlay/index.html?source=canonical&trace=/results/gamepad_overlay_left_stick_circle/trace.json&autoplay=1
```

页面同时显示关节角、`left_x/left_y`、信号半径和虚拟摇杆位置。项目适配器只接受
`sdl3-gamepad-core-v1` 的 32 维值、两个 mask 和 `device_id`，不会按 W3C 下标猜测输入。
正式演示视频以 RoboTwin/SAPIEN 手柄为主画面，并把透明虚拟手柄叠加在右下角：
[左摇杆单位圆演示](results/gamepad_overlay_left_stick_circle/left_stick_circle_overlay.mp4)。
圆周轨迹作为运动学测试输入写入 articulation；渲染循环随后读回实际 `qpos`，调用
`GamepadSignalController` 生成 `observed_trace.json`，overlay 只消费该读回记录。该演示
验证关节状态到信号的链路，不包含手指接触或动力学驱动声明。

## 关键入口

- [资产索引](assets/asset_index.json)：候选、派生版本、哈希和准入状态。
- [目标物理规格](specs/xbox_v1.json)：部件、物理字段和未决项。
- [交互验收规格](specs/interactive_acceptance.json)：浏览器双向交互的验收门禁。
- [32 维张量契约来源](sources/gamepad_tensor_contract_v1.json)：通道顺序、mask 与设备标识的依据和项目选择。
- [虚拟手柄适配器](viewer/gamepad_overlay/index.html)：将 canonical 状态交给现成 SVG 手柄渲染器。
- [完整控件使用说明](docs/full_controls.md)：20-DOF 双后端资产、信号接口和运行记录。
- [待统一确认与实测清单](docs/pending_user_review.md)：延后处理的视觉确认和硬件测量。
- [完整控件逐项验收视频](results/full_controls_user_review/README.md)：六组双后端运动对照和实体球接触材料。
- [estimated-v0 来源](sources/appearance_matched_estimated_v0.json)：估计运动学的来源、推导和限制。
- [estimated-v0 profile](assets/appearance_matched_estimated_v0/viewer_profile.json)：viewer 使用的运动配置。
- [官方尺寸记录](sources/1708_dimensions.json)：整体尺寸及其适用边界。
- [方向键记录](sources/1708_dpad_assembly.json)：十字键整体结构证据。
- [扳机记录](sources/1708_trigger_mechanism.json)：外帽、内部组件和缓冲接触证据。
- [FCC 照片记录](sources/1708_fcc_internal.json)：内部照片来源与限制。
- [第三方声明](THIRD_PARTY_NOTICES.md)：进入 Git 的第三方内容及许可证。

目录分工：

- `assets/` 保存轻量运行描述；
- `src/xbox_gamepad_physics/` 保存公共状态接口和双后端运行时；
- `schemas/` 保存可发布资源的 manifest 格式；
- `docs/` 保存导入与维护约定；
- `sources/` 保存来源、推导和适用范围；
- `specs/` 保存当前规格和明确的未知项；
- `viewer/` 保存浏览器检查器；
- `scripts/` 保存构建、转换和审计程序；
- `tests/` 保存当前行为的回归测试；
- `results/` 保存已审阅结果和历史实验报告。

`results/` 中的实验报告保留其生成时的提交和环境含义，不自动代表当前 HEAD 已通过。

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

检查 estimated-v0 生成物是否与来源一致：

```sh
python3 scripts/build_estimated_v0.py --check
```

运行默认回归：

```sh
python3 scripts/run_regression.py fast
```

检查可安装包和双后端资源状态：

```sh
python3 -m pip install -e .
python3 -m xbox_gamepad_physics verify \
  --backend all --profile full_controls_estimated_v0
```

离线的既有 RoboTwin 环境使用 `python3 -m pip install -e . --no-build-isolation`，仓库中的
`setup.py` 兼容其 Python 3.10 / setuptools 59 安装链。

历史 `estimated_v0` profile 继续报告 `blocked`。可运行 profile 为双后端
`full_controls_estimated_v0` 和 RoboTwin 局部 `left_stick_estimated_v0`。完整导入接口见
[RoboTwin 与 MuJoCo 导入约定](docs/importing.md)。

需要定位失败时，可直接运行底层测试：

```sh
python3 -m unittest discover -s tests
node --test tests/test_*.mjs
```

## 启动交互预览

需要 Python 3.10 或更新版本、Node.js 22、npm 和 Blender 4.5.9。Xbox One S 网格、材质和贴图已在仓库中，
Three.js 版本由 npm 锁文件固定。全新环境执行：

```sh
git clone https://github.com/5o1/xbox_gamepad_physics.git
cd xbox_gamepad_physics
npm ci
npm run viewer
```

打开 `http://127.0.0.1:8766/v0.html`。无需连接 GPU 节点或提供额外的模型路径。
视觉验收由用户检查并确认。需要指定端口时使用 `npm run viewer -- --port 8767`。
Blender 未加入 PATH 时，使用 `npm run viewer -- --blender "/完整路径/blender"`。

当前画面直接由 Blender/Cycles 绘制，复用用户确认的 Boiler Room 强度 1.0 / Standard / 35°
方案。`assets/xbox_one_s/render/Xbox_One_S_approved_cycles.blend` 已打包模型、材质和 HDRI，
也可以直接用 Blender 打开。浏览器仅处理鼠标、手柄输入与图片显示；Three.js 用于拾取和坐标计算。
同一服务只有一个常驻渲染进程，有新姿态时才出图；渲染期间只保留最新待处理姿态。
这是 Cycles 交互检查器，画面更新速度取决于硬件，不保证游戏帧率。

复用远端安装时，可以通过 `--cycles-command` 显式指定 SSH 启动命令；
命令须打开同一份打包场景并执行 `scripts/cycles_worker.py`。

手动指定资源目录的等价命令：

```sh
python3 scripts/serve_viewer.py \
  --assets assets/xbox_one_s/visual \
  --vendor <three.js-package-directory> \
  --variant-id xbox_one_s_batonyrobson_appearance_matched_estimated_v0 \
  --port 8766
```

打开 `http://127.0.0.1:8766/v0.html`。服务应只绑定本地地址；手柄接在运行浏览器的电脑上，
通过 `navigator.getGamepads()` 读取，不需要把 USB 设备转发到计算节点。

当前页面是运动学检查器。鼠标或 Gamepad 能驱动网格，只说明输入、映射和显示链路工作；
在 canonical schema-v2 到 viewer 的适配器完成并通过哈希绑定前，不计作物理验收。

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

1. 按 `docs/pending_user_review.md` 测量并替换目标手柄参数。
2. 统一检查完整控件的轴向、轴心、穿插和两个后端的外观。
3. 用真实 Xbox One S 和鼠标分别驱动完整 profile，记录并发输入。
4. 将完整 profile 接入机械臂任务与训练数据生成流程。

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
| 动力学 | 尚未完成；质量、惯量、碰撞和接触参数仍有空缺 |
| 双后端基础设施 | Python 包、RoboTwin 场景加载器、MuJoCo `MjSpec` 附加器已建立；物理资源仍被 readiness 门禁阻断 |
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

本仓库的浏览器传输向量为 21 个浮点数：4 个标准轴，随后是 17 个标准按钮值。
这是 W3C Standard Gamepad 状态的本地序列化方式，不是游戏/VLA 分支的 20 维
`xinput-normalized-v1`。连接两者时必须显式处理字段重排、Guide 和摇杆 Y 轴符号，不能按下标直连。

## 关键入口

- [资产索引](assets/asset_index.json)：候选、派生版本、哈希和准入状态。
- [目标物理规格](specs/xbox_v1.json)：部件、物理字段和未决项。
- [交互验收规格](specs/interactive_acceptance.json)：浏览器双向交互的验收门禁。
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
python3 -m xbox_gamepad_physics status
```

离线的既有 RoboTwin 环境使用 `python3 -m pip install -e . --no-build-isolation`，仓库中的
`setup.py` 兼容其 Python 3.10 / setuptools 59 安装链。

当前两个 backend profile 都会报告 `blocked`。这表示导入基础设施可用，物理 URDF/MJCF
仍未通过资源、惯量、碰撞和动力学门禁。完整导入接口见
[RoboTwin 与 MuJoCo 导入约定](docs/importing.md)。

需要定位失败时，可直接运行底层测试：

```sh
python3 -m unittest discover -s tests
node --test tests/test_*.mjs
```

## 启动交互预览

Xbox One S 视觉网格已归档到仓库的 `assets/xbox_one_s/visual/`；Three.js 依赖由外部目录提供：

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

1. 测量并登记目标手柄的局部尺寸、内部结构和可动部件坐标。
2. 实现 canonical schema-v2 到 viewer 的 fail-closed 适配器，并验证双向映射。
3. 按部件生成可检查的碰撞候选，避免用整机凸包堵住按钮和摇杆开口。
4. 以有来源的估计值建立第一版被动关节；保留待推拉计和尺寸测量替换的字段。
5. 完成鼠标双向检查和真实 Xbox One S 手柄录屏验收。
6. 通过交互门禁后，再进入 PhysX/SAPIEN 接触验证和机器人训练。

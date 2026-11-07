# v0.4.2 RoboTwin 默认物理策略与验证边界

本版本把已验证策略纳入 full_controls 默认构建，无需外传一次性实验配置。它是仿真兼容选择，不是1708硬件摩擦或完整回中曲线识别。公开参数、来源和未知不确定度见[版本化reference](../../../references/robotwin_v042_policy.json)，小型测量/验证摘要见[robotwin_validation.json](robotwin_validation.json)。原模型作者、资产许可及测量来源不变。

## 默认行为和历史替代

| 项目 | v0.4.2 full_controls | 来源/适用范围 |
|---|---|---|
| tilt static/dynamic | 均0Nm | 独立登记的有限兼容族选择，不能宣称硬件干摩擦为0 |
| tilt粘性b | .0018707873827064705N*m*s/rad | 8×原D；选值在T1–T4之前冻结 |
| 线性回中 | 原K≈.03487569188Nm/rad保留；总D≈.002104635816Nms/rad | 原线性模型，未采用tanh诊断代理或.002Nm诊断摩擦 |
| 粘性通道 | force-mode drive damping；新friction的viscous getter=0 | 与弹簧共享原force_limit，只有未饱和区间等价于无界−b*v |
| 角锥 | 原生D6两swing角上限；click.child→stick共pivot，平移/twist FREE | 公共23°保持；替代历史distance附加闭环 |
| 求解数值 | 本articulation64/16 | 双引擎同输入View对照，不是摩擦family的推导或硬件物性 |
| 按压 | 原前置壳体系轴、7.4N+1000q、0.4mm | CPU原生恒定−7.4N qf+零target低刚度drive；10.4N仅约束spring drive |
| ABXY与信号 | 行程1.22mm；原归一化/死区保留 | 负责人1708实测B/X/Y，A为结构推断，未知仍未知 |

旧mu=.1仍作为2026-10-09用户选定的数值设置保留来源，历史资源可加载；新full_controls在生成和加载时都清零其legacy coefficient。历史distance锚点/公式和来源保留，未把旧报告改写成当时已用新角锥。未配置的新左摇杆旧profile不套用full_controls字段。其他后端独立选择原生机制，不继承RoboTwin数值。

## 参数选择与实现证据

原free-root shake资源和聚合已恢复，原逐tick波形及完整启动argv未找到。以指定旧资源重新生成参照，480Hz原聚合raw峰.00775021048，新回放.00775025343；这不是恢复到的原始波形。拟合协议和力时序已版本化到[compatibility protocol](../../../tests/acceptance/robotwin/data/v042_compatibility_protocol.json)和[shake reference](../../../tests/acceptance/robotwin/data/v042_shake_reference.json)。

选择目标为原raw≤.01和与再生成旧轨迹四轴q的归一化MSE，合格族内按已登记规则择优；没有从T1–T4分数反挑物性。选中静/动0、b=8D，训练峰.00932347184。static960Hz保留工况新raw峰.00125281680、旧.00000174359；shake240Hz新.01142787798、旧.01009614382，二者未参与再调参，不能声称所有时间基准完全等价。

同b的小惯量原生通道对照支持implicit drive damping映射。原native-friction viscous在小惯量/较大b*dt/I下有可复现衰减差异；不能用过大的显式Euler误差冒充API单位bug，也未证明唯一内核根因。PGS和TGS分别与整步/位置子步隐式参照相符，未据此更改SDK或迭代数追分。

64/16的独立依据：同一资源/球体/根pose/材质/offset/dt下，官方3.0.3与a1均在10/1失败、64/16通过，单独增加idle仍失败。历史gripper64/16有记录，但历史gamepad有效求解组次数未知。最终只改手柄per-art属性；连接组可能使用最大迭代，不能从球体getter10/1推导有效次数。

## 实测结果与评分修复

历史完整策略验证使用a2。a3公开重建已完成；最终wheel的正常DAG、公开加载、信号往返和T1/T2/圆锥/T3v2/T4均已直接运行，见[安装包验收](robotwin_wheel_validation.json)。本文件的参数选择与控制对照仍保留历史a2身份。native cone只接受列出的a2/a3构建，stock/a1同名setter不是能力证明。

| 测试 | 已保存原数据复核 |
|---|---|
| T1左右0/12/20° | 6/6 |
| T2左右六档 | 12/12 |
| 圆锥/回中 | 6/6原书面判据 |
| T3 v2 | 新10/10；旧6/10 |
| T4原26项 | 候选64/16为23/26，无原通过项退化 |
| 同候选10/1控制 | 21/26，View/Menu/Guide退化 |

三个历史T4失败仍为Pair/L3/R3，没有冒充新失败或新通过。T3旧模型并非所有低档都失败：6N两侧约.054/.057超过.05，8.14N只到约.66/.65；新模型在同协议的低力和正对照均通过。

原runner误把单轴下限用于斜推。正式score_trace现为斜向≤23.1°、单轴22.9–23.1°及原回中条件；boundary_reached仅诊断。一个小行为测试覆盖斜向22.89°通过、单轴22.89°失败、斜向23.11°失败。旧false与原trace保留，新结果从同trace复算。无锥同载荷斜推26.975°/24.998°证明载荷有区分力；不是修改物性追通过。

## 饱和和额外压力边界

保留原力限。拟合/保留/正式验收63组状态估计中，四组单轴圆锥有瞬态未截断需求超过.024Nm（最高.081659Nm）；T3保守界也有超过cap样本。估计不是求解器内部力读回，低于cap不排除未采样子步饱和，保守界高于cap也不证明单轴实际饱和。

额外overdrive+press同时令两tilt目标=2×逐轴上限并轴向压12N；click最小raw约.914/.899，限制仍在。正式生产圆锥是2.910747N横推、原回中drive，没有越界目标；T1/T2持角夹具的100Nm/rad、10Nm上限也不是生产物性或已测实际力矩，三者分别报告。压力诊断不等于正式2.91N检测失败，也不因正式检测通过被隐藏。

CPU加载叠加持续qf，不替调用方初始化或步进；后续set_qf覆盖会丢预压。GPU物理click预压暂不支持，CPU物理+GPU渲染可用。没有硬件IO、训练或新外观身份验收结论。公开报告只分发小型协议/摘要；大型逐步trace、临时截图、私有日志和SDK构建中间物不随本报告发布。

## 正常使用

checkout具备批准输入与build依赖时：

```sh
python scripts/build_resources.py --inputs . --output ./gamepad_resources --backend robotwin
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$PWD/gamepad_resources"
```

在调用方创建的CPU SAPIEN场景中使用原load_into_scene；全局配置和生命周期由调用方掌控，不需要手改manifest或实验calibration。安装版入口、平台依赖和Release资产由项目README统一提供。

# v0.4.2 发布与安装包验收

本版本整合三个后端最新摇杆/按钮实现。主wheel与仅One S输入zip配套发布；原模型、2K贴图与52个已批准输入payload相对v0.4.1完全相同。未知硬件物性仍保留null，信号归一化和死区没有调整。

## 交付与环境

| 制品 | 用途 |
|---|---|
| `xbox_gamepad_physics-0.4.2-py3-none-any.whl` | 主包、构建器、小型参数证据与下游示例 |
| `xbox_gamepad_physics-resources-0.4.2.zip` | 仅已批准One S原始输入、署名及许可；本地生成后端资源 |
| `sapien-3.0.3+concon.physx5.6.1.a3-cp310-cp310-manylinux_2_35_x86_64.whl` | RoboTwin默认原生依赖，Python3.10/Linux x86_64/glibc≥2.35 |
| `sapien-3.0.3-concon-physx5.6.1-a3-source.tar.gz` | 固定上游提交、完整补丁、通用重建脚本与完整许可证 |
| `PUBLIC_ENGINE.json`、`verification-summary.json`、`REPORT.md` | 引擎制品身份、实际验证和限制 |
| `VALIDATION.json`、`SHA256SUMS` | 本版本安装包验收摘要及全部附加payload校验和 |

制品来自[同一Release](https://github.com/5o1/xbox_gamepad_physics/releases/tag/v0.4.2)。RoboTwin采用CPU PhysX，支持GPU渲染；其GPU物理click预压尚不支持。MuJoCo保留固定`3.16.0+concon.sdf3689.2` fork；上游对应PR已合并，但本次未自动升级为未验收的新引擎。Isaac使用外部Lab2.3.2/Sim5.1/Python3.11/兼容torch，必须先启动AppLauncher再author USD。

## 已执行的整合检查

Python unittest320项，17项因外部前置条件跳过；MuJoCo pytest30项和Node35项全部通过。沙箱禁止回环socket导致第一次服务测试无法启动；在宿主按原命令重跑通过。一次旧公共物理夹具只含左关节且期待已替代的旧摩擦，补齐左右关节并更新默认预期后通过；未改物理实现或阈值。最后补齐实际导入的RoboTwin映射模块指纹，资源解析15项通过。

实际最终wheel在隔离site-packages导入，断言包版本及所有Python源字节与wheel一致；QA路径只提供tests，不包含checkout/src。资源从本次wheel和输入zip正常offline DAG重新生成，未把历史资源冒充本次产物。主wheel、输入zip、原生依赖和源码包均扫描私有路径/凭证；原生库还检查RPATH及CUDA设备代码。

| 后端 | 最终wheel验证 | 详细记录 |
|---|---|---|
| RoboTwin/SAPIEN a3 | 正常DAG、公开SDF加载、20DOF/64/16、加载/释放非零信号往返；T1 6/6、T2 12/12、圆锥回中6/6、点力T3v2 10/10；冻结T4 23/26，无历史通过项退化 | [安装包记录](robotwin_wheel_validation.json) |
| MuJoCo | fresh DAG/数值读回、31组件测试、真实外力加载/卸载、K2b；T1 6/6、T2 12/12、点力T3v2 10/10；T4 25/26，无历史通过项退化，全部T4原始轨迹独立重评分一致 | [安装包记录](mujoco_wheel_validation.json) |
| Isaac Preview | fixed/free N1、free N64公开加载及自动预压生命周期/信号往返；T1 6/6、T2 12/12、点力T3v2 10/10；T4 23/26，无原通过项退化，全部原始T4轨迹已独立重评分 | [安装包记录](isaac_wheel_validation.json) |

RoboTwin参数选择、训练/保留工况和额外overdrive限制见[专项报告](robotwin.md)；旧a2参数选择证据保持其历史身份，新a3完整运行另列。[引擎a3报告](sapien_a3.md)记录108个物理源文件与a2相同、CPU检查、GPU20步和真实RoboTwin reset；它们不能代替全手柄或任意GPU API覆盖。

## 保留的资格边界

冻结26项结果允许保留已知失败，不等于26/26：RoboTwin为Pair/L3/R3，MuJoCo为Pair，Isaac为Guide/Pair/R3。Isaac继续Preview。23°严格瞬态/批量界限、任意负载、完整接触就绪、实物标定和RL均未由本次验收建立；ALPS代表规格没有识别实际1708模块。

旧球夹具T3仍归档为无效，不用其零信号证明物理正确。原始逐步数据、20张网格/测量示意和历史报告保留在工作区，未作为临时图片或私有日志打入Release。公开小型汇总保留实际输入SHA、每项分数和失败，不隐藏历史差异。

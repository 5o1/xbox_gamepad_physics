# Xbox One S 资产交付清单

范围：Xbox One S 资产及其 RoboTwin/SAPIEN、MuJoCo 接入。逐项完成后验收；实验过程保存在 `results/`。

## 1. 两平台视觉资产与流畅检查

- [x] RoboTwin/SAPIEN
- [ ] MuJoCo
- [ ] 用户确认外观与交互效果

产物：带 UV、法线、2K 贴图和材质的分件资源；两平台原生检查入口与相机图像输出。

验收：完整显示手柄；旋转、缩放流畅；没有错误遮挡、明显曝光或颜色问题；
外观以用户认可的 [Boiler Room/Cycles 图](../results/xbox_official_import_comparison/official_import_4.5.9_LTS/reference_matched_cycles_probe/boiler_room_vertical_fov35_strength_1p0.png) 为参考，最终由用户确认。
使用各平台原生显示能力，保持原资产与材质来源可追溯。

当前：RoboTwin/SAPIEN 已由用户确认通过，见
[视觉验收记录](../results/robotwin_visual_stage/README.md)；正在接入 MuJoCo。物理参数不属于本项。

## 2. 共用运动学与手柄状态映射

- [ ] 完成并验收

产物：部件和关节装配定义、轴向、限位、来源，以及两平台共用的状态映射。

验收：中立、端点、对角和并发输入正确；越界返回连续；状态与可见部件运动一致。
有来源的估计明确标注，无法推断的字段留空。

当前：已有估计运动学预览，正式规格与两平台尚未接通。

## 3. 接触物理资产

- [ ] 左摇杆接触链路
- [ ] 其余控件
- [ ] 两平台验证

产物：碰撞体、惯量、回弹、阻尼、摩擦及 URDF/MJCF。先完成左摇杆，再扩展其余控件。

验收：接触能推动控件并产生对应信号；释放回位、限位、穿插和数值稳定性通过。
运行所需参数有依据；缺项明确报告，不静默使用默认值补齐未知物理量。

当前：两个物理后端仍未就绪。

## 4. 分发与完整导入

- [ ] 完成并验收

产物：自包含资源、加载接口、最小示例、许可和安装说明。

验收：全新 clone 后按文档导入两平台，无需开发环境的私有资产目录；
鼠标操作与真实 Xbox One S 输入可分别驱动资产，并完成失焦、断开和释放检查。

当前：基础加载接口已有；运行资产与完整验收待完成。

## 项目依据

[资产索引](../assets/asset_index.json) · [物理规格](../specs/xbox_v1.json) ·
[导入接口](importing.md) · [许可声明](../THIRD_PARTY_NOTICES.md)

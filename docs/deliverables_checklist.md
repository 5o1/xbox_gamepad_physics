# Xbox One S 资产交付清单

范围仅包括 Xbox One S 手柄资产及其两个仿真后端。RoboTwin/SAPIEN 与 MuJoCo
分别推进、分别验收；共用同一份视觉来源、物理规格和手柄状态通道定义。

未知的机构或动力学参数继续留空并标注，不能由仿真器默认值静默补齐。

## 路线 A：RoboTwin / SAPIEN

### A1. 视觉资产

- [x] 16 个分件、UV、法线和 2K PBR 贴图接入 SAPIEN
- [x] 在 RoboTwin 实验台、默认灯光和 head camera 中渲染
- [x] 用户确认外观通过

记录：[RoboTwin 视觉验收](../results/robotwin_visual_stage/README.md)。

### A2. 左摇杆物理闭环（第一版已通过）

- [x] 确定左摇杆两自由度机构、关节轴、中心和限位；逐项记录来源或留空
- [x] 生成摇杆帽、杆体和机身开孔 gate 的第一版碰撞几何
- [x] 为相关 link 写入显式估计质量、COM 和正定惯量
- [x] 在 URDF 中加入两轴关节及估计的回中刚度、阻尼和摩擦
- [x] 通过 RoboTwin loader 载入 SAPIEN articulation，解除该切片的 readiness 门禁
- [x] 从关节 `qpos` 输出 `left_x, left_y ∈ [-1, 1]`，符号、饱和和径向投影连续
- [x] 用可见 kinematic sphere 通过 PhysX 接触推动摇杆，释放后回中
- [x] 用户查看接触视频，确认球体、摇杆和外壳的可见运动关系
- [x] 保存接触、限位、回中和固定时间步/参数敏感性测试
- [x] 用独立虚拟手柄 overlay 显示左摇杆单位圆信号轨迹并保存视频

验收条件：外力能够通过 PhysX 接触推动左摇杆；状态输出覆盖中立、四个端点、
对角和越界；释放后回中；无明显穿插、爆振或数值跳变。

### A3. 其余控件

- [ ] 右摇杆
- [ ] ABXY、Menu、View、Xbox 和 Connect 按钮
- [ ] D-pad
- [ ] LB/RB 与 LT/RT
- [ ] 摇杆按压 L3/R3
- [ ] 并发输入和完整标准手柄状态张量

### A4. RoboTwin 交付

- [ ] 完整 `mobility.urdf`、碰撞资源、`model_data.json`、`bounding_box.json` 和 `semantics.txt`
- [ ] 完整手柄 profile 通过 readiness 检查
- [ ] 全新 clone 后可加载、仿真和读取手柄状态
- [ ] 真实手柄输入可以驱动虚拟 articulation 完成对应动作

## 路线 B：MuJoCo

### B1. 视觉资产与 Filament 接入（当前项）

- [x] 16 个分件和共用视觉资源转换为可加载的 MuJoCo 资产
- [x] 独立场景与父 `MjSpec` 附加接口
- [x] classic/EGL 基础加载与首帧验证
- [ ] 完成带 opacity 修复的 MuJoCo 3.15 Filament wheel 构建
- [ ] 用最小 opacity 场景验证官方版本与补丁版本的差异
- [ ] 在 MuJoCo 原生场景生成最终对比图
- [ ] 用户确认 MuJoCo 外观通过

参考外观：[Boiler Room/Cycles 验收图](../results/xbox_official_import_comparison/official_import_4.5.9_LTS/reference_matched_cycles_probe/boiler_room_vertical_fov35_strength_1p0.png)。

### B2. 左摇杆物理闭环

- [ ] 使用与路线 A 相同的机构规格生成 MJCF body、joint、geom 和 inertial
- [ ] 设置两轴限位、回中刚度、阻尼和摩擦
- [ ] 从 `qpos` 输出与路线 A 同序、同符号、同范围的 `left_x, left_y`
- [ ] 完成接触、释放回中、限位和固定时间步稳定性测试
- [ ] 对同一组控制点比较两个后端的位移与状态响应

### B3. 其余控件

- [ ] 右摇杆
- [ ] ABXY、Menu、View、Xbox 和 Connect 按钮
- [ ] D-pad
- [ ] LB/RB 与 LT/RT
- [ ] 摇杆按压 L3/R3
- [ ] 并发输入和完整标准手柄状态张量

### B4. MuJoCo 交付

- [ ] 自包含 MJCF/MJZ、碰撞资源和状态绑定
- [ ] `estimated_v0` manifest 通过 readiness 检查
- [ ] 全新 clone 后可加载、仿真和读取手柄状态
- [ ] 鼠标交互和真实手柄输入均可驱动虚拟资产

## 共用依据

[资产索引](../assets/asset_index.json) · [物理规格](../specs/xbox_v1.json) ·
[导入接口](importing.md) · [许可声明](../THIRD_PARTY_NOTICES.md)

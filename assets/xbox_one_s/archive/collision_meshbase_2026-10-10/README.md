# Xbox One S collision mesh base

作者：BatonyRobson。作品：Xbox One S Controller/Gamepad (Animated)。

- 来源：https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4
- 许可：[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
- 许可全文：https://creativecommons.org/licenses/by/4.0/legalcode

本目录是碰撞体生成的输入资产：17 个组件各自保存为独立的闭合壳（封闭、流形、法向朝外）。
它只保留可触碰的外形，不复现视觉细节，也不是已验证的接触模型。

派生操作：

- 按视觉 manifest 的比例转换为仿真坐标系，单位米，Z 轴向上。
- 主壳：修复两处自交折叠片；7 个圆孔（ABXY、Xbox 键、左右摇杆）与周围外壳齐平封闭；下侧接口凹槽填平。
- 前板：USB 凹槽填平，背面开口封闭。主壳与前板分别保存，不做合并。
- ABXY 只保留键帽，排除字形装饰片和零厚度视觉底片。
- 摇杆的主体和帽沿防滑环分别封闭，允许二者在同一组件内重叠。
- 其余控件封闭机身内部看不到的开口。
- 排除接口内衬和舌片。顶边凹槽、十字键和配对键凹坑保持原样。

文件：

- `meshes/`：17 个 OBJ，仿真坐标系，单位米，固定 9 位小数。
- `manifest.json`：文件列表、来源记录、署名，以及各组件的取舍。
- 生成器：仓库中的 `scripts/build_collision_meshbase.py`。它只适用于上述审定过的源 mesh；源 mesh 以后变化时，本目录保持不变，可继续使用，不要求同步重新生成。

分发副本时，保留作者、来源、许可和以上修改说明。作者未被声明为本项目的背书者。

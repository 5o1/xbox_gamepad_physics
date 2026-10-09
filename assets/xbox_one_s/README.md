# Xbox One S 视觉资源归档

作者：BatonyRobson。作品：Xbox One S Controller/Gamepad (Animated)。

- 来源：https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4
- 许可：[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
- 许可全文：https://creativecommons.org/licenses/by/4.0/legalcode

`source/xbox_one_s_controllergamepad_animated.glb` 是未修改的原始 2K GLB。
SHA-256：`5c5671c83a9cf15db4b8399e7010aa7d5cde915687ceb348b583eb00b0ed24e2`。

`visual/` 包含当前预览所用的静态 GLB、16 个独立 OBJ 和 `inventory.json`。
派生操作为求值原模型第 0 帧，将部件变换烘焙到世界坐标；未做减面或尺度拟合。
静态 GLB 保留材质和内嵌贴图；OBJ 只包含几何。部件名称、哈希及原始装配变换见 inventory。
机械参数及几何精度尚未完成标定。

运行时运动学配置由 `scripts/build_estimated_v0.py` 生成到
`build/generated/kinematics/xbox_one_s_estimated_v0.json`，来源记录位于
`references/appearance_matched_estimated_v0.json`。
从仓库根目录启动现有查看器时，使用 `--assets assets/xbox_one_s/visual`；
其余参数见主 README 的启动说明。

此归档于 2026-10-08 从 GPU 节点复制，原始与派生文件保持字节不变。
分发副本时保留作者、来源、许可和以上修改说明。作者未被声明为本项目的背书者。

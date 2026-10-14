# Xbox One S 输入包归属与许可

本 zip 只分发已审输入快照、来源和许可说明；运动学、运动契约、sim_visual、URDF、运行时 manifest、SDF 网格由 wheel 在用户机器本地构建。完整第三方历史记录保留在源码仓库根 THIRD_PARTY_NOTICES.md，本输入包不分发其他手柄型号、overlay 或其他第三方代码。

- 作者模型：BatonyRobson，Xbox One S Controller/Gamepad (Animated)。来源：https://sketchfab.com/3d-models/xbox-one-s-controllergamepad-animated-a62cf7475b7d4ead9fbf1a86e5a2b6a4 。许可 CC BY 4.0，规范正文：https://creativecommons.org/licenses/by/4.0/legalcode 。原作者 GLB 保持不变；STATIC_VISUAL 是第 0 帧求值、世界变换烘焙的已审快照；meshbase 是闭合壳派生；CoACD 是 v0.2.0 凸分解快照；具体修改见各目录 README/manifest。未声明实物机械或接触校准。
- 已批准参考图：`assets/xbox_one_s/render/boiler_room_vertical_fov35_strength_1p0.png`，由上述 BatonyRobson 模型在批准的 Boiler Room Cycles 场景中渲染；作为模型派生图像按 CC BY 4.0 分发，作者与规范链接同上。PNG 随输入 zip 分发，wheel 不含此图；渲染配方见 `approved_render.json` 与 `render/README.md`。
- Boiler Room HDR：Oliksiy Yakovlyev / Poly Haven。来源：https://polyhaven.com/a/boiler_room 。许可 CC0，规范正文：https://creativecommons.org/publicdomain/zero/1.0/legalcode 。HDR 已 packed 在批准 .blend 内；不重复附带外部 EXR。
- 自有代码许可 MIT，Copyright (c) 2026 5o1；见所附 LICENSE。输入模型的 CC BY 4.0 和 HDR 的 CC0 不被 MIT 替代。

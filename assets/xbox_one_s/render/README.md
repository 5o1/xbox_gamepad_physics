# 用户指定的 Cycles 场景

`Xbox_One_S_approved_cycles.blend` 直接复用用户确认的
`boiler_room_vertical_fov35_strength_1p0.png` 对应配方。
该文件由原 Blender 4.5.9 场景准备，模型、原始材质和 Boiler Room HDRI 均已打包。
设置与文件哈希见上一级 `approved_render.json`。

固定参数：Cycles、Boiler Room 强度 1.0、关闭额外面光源、Standard / None / Exposure 0 /
Gamma 1、35° 垂直视场角、64 samples、降噪；相机背景沿用原脚本的中性背景。

可直接用 Blender 4.5.9 打开并渲染。`npm run viewer` 通过一个常驻 Blender 进程
渲染交互姿态，浏览器不重新实现着色和灯光。

模型：BatonyRobson，CC BY 4.0，来源与修改说明见 `../README.md`。
Boiler Room：Oliksiy Yakovlyev / Poly Haven，CC0，来源：
https://polyhaven.com/a/boiler_room 。

准备脚本：`scripts/prepare_approved_cycles.py`。它复用原
`scripts/render_reference_matched_probe.py` 的场景设置，只选用户指定的强度 1.0，
另存可分发的场景，不覆盖历史文件。

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

## 2026-10-14 私有路径修订（裁定 4）

按负责人决定原地清理四处路径元数据：load_ui=False 打开；FileSelectParams.directory 清空，HDR Image.filepath 和 ImagePackedFile.filepath 改为相对原文件名，Scene.render.filepath 改为相对目录。固定字符字段的旧尾部字节一并覆盖，不改其他场景属性。网格坐标、拓扑、UV、全部 packed 图像字节保持相同；HDR 仍为 23,613,147 B。原件仅在节点任务目录归档，不随包分发。

预先写定的裁定 4 验收：同 Blender 4.5.9 / GPU 0 / 批准第0帧与全部原参数，旧、新各5次全新交错渲染；比较10对旧旧与25对新旧。全部35对最大差≤1级；新旧不同像素数和平均差中位数均≤旧旧中位数的1.5倍；同色标热图没有出现旧旧没有的新区域集中。实测不同像素中位数为84.5（旧旧）与86（新旧），平均差中位数为0.000014670138888888888与0.000014930555555555555；三条通过，替换前复扫零真实命中。热图与35对明细见 release_v030_b12 报告。

参考 PNG 同时删除了一个含私有信息的文本块；IDAT字节和解码像素不变。approved_render.json 的 reference_sha256 继续表示历史批准绑定，reference_file_sha256 表示当前像素不变、文本元数据已清理的 PNG 文件。

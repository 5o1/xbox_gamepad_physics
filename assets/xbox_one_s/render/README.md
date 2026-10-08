# 已保存 Blender 场景的渲染设置

这些参数和 Filmic LUT 由 `scripts/export_saved_render_settings.py` 从原有 Blender 4.5.9
场景及其随附色彩配置导出。场景 SHA-256 与原审计记录一致：
`8f517046e08da298a35fa2d42c803b09e88ede897afe07e982769b21c9f27432`。

- `settings.json`：原场景环境色、强度、面光源位置/旋转/尺寸/功率、色彩设置。
- `blender_config.ocio`：原始色彩配置，保留来源说明；浏览器使用其中的 Filmic/None 路径。
- `filmic_desat_33.cube`、`filmic_to_0-70_1-03.spi1d`：未修改的原始 LUT。
- `color_samples.json`、`blender_color_samples.png`：通过 Blender 原生色彩处理保存的校验色块。

浏览器通过同一 LUT 的四面体插值和一维曲线接入 Filmic。面光源按
`power / (pi * width * height)` 转为辐亮度，位置及尺寸与模型等比缩放。
这是同一套材质、光源和色彩设置在 WebGL 的实现；Cycles 的路径追踪、间接反射及阴影
与 WebGL 面光源近似仍存在差异，不声明两个引擎像素一致。最终视觉效果由用户验收。

来源：

- https://github.com/blender/blender/blob/v4.5.0/release/datafiles/colormanagement/config.ocio
- https://github.com/blender/blender/blob/v4.5.0/intern/cycles/kernel/light/area.h
- https://github.com/mrdoob/three.js/blob/r180/src/lights/RectAreaLight.js

Filmic 作者为 Troy James Sobotka；其他贡献者见 `blender_config.ocio` 文件头。
这些文件来自 Blender 官方分发包，保留源格式与作者声明，随附 Blender 分发许可全文 `COPYING`。
它们不适用 Xbox 模型的 CC BY 4.0 许可。

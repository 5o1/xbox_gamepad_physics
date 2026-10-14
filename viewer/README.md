# Viewer 与信号 overlay

用户安装后直接运行 `xbox-gamepad-physics viewer --resources ./gamepad_resources --offline --blender /path/to/blender`，或 `xbox-gamepad-physics overlay`。无需 CDN/npm 下载。Blender 4.5 由用户提供；缺少时静态 UI 可用、Cycles 请求明确报错。overlay 含合成 demo trace，可用 --trace-dir 指定用户数据，显示连续上游信号。

检出中的 npm run viewer / npm run gamepad-overlay 仍可用。Python 服务端、worker 与 example 的实现分别在包内 web/ 和 examples/；本目录保留 UI 开发源与历史独立诊断页。发行的 UI 是这些源文件的静态复制，Three 只收实际模块闭包，打包前同步并验证复制内容；不要把 node_modules 或历史在线参考页整体收入 wheel。

资源使用已审输入与同一 kinematics DAG，不再另写 build/generated。真实 Blender/SAPIEN 渲染和交互在 B4 验证。

参考 PNG 只随输入 zip 分发（CC BY 4.0），不收入 wheel。viewer 保持 `/accepted-reference/boiler_room_vertical_fov35_strength_1p0.png` 路由，从资源根 `inputs/assets/xbox_one_s/render/` 读取；缺图显示“缺少输入资源”，不影响页面。

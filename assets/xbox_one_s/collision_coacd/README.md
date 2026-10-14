# 冻结 CoACD 输入快照

来源：v0.2.0 Release 的 xbox_gamepad_physics-resources-0.2.0.zip，原路径 common/xbox_one_s/collision/coacd/，17 个 OBJ 原样提取。版本 coacd 1.0.14，单线程；完整参数、逐壳阈值和壳/凸包计数见 manifest.json。对应同发布包内 meshbase，与当前 ../collision_meshbase 的 19 文件逐字节比较一致；比较记录在 B1/B2 报告。本记录不以哈希断言来源。

这是一份已审冻结快照，下游小球按压和遥操作使用此版。运行时构建只读取，不重算 CoACD。模型来源 BatonyRobson，CC BY 4.0；由 meshbase 做凸分解，属于修改件，归属见 ../README.md，许可规范链接：https://creativecommons.org/licenses/by/4.0/legalcode 。CoACD 工具版本/参数是来源证据，不对凸分解结果赋予额外物理验证结论。

维护者更新必须运行 scripts/regenerate_collision_coacd.py；该命令先归档旧快照，再显式重算。重新生成不自动获得批准，不用于普通用户 build-resources，也不由打包器调用。

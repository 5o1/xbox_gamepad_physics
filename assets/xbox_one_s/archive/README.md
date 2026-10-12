# Xbox One S 资产旧版本归档

本目录保存已被替换的资产快照，文件与替换前逐字节相同，只用于追溯，不参与构建、测试或发布包。

| 目录 | 替换为 | 生成器版本 | 替换原因 |
|---|---|---|---|
| `collision_meshbase_2026-10-10/` | `../collision_meshbase/`（2026-10-11） | 提交 `9bf91a3` 的 `scripts/build_collision_meshbase.py` | 主壳有 10 对不相邻的自交三角形：顶边下方内斜面穿过 Xbox 键圆孔侧壁和封口（8 对），左侧折叠修补的封口穿过两块原始面（2 对）。其余 16 个组件与新版相同。 |

归档内的 `manifest.json` 和 `README.md` 保持原样，其中的生成器路径指向当时的版本。
作者、来源和许可与 `../collision_meshbase/README.md` 相同（BatonyRobson，CC-BY-4.0）；分发副本时保留这些信息。

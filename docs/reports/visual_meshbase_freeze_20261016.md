# visual_meshbase 裁定6：已审v2仓库冻结记录

日期：2026-10-16。负责人已确认裁定5对照图与外观，批准把v2冻结为
`assets/xbox_one_s/visual_meshbase/`。本轮只放入仓库；未接入DAG、加载器、资源包或dist，
未改上游作者GLB、STATIC_VISUAL和冻结MuJoCo树，未commit/push，等待主助手审查和提交。

## 快照与材质

- `visual_meshbase.glb`直接复制已审candidate_v2，仅改文件名，逐字节一致。
- `materials.json`以candidate_v2版本为基础补充半透明组常数不透明度64/255：256个BLEND面的精确覆盖alpha全为64；不是拟合值。
- SAPIEN3.0.3的常数负责透明pass分流，存在底色贴图时shader直接取纹理RGBA，不与常数alpha再次相乘；MuJoCo经典使用RGB贴图和材质常数一次。GLB本身不改因子，继续满足已审Cycles外观。
- `KHR_materials_specular`保持STATIC_VISUAL的`specularColorTexture`（sRGB RGB），作者GLB使用`specularTexture`（线性A）；两者差异保留，后续另行处理。
- manifest记录来源、全部v2参数、6590/256面统计、交界缝/K1/K1b/K2及裁定5后端收益证据、负责人确认与本轮仓库冻结范围。没有哈希断言或私有路径。

固定源码依据：[svulkan2 renderer.cpp:765–800](https://github.com/haosulab/sapien-vulkan-2/blob/2ad24e1e96d88d3dd00fb1a7821ffcef42ab1ed9/src/renderer/renderer.cpp#L765)
按常数opacity/visibility分流。裁定5读取的SAPIEN3.0.3已装`default/gbuffer1.frag:85–94、205`
直接采样纹理RGBA；其副本与证据路径列在快照materials.json中。

## 生成、复现与修订

新增独立维护者命令：

```sh
conda run -n xbox_gamepad_physics python3 scripts/build_visual_meshbase.py --output build/review/visual_meshbase
```

只接受仓库指定的已审STATIC_VISUAL和对应inventory，直接从原2K纹理重新计算精确UV覆盖与一纹素3×3保护层。
BLEND判据是exact_min<255或halo_min<250；不细分、重烘焙、移动顶点或更改UV/法线。
精确坐标边配对和共享索引入射检查在写出GLB前执行，任何异类面切开原共享顶点即报错。
脚本自身逐值验证K1；普通构建不调用它。

在临时目录实际重新生成，结果与candidate_v2的**整个GLB逐字节相同**，元数据也无差异。
另按已审face_partition逐原面号比较两组索引完全一致；全部属性和嵌入贴图当然随完整字节相等。
初次冻结没有旧正式快照可归档。后续覆盖必须通过`--archive`先把旧目录完整复制到
`assets/xbox_one_s/archive/`下新的目录；临时夹具验证了缺少参数会拒绝覆盖、归档先于替换，
以及再生成结果仍标为review_candidate，不能自动沿用历史外观批准。

历史交界缝、K1、K1b与Cycles K2通过依据适用于此次未变字节。
裁定5中SAPIEN光栅恢复ABXY四字、12955改变像素全部在ABXY矩形内；MuJoCo经典四字恢复、13254改变像素亦全在矩形内。
外壳和其它部件不受常数改动影响。RTX线性双球校准失败和Filament缺X display的未完成状态保持，未新增后端通过声明。

## 验证

使用本地conda环境执行`python3 scripts/run_regression.py fast`，退出码0：
Python269项，244通过、25跳过、0失败；JavaScript35项全部通过。
新增4项快照结构测试全部通过：两材质/分组统计、BLEND仅ABXY、常数与来源字段、manifest必需字段及已审检查。
未安装任何依赖。

25项跳过逐项如下，未计作通过：

| 测试 | 跳过原因 |
| --- | --- |
| `infrastructure.test_common_runtime.GamepadStateTests.test_numeric_action_mask_preserves_gradients_on_active_channels` | Torch is an optional training dependency |
| `infrastructure.test_muble_adapter.MuBlEPoseExportTest.test_public_mujoco_handle_exports_muble_trace` | MuJoCo is outside the v0.3 release scope; real MuBlE/MuJoCo integration is therefore skipped |
| `infrastructure.test_mujoco_full_controls_asset.MujocoFullControlsAssetTest.test_generated_profile_is_fresh` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_full_controls_asset.MujocoFullControlsAssetTest.test_mjcf_declares_complete_named_mechanism` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_full_controls_asset.MujocoFullControlsAssetTest.test_runtime_manifest_builds_shared_signal_controller` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_attach_requires_exactly_one_target_and_nonempty_prefix` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_attach_to_frame_preserves_prefix_and_binds_after_compile` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_attach_to_site_and_external_bind_use_named_elements` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_backend_import_is_lazy_and_uses_project_error` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_filament_reference_scene_uses_declared_renderer_resource` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_load_scene_accepts_mjz_declared_by_manifest` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_load_scene_compiles_xml_and_binds_names` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_load_scene_propagates_missing_resource_without_importing_backend` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_missing_compiled_name_fails_instead_of_using_an_index` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_visual_attachment_compiles_and_runs_forward` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_visual_resources_are_complete_and_render_only` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `infrastructure.test_mujoco_runtime.MujocoRuntimeTests.test_visual_scene_runs_forward_before_first_render` | MuJoCo is outside the v0.3 release scope; the frozen tree is retained only as a historical baseline |
| `test_run_robotwin.SapienSmokeTest.test_smoke_twenty_steps_passes` | SAPIEN is an optional backend dependency |
| `test_teleop_shutdown.GatewayShutdownTest.test_detached_gateway_logs_to_file_and_checked_cleanup` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_shutdown.GatewayShutdownTest.test_idle_watchdog_exits_with_broken_stdout` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_shutdown.GatewayShutdownTest.test_shutdown_with_broken_stdout` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_shutdown.GatewayShutdownTest.test_sigint_exits_with_broken_stdout` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_shutdown.GatewayShutdownTest.test_sigterm_exits_with_broken_stdout` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_shutdown.GatewayShutdownTest.test_stop_reason_and_stdout_errors_do_not_block_shutdown` | gateway process tests need aiohttp or XBOX_TELEOP_TEST_PYTHON |
| `test_teleop_slow_clients.GatewaySlowClientsTest.test_real_gateway_slow_client_and_cancellation_contract` | gateway video process tests need aiohttp and FFmpeg |

对全部新增/修改交付文件以及GLB的可读JSON与内嵌PNG文本元数据做隐私扫描，结果见本轮privacy_scan.json。
扫描包含私有绝对路径、机器名、私有IP、代理/SSH端口及本地用户名；未发现匹配。
只保留仓库相对来源、公开作者署名和公开文档链接，没有增加摘要断言。

## 证据索引与交付文件

以下路径均为仓库相对路径；build下历史实验记录是本地实验资料，非构建依赖：

- `build/experiments/visual_meshbase_20261015/REPORT.md`：主报告，追加裁定6。
- `build/experiments/visual_meshbase_20261015/ruling6/regeneration_comparison.json`：完整GLB、分组和属性/纹理直接比较结果。
- `build/experiments/visual_meshbase_20261015/ruling6/archive_check.json`：临时夹具的归档行为核对。
- `build/experiments/visual_meshbase_20261015/ruling6/fast_regression.log`及`regression_results.json`：实际回归输出和逐项跳过结果。
- `build/experiments/visual_meshbase_20261015/ruling6/privacy_scan.json`：本轮交付文件的隐私扫描。

新增：

1. `assets/xbox_one_s/visual_meshbase/visual_meshbase.glb`
2. `assets/xbox_one_s/visual_meshbase/materials.json`
3. `assets/xbox_one_s/visual_meshbase/manifest.json`
4. `assets/xbox_one_s/visual_meshbase/README.md`
5. `scripts/build_visual_meshbase.py`
6. `tests/infrastructure/test_visual_meshbase_asset.py`
7. `docs/reports/visual_meshbase_freeze_20261016.md`

修改：`assets/xbox_one_s/README.md`，增加新快照入口；`.gitignore`仅为正式快照GLB增加精确例外，避免其被现有`*.glb`规则忽略，不改资源包白名单。
实验目录另保存本轮报告与核对记录；没有接入改动，等待审查后由主助手提交。

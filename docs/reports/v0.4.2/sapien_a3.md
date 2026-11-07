# v0.4.2 引擎公共重建 a3

本线已完成 a3 wheel、可重建源码补丁包、许可证整理和直接安装回归，交主监督者集成。未自行发布、push 或新建仓库。

本轮没有物理检查失败。仍保留小惯量 native-viscous 响应限制；GPU/API/全接触覆盖、全手柄正式 T1–T4、实物参数识别、历史 Bus error 因果结论均不在本次“通过”范围内。没有宣称 a3 已解决这些问题。

## 制品与边界

- 版本：`3.0.3+concon.physx5.6.1.a3`；CPython3.10 / Linux x86_64 / glibc≥2.35。
- wheel：`sapien-3.0.3+concon.physx5.6.1.a3-cp310-cp310-manylinux_2_35_x86_64.whl`。
- 源码包：`sapien-3.0.3-concon-physx5.6.1-a3-source.tar.gz`；具体 SHA 以 `SHA256SUMS` 和 `PUBLIC_ENGINE.json` 为准。
- 保留 a1/a2 源码改动、wheel、环境和原证据。a3 使用独立源码副本、新 build、独立安装环境。未修改手柄生产源码/参数、其他后端或共享环境。
- 固定 SAPIEN3.0.3 `731622eac5b140b320076c8a1b6eb4b553c3ccd4`，PhysX5.6.1 `5ca9f472105a90d70d957c243cb0ef36fe251a9f`。108 个 src/include/pybind 文件与保留的 a2 完全相同；SDK 唯一 a3 差异是 release `-lineinfo` 的构建元数据开关。没有改变求解器/摩擦公式/质量/驱动参数或架构矩阵。

## a2 路径来源审计与 a3 处理

a2 的问题既包含诊断信息，也包含运行搜索路径：pysapien 一处旧安装目录属于遗留字符串；Pinocchio、libsapien、svulkan2、simsense 和 GPU 的绝对源码路径来自编译器文件/断言/设备 line 信息；三份 OIDN 库还实际带绝对 RUNPATH。不能将这些都解释为无影响的调试字符串。

采用支持的编译/链接流程处理：

| 文件/范围 | a3 改动及理由 |
|---|---|
| `setup.py` | a3 版本；三处 CMake 配置支持 `SAPIEN_CMAKE_ARGS`；绝对通用源码入口；复制 OIDN 后用 patchelf 设置 `$ORIGIN`；打包 notices/licenses；将上游误写 MIT 的 metadata 校正为实际 Apache-2.0 |
| `scripts/public_flags.cmake` | 同时映射逻辑通用根与解析后的根；C/C++ 的 file/debug/macro prefix-map，NVCC host 同样传入三种 map；相对 install RPATH |
| PhysX `source/compiler/cmakegpu/linux/CMakeLists.txt` | 仅 release 去掉 `-lineinfo`；checked/profile 不变，设备断言的 `__FILE__` 通过通用路径及宏映射处理 |
| wheel GPU runtime | 重新构建，沿用 a2 已验证的 `libPhysXGpu_64.so` SONAME 修正；保留原 SDK/runtime，不覆盖 |
| `THIRD_PARTY_NOTICES.md`、`licenses/` | 完整条款、作者声明、组件来源和逐文件 SHA256 |

没有进行 ELF/fatbin 原地字符串替换。patchelf 仅用于记录的 RPATH/SONAME，auditwheel 负责相对查找路径及 libdeflate graft。

最终 ZIP 所有成员未检出已知私有根；11 个 ELF 的 RPATH/RUNPATH 均为相对路径或不存在。扩大扫描常见 Unix 绝对路径根也无候选路径。用独立 cuobjdump 解出4个 CUDA-bearing ELF 的254个 cubin/PTX：OIDN12、PhysX122、libsapien24、simsense96，私有根命中0、debug line 段0。系统 readelf 对 NVIDIA 专用 section 的 info 字段发出格式警告；未把警告解释成设备代码失败，解包及扫描结果保留在 `cuda-audit.json`。

## 许可证

wheel 和 source bundle 均带86份完整条款/notice，`licenses/MANIFEST.json` 逐文件记录 SHA。wheel 内容与收集文本的86个摘要已逐项相符。合法上游署名没有删除。

特别核对：

- SAPIEN 实际为 Apache-2.0，原 Hillbot/UCSD 声明保留，并附完整 Apache 文本。
- Pinocchio2.6.18 文件虽名 `COPYING.LESSER`，实际是 BSD-2-Clause，不凭文件名推断 LGPL。
- Eigen3.4.0 的 MPL2/BSD/MINPACK 条款及源码可用链接保留。实际构建依赖记录未引用两份 LGPL 标记的 unsupported solver 头文件。
- OIDN2.0.1 为源码构建，提供 Apache2、weights、CUTLASS、完整 third-party-programs；未将未使用的 Intel 预编译包专有许可错套到源码构建。
- Assimp/KTX/ImGui/stb/嵌入字体/DLPack/urchin/Boost 等随实际构建源收集；auditwheel graft 的 libdeflate1.10 附完整发行版 copyright/MIT 文本。
- CUDA12.4/12.8.1 原始条款与 OptiX7.6 的 DesignWorks 协议及 API/stub 声明均保留；Vulkan-loader1.3.224 带对应完整许可。没有捆绑驱动、libnvoptix 实现或整套 CUDA SDK。
- NVIDIA 的独立分发条件仍适用；本线没有发送任何商业分发通知，也不将整份 wheel 重新声明为 Apache2。协议原文供发布方核对。

来源为固定依赖源码/本次真实使用的工具包/系统发行包。补收的 OptiX、DLPack、Vulkan 许可 URL 和 SHA 在 bundle 的 `LICENSE_ORIGINS.json`。Vulkan 上游原始 binary blob 沿用，未独立重建其历史编译来源，这是已知限制。

## 构建与重现

通用重建说明见源码包 `README.md`、`INPUTS.json`、`DEPENDENCIES.json`、`CUDA_INPUTS.json`。源码包按106文件 allowlist 导出，含两份完整公共 patch、通用准备/固定依赖下载/构建/repair 脚本、完整许可和最小摩擦入口；没有缓存、原始私有日志、SSH/profile、controller 模型或其他 controller。

本次使用 GNU C++11.4；SAPIEN C/NVCC host 为 GNU12.3，PhysX C/C++/CUDA host 为 GNU11.4；CUDA12.4.131/12.8.93，CMake3.31.6，Ninja1.11.1.4，Python3.10.12，setuptools75.8.0，wheel0.45.1，auditwheel6.2.0，patchelf0.17.2.1。PhysX SASS89/PTX89、SAPIEN CUDA60/61/70/75/80/86，均沿用 a2。

实际构建用了独立源副本与固定输入缓存，没有复用旧二进制 build。PhysX、SAPIEN native、Python/wheel/repair 均首次构建成功。SDK patch 已对精确基线 Git index 检查；SAPIEN patch 已在隔离基线副本实际应用。固定依赖检查逐个核对21个 Git HEAD，且显式核对 FetchContent override 会跳过的原 SAPIEN copy patches。没有执行整套“空缓存联网下载再构建”，也不作逐位可重现承诺。

CPU 重跑入口（使用独立已安装 a3 的环境）：

```sh
PYTHONDONTWRITEBYTECODE=1 DISPLAY='' CUDA_VISIBLE_DEVICES='' \
  /tmp/sapien-public-a3-venv310/bin/python concon/scripts/minimal_friction.py --output OUT/friction
PYTHONDONTWRITEBYTECODE=1 DISPLAY='' CUDA_VISIBLE_DEVICES='' \
  /tmp/sapien-public-a3-venv310/bin/python concon/public_a3/checks/cone_behavior.py --label a3 --output OUT/cone
```

角锥重放协议 `cpu/cone/registration.json` 先于该重放执行写入。CPU 摩擦使用原冻结模型/评分。SDF 检查调用现有公共 `load_into_scene`，仅将资源根指向只读快照以避免 builder；同时跑了历史快照和当前 release 默认快照，未替换物理/信号实现。`sdf-inputs.json` 固定了后者实际输入摘要。

## 直接安装 a3 的结果

| 检查 | 实测结果 |
|---|---|
| CPU 36起动 +24量纲 +生命周期 | 原四项 passed 均为 true；新 effort 的所有起动档位0.00201 N·m，跨预压差0% |
| 默认TGS隔离角锥 | 64组稳态23.020412–23.073531°；64组无锥对照最小45.956667°；2个平移/twist FREE探针均通过 |
| SDF公共加载/步进/信号往返 | 两快照均20DOF、20步有限状态、roundtrip通过；不代表完整正式手柄验收 |
| GPU3短测 |20步 DirectGPUAPI qpos往返、qf运动、DLPack有限状态，通过；墙钟4.66s，小于30s |
| 真实 RoboTwin reset | `stack_blocks_two` seed0，通过；setup35.30s，墙钟64.98s，小于180s；4路RGB有效 |
| reset 对照 | 与a2 robot qpos最大差0；对官方3.0.3最大差1.454282028e-9；两方块位置最大差0m |

先在新环境完成安装，再导入/测试；没有用 a2 哈希相等代替 a3 运行。GPU/renderer 固定设备3的PCI；短测及reset前分别检查占用，设备3没有其他compute任务；全卡进程采样保留，未在0–2执行任务。

`0.002 N·m` 始终是诊断值，不是生产摩擦标定。本次没有改变手柄线选择的显式 native drive damping 映射。

## 失败、修复与尚未验证

没有物理失败、构建失败或30/180s超时。执行辅助错误均有界：汇总脚本最初误用无NumPy的系统Python，改用标准库最大差计算后成功（1次）；一次证据 rsync 错拼 key 文件名，按原正确路径重试成功（1次）。节点短测脚本路径在启动前发现旧目录不存在，先将同一诊断脚本复制到本任务目录后才执行。Vulkan许可本机直连两次TLS失败，节点直连确认失败后按约定使用节点fallback；未安装依赖或改共享环境来规避。

尚未验证：完整GPU API/contact/multiscene矩阵、更多架构/驱动下限、OIDN实际去噪任务、空缓存端到端重建、历史Bus error的因果解释、实物回中曲线/静动摩擦、完整手柄/其他后端的正式发布集成评分。通过本次回归只支持“已测用例下公共重建保持a2行为”的假设。

## 我自行做出的选择

使用通用路径别名和解析根双重 prefix-map；仅 release 删除设备 lineinfo；按实际许可文本纠正 MIT metadata；以完整 notices overlay 随源码包提供；增加精确 FetchContent 依赖准备步骤以显式保留原 copy patches；可公开摘要与内部原始日志分开。未选择新的物理参数/求解器/架构，也未扩大 native-viscous 修复范围。

## 交监督者

以 `PUBLIC_ENGINE.json`、`release_allowlist.json` 和 `SHA256SUMS` 作为集成入口。只发布明确 allowlist 制品，不能递归发布本输出目录：`a2_path_audit_private.json`、`build-logs-private.tar.gz`、node进程证据和原始日志可能含私有构建根/他人进程路径。主监督者负责主包a3依赖、a2兼容说明、完整手柄及其他后端集成验收，以及最终GitHub发布；本线没有执行这些发布动作。

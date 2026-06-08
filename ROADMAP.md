# Motion Control — Precision Force Control ROADMAP

> 创建: 2026-06-04 | 最后更新: 2026-06-07 (Session: P1.1 CSV Export + P1.2 Tuning Aliases) | 宪法: CONSTITUTION.md

---

## 能力基线

| 维度 | 当前 | 目标 (6个月) | 目标 (12个月) |
|------|------|------------|------------|
| EtherCAT 主站 | **L3** (1 kHz DC, CoE, 模拟模式) | L3 (硬件实测) | L4 (多品牌即插即用) |
| 示波器前端 | **L4** (3 前端: tkinter/PySide6/Web, 381 FPS) | L4 (硬件联调) | L5 (移动端适配) |
| 伺服参数库 | **L5** (12 品牌, 3,245 CoE 对象, 148 调参别名) | — | — |
| AI 分析引擎 | **L4** (三检测器 + HITL + CLI + 别名 + CODESYS, 240 测试) | L4 (硬件实测标注) | L5 (PPO 一键整定) |
| 力控自学习 | **L1** (CODESYS FB 已编写) | L2 (PPO 离线训练) | L4 (在线自适应) |
| CODESYS 集成 | **L3** (5 FBs + DUT + 自动代码生成) | L3 (硬件联调) | L4 (在线更新) |
| 测试体系 | **L4** (285 测试, 22 文件) | L4 (CI/CD) | L5 (硬件-in-the-loop) |

---

## Phase 0: 市场调研 ✅ (2026-06-06 完成)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| M0.1 | 竞品分析 | `01-market-research/competitive-analysis.md` | ✅ |
| M0.2 | 市场规模评估 | `01-market-research/market-sizing.md` | ✅ 2026-06-06 |
| M0.3 | 技术栈选型 | `02-architecture/technology-stack.md` | ✅ |
| M0.4 | 差距分析 (vs 标杆) | `01-market-research/gap-analysis.md` | ✅ 2026-06-06 |
| M0.5 | 可行性报告 | `01-market-research/feasibility-report.md` | ✅ 2026-06-06 |

## Phase 1: Delta A3 参数库 ✅ (2026-06-03 完成)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P1.0 | ESI XML 解析 | `extract_esi.py` — 693 CoE 对象 | ✅ |
| P1.1 | CHM 帮助文件反编译 | 1011 HTML 文件 → 738 参数中文描述 | ✅ |
| P1.2 | ESI + CHM 合并 | `delta-a3-merged.json` — 693 对象含中文名/单位/范围/默认值 | ✅ |
| P1.3 | 示波器通道配置 | `delta-a3-scope-config.json` — 32 信号 → 8 通道 | ✅ |
| P1.4 | 调参快速指南 | `delta-a3-tuning-guide.md` — 76 个调参相关参数 | ✅ |

## Phase 1: 原型验证 ✅ (2026-06-06 完成)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P1.1 | EtherCAT 主站搭建 | `03-ethercat-master/` — SOEM GCC 编译, `libsoem.a` 116KB, 11 模块, 37 测试 | ✅ |
| P1.2 | 台达 A3 参数库 | `05-servo-params/delta-a3/` — 693 CoE 对象, PDO 映射, 示波器配置 | ✅ |
| P1.3 | 8 通道示波器原型 | `04-oscilloscope/` — PySide6 + QPainter + Web, 3 套前端 | ✅ |
| P1.4 | AI 分析引擎集成 | `06-ai-analyzer/` — 三检测器管线 (电流/跟踪误差/谐振) + AI&ML Agent 桥接 | ✅ |
| P1.5 | 集成测试 | `tests/` + `06-ai-analyzer/tests/` — 63 测试 (43 单元 + 20 集成), 全部通过 | ✅ |

### Phase 1 交付统计

| 指标 | 数值 |
|------|------|
| 新增源文件 | 16 (AI 分析器 10 + HITL 6) |
| 新增 Python 代码 | ~4,600 行 |
| 单元测试 | 118 (9 测试文件) |
| 集成测试 | 20 (2 测试文件) |
| 总测试通过 | **138/138** |
| Phase 0 文档 | 5 (竞品分析/市场规模/差距/可行性/技术栈) |

---

## Phase 1.6: 开源基础设施 ✅ (2026-06-06 完成)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| O1.1 | 许可证 GPLv2 → MIT | `LICENSE` + 全量代码头更新 | ✅ 2026-06-06 |
| O1.2 | Pro/Free 模块拆分 | `pro/` 目录 + `.gitignore` 隔离 | ✅ 2026-06-06 |
| O1.3 | 差距评估报告 | `01-market-research/pro-free-gap-analysis.md` | ✅ 2026-06-06 |
| O1.4 | CONSTITUTION 更新 | G6, G7 门禁 (Pro/Free 边界) | ✅ 2026-06-06 |

## Phase 1.7: HITL 工程师反馈闭环 (当前 ← 2026-06-06)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| HITL.1 | HITL 数据类型 | `hitl_types.py` — EngineerPrompt / EngineerFeedback / AuthorizedAction | ✅ |
| HITL.2 | HITL 门控核心 | `hitl_gate.py` — classify() + generate_prompt() + process_feedback() + authorize() | ✅ |
| HITL.3 | 多模态工程师提问模板 | `engineer_prompts.py` — 7 类异常, 中英检查清单, 语音/图片/视频提示 | ✅ |
| HITL.4 | 审计日志 | `action_logger.py` — 不可变审计追踪, JSON 导出 | ✅ |
| HITL.5 | Pipeline 集成 | `analyzer_pipeline.py` — prompt_engineer() / process_engineer_feedback() / get_authorized_actions() | ✅ |
| HITL.6 | Web UI 反馈面板 | `scope_server.py` — /hitl/analyze + /hitl/feedback API, 授权/拒绝/提交观察按钮 | ✅ |
| HITL.7 | 单元测试 | `test_hitl_gate.py` (63 测试) + `test_action_logger.py` (18 测试) | ✅ |
| HITL.8 | 差距分析更新 | `scenario_resonance_field.py` — 7 项全覆盖: 2 自主 + 5 HITL-bridged | ✅ |
| HITL.9 | LLM 诊断精化器 | `llm_refiner.py` — Claude API 驱动, 三级降级 (LLM→关键词→通用回退) | ✅ |
| HITL.10 | HITL Gate LLM 集成 | `hitl_gate.py` — _refine_diagnosis() LLM 优先 + _build_annotation_from_llm() | ✅ |
| HITL.11 | Web UI LLM 展示 | `scope_server.py` — HITL 面板展示 LLM 精化诊断（诊断/建议/零件/参数补偿） | ✅ |
| HITL.12 | LLM 单元测试 | `test_llm_refiner.py` (22 测试) — 解析/降级/消息构建/完整流程 | ✅ |
| HITL.13 | CLI 命令系统 | `servo_cli.py` + `cli_commands.py` — REPL/单命令/脚本/管道 4 模式, 零依赖 | ✅ |
| HITL.14 | CLI LLM 翻译层 | `cli_llm_bridge.py` — System prompt 教 LLM CLI 语法, NL→精确命令翻译 | ✅ |
| HITL.15 | CLI 测试 | `test_servo_cli.py` (63 测试) — 命令引擎/REPL/LLM 翻译/别名系统/优雅降级 | ✅ |
| HITL.16 | CLI 别名系统 | `cli_aliases.py` — 83 内置别名 + 15 分类别名 + 用户自定义 + 文件持久化 | ✅ |
| HITL.17 | LPF + S-Curve 规则 | `tuning_rules.py` — current_ripple(2 LPF params) + velocity_ripple(3 jerk/S-curve params) + 12-brand LPF aliases | ✅ |
| HITL.18 | 差距分析更新 | #3 低通滤波 ✅Covered + #6 S曲线 ✅Covered — 7 项现场报告: 4 自主 + 3 HITL-bridged | ✅ |

### HITL 交付统计

| 指标 | 数值 |
|------|------|
| 新增 Python 文件 | 6 (`hitl_types.py`, `hitl_gate.py`, `engineer_prompts.py`, `action_logger.py`, `test_hitl_gate.py`, `test_action_logger.py`) |
| 新增 Python 代码 | ~1,800 行 |
| 修改文件 | 5 (`config.py`, `analyzer_base.py`, `analyzer_pipeline.py`, `__init__.py`, `scope_server.py`) |
| 新增测试 | 81 (63 HITL + 18 审计日志) |
| 总测试通过 | **138/138** (原 63 + 新 75 + 调整) |
| 异常分类覆盖 | 7/7 类别: 2 safe, 3 actionable, 2 ambiguous |

## Phase 1.8: Free 层关键功能 ✅ (2026-06-07 完成)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P1.1 | CSV 波形导出 | `csv_export.py` — 单轴/多轴/标注/会话包导出, 3 前端 + CLI + Web, 21 测试 | ✅ 2026-06-07 |
| P1.2 | 9 品牌调参别名 | `tuning_rules.py` — 148 别名/12 品牌, BRAND_CAPABILITY_NOTES, 56 参数描述 | ✅ 2026-06-07 |

### P1.1 + P1.2 交付统计

| 指标 | 数值 |
|------|------|
| 新增 Python 文件 | 2 (`csv_export.py`, `test_csv_export.py`) |
| 新增 Python 代码 | ~600 行 (csv_export 300 + 测试 370) |
| 修改文件 | 5 (`scope_app.py` + `scope_tk.py` + `scope_server.py` + `servo_cli.py` + `tuning_rules.py`) |
| 新增测试 | 21 (CSV 导出全覆盖) |
| 品牌调参别名 | **148** (12/12 品牌完整) |
| 参数描述 | **56** (CiA 402 标准 + 品牌特定) |
| 总测试通过 | **285/285** |

## Phase 1.9: Sim/Discover 模式切换 (2 天 — 无需硬件)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| S1.1 | 模式切换架构 | `scope_app.py` 工具栏增加 Sim/Discover 切换开关 | ✅ 2026-06-08 |
| S1.2 | Discover 扫描流程 | Discover 为默认启动行为，无硬件则弹 Sim/Exit 对话框 | ✅ 2026-06-08 |
| S1.3 | 主站信息面板 | 显示 Master 状态 (运行/配置)、DC 周期、slave 数量 | ✅ 2026-06-08 |
| S1.4 | 节点树自动构建 | 根据 discover() 结果自动建立 AxisTreePanel | ✅ 2026-06-08 |
| S1.5 | Sim 模式状态保存 | 切换到 Sim 时保存当前拓扑 + 最后波形数据 | ✅ 2026-06-08 |
| S1.6 | 连线断开保护 | Discover 模式下丢失连接时自动提示，回退 Sim | ✅ 2026-06-08 |
| S1.7 | 被动读取模式 | ScopeEngine 增加 `passive` 模式 (不调 exchange，只读 buffer) | ✅ 2026-06-08 |

**详细方案**: 见 `02-architecture/sim-discover-mode.md`

## Phase 1.5: 硬件实测 (4 周 — 待硬件)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| H1.1 | EtherCAT 硬件通信 | SOEM → Delta A3-E 真实 PDO 交换 | ⬜ |
| H1.2 | 示波器硬件数据源 | 真实 PDO 数据 → 示波器 GUI 显示 | ⬜ |
| H1.3 | AI 管线实测验证 | 真实伺服运行 → 三检测器产⽣标注 | ⬜ |
| H1.4 | 10 kHz DC 同步验证 | PREEMPT_RT + Intel I210, <50μs 抖动 | ⬜ |
| H1.5 | CODESYS FB 联调 | FB_ForceControl 在 CODESYS runtime 运行 | ⬜ |

**硬件需求**: Delta A3-E 驱动器+电机 (~$800), 力传感器 (~$500), Intel I210 网卡 (~$100)

## Phase 2: 力控闭环 (8 周) — 待 Phase 1.5 硬件到位后启动

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P2.1 | 力传感器集成 | 模拟量 (0-10V)/数字力传感器 → EtherCAT 从站, 标定曲线 | ⬜ |
| P2.2 | 力控 FB 闭环验证 | `07-codesys-fb/FB_ForceControl.st` — 6 状态 FSM 硬件联调 | ⬜ |
| P2.3 | PPO 力控自整定 | `06-ai-analyzer/models/force_ppo.pth` — 引用 AI&ML Agent Solution 01 | ⬜ |
| P2.4 | 多品牌 ESI 解析 | 松下 A6 + 安川 Σ-7 + 汇川 SV660 + 埃斯顿 + 英威腾 + 雷赛 + Elmo + Servotronix + Lenze → **12 品牌** ✅ | ✅ 2026-06-06 |
| P2.5 | AI 参数推荐引擎 | 基于差距分析结果, 自动推荐调参值 (0x60FB, 0x610B 等) | ✅ 2026-06-06 (核心: ParameterRecommender + HITL 授权门) |
| P2.6 | CODESYS 代码自动生成 | `codegen_st.py` → FB_ServoDiag + FB_ServoTune + DUT, self-contained, 17 tests | ✅ 2026-06-06 |

## Phase 3: 产品化 (12 周) — 远期

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P3.1 | 用户手册 | `08-docs/user-manual/README.md` — 安装/CLI命令/别名/Web/HITL/CODESYS/品牌 | ✅ 2026-06-06 |
| P3.2 | 开发者指南 | `08-docs/developer-guide/README.md` — 架构/API/HITL/LLM/CLI/Codegen/测试/贡献 | ✅ 2026-06-06 |
| P3.3 | 在线自适应 PPO | 力控参数在线更新, 工况变化自动调节 | ⬜ |
| P3.4 | 4 品牌全参数库 | 台达 A3 + 松下 A6 + 安川 Σ-7 + 汇川 SV660 | ⬜ |
| P3.5 | CI/CD Pipeline | GitHub Actions — pytest + SOEM 编译 + CODESYS 语法检查 | ⬜ |

---

## 外部资源依赖

| 资源 | 优先级 | 状态 |
|------|--------|------|
| SOEM (Simple Open EtherCAT Master) 源码 | 🔴 P0 | ✅ **已有** `D:\Solution Pack\BECKHOFF\Simple Open EtherCAT\SOEM\` |
| 台达 ASDA-Soft (含对象字典) | 🔴 P0 | ✅ **已有** V7.0.0.7 安装在 `D:\MyDeskWORKS\desk2\ASDA_Soft_V7.0.0.7\` + V7.2 安装包 |
| 台达 A3 手册 + ESI 文件 | 🔴 P0 | ✅ **已有** `D:\Solution Pack\My MANUALS\A3,B3,E3手册\` |
| Panasonic/Yaskawa ESI 文件 | 🟡 P1 | ✅ **已有** `D:\Solution Pack\C#\DELTA_IA-IPC_EtherCAT-X64_*\ESI\` |
| 伺服调试框架参考 | 🟡 P1 | ✅ **已有** `D:\GitHub\servo-tuning-framework\` |
| VDI CAM Manager (B-spline/S-curve) | 🟢 P2 | ✅ **已有** `D:\Solution Pack\vdi-backup\` |
| MSYS2 UCRT64 + libpcap | 🔴 P0 | ✅ **GCC 15.2.0 已配置** — SOEM win32 移植完成 |

---

## 技术笔记

### 2026-06-04: SOEM GCC 适配

- **编译器**: GCC 15.2.0 (MSYS2 UCRT64), 64-bit
- **移植修改** (4 files):
  - `osal/osal.h` — 修复 `osal_timer_is_expired` const 声明
  - `osal/win32/osal_win32.h` — 添加 `#include <sys/time.h>`
  - `osal/win32/stdint.h` / `inttypes.h` — 重命名为 `.msvc` (GCC 用自带头文件)
- **NIC 驱动**: `oshw/win32/nicdrv.c` 使用 MSYS2 libpcap (含 WinPcap 兼容扩展)
- **构建**: `build/libsoem.a` (116KB) + `build/test_soem.exe` (185KB)
- **验证**: 36 组测试 / 52 断言全部通过
- **运行时依赖**: Npcap (`libpcap.dll`) — 实际 EtherCAT 通信需要
- **详见**: `03-ethercat-master/README.md`

### 2026-06-06: AI 分析引擎 P1.4 交付

- **模块**: `06-ai-analyzer/ai_analyzer/` — 10 文件, ~1,600 行 Python
- **三检测器管线**:
  - `CurrentAnomalyDetector` — z-score + IQR + CUSUM 集成 (35%/30%/35% 权重)
  - `TrackingErrorDetector` — Pearson 相关性 + 动态阈值 (3σ)
  - `MechanicalResonanceDetector` — 滑动窗口 FFT (1024 点, Hann 窗) + 谐波匹配
- **后处理**: `AIAnnotator` — Sigmoid 置信度校准 + 严重度升级 (info→warning→critical)
- **桥接**: `AIAnalyzerBridge` — 延迟导入 AI&ML Agent (Solution 01/02, SL1, AR4), 优雅降级
- **集成**: `scope_engine.py` `_run_ai()` 由硬编码规则替换为 `AIAnalyzerPipeline`, 保留 Legacy 回退
- **测试**: 43 单元 + 20 集成 = 63 全部通过
- **包结构**: `06-ai-analyzer/ai_analyzer/` (Python package, `import ai_analyzer`)
- **详见**: `06-ai-analyzer/README.md`

### 2026-06-06: Phase 0 市场调研完成

- **M0.2** `01-market-research/market-sizing.md` — TAM $9.2B, SAM $150M, SOM $7.5M Y5
- **M0.4** `01-market-research/gap-analysis.md` — 8 维度 vs PANATERM/Musashi/TwinCAT
- **M0.5** `01-market-research/feasibility-report.md` — Go 决策, 风险矩阵 (R1-R7), 资源评估 ($2,600)
- **结论**: AI 分析是最大差异化 (所有竞品 L0-L1), 开源是核心壁垒

### 2026-06-06: 多品牌参数库 — 12 品牌 3,245 CoE 对象

- **来源**: Delta IA EtherCAT 安装包内嵌 ESI 缓存 (`/g/work/EtherCAT/`)
- **新增品牌** (9): 汇川 SV660, 安川 Σ-7, 埃斯顿 ProNet, 英威腾 DA200, 雷赛 DM3E/CL3, Elmo Gold, Servotronix CDHD, Lenze i700
- **已有** (3): 台达 A3, 安川 Σ-5, 松下 A6
- **通用解析器**: `extract_esi_generic.py` — 3 种格式 (Delta A3 / ETG.2000 Dictionary / PDO-embedded)
- **统一注册表**: `brands.json` + `brand_loader.py` — 跨品牌查询 API
- **自动示波器配置**: `generate_scope_configs.py` — 每个品牌生成 8 通道映射
- **覆盖**: JP 3, CN 5, TW 1, IL 2, DE 1 = 5 个国家/地区
- **示波器通道可用性**: 5-8/8 (取决于品牌默认 PDO 映射)
- **详见**: `05-servo-params/`

### 2026-06-06: HITL 工程师反馈闭环 (Phase 1.7 交付)

- **模块**: `06-ai-analyzer/ai_analyzer/` — 新增 6 文件, ~1,800 行 Python
- **HITL 三层分类**:
  - `safe` (2): current_sensor_fault, system_overload — 纯信息输出
  - `actionable` (3): resonance_detected, tracking_gain_deficiency, current_saturation — AI 可修复, 需工程师授权
  - `ambiguous` (2): current_wear, tracking_mechanical_bind — AI 检测到症状, 需工程师感官输入精化诊断
- **核心设计原则**: 无授权不侵入 — 任何 `increase/decrease/set/write` 操作必须经过 `HITLGate.authorize()`
- **多模态反馈**: 文字/图片([可拍照])/音频([可录音])/视频([可录视频]) — 4 通道诊断检查清单
- **诊断精化**: `process_feedback()` — 关键词匹配将 `current_wear` 精化为 5 种子类型 (联轴器/丝杆/轴承/皮带/导轨)
- **审计追踪**: `ActionLogger` — 不可变日志, JSON 导出, 会话摘要 (授权率/待处理数)
- **Web UI**: `scope_server.py` — 3 个 HITL API 端点 (/hitl/analyze, /hitl/feedback, /hitl/status), 授权/拒绝/提交观察按钮
- **差距分析更新**: 7 项现场报告全覆盖 — 2 项 AI 自主 (增益/陷波) + 5 项 HITL-bridged (低通滤波/联轴器/导轨预压/S 曲线/中间支撑)
- **测试**: 81 新增测试 (63 HITL + 18 审计日志), 总 138 全部通过
- **详见**: 本文件 Phase 1.7

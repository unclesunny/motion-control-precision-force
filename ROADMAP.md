# Motion Control — Precision Force Control ROADMAP

> 创建: 2026-06-04 | 最后更新: 2026-06-06 | 宪法: CONSTITUTION.md

---

## 能力基线

| 维度 | 当前 | 目标 (6个月) | 目标 (12个月) |
|------|------|------------|------------|
| EtherCAT 主站 | **L3** (1 kHz DC, CoE, 模拟模式) | L3 (硬件实测) | L4 (多品牌即插即用) |
| 示波器前端 | **L4** (3 前端: tkinter/PySide6/Web, 381 FPS) | L4 (硬件联调) | L5 (移动端适配) |
| 伺服参数库 | **L5** (12 品牌, 3,245 CoE 对象) | — | — |
| AI 分析引擎 | **L3** (三检测器管线, 全端接入, 63 测试) | L4 (硬件实测标注) | L5 (PPO 一键整定) |
| 力控自学习 | **L1** (CODESYS FB 已编写) | L2 (PPO 离线训练) | L4 (在线自适应) |
| CODESYS 集成 | **L2** (5 FBs + DUT) | L2 (硬件联调) | L3 (自动代码生成) |
| 测试体系 | **L3** (63 测试, 7 文件) | L4 (CI/CD) | L5 (硬件-in-the-loop) |

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
| 新增源文件 | 10 (AI 分析器) |
| 新增 Python 代码 | ~2,800 行 |
| 单元测试 | 43 (7 测试文件) |
| 集成测试 | 20 (2 测试文件) |
| 总测试通过 | **63/63** |
| Phase 0 文档 | 5 (竞品分析/市场规模/差距/可行性/技术栈) |

---

## Phase 1.6: 开源基础设施 (当前 ← 2026-06-06)

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| O1.1 | 许可证 GPLv2 → MIT | `LICENSE` + 全量代码头更新 | ✅ 2026-06-06 |
| O1.2 | Pro/Free 模块拆分 | `pro/` 目录 + `.gitignore` 隔离 | ✅ 2026-06-06 |
| O1.3 | 差距评估报告 | `01-market-research/pro-free-gap-analysis.md` | ✅ 2026-06-06 |
| O1.4 | CONSTITUTION 更新 | G6, G7 门禁 (Pro/Free 边界) | ✅ 2026-06-06 |

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
| P2.5 | AI 参数推荐引擎 | 基于差距分析结果, 自动推荐调参值 (0x60FB, 0x610B 等) | ⬜ |
| P2.6 | CODESYS 代码自动生成 | `AIAnalyzerBridge.export_codesys_st()` → 完整 FB 部署 | ⬜ |

## Phase 3: 产品化 (12 周) — 远期

| # | 任务 | 交付物 | 状态 |
|---|------|--------|------|
| P3.1 | 用户手册 | `08-docs/user-manual/` — 安装/配置/调试指南 | ⬜ |
| P3.2 | 开发者指南 | `08-docs/developer-guide/` — API 文档 + 架构说明 | ⬜ |
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

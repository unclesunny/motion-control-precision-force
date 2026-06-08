# Motion Control — Precision Force Control 落地实施前完整评估报告

> 评估日期: 2026-06-07 | 基准代码行数: 21,582 行 Python (58 文件) | 测试通过: 285/285
> 
> 下次复审: 2026-06-14 (每周)

---

## 一、项目现状总览

### 1.1 已完成模块 (✅ 可直接用)

| 模块 | 成熟度 | 关键指标 |
|------|--------|---------|
| **EtherCAT 主站** | L3 | 3 后端 (SOEM/IgH/Sim), 多轴支持, SII 发现 |
| **示波器前端** | L4 | 3 前端 (tkinter 143FPS / pyqtgraph 381FPS / Web 77FPS) |
| **伺服参数库** | L5 | 12 品牌, 3,245 CoE 对象, 148 调参别名 |
| **AI 分析引擎** | L4 | 3 单轴检测器 + 1 跨轴检测器, 285 测试 |
| **HITL 闭环** | L3 | 分类→提示→反馈→授权→审计, 完整链路 |
| **CLI 命令系统** | L4 | 4 模式 (REPL/单命令/脚本/管道), 83 别名 |
| **CODESYS 集成** | L3 | 5 FB + 2 DUT + 代码生成器 |
| **CSV 导出** | L3 | 单轴/多轴/标注/会话包 |
| **文档** | L3 | 用户手册 + 开发者指南 |

### 1.2 代码总量

```
58 Python 文件, 21,582 行
├── 03-ethercat-master/     ~1,900 行   (EtherCAT 主站)
├── 04-oscilloscope/       ~3,100 行   (示波器 3 前端 + 采集引擎)
├── 05-servo-params/       ~1,200 行   (参数库 + 品牌解析)
├── 06-ai-analyzer/        ~10,200 行  (AI 引擎 + CLI + HITL)
├── 07-codesys-fb/         5 FB + DUT  (CODESYS ST 代码)
├── demo/tests             ~5,200 行   (演示 + 测试)
```

---

## 二、待提交代码状态 — ⚠️ 高优先级

### 2.1 未跟踪文件 (29 个, 不在 Git 中)

当前有 **29 个文件处于 untracked 状态**, 这些是多轴架构、跨轴检测、CLI 系统、HITL 闭环等核心功能的代码, **必须提交才能落地**:

```
核心逻辑 (必须提交):
  ⬜ 06-ai-analyzer/ai_analyzer/cross_axis.py       ← 第4检测器 (跨轴分析)
  ⬜ 06-ai-analyzer/ai_analyzer/hitl_gate.py        ← HITL 安全门
  ⬜ 06-ai-analyzer/ai_analyzer/hitl_types.py       ← HITL 数据类型
  ⬜ 06-ai-analyzer/ai_analyzer/action_logger.py    ← 审计日志
  ⬜ 06-ai-analyzer/ai_analyzer/engineer_prompts.py  ← 工程师提示模板
  ⬜ 06-ai-analyzer/ai_analyzer/llm_refiner.py      ← LLM 诊断精化
  ⬜ 06-ai-analyzer/ai_analyzer/cli_commands.py     ← CLI 命令实现
  ⬜ 06-ai-analyzer/ai_analyzer/cli_aliases.py      ← CLI 别名系统
  ⬜ 06-ai-analyzer/ai_analyzer/cli_llm_bridge.py   ← LLM翻译层
  ⬜ 06-ai-analyzer/ai_analyzer/codegen_st.py       ← CODESYS 代码生成
  ⬜ 06-ai-analyzer/servo_cli.py                    ← CLI 入口

基础设施:
  ⬜ 03-ethercat-master/bindings/igh_bindings.py    ← IgH Linux 后端
  ⬜ 03-ethercat-master/bindings/discover.py        ← SII 自动发现
  ⬜ 04-oscilloscope/src/csv_export.py              ← CSV 波形导出

测试文件 (必须提交):
  ⬜ 06-ai-analyzer/tests/test_hitl_gate.py         (63 tests)
  ⬜ 06-ai-analyzer/tests/test_action_logger.py     (18 tests)
  ⬜ 06-ai-analyzer/tests/test_cross_axis.py        (23 tests)
  ⬜ 06-ai-analyzer/tests/test_llm_refiner.py       (22 tests)
  ⬜ 06-ai-analyzer/tests/test_servo_cli.py         (63 tests)
  ⬜ 06-ai-analyzer/tests/test_codegen_st.py        (17 tests)
  ⬜ tests/scenario_resonance_field.py
  ⬜ tests/test_csv_export.py                       (21 tests)

演示 + 文档:
  ⬜ demo_multi_axis.py
  ⬜ multi-axis-architecture.md
  ⬜ 07-codesys-fb/DUT_ServoDiag.st
  ⬜ 07-codesys-fb/FB_ServoTune.st
  ⬜ 08-docs/user-manual/README.md
  ⬜ 06-ai-analyzer/07-codesys-fb/  (重复目录)
```

### 2.2 已修改未提交文件 (21 个, 3,609 行增量)

21 个文件有未提交修改, 累计 +3,609 / -555 行。关键变更:

- `ec_master.py`: +605 行 (IgH 后端 + 多轴 + SII 发现)
- `scope_app.py`: +749 行 (多轴 UI + 树面板 + HITL 面板)
- `scope_server.py`: +536 行 (HITL API + LLM 展示)
- `scope_engine.py`: +339 行 (多轴采集 + 跨轴分析)
- `analyzer_pipeline.py`: +202 行 (HITL 集成 + 批量分析)
- `tuning_rules.py`: +445 行 (148 别名/12 品牌)

**⚠️ 风险**: 如果此时丢失工作树, 将丢失 29 个新文件 + 21 个修改文件中的所有工作。

### 2.3 Phase 1.9 变更 (2026-06-08, 未提交)

自上次评估后新增 Sim/Discover 模式切换功能 (~290 行, 6 文件):

| 文件 | 变更 | 说明 |
|------|------|------|
| `03-ethercat-master/bindings/discover.py` | +55 | `detect_ethercat_adapter()` — Win/Linux NIC 自动检测 |
| `04-oscilloscope/src/scope_app.py` | ~+200 | `DiscoveryPanel` 组件, 窗口内发现检查清单, Discover-first 启动 |
| `04-oscilloscope/src/scope_engine.py` | ~+35 | `passive` 模式参数, 断线检测, `on_disconnect` 回调 |
| `04-oscilloscope/src/scope_tk.py` | ~+120 | 窗口内发现检查清单, 模式横幅, Sim/Exit 提示 |
| `04-oscilloscope/src/scope_server.py` | ~+25 | `/mode` API 端点, Web UI 模式徽章 |
| `02-architecture/sim-discover-mode.md` | 更新 | 设计文档反映 Discover-first 策略 |

**行为**: 启动时先尝试探测真实 EtherCAT 硬件 (5 步检查清单), 成功则进入 Discover 模式, 失败则显示 Sim/Exit 按钮。

---

## 三、架构完整性评估

### 3.1 多轴架构 — ✅ 完整

```
EtherCAT Bus
├── Slave 0 (Axis X)  → RingBuf X  → Pipeline X  ─┐
├── Slave 1 (Axis Y)  → RingBuf Y  → Pipeline Y  ─┤
├── Slave 2 (Axis Z)  → RingBuf Z  → Pipeline Z  ─┤→ CrossAxisAnalyzer → HITL Gate → UI
└── Slave 3 (Spindle) → RingBuf S  → Pipeline S  ─┘
```

3 后端完整:
- **SOEM** (Windows 开发/调试) — `RealEtherCAT`
- **IgH** (Linux 生产) — `IgHEtherCAT`, 域缓冲 + 字节偏移
- **Sim** (无硬件) — `SimulatedEtherCAT`, `num_axes` 参数

### 3.2 检测器矩阵 — ✅ 7 个检测器

| 检测器 | 类型 | 覆盖范围 | 测试 |
|--------|------|---------|------|
| CurrentAnomalyDetector | 单轴 | z-score + IQR + CUSUM 集成 | ✅ |
| TrackingErrorDetector | 单轴 | Pearson + 动态 3σ | ✅ |
| MechanicalResonanceDetector | 单轴 | 1024-pt Hann FFT + 谐波 | ✅ |
| BusSagDetector | 跨轴 | 电源总线压降 | ✅ |
| ContouringDetector | 跨轴 | XY 轮廓误差 | ✅ |
| RingHealthDetector | 跨轴 | EtherCAT 环网级联故障 | ✅ |
| MechanicalCouplingDetector | 跨轴 | 龙门耦合振动 | ✅ |

### 3.3 Pro/Free 边界 — 🔴 未执行 (设计意图待落地)

**项目定位**: MIT 开源项目，但非完全开源。Free 版 (MIT) 提供基础采集/可视化/参数查询，Pro 版 (商业授权) 提供 AI 诊断/工业互联/预测维护。

**当前状态**: Pro/Free 分离是设计意图，尚未在代码中执行。

```
设计目标:                              当前实际:
  Free (MIT 开源, GitHub)               ├── 所有代码在 Free 目录
  ├── 示波器 3 前端                     ├── AI 检测器在 Free 目录
  ├── EtherCAT 采集                     ├── HITL/LLM 在 Free 目录
  ├── 12 品牌参数库                     ├── CLI/Codegen 在 Free 目录
  ├── CSV 导出                          ├── pro/ 目录不存在
  └── CODESYS FB                        └── 零代码引用 pro/ 路径
                                        └── Pro (商业授权)
Pro (闭源, 商业授权)                       ├── 无目录
  ├── AI 诊断 (3 检测器)                 ├── 无代码
  ├── HITL 闭环 + LLM 精化               ├── 无 .gitignore 排除
  ├── 跨轴分析                           └── 无任何实现
  ├── CLI 命令系统
  ├── 15 类高级诊断模型
  ├── SQLite/OPC UA/报表
  └── PHM/行业知识库
```

**关键发现**:

- `pro/` 目录不存在 — 尚未创建
- `.gitignore` 有 `pro/` 排除行 ✅
- 代码中零处引用 `pro/` 路径
- 无延迟导入、无优雅降级、无 Pro 模块检测逻辑
- 即使用户购买了 Pro 授权，也没有任何 Pro 代码可以加载

**根本原因**: commit `dbb1fbc` 将之前移到 `pro/` 的 AI 模块全部恢复到 `ai_analyzer/`（Free），当时可能是为了简化开发。但这次 Revert 之后，Pro/Free 边界的代码实现被完全搁置，只存在于文档中。

**Readme 对比表 vs 实际代码的差异**:

| Readme 声称 | 实际代码位置 | 差异 |
|------------|------------|------|
| 电流异常检测 → Pro | `ai_analyzer/current_anomaly.py` | 在 Free |
| 跟踪误差分析 → Pro | `ai_analyzer/tracking_error.py` | 在 Free |
| 机械谐振检测 → Pro | `ai_analyzer/mechanical_resonance.py` | 在 Free |
| 参数调参建议 → Pro | `ai_analyzer/parameter_recommender.py` | 在 Free |
| 多轴交叉分析 → Pro | `ai_analyzer/cross_axis.py` | 在 Free |
| HITL 工程师反馈 → Pro | `ai_analyzer/hitl_gate.py` | 在 Free |
| LLM 诊断精化 → Pro | `ai_analyzer/llm_refiner.py` | 在 Free |
| CLI 命令系统 → Free/Pro | `ai_analyzer/cli_*.py` | 部分在 Free |
| CODESYS 代码生成 → Free/Pro | `ai_analyzer/codegen_st.py` | 在 Free |

**结论**: 当前 Readme 的 "Free vs Pro" 对比表描述的是**目标架构**，而非**当前实际**。必须执行 Pro/Free 拆分才能与商业模型一致。

---

## 四、Pro/Free 拆分实施计划 — 🔴 最高优先级

### 4.1 目标架构

```
Free (MIT 开源, GitHub):                Pro (闭源, 商业授权, pro/ 不入 git):
──────────────────────────────          ──────────────────────────────
04-oscilloscope/ (3 前端)               pro/ai_analyzer/
05-servo-params/ (参数库)               ├── current_anomaly.py        ← 电流异常检测
06-ai-analyzer/ai_analyzer/             ├── tracking_error.py         ← 跟踪误差分析
├── analyzer_base.py      (ABC)         ├── mechanical_resonance.py   ← 机械谐振检测
├── analyzer_bridge.py    (桥接)        ├── parameter_recommender.py  ← 参数推荐
├── ai_annotator.py       (校准)        ├── cross_axis.py             ← 跨轴分析
├── config.py             (常量)        ├── hitl_gate.py              ← HITL 安全门
├── tuning_rules.py       (规则)        ├── hitl_types.py             ← HITL 类型
├── codegen_st.py         (代码生成)    ├── engineer_prompts.py       ← 工程师提示
├── cli_*.py              (CLI 基础)    ├── action_logger.py          ← 审计日志
├── analyzer_pipeline.py  (* 管线)      ├── llm_refiner.py            ← LLM 精化
└── __init__.py                         └── tuning_rules.py           ← 高级规则
                                        (15 类高级诊断模型 — 远期)
07-codesys-fb/ (5 FB)
03-ethercat-master/                     pro/sqlite/                   ← 历史数据库
                                        pro/opc_ua/                   ← OPC UA Server
                                        pro/reports/                  ← PDF/Excel 报表
                                        pro/phm/                      ← 趋势预测
```

### 4.2 `analyzer_pipeline.py` 改造方案

当前 `_default_analyzers()` 直接导入 3 个检测器。改造后使用延迟导入 + 优雅降级:

```python
@staticmethod
def _default_analyzers(sample_rate_hz: float = 1000.0) -> List[AnalyzerBase]:
    analyzers = []
    
    # Pro 模块路径 (延迟导入)
    PRO_DIR = Path(__file__).resolve().parent.parent.parent / "pro" / "ai_analyzer"
    
    def _try_import(module_name, class_name):
        """Try Pro first, fall back to Free shell, else skip."""
        # 1. Try Pro (commercial license)
        if PRO_DIR.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, PRO_DIR / f"{module_name}.py")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return getattr(mod, class_name)()
            except Exception:
                pass
        # 2. Try Free shell (MIT — basic stats only, no ML)
        try:
            mod = importlib.import_module(f".{module_name}", package="ai_analyzer")
            return getattr(mod, class_name)()
        except Exception:
            pass
        return None
    
    for mod, cls in [
        ("current_anomaly", "CurrentAnomalyDetector"),
        ("tracking_error", "TrackingErrorDetector"),
        ("mechanical_resonance", "MechanicalResonanceDetector"),
    ]:
        det = _try_import(mod, cls)
        if det:
            analyzers.append(det)
    
    return analyzers
```

### 4.3 拆分步骤

| 步骤 | 操作 | 说明 |
|------|------|------|
| S1 | 创建 `pro/ai_analyzer/` 目录 | 空目录, `.gitignore` 已有 `pro/` |
| S2 | 移入 Pro 模块 | 将 12 个文件从 `ai_analyzer/` 移到 `pro/ai_analyzer/` |
| S3 | 创建 Free shell | Free 版每模块提供一个空壳类 (返回空列表/默认值) |
| S4 | 改造 `analyzer_pipeline.py` | 延迟导入逻辑, 自动检测 Pro 模块 |
| S5 | 改造 `__init__.py` | 公共 API 不变, 内部自动路由 |
| S6 | 更新 Readme 对比表 | 与代码一致 |
| S7 | 验证 285 测试通过 | 确保 Free 版无 Pro 模块时仍可运行 |

---

## 五、硬件依赖 — 🔴 阻塞项

### 4.1 Phase 1.5 (硬件实测) 完全阻塞

**这是项目最大的未完成依赖。** 在没有真实硬件的情况下:

| 验证项 | 当前状态 | 影响 |
|--------|---------|------|
| SOEM → Delta A3-E 真实 PDO | ❌ 未验证 | 核心采集链路未跑通 |
| 示波器硬件数据源 | ❌ 未验证 | 3 前端均只跑过模拟数据 |
| AI 管线真实伺服运行 | ❌ 未验证 | 所有检测器阈值基于理论计算 |
| 10 kHz DC 同步 (<50μs 抖动) | ❌ 未验证 | PREEMPT_RT + I210 未测试 |
| CODESYS FB 联调 | ❌ 未验证 | 5 个 FB 均只在 PLC 仿真运行 |
| IgH 生产后端 | ❌ 未验证 | `igh_bindings.py` 未经真实内核模块测试 |
| 力传感器集成 | ❌ 未开始 | Phase 2 的前置条件 |

**所需硬件** ($1,400):
- Delta A3-E 驱动器+电机 (~$800)
- 力传感器 (~$500)
- Intel I210 网卡 (~$100)

### 4.2 风险: 无硬件下的理论假设

所有 AI 检测器阈值 (config.py) 基于 Delta A3 规格书和 AI&ML Agent 的训练数据推断。真实伺服运行时的噪声水平、采样抖动、PDO 数据格式、字节序等可能与模拟环境有显著差异。

---

## 五、测试覆盖 — ⚠️ 良好但有盲区

### 5.1 覆盖统计

```
285 测试, 全部通过
├── tests/                         20 测试  (集成 + E2E + CSV)
├── 06-ai-analyzer/tests/          265 测试
│   ├── test_current_anomaly.py     ~30
│   ├── test_tracking_error.py      ~10
│   ├── test_mechanical_resonance.py ~30
│   ├── test_ai_annotator.py        ~15
│   ├── test_parameter_recommender.py ~20
│   ├── test_hitl_gate.py           63
│   ├── test_action_logger.py       18
│   ├── test_llm_refiner.py         22
│   ├── test_cross_axis.py          23
│   ├── test_servo_cli.py           63
│   └── test_codegen_st.py          17
```

### 5.2 测试盲区

| 盲区 | 风险 | 优先级 |
|------|------|--------|
| **硬件 I/O 路径** | SOEM `read_pdo` / `exchange` 只测了模拟 | 🔴 P0 |
| **实时性能** | 1kHz/10kHz 时序从未用真实负载测试 | 🔴 P0 |
| **IgH 后端** | `IgHEtherCAT` 类无任何测试 | 🔴 P0 |
| **Web 前端** | `scope_server.py` 无 HTTP 层测试 | 🟡 P1 |
| **tkinter 前端** | 无 GUI 自动化测试 | 🟡 P1 |
| **端到端压力测试** | 无长时间运行 (>1h) 内存/性能测试 | 🟡 P1 |
| **品牌参数加载** | 12 品牌 ESI 解析无集成测试 | 🟡 P1 |
| **LLM 桥接** | `cli_llm_bridge.py` / `llm_refiner.py` 仅测解析, 未测真实 API | 🟢 P2 |

---

## 六、代码质量问题

### 6.1 CRLF 警告 — ⚠️ 低风险但需修复

大量文件显示 `LF will be replaced by CRLF` 警告。对功能无影响, 但 CI/CD 中可能引发不必要的 diff。

### 6.2 重复目录 — ⚠️ 需清理

```
06-ai-analyzer/07-codesys-fb/    ← 与 07-codesys-fb/ 重复
    DUT_ServoDiag.st
    DUT_ServoDiag_v1.st
```

### 6.3 遗留代码 — ⚠️ 低风险

`scope_engine.py:43` 中的 `_LEGACY_ANOMALY_RULES` 在 AI 管线不可用时作为回退使用, 合理。但硬编码阈值 (`Current > 200%`, `Velocity > 500 rpm`) 对多品牌场景可能不准确。

### 6.4 import 脆弱性

所有模块使用 `try/except ImportError` 双路径 import, 这是优雅降级的标准做法。但缺乏统一的 import 测试来验证所有降级路径。

---

## 七、落地前必须完成的优化清单

### 🔴 P0 — 阻塞项 (不完成无法交付)

| # | 任务 | 说明 | 预计工作量 | 状态 |
|---|------|------|-----------|------|
| **P0.1** | **采购硬件并执行 Phase 1.5** | Delta A3-E + 力传感器 + I210 网卡, $1,400 | 4 周 | ⬜ |
| **P0.2** | **提交所有未跟踪代码** | 29 个新文件 + 21 个修改文件 → Git | 1 小时 | ⬜ |
| **P0.3** | **执行 Pro/Free 代码拆分** | 创建 `pro/` 目录, 移入 AI 检测器/HITL/LLM/跨轴分析, 实现延迟导入+优雅降级, 更新 Readme | 1 天 | ⬜ |
| **P0.4** | **清理重复目录** | 删除 `06-ai-analyzer/07-codesys-fb/` | 5 分钟 | ⬜ |
| **P0.5** | **修正 CRLF 设置** | `.gitattributes` 或 `git config core.autocrlf` | 10 分钟 | ⬜ |

### 🟡 P1 — 重要项 (影响交付质量)

| # | 任务 | 说明 | 预计工作量 | 状态 |
|---|------|------|-----------|------|
| **P1.1** | **CI/CD Pipeline** | GitHub Actions: pytest + lint + SOEM 编译 | 4 小时 | ⬜ |
| **P1.2** | **IgH 后端测试** | `IgHEtherCAT` 类需模拟测试 (至少 mock libethercat) | 4 小时 | ⬜ |
| **P1.3** | **Web 前端集成测试** | `scope_server.py` HTTP 端点测试 | 3 小时 | ⬜ |
| **P1.4** | **长时间运行测试** | 1 小时持续采集, 监控内存/CPU/事件队列 | 2 小时 | ⬜ |
| **P1.5** | **12 品牌 ESI 集成测试** | 验证每个品牌的 PDO 映射可用通道数 | 3 小时 | ⬜ |
| **P1.6** | **硬件 I/O 字节序验证** | SOEM PDO 数据解析在大/小端下的正确性 | 需硬件 | ⬜ |
| **P1.7** | **10kHz DC 同步性能验证** | PREEMPT_RT + I210, 抖动需 <50μs | 需硬件 | ⬜ |

### 🟢 P2 — 优化项 (锦上添花)

| # | 任务 | 说明 | 预计工作量 | 状态 |
|---|------|------|-----------|------|
| **P2.1** | **Pro 版 15 类高级诊断模型** | 轴承磨损/接触器拉弧/IGBT 老化/三相不平衡/齿轮故障等 | 8 周 | ⬜ |
| **P2.2** | **SQLite 历史数据库** | 录波 + 查询回放 | 2 周 | ⬜ |
| **P2.3** | **PDF/Excel 报表引擎** | reportlab + openpyxl | 2 周 | ⬜ |
| **P2.4** | **OPC UA Server** | 工业互联标准协议 | 3 周 | ⬜ |
| **P2.5** | **PHM 趋势预测** | 7/30/90 天健康退化曲线 | 3 周 | ⬜ |
| **P2.6** | **tkinter/PyQt GUI 自动化测试** | pytest-qt 或类似框架 | 2 周 | ⬜ |
| **P2.7** | **行业故障知识库** | 锂电/3C 点胶/注塑/风电定制 | 4 周 | ⬜ |

---

## 八、路线图时间线评估

```
当前 (2026-06-07)
  │
  ├─ P0.1-P0.5  完成 (~1 天, 不含硬件采购)
  │
  ├─ Phase 1.5 硬件实测 (4 周, 取决于硬件采购)
  │   ├─ H1.1: SOEM → A3-E 真实 PDO
  │   ├─ H1.2: 示波器硬件数据源
  │   ├─ H1.3: AI 管线实测验证
  │   ├─ H1.4: 10 kHz DC 同步
  │   └─ H1.5: CODESYS FB 联调
  │
  ├─ Phase 2 力控闭环 (8 周, 需硬件到位)
  │   ├─ P2.1: 力传感器集成
  │   ├─ P2.2: 力控 FB 闭环验证
  │   ├─ P2.3: PPO 力控自整定
  │   └─ P2.4-P2.6: 已完成 ✅
  │
  └─ Phase 3 产品化 (12 周)
      ├─ P3.1-P3.2: 已完成 ✅
      ├─ P3.3: 在线自适应 PPO
      ├─ P3.4: 4 品牌全参数库
      └─ P3.5: CI/CD Pipeline
```

**关键路径**: 硬件采购 → Phase 1.5 验证 → Phase 2 力控闭环 → Phase 3 产品化

**最快交付时间线**: 如果今天下单硬件, 2 周到货 + 4 周 Phase 1.5 + 8 周 Phase 2 = **约 14 周可完成力控闭环验证**。

---

## 九、总结

### 优势
1. **架构完整**: 7 个检测器覆盖单轴+跨轴, 3 后端 (SOEM/IgH/Sim), 3 前端 (tkinter/PyQt/Web)
2. **测试充分**: 285 测试全部通过, 核心检测器都有单元测试
3. **差异化明显**: AI 诊断 + 多品牌 + HITL 闭环是竞品不具备的能力
4. **CLI + CODESYS 双工具链**: 工程师在线调试 + PLC 离线部署

### 核心风险
1. **🔴 Pro/Free 拆分未执行** — `pro/` 目录不存在, 所有 AI 模块混在 Free 中, 商业模型无代码支撑
2. **🔴 硬件未到位** — Phase 1.5 完全阻塞, 所有功能未经真实伺服验证
3. **🔴 代码未提交** — 29 个文件 untracked, 21 个文件 modified, 工作进度有丢失风险
4. **🟡 无 CI/CD** — 没有自动化流水线, 每次提交后需手动运行测试
5. **🟢 Pro 版 15 类诊断模型为零** — 需要大量领域数据和训练工作

### 即刻行动项 (本周)
1. **执行 Pro/Free 代码拆分**: 创建 `pro/` 目录, 移入 AI 模块, 实现延迟导入+优雅降级
2. `git add` + `git commit` 所有未跟踪/修改文件
3. 修复 CRLF 警告
4. 删除重复目录 `06-ai-analyzer/07-codesys-fb/`
5. 更新 Readme 中 Free/Pro 对比表与代码一致
6. 下单采购硬件 (Delta A3-E + 力传感器 + I210)

---

## 十、复审记录

| 日期 | 检查人 | P0 剩余 | P1 剩余 | 备注 |
|------|--------|---------|---------|------|
| 2026-06-07 | Claude | 5 项 (含 Pro/Free 拆分) | 7 项 | 初始评估, 所有项目待执行 |
| 2026-06-08 | Claude | 5 项 (无变化) | 5 项 | Phase 1.9 新增实现; P1.6/P1.7 仍阻塞于硬件; 测试保持 285/285 |
| | | | | |

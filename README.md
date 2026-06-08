# Motion Control — Precision Force Control

> 基于 EtherCAT 的 3C 点胶机精密力控系统

## 定位

不做万能运动控制器。聚焦：
- **机型:** 3C 点胶机 (流体精密分配)
- **协议:** EtherCAT CoE (CANopen over EtherCAT)
- **核心:** 力觉闭环 + AI 辅助调试

## 快速启动

```bash
python run_scope.py              # 自动检测环境, 选择最佳前端
python run_scope.py --tk         # tkinter (0 依赖, 143 FPS)
python run_scope.py --qt         # pyqtgraph (381 FPS, GPU 加速)
python run_scope.py --web        # 浏览器 (http://localhost:8888)
python run_scope.py --demo       # AI 模拟演示
```

## 目录结构

```
motion-control-precision-force/
├── run_scope.py                 ← 一键启动器
├── demo_ai_scope.py             ← AI 分析模拟演示
│
├── 01-market-research/          ← 市场调研 (5 文档, Phase 0 完成)
├── 02-architecture/             ← 系统架构设计 + 技术栈选型
│
├── 03-ethercat-master/          ← EtherCAT 主站 (SOEM C 核心 + Python ctypes)
│
├── 04-oscilloscope/src/         ← 实时示波器 (3 前端)
│   ├── scope_tk.py              ← tkinter (Python stdlib, 0 deps, 143 FPS)
│   ├── scope_app.py             ← pyqtgraph (GPU 加速, 381 FPS) + AI 标注
│   ├── scope_server.py          ← Web HTML5 Canvas (浏览器远程访问)
│   ├── scope_engine.py          ← 采集引擎 (EtherCAT → 环形缓冲 → AI 管线)
│   └── ring_buffer.py           ← 高性能环形缓冲 (8ch × 60s)
│
├── 05-servo-params/             ← 多品牌伺服参数库 (12 品牌, 3,245 CoE 对象)
│   ├── brands.json              ← 统一品牌注册表
│   ├── brand_loader.py          ← 跨品牌查询 API
│   ├── extract_esi_generic.py   ← 通用 ESI 解析器 (3 种格式)
│   ├── generate_scope_configs.py ← 自动生成示波器配置
│   ├── delta-a3/                ← 台达 A3 (693 obj, 完整)
│   ├── yaskawa-sigma7/          ← 安川 Σ-7 (294 obj)
│   ├── yaskawa-sigma5/          ← 安川 Σ-5 (223 obj)
│   ├── panasonic-a6/            ← 松下 A6 (18 obj, PDO-only)
│   ├── inovance-sv660/          ← 汇川 SV660 (102 obj)
│   ├── estun-pronet/            ← 埃斯顿 ProNet (195 obj)
│   ├── invt-da200/              ← 英威腾 DA200 (547 obj)
│   ├── leadshine-dm3e/          ← 雷赛 DM3E (124 obj)
│   ├── leadshine-cl3/           ← 雷赛 CL3-EC (115 obj)
│   ├── elmo-gold/               ← Elmo Gold (167 obj)
│   ├── servotronix-cdhd/        ← Servotronix CDHD (429 obj)
│   └── lenze-i700/              ← Lenze i700 (421 obj)
│
├── 06-ai-analyzer/              ← AI 分析引擎 (Free 版: 基础统计)
│   ├── ai_analyzer/             ← Python 包 (MIT 开源)
│   │   ├── analyzer_pipeline.py ← 管线编排 (自动检测 Pro 模块)
│   │   ├── ai_annotator.py      ← 置信度校准
│   │   ├── analyzer_base.py     ← AIAnnotation / AnalyzerBase ABC
│   │   ├── config.py            ← 共享常量
│   │   └── __init__.py          ← 公共 API
│   └── tests/                   ← Free 版测试
│
├── pro/                         ← Pro 商业授权 (不入 Git)
│   ├── ai_analyzer/             ← Pro AI 模块
│   │   ├── current_anomaly.py   ← 电流异常 (z-score + IQR + CUSUM)
│   │   ├── tracking_error.py    ← 跟随误差分析
│   │   ├── mechanical_resonance.py ← FFT 谐振检测
│   │   ├── parameter_recommender.py ← 参数调参建议
│   │   ├── tuning_rules.py      ← 调参知识库
│   │   └── analyzer_bridge.py   ← AI&ML Agent 桥接
│   └── tests/                   ← Pro 版测试 (55)
│
├── 07-codesys-fb/               ← CODESYS 功能块 (5 FBs + DUT)
├── 08-docs/                     ← 开发者 + 用户文档
└── tests/                       ← 集成测试 (20)
```

## 与 AI&ML Agent 的关系

本项目**引用**（不复制）AI&ML Agent 的能力模块：
- Solution 01 (PPO PID 自整定) → 力控参数优化
- Solution 02 (伺服电流异常) → 示波器 AI 标注
- SL1 (漂移根因分析) → 机械共振检测
- AR4 (方案生成器) → 新机型适配

桥接方式: `analyzer_bridge.py` 延迟导入, 优雅降级。

## 当前阶段

**Phase 1.5: 硬件实测** (待采购 Delta A3-E + Intel I210 NIC)

| Phase | 状态 | 关键交付 |
|-------|------|---------|
| Phase 0 市场调研 | ✅ | 5 文档 |
| Phase 1 原型验证 | ✅ | SOEM, 示波器 3 前端, AI 引擎, 12 品牌参数库 (148 别名) |
| Phase 1.6 开源基础 | ✅ | MIT 许可证, Pro/Free 拆分 |
| Phase 1.7 HITL 闭环 | ✅ | 工程师反馈回路, LLM 精化, CLI 命令系统 |
| Phase 1.8 Free 层功能 | ✅ | CSV 波形导出 (P1.1), 12 品牌调参别名 (P1.2) |
| Phase 1.5 硬件实测 | ⬜ | 需 $1,400 硬件 |
| Phase 2 力控闭环 | ⬜ | PPO + 力传感器 |
| Phase 3 产品化 | ⬜ | CI/CD + 完整文档 |

## Free vs Pro

> Free (MIT): 开源社区版 — 完整的数据采集、可视化、参数查询能力。个人调试足够。
> Pro (商业授权): 企业版 — AI 诊断、工业互联、预测维护、OEM 定制。量产必备。

### 采集与可视化

| 功能 | Free (MIT) | Pro (商业授权) | 说明 |
|------|:---:|:---:|------|
| 8 通道实时示波器 (3 前端) | ✅ | ✅ | tkinter (143 FPS) / pyqtgraph (381 FPS) / Web (77 FPS) |
| EtherCAT CoE PDO 采集 | ✅ | ✅ | SOEM (Win) + IgH (Linux) + Sim (无硬件) |
| 1 kHz 采样 (软件时间戳) | ✅ | ✅ | 演示/调试模式 |
| 10 kHz DC 同步采样 | — | ✅ | 需 PREEMPT_RT + Intel I210 |
| 12 品牌 ESI CoE 参数库 | ✅ | ✅ | 3,245 对象, 148 调参别名 |
| CSV 波形导出 (含元数据) | ✅ | ✅ | 单轴/多轴/标注/会话包 |
| 环形缓冲内存录波 | ✅ | ✅ | 8ch × 60s |
| 自动触发录波 (磁盘) | — | ✅ | 触发事件 → 自动保存到 SQLite |
| 模拟量采集 (0-10V/4-20mA) | — | ✅ | 力传感器等模拟信号 |

### AI 诊断引擎

| 功能 | Free (MIT) | Pro (商业授权) | 说明 |
|------|:---:|:---:|------|
| 电流异常检测 | — | ✅ | z-score + IQR + CUSUM (3 集成方法) |
| 跟踪误差分析 | — | ✅ | Pearson 相关 + 动态 3σ 阈值 |
| 机械谐振检测 (FFT) | — | ✅ | 1024-pt Hann 窗 + 谐波匹配 |
| 参数调参建议 | — | ✅ | 8 类异常 → 17 条规则 → 品牌解析 |
| 品牌感知参数推荐 | — | ✅ | 12 品牌自动索引转换 |
| 多轴交叉分析 | — | ✅ | Bus Sag / Contouring / Ring / Coupling (4 检测器) |
| HITL 工程师反馈闭环 | — | ✅ | 分类 → 提问 → 反馈 → 授权 → 审计 |
| 低通滤波 + S-Curve 建议 | — | ✅ | current_ripple / velocity_ripple 检测 |
| LLM 诊断精化 | — | ✅ | Claude API 驱动, 3 级降级回退 |
| 15+ 高级诊断模型 | — | ✅ | 轴承磨损 / 接触器拉弧 / IGBT 老化 / 三相不平衡 / 齿轮故障 |
| 分行业故障知识库 | — | ✅ | 锂电 / 3C 点胶 / 注塑 / 风电 |
| 自动巡检 (定时模式) | — | ✅ | 非实时, 周期性扫描 |

### 数据管理与互联

| 功能 | Free (MIT) | Pro (商业授权) | 说明 |
|------|:---:|:---:|------|
| 本地 CSV 导出 | ✅ | ✅ | P1.1 已交付 (2026-06-07) |
| 波形存盘 (SQLite) | — | ✅ | 结构化录波 + 查询回放 |
| 自动录波 (触发) | — | ✅ | 磁盘 I/O, 不限时存储 |
| OPC UA Server | — | ✅ | 工业互联标准协议 |
| MES/SCADA 对接 | — | ✅ | 上层制造执行系统 |
| PDF/Excel 报表引擎 | — | ✅ | reportlab + openpyxl |
| PHM 趋势预测 | — | ✅ | 7/30/90 天健康退化曲线 |
| 云上传 + AI 返回 | — | ✅ | Web 上传 → Pro 分析 → 诊断报告 |

### 工程化与部署

| 功能 | Free (MIT) | Pro (商业授权) | 说明 |
|------|:---:|:---:|------|
| Windows + Linux 跨平台 | ✅ | ✅ | Python 3.11+ |
| 中文原生 UI | ✅ | ✅ | 3 前端均原生中文 |
| 12 品牌参数库 | ✅ | ✅ | JP 3 / CN 5 / TW 1 / IL 2 / DE 1 |
| CLI 命令系统 (servo_cli) | ✅ | ✅ | REPL / 单命令 / 脚本 / 管道 4 模式 |
| CODESYS ST 代码自动生成 | ✅ | ✅ | FB_ServoDiag + FB_ServoTune + DUT |
| GitHub Actions CI/CD | ✅ | ✅ | pytest + 自动验证 |
| 三级权限管理 | — | ✅ | 操作员 / 工程师 / 管理员 |
| OEM 贴牌定制 | — | ✅ | Logo + 品牌色 + 启动画面 |
| 专属技术支持 | — | ✅ | 工单系统, 48h 响应 |
| 信创适配 (麒麟/统信) | — | ✅ | 国产 OS 认证 |

### 商业模型对标

| | 本项目 | TwinCAT | PANATERM | SigmaWin+ |
|---|:---:|:---:|:---:|:---:|
| 基础示波器 | Free MIT | $500-2000 | Free (随驱动器) | Free (随驱动器) |
| AI 诊断 | Pro (商业) | ❌ | ❌ | ❌ |
| 多品牌支持 | Free (12 品牌) | 仅 EtherCAT | 仅松下 | 仅安川 |
| 开源 | ✅ MIT | ❌ | ❌ | ❌ |
| 调参推荐 | Pro | 手动 | 手动 | 手动 (Auto-Tune) |
| 预测维护 | Pro | ❌ | ❌ | ❌ |

> **核心优势:** 竞品没有一个具备 AI 诊断能力。Pro 版售价对标一个 TwinCAT 运行时授权，但提供的能力是其完全不具备的。开源 Free 版永远免费，降低行业调试门槛。

## 测试

```bash
python -m pytest tests/ -v                        # 92 Free tests
python -m pytest 06-ai-analyzer/tests/ -v         # 193 AI analyzer tests
python -m pytest tests/ 06-ai-analyzer/tests/ -q  # 285 total (all passing)
```

## 技术规格

| 指标 | 目标 |
|------|------|
| EtherCAT DC 周期 | 1 ms |
| 示波器采样率 | 10 kHz |
| 示波器通道 | 8 (CiA 402 标准) |
| 示波器前端 | tkinter (143 FPS) / pyqtgraph (381 FPS) / Web (77 FPS) |
| AI 检测器 | 电流异常 + 跟踪误差 + 机械谐振 |
| 伺服品牌 | **12** (台达/安川/松下/汇川/埃斯顿/英威腾/雷赛/Elmo/Servotronix/Lenze) |
| CoE 对象总数 | **3,245** |
| 开发语言 | C (SOEM) + Python 3.11+ + ST (CODESYS) |
| 许可证 | MIT (社区版) / 商业授权 (Pro 版) |

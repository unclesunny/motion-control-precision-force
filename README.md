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
├── 06-ai-analyzer/              ← AI 分析引擎 (10 文件, 63 测试)
│   ├── ai_analyzer/             ← Python 包
│   │   ├── analyzer_pipeline.py ← 三检测器编排
│   │   ├── current_anomaly.py   ← 电流异常 (z-score + IQR + CUSUM)
│   │   ├── tracking_error.py    ← 跟随误差分析
│   │   ├── mechanical_resonance.py ← FFT 谐振检测
│   │   ├── ai_annotator.py      ← 置信度校准 + 严重度升级
│   │   └── analyzer_bridge.py   ← AI&ML Agent 桥接
│   └── tests/                   ← 43 单元测试
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
| Phase 1 原型验证 | ✅ | SOEM, 示波器 3 前端, AI 引擎, 12 品牌参数库, 63 测试 |
| Phase 1.5 硬件实测 | ⬜ | 需 $1,400 硬件 |
| Phase 2 力控闭环 | ⬜ | PPO + 力传感器 |
| Phase 3 产品化 | ⬜ | 文档 + CI/CD |

## 测试

```bash
python -m pytest 06-ai-analyzer/tests/ tests/ -v   # 63 tests
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

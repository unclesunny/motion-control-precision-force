---
name: technology-stack
description: 技术栈选型 — EtherCAT 主站、实时内核、示波器框架、AI 分析引擎
date: 2026-06-06
---

# 技术栈选型

## 一、三层技术架构

```
┌──────────────────────────────────────────────┐
│  应用层 (Python 3.11)                         │
│  - 示波器 UI: PySide6 (Qt 6.5)               │
│  - AI 分析: numpy + lightgbm + pytorch (复用) │
│  - 参数库管理: JSON Schema + SQLite            │
├──────────────────────────────────────────────┤
│  中间层 (C++ 20)                              │
│  - EtherCAT 主站: SOEM (C 核心)               │
│  - Python 绑定: ctypes / pybind11             │
│  - 环形缓冲区: boost::circular_buffer         │
├──────────────────────────────────────────────┤
│  实时层 (Linux + PREEMPT_RT)                  │
│  - 内核: Linux 6.1 + PREEMPT_RT patch         │
│  - 网卡驱动: Intel I210 / I226 (EtherCAT 原生) │
│  - DC 同步: SOEM distributed clocks           │
└──────────────────────────────────────────────┘
```

## 二、EtherCAT 主站方案对比

| 方案 | 许可证 | 实时性 | 易用性 | 社区 | 选择 |
|------|--------|--------|--------|------|------|
| **SOEM** | GPLv2 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | **✅ 首选** |
| IgH EtherCAT Master | GPLv2 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | 备选 |
| TwinCAT | 商业授权 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ (付费) | 仅对标 |
| Acontis EC-Master | 商业授权 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | 不考虑 |
| LinuxCNC EtherCAT | GPLv2 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 不考虑 |

**选择 SOEM 的理由:**
1. 代码量小 (~20K 行 C)，易理解、易修改
2. 有活跃的社区维护 (OpenEtherCATSociety)
3. Python 绑定已有社区方案 (pySOEM)
4. 支持 DC 同步、CoE 邮箱、FoE 固件升级
5. GPLv2 许可证对工具软件友好 (用户不修改主站代码即不受传染)

## 三、实时性能目标

| 指标 | 目标 | 对标 (TwinCAT) |
|------|------|---------------|
| DC 同步周期 | 1 ms (默认) | 250 μs - 10 ms |
| PDO 交换抖动 | < 50 μs | < 10 μs |
| 示波器采样率 | 10 kHz (100 μs) | 可配 |
| 力控闭环周期 | 1 ms | 250 μs |
| 环形缓冲区深度 | 60 秒 @ 1 kHz | — |

### 示波器前端性能 (实测)

| 前端 | ms/帧 | FPS | 依赖 | 文件 |
|------|-------|-----|------|------|
| pyqtgraph | 2.6 | 381 | PySide6 150MB | `scope_app.py` |
| tkinter Canvas | 7.0 | 143 | Python stdlib (0) | `scope_tk.py` |
| Web HTML5 Canvas | 13.0 | 77 | 浏览器 (0) | `scope_server.py` |

## 四、伺服品牌支持 (参数库) — 2026-06-06 更新

| 等级 | 品牌 | 型号 | CoE 对象 | CiA 402 | 国家 |
|------|------|------|---------|---------|------|
| ◆ | **台达** | A3-E | 693 | 54 | TW |
| ◆ | **安川** | Σ-7 (SGD7S) | 294 | 57 | JP |
| ◆ | **安川** | Σ-5 (SGDV) | 223 | 54 | JP |
| ◆ | **松下** | Minas A6 | 18* | 18 | JP |
| ◆ | **Elmo** | Gold | 167 | 79 | IL |
| ◆ | **Servotronix** | CDHD | 429 | 71 | IL |
| ◆ | **Lenze** | i700 | 421 | 112 | DE |
| ○ | **汇川** | SV660 | 102 | 65 | CN |
| ○ | **埃斯顿** | ProNet Plus | 195 | 68 | CN |
| ○ | **英威腾** | DA200 | 547 | 49 | CN |
| ○ | **雷赛** | DM3E | 124 | 36 | CN |
| ○ | **雷赛** | CL3-EC | 115 | 46 | CN |

> ◆ Premium tier | ○ Value tier | * Panasonic ESI 仅含 PDO 映射, 完整字典需手册
> **总计: 12 品牌, 3,245 CoE 对象, 覆盖 JP/CN/TW/IL/DE 5 个国家/地区**

## 五、AI 能力复用

| AI 功能 | 来源 (AI&ML Agent) | 接入方式 |
|---------|-------------------|---------|
| 电流异常检测 | Solution 02 `train_servo_regression.py` | 本地实现 (性能), 桥接引用 (模型) |
| PPO PID 自整定 | Solution 01 `train_poly_reg.py` | `AIAnalyzerBridge.load_ppo_tuner()` |
| 漂移根因分析 | SL1 `drift_root_cause.py` | `AIAnalyzerBridge.load_root_cause_classifier()` |
| 方案自动生成 | AR4 `solution_generator.py` | `AIAnalyzerBridge.load_solution_generator()` |
| 故障诊断 ST 规则 | Solution 03 `FB_FaultDiag.st` | `AIAnalyzerBridge.export_codesys_st()` |

# AI Analyzer — 伺服信号 AI 分析引擎

> P1.4 | 替换 scope_engine.py 硬编码规则为 ML 驱动的三检测器管线

## 架构

```
scope_engine.py             06-ai-analyzer/
    │                           │
    ├── _run_ai() ──→ AIAnalyzerPipeline
    │                      │
    │                      ├── CurrentAnomalyDetector     (z-score + IQR + CUSUM)
    │                      ├── TrackingErrorDetector      (correlation + ratio analysis)
    │                      ├── MechanicalResonanceDetector (sliding-window FFT)
    │                      │
    │                      └── AIAnnotator (confidence calibration + severity escalation)
    │                           │
    │                           └── AIAnalyzerBridge (→ AI&ML Agent, 引用不拷贝)
    │
    └── anomaly_events ← AIAnnotation[]
```

## 快速开始

```python
from ai_analyzer import AIAnalyzerPipeline

# 默认三检测器 + 自动桥接
pipeline = AIAnalyzerPipeline(sample_rate_hz=1000)

# 每样本分析 (由 scope_engine 每 10 样本调用一次)
annotations = pipeline.analyze(
    values=[1000.0, 500.0, 85.0, 60.0, 15.0, 0.0, 0x0237, 1.0],
    channel_names=["Position", "Velocity", "Current", "Torque", "Foll.Err", "DIO", "Status", "OpMode"],
    buffer_stats={"Current": {"mean": 80.0, "std": 12.0, "min": 50.0, "max": 200.0, "rms": 85.0}},
)

for ann in annotations:
    print(f"{ann.severity}: {ann.message}")
    print(f"  → {ann.suggestion}")
```

## 检测能力

| 检测器 | 检测类型 | 方法 | 性能 |
|--------|---------|------|------|
| CurrentAnomaly | 电流饱和、机械磨损、传感器故障 | z-score + IQR + CUSUM 集成 | ~50μs/样本 |
| TrackingError | 机械卡死、增益不足、绝对值超限 | Pearson 相关性 + 动态阈值 | ~30μs/样本 |
| MechanicalResonance | 主谐振峰、谐波模式 | 滑动窗口 FFT (1024点) | ~200μs/256样本 |

## 配置

所有阈值在 `src/config.py` 中定义，按检测器分组：
- `CURRENT_ANOMALY` — 电流阈值、集成权重、窗口大小
- `TRACKING_ERROR` — 跟随误差 sigma 倍数、相关性阈值
- `MECHANICAL_RESONANCE` — FFT 窗口、步幅、峰值检测参数

## 与 AI&ML Agent 的关系

按照 CONSTITUTION.md 第三条，本模块**引用** AI&ML Agent 的能力但不复制代码：
- `analyzer_bridge.py` 提供延迟导入接口
- 流式统计算法**嵌入**在本模块中 (性能原因，1kHz 运行时不能承受跨模块导入开销)
- 离线任务 (模型加载、CODESYS ST 导出) 通过 bridge 延迟加载

当 AI&ML Agent 不可用时，bridge 优雅降级 (`bridge_available=False`)。

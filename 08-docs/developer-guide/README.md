# Developer Guide — Precision Force Control System

> Architecture, API reference, and contribution workflow.
> Last updated: 2026-06-06

---

## Architecture Overview

```
run_scope.py                     ← One-click launcher
    │
    ├── scope_tk.py              ← tkinter (0 deps, 143 FPS)
    ├── scope_app.py             ← pyqtgraph (Qt, 381 FPS)
    └── scope_server.py          ← Web (browser, 77 FPS)
            │
            └── scope_engine.py  ← Acquisition engine
                    │
                    ├── ring_buffer.py      ← 8ch × 60s buffer
                    ├── ec_master.py        ← EtherCAT master (SOEM)
                    └── ai_analyzer/        ← AI pipeline
                            │
                            ├── analyzer_pipeline.py
                            ├── current_anomaly.py
                            ├── tracking_error.py
                            ├── mechanical_resonance.py
                            ├── ai_annotator.py
                            └── analyzer_bridge.py  → AI&ML Agent
```

## Key APIs

### AIAnalyzerPipeline (import from `ai_analyzer`)

```python
from ai_analyzer import AIAnalyzerPipeline

pipeline = AIAnalyzerPipeline(sample_rate_hz=1000.0)

annotations = pipeline.analyze(
    values=[1000.0, 500.0, 85.0, ...],      # 8 channel values
    channel_names=["Position", "Velocity", ...],
    buffer_stats={"Current": {"mean": 80.0, "std": 10.0, ...}},
)

for ann in annotations:
    print(f"{ann.severity}: {ann.channel} — {ann.message}")
    print(f"  → {ann.suggestion}")
```

### RingBuffer

```python
from ring_buffer import RingBuffer

buf = RingBuffer(n_channels=8, buffer_size=60000)  # 60s @ 1kHz
buf.append([v0, v1, ...], timestamp_s)
data, timestamps = buf.get_recent(6000)  # last 6000 samples
stats = buf.channel_stats(channel_index)  # {"mean": ..., "std": ..., ...}
```

### EcMaster (EtherCAT)

```python
from ec_master import EcMaster

master = EcMaster(adapter="sim")  # or "eth0" for real hardware
master.scan()                     # discover slaves
master.go_operational()           # enter cyclic data exchange
while True:
    master.exchange()             # one PDO cycle
    pos = master.read_pdo(0x6064, 0)  # read position
master.close()
```

## Adding a New AI Detector

1. Create `ai_analyzer/my_detector.py`:

```python
from analyzer_base import AIAnnotation, AnalyzerBase

class MyDetector(AnalyzerBase):
    def analyze(self, values, channel_names, buffer_stats):
        # Return [] if nothing detected
        # Return [AIAnnotation(...)] if anomaly found
        return []
```

2. Register in `ai_analyzer/analyzer_pipeline.py` `_default_analyzers()`:

```python
return [
    CurrentAnomalyDetector(),
    TrackingErrorDetector(),
    MechanicalResonanceDetector(sample_rate_hz=sample_rate_hz),
    MyDetector(),  # ← add here
]
```

3. Add thresholds to `ai_analyzer/config.py`.

4. Write tests in `06-ai-analyzer/tests/`.

## Adding a New Servo Brand (Parameter Library)

1. Place the ESI XML file in `05-servo-params/<brand>/`.
2. Run the generalized ESI parser (when available).
3. Add channel config in `<brand>-scope-config.json`.
4. Update `05-servo-params/README.md`.

## Running Tests

```bash
# All tests (63)
python -m pytest 06-ai-analyzer/tests/ tests/ -v

# Unit tests only (43)
python -m pytest 06-ai-analyzer/tests/ -v

# Integration tests only (20)
python -m pytest tests/ -v
```

## Project Constitution (G1-G5)

Per `CONSTITUTION.md`:
- **G1**: Must directly serve precision force control / servo debugging / EtherCAT
- **G2**: All code runnable (`python xxx.py` or `gcc xxx.c`)
- **G3**: Don't duplicate existing modules
- **G4**: No empty shell demo code
- **G5**: CODESYS ST must contain complete FB definitions

## AI&ML Agent Relation

This project **references** (not copies) code from the sibling `AI&ML Agent` project:
- `analyzer_bridge.py` provides lazy imports with graceful degradation
- Streaming algorithms are re-implemented locally for performance (1 kHz runtime can't afford cross-module imports)
- Offline tasks (model loading, ST export) use the bridge's deferred imports

# Developer Guide — Precision Force Control System

> Architecture, API reference, and contribution workflow.
> Last updated: 2026-06-06 | 241 tests | 12 test files

---

## Architecture Overview

```
servo_cli.py                     ← CLI REPL (offline-first, LLM optional)
run_scope.py                     ← One-click launcher
    │
    ├── scope_tk.py              ← tkinter (0 deps, 143 FPS)
    ├── scope_app.py             ← pyqtgraph (Qt, 381 FPS)
    └── scope_server.py          ← Web (browser, 77 FPS) + HITL API
            │
            └── scope_engine.py  ← Acquisition engine
                    │
                    ├── ring_buffer.py      ← 8ch x 60s buffer
                    ├── ec_master.py        ← EtherCAT master (SOEM)
                    └── ai_analyzer/        ← AI pipeline + HITL + CLI
                            │
                            ├── analyzer_pipeline.py  ← Orchestrator
                            ├── current_anomaly.py    ← z-score + IQR + CUSUM
                            ├── tracking_error.py     ← Pearson + dynamic threshold
                            ├── mechanical_resonance.py ← FFT + harmonic matching
                            ├── ai_annotator.py       ← Confidence calibration + escalation
                            ├── analyzer_bridge.py    → AI&ML Agent (lazy)
                            │
                            ├── hitl_gate.py          ← classify / prompt / authorize
                            ├── hitl_types.py         ← EngineerPrompt / Feedback / AuthorizedAction
                            ├── engineer_prompts.py   ← 9 multi-modal prompt templates
                            ├── action_logger.py      ← Immutable audit trail
                            │
                            ├── llm_refiner.py        ← Claude API diagnosis refinement
                            ├── cli_llm_bridge.py     ← NL → CLI command translator
                            │
                            ├── cli_commands.py       ← 11 pure-function command executors
                            ├── cli_aliases.py        ← 83 built-in + user aliases
                            ├── codegen_st.py         ← CODESYS ST code generator
                            │
                            ├── parameter_recommender.py ← Annotation → brand param
                            ├── tuning_rules.py       ← 9 anomaly → parameter rules
                            └── config.py             ← Thresholds + categories + HITL
```

---

## Quick API Reference

### AIAnalyzerPipeline

```python
from ai_analyzer import AIAnalyzerPipeline

pipeline = AIAnalyzerPipeline(
    sample_rate_hz=1000.0,
    brand="delta-a3",
    enable_hitl=True,
    llm_api_key=None,         # reads ANTHROPIC_API_KEY env var
)

# Real-time analysis (per sample)
annotations = pipeline.analyze(values, channel_names, buffer_stats)

# Batch analysis (post-capture)
annotations = pipeline.batch_analyze(data_array, timestamps, channel_names)

# HITL workflow
prompts = pipeline.prompt_engineer(annotations)
refined = pipeline.process_engineer_feedback(prompt_id, feedback)
actions  = pipeline.get_authorized_actions()

# Parameter recommendations
recs = pipeline.recommend(require_authorization=True)
print(pipeline.format_recommendations())

# CODESYS export
bridge = pipeline.bridge
st_files = bridge.export_codesys_full(annotations, recs, output_dir="07-codesys-fb/")

# Session management
pipeline.disable_analyzer("MechanicalResonance")
pipeline.reset()
```

### RingBuffer

```python
from ring_buffer import RingBuffer

buf = RingBuffer(n_channels=8, buffer_size=60000)  # 60s @ 1kHz
buf.append([v0, v1, ...], timestamp_s)
data, timestamps = buf.get_recent(6000)
stats = buf.channel_stats(channel_index)
```

### EcMaster (EtherCAT)

```python
from ec_master import EcMaster

master = EcMaster(adapter="sim")  # or "eth0" for real hardware
master.scan()
master.go_operational()
while True:
    master.exchange()
    pos = master.read_pdo(0x6064, 0)
master.close()
```

---

## HITL API

### Classification

| Type | Categories | Behavior |
|------|-----------|----------|
| `safe` | `sensor_fault`, `system_overload` | Direct output |
| `actionable` | `resonance_*`, `gain_deficiency`, `saturation`, `current_ripple`, `velocity_ripple` | Needs engineer auth |
| `ambiguous` | `current_wear`, `mechanical_bind` | Needs observation → refine |

### HITLGate

```python
from ai_analyzer import HITLGate, EngineerFeedback

gate = HITLGate(brand="yaskawa-sigma7")

classification = gate.classify(annotation)
prompt = gate.generate_prompt(annotation)
refined = gate.process_feedback(prompt, feedback)
actions = gate.authorize(recommendations, feedback)
```

### Engineer Prompt Structure

```python
EngineerPrompt(
    prompt_id="hitl-abc123",
    category="current_wear",
    classification="ambiguous",     # "actionable" | "ambiguous"
    question="电流漂移 — 请检查机械部件",
    context="Current drift: 80% → 160% over 300 samples",
    suggested_checks=[
        "联轴器：是否有橡胶粉尘？[可拍照]",
        "丝杆：是否有异响？[可录音]",
        "轴承：温度>60°C？[可拍照]",
    ],
    expected_modalities=["text", "image", "audio", "video"],
    urgency="soon",
)
```

### Web HITL Endpoints

```
POST /hitl/analyze   → {annotations: [...], prompts: [...]}
POST /hitl/feedback  → {status: "ok", refined_annotations: [...], authorized_actions: [...]}
GET  /hitl/status    → {available: true, pending: 3, prompts: [...]}
```

---

## LLM Refiner API

```python
from ai_analyzer import LLMDiagnosisRefiner

refiner = LLMDiagnosisRefiner()  # reads ANTHROPIC_API_KEY

if refiner.available:
    result = refiner.refine(prompt, feedback)
    # → {"refined_category": "current_wear_coupling",
    #    "diagnosis": "联轴器弹性体碎裂",
    #    "recommendation": "更换弹性体 XD-40, 千分表对中 <0.05mm",
    #    "confidence": 0.95,
    #    "requires_parts": ["弹性体 XD-40"],
    #    "urgency": "immediate",
    #    "parameter_adjustment": "临时降增益30%"}
```

Degradation: LLM fails → keyword matching → generic fallback.

---

## CLI Architecture

```
servo_cli.py (cmd.Cmd REPL)
    │
    ├── cli_commands.py     ← Pure functions (no Cmd dependency)
    ├── cli_aliases.py      ← AliasRegistry (83 built-in + user)
    └── cli_llm_bridge.py   ← CLICommandTranslator (NL → command)
```

### Adding a CLI Command

1. Add `cmd_<name>()` to `cli_commands.py`:

```python
def cmd_mycommand(pipeline, args: dict) -> dict:
    """Execute mycommand, return structured result."""
    return {"status": "ok", "data": ...}
```

2. Add `do_mycommand()` to `ServoCli` in `servo_cli.py`.
3. Add alias: `cli_aliases.py` → `BUILTIN_ALIASES["mc"] = "mycommand"`.
4. Write test in `tests/test_servo_cli.py`.

### Adding a CLI Alias

```python
# Built-in (ships with system):
BUILTIN_ALIASES["myalias"] = "analyze --stride 5"

# User-defined (persisted to ~/.servo_aliases):
registry.add_user_alias("myalias", "analyze --stride 5")
registry.save()
```

---

## CODESYS Codegen API

```python
from ai_analyzer import CodegenST

gen = CodegenST(brand="delta-a3")

fb_diag = gen.generate_fb_diag(annotations)     # FB_ServoDiag
fb_tune = gen.generate_fb_tune(recommendations)  # FB_ServoTune
dut     = gen.generate_dut()                     # DUT enums + structs

# Export all (versioned, never overwrites)
files = gen.export_all("07-codesys-fb/", annotations, recommendations)
# → FB_ServoDiag_v1.st, FB_ServoTune_v1.st, DUT_ServoDiag_v1.st
```

### Generated Code Structure

| Block | Pattern |
|-------|---------|
| FB_ServoDiag | IF-THEN detection per category → ELSIF fault aggregation (priority-sorted) |
| FB_ServoTune | CASE state machine: idle → per-param write → done. Authorization gate: `bAuthorized AND bExecuteRising` |
| DUT | `E_ServoFault` (11 codes), `E_HITLState` (4 states), `ST_ServoSession` (persistent record) |

---

## Adding a New AI Detector

1. Create `ai_analyzer/my_detector.py`:

```python
from analyzer_base import AIAnnotation, AnalyzerBase

class MyDetector(AnalyzerBase):
    def analyze(self, values, channel_names, buffer_stats):
        return []  # or [AIAnnotation(...)]
```

2. Register in `analyzer_pipeline.py` `_default_analyzers()`.
3. Add category + thresholds to `config.py` (ANOMALY_CATEGORIES, SUGGESTION_TEMPLATES, HITL_CLASSIFICATION).
4. Add tuning rule to `tuning_rules.py` (TUNING_RULES + PARAM_DESCRIPTIONS).
5. Add engineer prompt to `engineer_prompts.py` (AMBIGUOUS_PROMPTS or ACTIONABLE_PROMPTS).
6. Write tests in `06-ai-analyzer/tests/`.

---

## Adding a New Servo Brand

1. Place the ESI XML file in `05-servo-params/<brand>/`.
2. Add brand aliases to `tuning_rules.py` BRAND_ALIASES.
3. Add channel config in `<brand>-scope-config.json`.
4. Update `05-servo-params/brands.json`.

---

## Running Tests

```bash
# All tests (241)
python -m pytest 06-ai-analyzer/tests/ tests/ -v

# Unit tests only (221)
python -m pytest 06-ai-analyzer/tests/ -v

# Integration tests only (20)
python -m pytest tests/ -v

# Specific module
python -m pytest 06-ai-analyzer/tests/test_hitl_gate.py -v
python -m pytest 06-ai-analyzer/tests/test_codegen_st.py -v
```

### Test File Map

| File | Tests | Covers |
|------|-------|--------|
| `test_current_anomaly.py` | 14 | z-score, IQR, CUSUM, ensemble |
| `test_tracking_error.py` | 10 | Pearson, dynamic threshold |
| `test_mechanical_resonance.py` | 6 | FFT, harmonic matching |
| `test_ai_annotator.py` | 9 | Confidence calibration, escalation |
| `test_parameter_recommender.py` | 12 | Brand resolution, dedup, format |
| `test_hitl_gate.py` | 63 | Classify, prompt, feedback, authorize |
| `test_action_logger.py` | 18 | Log, export, session |
| `test_llm_refiner.py` | 22 | Parse, degrade, build annotation |
| `test_servo_cli.py` | 63 | Commands, REPL, aliases, LLM bridge |
| `test_codegen_st.py` | 18 | FB generation, DUT, export, versioning |
| `test_integration_e2e.py` | 10 | Pipeline, buffer, cross-module |
| `test_integration_scope_ai.py` | 10 | Scope+AI, batch, degradation |

---

## Project Constitution

- **G1**: Directly serve precision force control / servo debugging / EtherCAT
- **G2**: All code runnable (`python xxx.py` or `gcc xxx.c`)
- **G3**: Don't duplicate existing modules
- **G4**: No empty shell demo code
- **G5**: CODESYS ST must contain complete FB definitions
- **G6**: Pro modules in `pro/`, Free modules in main tree
- **G7**: MIT License for Free modules; Pro modules proprietary

---

## AI&ML Agent Relation

This project **references** (not copies) the sibling `AI&ML Agent` project:
- `analyzer_bridge.py` provides lazy imports with graceful degradation
- Streaming algorithms re-implemented locally for 1 kHz performance
- Offline tasks (PPO training, ST export) use bridge's deferred imports
- Solution 01 (furnace PID) → PPO tuner reference
- Solution 02 (servo current) → current regression model reference

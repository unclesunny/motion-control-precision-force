# Servo Diagnostic System — User Manual

> Version 1.0 | 2026-06-06 | 12 brands | 240 tests

---

## Quick Start

### 1. Install

```bash
git clone <repo>
cd motion-control-precision-force
pip install -r requirements.txt   # numpy, requests (optional)
```

### 2. Launch

| Mode | Command | Use Case |
|------|---------|----------|
| CLI REPL | `python servo_cli.py` | Interactive diagnosis |
| Single cmd | `python servo_cli.py -c "analyze"` | Quick check |
| Web scope | `python 04-oscilloscope/src/scope_server.py` | Visual waveforms + HITL |
| Demo | `python demo_ai_scope.py` | 5-scenario simulation |

### 3. First Diagnosis

```
servo> analyze                      # Run AI 3-detector analysis
servo> status                       # View system state
servo> hitl prompt --all            # Generate engineer checklists
servo> recommend --brand delta-a3   # Get tuning suggestions
```

---

## CLI Command Reference

### Analysis

| Command | Description |
|---------|-------------|
| `analyze` | Run AI 3-detector analysis on demo data |
| `analyze --data file.csv` | Analyze exported scope data |
| `analyze --stride 20` | Faster analysis (skip samples) |

### HITL Workflow

| Command | Description |
|---------|-------------|
| `hitl prompt --all` | Generate engineer checklists for all anomalies |
| `hitl prompt --category current_wear` | Checklist for specific anomaly |
| `hitl feedback <id> --text "..." --observation "..." --auth pending` | Submit observation |
| `hitl feedback <id> --auth approved --by "Zhang"` | Authorize parameter change |
| `hitl feedback <id> --auth rejected` | Reject recommendation |
| `hitl pending` | Show waiting prompts |
| `hitl history` | Show feedback history |

### Parameter Recommendations

| Command | Description |
|---------|-------------|
| `recommend` | Generate tuning suggestions |
| `recommend --brand yaskawa-sigma7` | Brand-specific suggestions |
| `recommend --format json` | Machine-readable output |
| `params lookup 0x6083` | Look up CiA 402 parameter description |
| `params brands` | List 12 supported servo brands |

### System

| Command | Description |
|---------|-------------|
| `status` | System dashboard (detectors, HITL, log) |
| `detectors` | List/manage AI detectors |
| `detectors --disable MechanicalResonance` | Disable a detector |
| `log show` | Recent audit events |
| `log summary` | Authorization rate + event counts |
| `log export` | Export JSON audit trail |
| `session info` | Session ID, brand, sample count |
| `session reset` | Reset all state |
| `codesys export` | Export CODESYS ST code (versioned) |
| `alias list` | Show all 83 built-in + user aliases |
| `alias add mydiag "analyze\nhitl prompt --all"` | Create macro |
| `help` | Full command list |

---

## Alias Quick Reference

### English Shorthand

| Alias | Expands To |
|-------|-----------|
| `a` | `analyze` |
| `st` | `status` |
| `hf` | `hitl feedback` |
| `hp` | `hitl prompt --all` |
| `hpe` | `hitl pending` |
| `ha` | `hitl authorize` |
| `r` | `recommend` |
| `pl` | `params lookup` |
| `pb` | `params brands` |
| `ls` | `log show` |
| `dc` | `codesys export` |
| `q` | `quit` |

### Chinese / Pinyin

| Alias | Expands To |
|-------|-----------|
| `分析` / `fx` | `analyze` |
| `状态` / `zt` | `status` |
| `推荐` / `tj` | `recommend` |
| `磨损` / `ms` | `hitl prompt --category current_wear` |
| `共振` / `gzh` | `hitl prompt --category resonance_detected` |
| `反馈` / `fk` | `hitl feedback` |
| `授权` / `sq` | `hitl authorize` |
| `快诊` / `kz` | `analyze` + `hitl prompt --all` |
| `导出` / `dc` | `codesys export` |
| `帮助` / `bz` | `help` |
| `退出` / `tc` | `quit` |

### Custom Aliases

```
servo> alias add my "status\nanalyze\nhitl prompt --all\nrecommend"
servo> alias save     # persists to ~/.servo_aliases
```

---

## Web Oscilloscope

Launch: `python 04-oscilloscope/src/scope_server.py` → http://localhost:8888

### Features
- 8-channel real-time waveform display (Canvas, 60 FPS)
- AI analysis button — runs detectors on current buffer
- HITL feedback panel — engineer observation + authorization
- LLM-refined diagnosis display (when ANTHROPIC_API_KEY set)
- Pause / Clear / Export CSV

### HITL Panel
1. Click **AI Analysis** button
2. Review anomaly list + HITL classification
3. For ambiguous detections: read checklist, input observations, submit
4. For actionable detections: review parameter preview, authorize or reject
5. LLM-refined diagnosis appears with parts list + parameter compensation

---

## AI Detection Categories

### Autonomous (AI can fix, requires engineer authorization)

| Category | What It Detects | Suggested Fix |
|----------|----------------|---------------|
| `current_saturation` | Current > 200% rated | Reduce torque limit (0x6072), lower acceleration (0x6083) |
| `resonance_detected` | FFT peak at mechanical resonance | Set notch filter (0x610B) to detected frequency |
| `resonance_harmonic` | Harmonic resonance pattern | Multi-notch filter (0x610B - 0x6113) |
| `tracking_gain_deficiency` | Following error / velocity ratio high | Increase position gain (0x60FB), add feedforward (0x60B1) |
| `tracking_absolute_limit` | Error > hardware window | EMERGENCY: check mechanics, widen window as temp fix |
| `current_ripple` | HF current noise | Enable torque LPF (brand-specific: P1-07, Pn412, ...) |
| `velocity_ripple` | HF velocity oscillation | Enable S-curve (0x6086=3), reduce jerk (0x60A4) |

### Ambiguous (AI needs engineer observation)

| Category | What It Detects | Engineer Checks |
|----------|----------------|-----------------|
| `current_wear` | Gradual current drift (CUSUM) | Coupling dust? Ballscrew noise? Bearing temp? Belt wear? Guide stick? |
| `tracking_mechanical_bind` | Error + current correlation | Guide lube? Backlash? Cover interference? Debris? |

### Safe (Informational only)

| Category | What It Detects |
|----------|----------------|
| `current_sensor_fault` | Sudden current dropout (z-score > 5) |
| `system_overload` | General overload — check sizing |

---

## CODESYS Integration

### Export

```bash
servo> codesys export     # → 07-codesys-fb/FB_ServoDiag_v1.st
                           # → 07-codesys-fb/FB_ServoTune_v1.st
                           # → 07-codesys-fb/DUT_ServoDiag_v1.st
```

Each export creates versioned files (`_v1`, `_v2`, ...). Old files are never overwritten.

### Import into CODESYS IDE

1. Project → Add Object → POU → Structured Text
2. Copy generated FB + DUT code
3. Map PDO variables to FB inputs (0x6078 → iActualCurrent, etc.)
4. Set `bAuthorized := TRUE` only after engineer confirms

### Generated FBs

| Block | Purpose |
|-------|---------|
| `FB_ServoDiag` | Continuous anomaly detection (IF-THEN + ELSIF aggregation) |
| `FB_ServoTune` | Parameter write state machine (CASE, authorization-gated) |
| `DUT_ServoDiag` | Data types: E_ServoFault, E_HITLState, ST_ServoSession |

---

## Multi-Brand Support

12 brands, 3,245 CoE objects. Parameters auto-resolved by brand.

```
servo> recommend --brand yaskawa-sigma7     # Uses Pn102, Pn109, Pn409...
servo> recommend --brand delta-a3           # Uses 0x60FB, 0x60B1, 0x610B...
servo> params brands                        # List all supported brands
```

| Brand | Country | LPF Param | Notch Param |
|-------|---------|-----------|-------------|
| Delta A3-E | TW | P1-07 (0x2107) | 0x610B |
| Yaskawa Sigma-7 | JP | Pn412 (0x2412) | Pn409 (0x2409) |
| Panasonic A6 | JP | CiA 402 standard | CiA 402 standard |
| Servotronix CDHD | IL | 0x20E1 | CiA 402 standard |
| INVT DA200 | CN | P0.33 (0x2033) | CiA 402 standard |
| ... | | | |

---

## Safety Principles

1. **No authorization = no invasive operation.** All parameter writes require engineer approval via HITL gate.
2. **Audit trail is immutable.** Every AI suggestion + engineer decision is logged (JSON exportable).
3. **Graceful degradation.** LLM unavailable → keyword matching. API down → offline CLI works fully.
4. **Old files never overwritten.** CODESYS exports are versioned (`_v1`, `_v2`, ...).

---

## LLM Natural Language (Optional)

Set `ANTHROPIC_API_KEY` environment variable to enable:

```bash
set ANTHROPIC_API_KEY=sk-ant-...
python servo_cli.py
```

```
servo> 分析一下当前数据           # Natural language → LLM translates to: analyze
servo> 联轴器橡胶碎了怎么办       # → hitl prompt --category current_wear
servo> 给我安川的参数建议         # → recommend --brand yaskawa-sigma7
```

Multi-Axis Architecture — COMPLETE
===================================

Date: 2026-06-07
Status: All 4 catches resolved, 8 phases implemented.
Tests: 244 passing.

Current State
-------------
Multi-axis: 8 CiA 402 channels × N servo drives (1-64 axes).
Cross-axis: 4 sub-detectors for multi-axis problems (bus sag, contouring, 
            ring health, mechanical coupling).
3 backends: SOEM (Windows dev), IgH (Linux production), Sim (no hardware).
Auto-discovery: SII EEPROM scan → ESI matching → auto axis naming.


Catch 1: Data Plane — FIXED ✓
-------------------------------
Created complete 3-backend architecture:

  03-ethercat-master/bindings/
  ├── soem_bindings.py       ✅ exists    — ctypes for libsoem.dll (Windows)
  ├── igh_bindings.py        ✅ NEW       — ctypes for libethercat.so (Linux)
  └── ec_master.py           ✅ UPDATED   — +IgHEtherCAT class, +slave params

Backend comparison:
  | Feature              | SOEM (RealEtherCAT) | IgH (IgHEtherCAT) | Sim (SimulatedEtherCAT) |
  |----------------------|---------------------|-------------------|-------------------------|
  | Platform             | Windows + Linux     | Linux only        | Any                     |
  | Multi-slave support  | ✅ (SOEM native)    | ✅ (native)       | ✅ (NEW: num_axes param) |
  | PDO read model       | Per-object call     | Domain byte offset| Per-object call         |
  | slave param plumbed  | ✅ (FIXED)          | ✅ (axis_id)      | ✅ (FIXED)              |
  | Real-time            | Software timestamp  | Hardware DC       | N/A                     |

All EcMaster facade methods now forward slave:
  - sdo_read(idx, sub, slave=1)       ✅ slave forwarded
  - sdo_write(idx, sub, val, slave=1) ✅ slave forwarded
  - read_pdo(idx, sub, slave=1)       ✅ slave forwarded (NEW param)
  - write_pdo(idx, sub, val, slave=1) ✅ slave forwarded (NEW param)
  - read_scope(axis_id)               ✅ NEW — per-axis scope read
  - read_scope_all_axes()             ✅ NEW — all axes in one call

Status: ☑ DONE — 3 backends, slave param plumbed through all layers


Catch 2: HITL Complexity Explosion — DISMISSED ✗
--------------------------------------------------
RESOLUTION: Not a real problem. Tag every artifact with axis metadata:

  - axis_name:   "X", "Y", "Z", "Spindle"
  - slave_id:    EtherCAT slave position (0, 1, 2, ...)
  - drive_model: "Delta A3", "Yaskawa Sigma-7", etc.

All prompt/annotation/authorization info carries this tag. Engineer sees:

  [+] Axis X (Slave 0, Delta A3): resonance 320Hz → set notch filter 0x610B?
  [!] Axis Y (Slave 1, Delta A3): current saturation 210% → reduce accel 0x6083?
  [ ] Axis Z (Slave 2, Yaskawa S7): mechanical bind → check guide rails?
  --- Cross-axis: all 3 axes current sag when spindle starts → power bus?

One engineer can handle 64 axes with proper tagging. No complexity explosion.

Fields to add:
  AIAnnotation.axis_id: str
  AIAnnotation.slave_position: int
  EngineerPrompt.axis_id: str
  EngineerFeedback.axis_id: str
  AuthorizedAction.axis_id: str
  ActionLogger: per-axis event tagging

CLI examples:
  servo> analyze --axis X
  servo> hitl prompt --axis all
  servo> status --axis Z

Status: ☑ RESOLVED — just metadata, no architectural change


Catch 3: Cross-Axis Correlation — REAL PROBLEM 🔴
--------------------------------------------------
Current `analyze()` signature is single-axis only:

  def analyze(self, values: List[float],     # 8 floats from ONE axis
              channel_names: List[str],       # ONE axis
              buffer_stats: Dict[str, dict])  # ONE axis

Cross-axis problems invisible to single-axis analysis:

  | Problem              | Single-axis sees        | Cross-axis sees                    |
  |----------------------|-------------------------|------------------------------------|
  | Contouring error     | X/Y foll.err normal     | X+Y error vectors → circles        |
  | Power bus sag        | Z current drops         | ALL axes current drop together     |
  | Mechanical coupling  | X vibrates              | X amplitude correlates with Y pos  |
  | EtherCAT ring fault  | Slave 3 errors          | Slave 4 also corrupted (upstream)  |
  | Coordinated trip     | X alone OK, Y alone OK  | X accelerates while Y decels → fault|

Needs a 4th detector (CrossAxisAnalyzer) with access to all axes' aggregated
snapshots. This is architecturally different from N single-axis pipelines.

Status: ☐ Not yet discussed


Catch 4: UI Channel Explosion — UX PROBLEM 🟡
----------------------------------------------
48 traces for 6 axes. pyqtgraph handles GPU rendering fine. The real question
is layout: per-axis tabs? tile grid? master event timeline?

Status: ☐ Not yet discussed


Proposed Architecture
---------------------
```
EtherCAT Bus (one NIC, one exchange() call)
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Slave 0 │  │ Slave 1 │  │ Slave 2 │  │ Slave 3 │  ...
│ Axis X  │  │ Axis Y  │  │ Axis Z  │  │ Spindle │
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
┌────▼────┐  ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
│RingBuf X│  │RingBuf Y│  │RingBuf Z│  │RingBuf S│  N instances (no change)
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
┌────▼────┐  ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
│Pipeline │  │Pipeline │  │Pipeline │  │Pipeline │  N instances (no change)
│ X        │  │ Y        │  │ Z        │  │ S        │
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
     └────────────┼────────────┼────────────┘
                  │            │
          ┌───────▼────────────▼────────┐
          │  CrossAxisAnalyzer (NEW)    │  ← 4th detector
          │  contouring / bus sag /     │
          │  coupling / ring health     │
          └───────────────┬─────────────┘
                          │
                  ┌───────▼────────┐
                  │  HITL Gate v2  │  ← axis-tagged metadata
                  └───────┬────────┘
                          │
                  ┌───────▼────────┐
                  │  Scope UI v2   │  ← per-axis tabs/tiles
                  └────────────────┘
```

Changes Summary
---------------
| Layer              | Current              | Multi-Axis                          | Effort |
|--------------------|----------------------|-------------------------------------|--------|
| RingBuffer         | 1 instance, 8ch      | N instances, 8ch each               | none   |
| ScopeEngine        | 1 slave              | N slaves via slave_id param         | small  |
| AIAnalyzerPipeline | 1 instance           | N instances + axis_id tag           | small  |
| AIAnnotation       | flat fields          | +axis_id, +slave_position           | small  |
| HITLGate           | flat pending dict    | +axis_id on all types               | small  |
| CrossAxisAnalyzer  | doesn't exist        | NEW 4th detector                    | medium |
| Scope UI           | 8 traces, one view   | per-axis tabs + cross-axis panel    | medium |
| CLI (servo_cli)    | global commands      | --axis flag on relevant commands    | small  |


Review Queue (one by one) — ALL DONE
-------------------------------------
☑ Catch 2: DISMISSED — axis_id + slave_position metadata on all types
☑ Catch 1: FIXED — 3 backends (SOEM + IgH + Sim), slave param plumbed through all layers
☑ Catch 3: IMPLEMENTED — CrossAxisAnalyzer with 4 sub-detectors, 23 tests
☑ Catch 4: IMPLEMENTED — Tree + Detail layout (AxisTreePanel + QStackedWidget)

Implementation Phases — ALL DONE
---------------------------------
☑ P0: Multi-axis ScopeEngine + axis_id on AIAnnotation (244 tests)
☑ P1: Multi-axis scope UI + cross-axis events panel (tree+detail)
☑ P2: Multi-axis simulation demo (5 scenarios, all pass)
☑ P3: CLI --axis flag (analyze --axis X, status --axis all, cross status)
☑ Discover: Slave SII EEPROM scan + ESI matching + auto axis naming + config persistence

Files Created/Modified (14 files):
  NEW: igh_bindings.py, cross_axis.py, discover.py, demo_multi_axis.py
  MODIFIED: ec_master.py, soem_bindings.py, scope_engine.py, scope_app.py,
           servo_cli.py, cli_commands.py, config.py, __init__.py,
           analyzer_base.py, analyzer_pipeline.py, engineer_prompts.py
  TESTS: test_cross_axis.py (23 tests)

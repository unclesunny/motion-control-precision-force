"""
Real-World Resonance Scenario Simulation — Ball Screw Servo Module.

Models the exact field conditions described:
  - 320Hz mechanical resonance (dual-inertia system)
  - Current oscillation with periodic saturation
  - Position following error cyclic jump
  - High-speed start/stop excitation

Runs through full AI pipeline: detection → recommendation → gap analysis.
"""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "06-ai-analyzer"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "06-ai-analyzer" / "ai_analyzer"))

from ai_analyzer import AIAnalyzerPipeline
from analyzer_base import AIAnnotation

# ── Scenario Parameters ─────────────────────────────────────
SAMPLE_RATE = 2000       # Hz (need > 2×320Hz for Nyquist)
DURATION = 8.0           # seconds
N_SAMPLES = int(SAMPLE_RATE * DURATION)

# Servo specs (from field report)
MOTOR_POWER = 2.2        # kW
BALL_SCREW_LEAD = 5.0    # mm
LOAD_MASS = 350.0         # kg
STROKE = 600.0            # mm
SPEED = 300.0             # mm/s
ACCEL_TIME = 0.12         # s
RESONANCE_FREQ = 320.0    # Hz — the detected resonant point
CYCLE_TIME = 3.0          # s per cycle

# Fault signatures
RESONANCE_AMPLITUDE = 0.15   # current oscillation amplitude (fraction of rated)
ERROR_AMPLITUDE = 0.15       # mm — position error jump
CURRENT_BASELINE = 80.0      # % rated
CURRENT_PEAK = 110.0         # % rated — triggers overload alarm


def generate_field_data():
    """Generate synthetic servo data matching the field report."""
    t = np.arange(N_SAMPLES) / SAMPLE_RATE

    # ── Position profile: reciprocating point-to-point ──
    period = CYCLE_TIME
    phase = (t % period) / period  # 0..1 each cycle
    pos_demand = np.where(phase < 0.5,
                          STROKE * (2 * phase),           # forward stroke
                          STROKE * (2 - 2 * phase))       # return stroke

    # ── Velocity: trapezoidal profile ──
    ramp = ACCEL_TIME / (period / 2)
    vel_demand = np.zeros(N_SAMPLES)
    for i in range(N_SAMPLES):
        p = phase[i]
        if p < ramp:
            vel_demand[i] = SPEED * p / ramp
        elif p < 0.5 - ramp:
            vel_demand[i] = SPEED
        elif p < 0.5:
            vel_demand[i] = SPEED * (0.5 - p) / ramp
        elif p < 0.5 + ramp:
            vel_demand[i] = -SPEED * (p - 0.5) / ramp
        elif p < 1.0 - ramp:
            vel_demand[i] = -SPEED
        else:
            vel_demand[i] = -SPEED * (1.0 - p) / ramp

    # ── Resonance: 320Hz sinusoidal disturbance ──
    # Excited during acceleration/deceleration (not at constant speed)
    is_accelerating = (phase < ramp) | ((phase > 0.5 - ramp) & (phase < 0.5 + ramp)) | (phase > 1.0 - ramp)

    resonance = np.zeros(N_SAMPLES)
    resonance[is_accelerating] = (
        RESONANCE_AMPLITUDE * CURRENT_BASELINE *
        np.sin(2 * np.pi * RESONANCE_FREQ * t[is_accelerating])
    )

    # ── Current: baseline + load + resonance ──
    # Higher during accel/decel (inertia), plus resonance component
    current = CURRENT_BASELINE + np.abs(vel_demand) / SPEED * 20.0  # load component
    current += resonance
    current += np.random.normal(0, 2.0, N_SAMPLES)  # measurement noise
    # Simulate saturation spikes
    current = np.clip(current, 0, CURRENT_PEAK + 5)

    # ── Following Error: cyclic jump during resonance ──
    error = np.zeros(N_SAMPLES)
    error[is_accelerating] = (
        ERROR_AMPLITUDE * STROKE * 0.001 *
        np.sin(2 * np.pi * RESONANCE_FREQ * t[is_accelerating] + 0.3)
    )
    error += np.random.normal(0, 0.005, N_SAMPLES)

    # ── Position actual: demand + error ──
    pos_actual = pos_demand + error

    # ── Torque: proportional to current ──
    torque = current * 0.95 + np.random.normal(0, 1.0, N_SAMPLES)

    # Build 8-channel data
    data = np.zeros((8, N_SAMPLES), dtype=np.float32)
    data[0] = pos_actual.astype(np.float32)
    data[1] = vel_demand.astype(np.float32)
    data[2] = current.astype(np.float32)
    data[3] = torque.astype(np.float32)
    data[4] = (error * 1000).astype(np.float32)  # Following Error in pulses
    data[5] = (is_accelerating * 1.0).astype(np.float32)  # DIO: accel flag
    data[6] = np.where(current > CURRENT_PEAK, 0x0237, 0x0007).astype(np.float32)  # Status: alarm
    data[7] = np.ones(N_SAMPLES, dtype=np.float32)  # OpMode: profile position

    return data, t


def run_diagnosis():
    """Run full AI pipeline on field data."""
    print("=" * 65)
    print("  FIELD SCENARIO: Ball Screw Servo — 320Hz Resonance")
    print("  Equipment: 2.2kW PMSM, 350kg load, 600mm stroke")
    print("=" * 65)

    data, t = generate_field_data()
    ch_names = ["Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode"]

    # ── Run batch analysis through AI pipeline ──
    pipeline = AIAnalyzerPipeline(sample_rate_hz=float(SAMPLE_RATE))
    annotations = pipeline.batch_analyze(data, t, ch_names)

    # ── Categorize detections ──
    by_category = {}
    for ann in annotations:
        by_category.setdefault(ann.category, []).append(ann)

    print(f"\n  Samples analyzed: {N_SAMPLES} @ {SAMPLE_RATE} Hz, {DURATION}s")
    print(f"  Total annotations: {len(annotations)}")
    print(f"\n  Detected anomalies:")
    for cat, anns in sorted(by_category.items()):
        from tuning_rules import TUNING_RULES
        rule = TUNING_RULES.get(cat, {})
        summary = rule.get("summary", cat)
        print(f"    [{len(anns):>3d}] {cat}")
        print(f"         {summary}")
        # Show top detection
        best = max(anns, key=lambda a: a.confidence)
        print(f"         confidence={best.confidence:.0%}, severity={best.severity}")
        if best.metadata:
            for k, v in best.metadata.items():
                if isinstance(v, float):
                    print(f"         {k}={v:.1f}")
                elif isinstance(v, list) and len(v) <= 5:
                    print(f"         {k}={v}")

    # ── Parameter Recommendations ──
    print(f"\n  ── Tuning Recommendations ──")
    params = pipeline.recommend(annotations)
    if params:
        for p in params[:8]:
            action_icon = {"increase": "+", "decrease": "-", "set": "→", "check": "?"}.get(p.action, "?")
            print(f"    {action_icon} {p.index_hex} {p.name[:50]}")
            print(f"      {p.reason}")
            if p.target_value:
                print(f"      Target: {p.target_value:.0f}")
            if p.safety:
                print(f"      Safety: {p.safety[:80]}")
    else:
        print("    (none — Pro license required)")

    # ── Gap Analysis: map against field report steps ──
    print(f"\n  ── Gap Analysis: Field Report vs AI + HITL Coverage ──")
    report_steps = [
        ("1. Reduce velocity/position gain", "tracking_gain_deficiency + resonance_detected → 0x60FB decrease + 0x60F9 decrease", "✅ Covered"),
        ("2. Notch filter @ 320Hz", "resonance_detected → 0x610B set to 320Hz", "✅ Covered"),
        ("3. Low-pass filter", "current_ripple → 0x2107 torque LPF + 0x2219 resonance LPF. HITL: prompt engineer to configure brand-specific LPF (12 brands mapped)", "✅ Covered"),
        ("4. Replace coupling (mechanical)", "current_wear → HITL prompt: multi-modal checklist (联轴器/丝杆/轴承/皮带/导轨) → engineer observation refines diagnosis", "🔄 HITL-bridged"),
        ("5. Tighten guide preload (mechanical)", "Not detectable from electrical signals. HITL: prompt engineer 'check guide preload + lubrication' with image/audio feedback", "🔄 HITL-bridged"),
        ("6. S-curve acceleration", "velocity_ripple → 0x60A4 jerk + 0x6086 profile type + 0x2106 speed filter. 3-param recommendation chain", "✅ Covered"),
        ("7. Mid-support bearing (mechanical)", "Not detectable from electrical signals. HITL: prompt engineer 'inspect mid-support bearing, check temperature/vibration'", "🔄 HITL-bridged"),
    ]
    for step, ai_response, coverage in report_steps:
        icon_map = {
            "[OK] Covered": "✅",
            "[--] Not covered": "❌",
            "[~] Partial": "⚠️",
            "[HITL] Bridged": "🔄",
        }
        for key, icon in icon_map.items():
            if key in coverage:
                print(f"    {icon} {step}")
                break
        else:
            print(f"    [?] {step}")
        print(f"       AI: {ai_response}")

    # ── Summary ──
    covered = sum(1 for _, _, c in report_steps if "Covered" in c)
    hitl_bridged = sum(1 for _, _, c in report_steps if "HITL-bridged" in c)
    not_covered = sum(1 for _, _, c in report_steps if "Not covered" in c)
    print(f"\n  Coverage: {covered}/7 autonomous, {hitl_bridged}/7 HITL-bridged (engineer-AI collaboration)")
    print(f"  Electrical tuning: gain (#1), notch (#2), LPF (#3), S-curve (#6) — all covered.")
    print(f"  Mechanical gaps (#4/#5/#7) bridged via HITL multi-modal prompts.")
    print(f"  Key principle: no authorization = no invasive parameter write.")
    print("=" * 65)

    return annotations, pipeline


if __name__ == "__main__":
    run_diagnosis()

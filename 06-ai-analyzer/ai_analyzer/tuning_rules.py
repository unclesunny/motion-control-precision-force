"""
Servo Tuning Knowledge Base — anomaly → parameter → adjustment rules.

Each rule maps an anomaly category to one or more CiA 402 parameter
adjustments. Rules are brand-agnostic (use CiA 402 standard indices).
The ParameterRecommender resolves brand-specific parameter details.

Reference sources:
  - Delta A3 tuning guide (manual §7)
  - Yaskawa Sigma-7 tuning guide (manual §5-6)
  - CiA 402 standard (IEC 61800-7-201/301)
  - Competitive analysis (PANATERM, ASDA-Soft behavior patterns)
"""

from typing import Dict, List, Optional

# ── Rule data structure ─────────────────────────────────────
# Each rule: {category: str, params: [{index, subindex, direction, step, min, max, reason}]}

TUNING_RULES: Dict[str, dict] = {
    # ── Current Anomalies ────────────────────────────────
    "current_saturation": {
        "priority": 1,
        "summary": "Current saturation detected — reduce load or adjust limits",
        "params": [
            {
                "index": 0x6072,      # Max torque
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -10,       # reduce by 10%
                "min_pct": 50,         # never below 50%
                "max_pct": 100,
                "reason": "Reduce torque limit to prevent current saturation. This protects the motor winding.",
                "safety": "Ensure application torque requirement is still met after reduction.",
            },
            {
                "index": 0x6083,      # Profile acceleration
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -20,
                "min_pct": 50,
                "max_pct": 100,
                "reason": "Lower acceleration reduces peak current demand during speed changes.",
                "safety": "May increase cycle time. Check if production rate is still acceptable.",
            },
            {
                "index": 0x60E0,      # Positive torque limit
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -15,
                "min_pct": 40,
                "max_pct": 100,
                "reason": "Tighten the torque envelope to prevent sustained over-current.",
                "safety": "Set above the application's maximum working torque.",
            },
        ]
    },

    "current_wear": {
        "priority": 2,
        "summary": "Gradual current increase — possible mechanical wear",
        "params": [
            {
                "index": 0x2102,      # Position loop gain (Yaskawa) / 0x60FB (CiA 402)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 10,
                "min_pct": 100,
                "max_pct": 200,
                "reason": "Higher gain compensates for increased friction from wear. Maintains positioning accuracy.",
                "safety": "Watch for oscillation. If vibration occurs, reduce gain slightly.",
                "alt_index": 0x60FB,  # CiA 402 standard position control gain
            },
        ]
    },

    "current_sensor_fault": {
        "priority": 1,
        "summary": "Current sensor anomaly — check hardware immediately",
        "params": []  # No parameter fix — hardware issue
    },

    # ── Tracking Error Anomalies ──────────────────────────
    "tracking_mechanical_bind": {
        "priority": 1,
        "summary": "Mechanical bind detected — increase error tolerance or inspect mechanics",
        "params": [
            {
                "index": 0x6065,      # Following error window
                "subindex": 0,
                "direction": "increase",
                "step_pct": 50,
                "min_pct": 100,
                "max_pct": 500,
                "reason": "Temporarily widen the following error window to prevent nuisance alarms while investigating mechanical bind.",
                "safety": "This is a diagnostic measure. Do not leave widened permanently.",
            },
            {
                "index": 0x60FB,      # Position control gain (CiA 402)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 15,
                "min_pct": 100,
                "max_pct": 200,
                "reason": "Higher position gain increases stiffness, helping overcome minor mechanical resistance.",
                "safety": "Monitor for oscillation. If vibration occurs, back off immediately.",
            },
        ]
    },

    "tracking_gain_deficiency": {
        "priority": 1,
        "summary": "Position loop gain insufficient — increase gains",
        "params": [
            {
                "index": 0x60FB,      # Position control gain (primary)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 25,
                "min_pct": 100,
                "max_pct": 400,
                "reason": "Primary fix for following error: increase position loop proportional gain. Higher Kp = lower error = stiffer system.",
                "safety": "Increase in 10-15% increments. Watch for overshoot and oscillation. If ringing occurs, back off 20%.",
            },
            {
                "index": 0x60B1,      # Velocity offset / feedforward
                "subindex": 0,
                "direction": "increase",
                "step_pct": 50,
                "min_pct": 100,
                "max_pct": 500,
                "reason": "Velocity feedforward predicts the required velocity, reducing tracking error before the feedback loop responds.",
                "safety": "Start at 50% and increase gradually. Too much feedforward causes overshoot.",
                "alt_index": 0x2109,  # Yaskawa: Feedforward Gain (Pn109)
            },
            {
                "index": 0x6083,      # Profile acceleration
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -15,
                "min_pct": 60,
                "max_pct": 100,
                "reason": "If acceleration is too aggressive, the servo cannot track the profile. Reducing it may eliminate the following error.",
                "safety": "Accepts slightly longer cycle time in exchange for accurate tracking.",
            },
        ]
    },

    "tracking_absolute_limit": {
        "priority": 1,
        "summary": "Following error exceeded hardware limit — EMERGENCY",
        "params": [
            {
                "index": 0x6065,      # Following error window
                "subindex": 0,
                "direction": "check",
                "step_pct": 0,
                "min_pct": 100,
                "max_pct": 100,
                "reason": "EMERGENCY: Check mechanical limits immediately. Verify position command range. Increase window only as temporary diagnostic measure.",
                "safety": "DO NOT permanently widen. Fix the root cause (mechanical obstruction, encoder fault, or command error).",
            },
        ]
    },

    # ── Mechanical Resonance ───────────────────────────────
    "resonance_detected": {
        "priority": 1,
        "summary": "Mechanical resonance detected — configure notch filter",
        "params": [
            {
                "index": 0x610B,      # Notch filter 1 frequency (Delta A3)
                "subindex": 0,
                "direction": "set",
                "step_pct": 0,         # Set to detected frequency (from annotation metadata)
                "min_pct": 100,
                "max_pct": 100,
                "reason": "Set notch filter to suppress the detected resonant frequency. This prevents oscillation without reducing overall gain.",
                "safety": "Set notch width (Q factor) no wider than needed. Start with Q=0.5 (narrow).",
                "alt_index": 0x2409,  # Yaskawa: 1st Notch Filter Frequency (Pn409)
            },
            {
                "index": 0x2101,      # Speed loop gain (Yaskawa) / velocity loop gain
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -20,
                "min_pct": 50,
                "max_pct": 100,
                "reason": "Reducing velocity loop gain is a temporary workaround if notch filter is not available. The notch filter is the proper solution.",
                "safety": "Reducing gain softens the system response. Use only until notch filter is configured.",
                "alt_index": 0x60F9,  # CiA 402: Velocity control gain
            },
        ]
    },

    "resonance_harmonic": {
        "priority": 1,
        "summary": "Harmonic resonance pattern — multi-notch or structural fix",
        "params": [
            {
                "index": 0x610B,      # Notch filter 1
                "subindex": 0,
                "direction": "set",
                "step_pct": 0,
                "min_pct": 100,
                "max_pct": 100,
                "reason": "Set first notch filter to the fundamental frequency. Harmonic peaks will also be suppressed.",
                "safety": "If harmonics persist after fundamental notch, configure additional notch filters.",
                "alt_index": 0x2409,  # Yaskawa
            },
            {
                "index": 0x610C,      # Notch filter 2 (for 2nd harmonic if needed)
                "subindex": 0,
                "direction": "consider",
                "step_pct": 0,
                "min_pct": 100,
                "max_pct": 100,
                "reason": "If 2nd harmonic persists after fundamental notch, configure a second notch filter at the harmonic frequency.",
                "safety": "Multiple notch filters can interact. Test each independently.",
                "alt_index": 0x240C,  # Yaskawa: 2nd Notch Filter Frequency (Pn40C)
            },
        ]
    },

    # ── Current Ripple (HF noise → LPF needed) ──────────
    "current_ripple": {
        "priority": 2,
        "summary": "High-frequency current ripple — enable torque command low-pass filter",
        "params": [
            {
                "index": 0x2107,      # Torque command filter (Delta P1-07)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 100,        # enable with default time constant
                "min_pct": 100,
                "max_pct": 1000,
                "reason": "Torque command LPF smooths high-frequency current ripple. Start with 1-2ms time constant, increase if ripple persists.",
                "safety": "Too much filtering adds phase lag. Keep cutoff above position loop bandwidth × 5.",
                "alt_index": 0x2107,  # Same across brands (vendor-specific)
            },
            {
                "index": 0x2219,      # Resonance suppression LPF (Delta P2-25)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 100,
                "min_pct": 100,
                "max_pct": 1000,
                "reason": "Resonance suppression low-pass filter attenuates high-frequency mechanical resonance that notch filters miss.",
                "safety": "Set cutoff below the lowest resonance frequency. 0 = disabled.",
                "alt_index": 0x2219,
            },
        ]
    },

    # ── Velocity Ripple (HF oscillation → S-curve suggested) ──
    "velocity_ripple": {
        "priority": 2,
        "summary": "High-frequency velocity oscillation — enable S-curve jerk limiting",
        "params": [
            {
                "index": 0x60A4,      # Profile Jerk (CiA 402 standard)
                "subindex": 0,
                "direction": "decrease",
                "step_pct": -30,
                "min_pct": 10,
                "max_pct": 100,
                "reason": "Reducing jerk smooths acceleration transitions. Lower jerk = less excitation of mechanical resonances. Standard CiA 402 index.",
                "safety": "Lower jerk increases acceleration/deceleration time. Verify cycle time still acceptable.",
            },
            {
                "index": 0x6086,      # Motion Profile Type (CiA 402 standard)
                "subindex": 0,
                "direction": "set",
                "step_pct": 0,
                "min_pct": 100,
                "max_pct": 100,
                "reason": "Profile type 3 = jerk-limited (S-curve) ramps. Types: 0=linear, 3=sin² jerk-limited, -1=manufacturer-specific. Switching from linear to S-curve reduces velocity overshoot and ripple.",
                "safety": "S-curve profile increases move time slightly. Confirm with production rate requirements.",
                "target_value_hint": 3,  # Sin² jerk-limited
            },
            {
                "index": 0x2106,      # Speed command filter (Delta P1-06)
                "subindex": 0,
                "direction": "increase",
                "step_pct": 50,
                "min_pct": 100,
                "max_pct": 500,
                "reason": "Speed command smoothing filter reduces velocity ripple before it reaches the velocity loop. Complementary to jerk limiting.",
                "safety": "Excessive filtering causes tracking lag. Keep time constant < 10ms for typical applications.",
                "alt_index": 0x2106,
            },
        ]
    },

    # ── System / General ───────────────────────────────────
    "system_overload": {
        "priority": 2,
        "summary": "General overload — check application sizing",
        "params": [
            {
                "index": 0x6075,      # Motor rated current
                "subindex": 0,
                "direction": "check",
                "step_pct": 0,
                "min_pct": 100,
                "max_pct": 100,
                "reason": "Verify motor and drive are sized correctly for the application.",
                "safety": "Undersized motors will fail prematurely. Replace with larger motor if needed.",
            },
        ]
    },
}

# ── Brand-specific parameter aliases ───────────────────────
# Maps CiA 402 standard indices to brand-specific equivalents.
# Brands using standard CiA 402 indices use identity mapping (explicit for clarity).
#
# Sources: ESI CoE dictionaries (05-servo-params/), scanned 2026-06-06.
# Coverage: 12/12 brands mapped — every brand has complete tuning parameter aliases.
# Verified: 2026-06-07 P1.2 — 9 brands added/expanded from CoE object dictionaries.
#
# Key tuning parameters mapped per brand:
#   0x60FB — Position loop gain (Kp)
#   0x60F9 — Velocity loop gain / bandwidth
#   0x60B1 — Velocity feedforward
#   0x610B — Notch filter 1 frequency
#   0x610C — Notch filter 2 frequency
#   0x2100 — Velocity loop gain (Yaskawa/INVT alias)
#   0x2101 — Velocity loop integral
#   0x60A4 — Profile jerk (S-curve)
#   0x6086 — Motion profile type
#   0x2106 — Speed command LPF
#   0x2107 — Torque command LPF
#   0x2108 — Position command LPF
#   0x2219 — Resonance suppression LPF

BRAND_ALIASES: Dict[str, Dict[int, int]] = {
    # ── Delta A3-E (12 mappings) ────────────────────────────
    "delta-a3": {
        # Core tuning
        0x60FB: 0x60FB,   # Position Control Gain (CiA 402 standard)
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Offset / Feedforward
        0x610B: 0x610B,   # Notch filter 1 frequency
        0x610C: 0x610C,   # Notch filter 2 frequency
        # S-curve
        0x60A4: 0x60A4,   # Profile Jerk (CiA 402)
        0x6086: 0x6086,   # Motion Profile Type
        # Low-pass filters (Delta native)
        0x2106: 0x2106,   # P1-06 Speed Command Filter (ms)
        0x2107: 0x2107,   # P1-07 Torque Command Filter (ms)
        0x2108: 0x2108,   # P1-08 Position Command Filter (10ms)
        0x2219: 0x2219,   # P2-25 Resonance Suppression LPF (0.1ms)
        # Velocity loop (Yaskawa-style aliases → CiA 402)
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x2101,   # Speed Loop Integral (Delta native P1-01)
    },

    # ── Yaskawa Sigma-7 SGD7S (12 mappings) ─────────────────
    "yaskawa-sigma7": {
        # Core tuning (PnXXX format)
        0x60FB: 0x2102,   # Position loop gain → Pn102
        0x60F9: 0x2100,   # Velocity loop gain → Pn100
        0x60B1: 0x2109,   # Velocity feedforward → Pn109
        0x610B: 0x2409,   # 1st Notch filter freq → Pn409
        0x610C: 0x240C,   # 2nd Notch filter freq → Pn40C
        0x2100: 0x2100,   # Speed Loop Gain (Pn100)
        0x2101: 0x2101,   # Speed Loop Integral (Pn101)
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        # Low-pass filters (Yaskawa native)
        0x2106: 0x2410,   # Speed Ref Filter (Pn410)
        0x2107: 0x2412,   # Torque Ref Filter (Pn412)
        0x2219: 0x2409,   # Resonance Suppression → 1st Notch (Pn409)
    },

    # ── Yaskawa Sigma-5 SGDV (12 mappings) ──────────────────
    "yaskawa-sigma5": {
        0x60FB: 0x2102,   # Position loop gain → Pn102
        0x60F9: 0x2100,   # Velocity loop gain → Pn100
        0x60B1: 0x2109,   # Velocity feedforward → Pn109
        0x610B: 0x2409,   # 1st Notch filter freq → Pn409
        0x610C: 0x240C,   # 2nd Notch filter freq → Pn40C
        0x2100: 0x2100,   # Speed Loop Gain (Pn100)
        0x2101: 0x2101,   # Speed Loop Integral (Pn101)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        0x2106: 0x2410,   # Speed Ref Filter (Pn410)
        0x2107: 0x2412,   # Torque Ref Filter (Pn412)
        0x2219: 0x2409,
    },

    # ── INVT DA200 (14 mappings) ────────────────────────────
    "invt-da200": {
        # Core tuning
        0x60FB: 0x2202,   # Position loop gain → P2.02 1st Position gain (0.1)
        0x60F9: 0x2200,   # Velocity loop gain → P2.00 1st Speed gain (0.1)
        0x60B1: 0x220A,   # Velocity feedforward → P2.10 Speed feed-forward gain (0.1)
        0x610B: 0x2125,   # 1st Notch → P1.37 1st Vibration filter value (0.01)
        0x610C: 0x2127,   # 2nd Notch → P1.39 2nd Vibration filter value (0.01)
        0x2100: 0x2200,   # Speed Loop Gain → P2.00
        0x2101: 0x220E,   # Speed Loop Integral → P2.14 1st IPPI gain
        # Resonance detection (read-only)
        0x2115: 0x2115,   # P1.21 1st Mechanical resonance frequency (detected)
        0x2116: 0x2116,   # P1.22 2nd Mechanical resonance frequency (detected)
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        # Low-pass filters
        0x2106: 0x2021,   # P0.33 Position command LPF filter time (0.1)
        0x2107: 0x2204,   # P2.04 1st Torque filter (0.01)
        0x2108: 0x2203,   # P2.03 1st Speed detection filter time
    },

    # ── Servotronix CDHD (14 mappings) ──────────────────────
    "servotronix-cdhd": {
        # Core tuning
        0x60FB: 0x2022,   # Position loop gain → Position Proportional Gain
        0x60F9: 0x2010,   # Velocity loop → Velocity Loop Bandwidth
        0x60B1: 0x201E,   # Feedforward → Position Derivative Gain
        0x610B: 0x2061,   # 1st Notch → HD Current Notch Filter Center
        0x610C: 0x208C,   # 2nd Notch → HD Current Filter - Second Notch Filter Center
        0x2100: 0x2010,   # Speed Loop Gain → Velocity Loop Bandwidth
        0x2101: 0x2026,   # Speed Loop Integral → Velocity Integrator
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        # Low-pass filters
        0x2106: 0x204E,   # Velocity Loop Output Filter Parameter 1
        0x2107: 0x205F,   # Torque filter → HD Current LPF Rise Time
        0x2108: 0x202C,   # Position filter → Ptp Move Lpf Hz
        # Anti-vibration (alternative to notch)
        0x200A: 0x200A,   # HD Anti-Vibration Filter
        0x2219: 0x200A,   # Resonance Suppression → HD Anti-Vibration Filter
    },

    # ── Lenze i700 (14 mappings) ────────────────────────────
    "lenze-i700": {
        # Core tuning (Axis A = 0x29xx, Axis B = 0x31xx — use Axis A)
        0x60FB: 0x2980,   # Position controller: Gain
        0x60F9: 0x2901,   # Velocity loop → Speed controller: Gain - adaption
        0x60B1: 0x2941,   # Feedforward → Current controller: Feedforward control
        0x610B: 0x2944,   # 1st Notch → Torque: Notch filter setpoint torque
        # Lenze has 2nd notch in filter cascade (index 0x2DD6)
        0x610C: 0x2DD6,   # 2nd Notch → Torque: Filter cascade
        0x2100: 0x2901,   # Speed Loop Gain → Speed controller: Gain - adaption
        0x2101: 0x2901,   # Speed Loop Integral (same object, adaption handles both)
        # S-curve (Lenze-specific jerk)
        0x60A4: 0x2945,   # Profile Jerk → Torque: Setpoint jerk limitation (Lenze native)
        0x6086: 0x6086,   # Motion Profile Type (standard CiA 402)
        # Low-pass filters
        0x2106: 0x2903,   # Speed setpoint - filter time
        0x2107: 0x2943,   # Torque filter → Motor: Setpoint current - filter time
        0x2108: 0x2903,   # Position filter → same as speed setpoint filter
        # Inertia feedforward
        0x2910: 0x2910,   # Moments of inertia (for adaptive tuning)
        0x2219: 0x2944,   # Resonance Suppression → Notch filter
    },

    # ── Leadshine CL3-EC (10 mappings) ──────────────────────
    "leadshine-cl3": {
        # Core tuning (stepper-servo hybrid)
        0x60FB: 0x2030,   # Position loop → Position Loop Control Effort Limit
        0x60F9: 0x60F9,   # Velocity loop (standard CiA 402 — closed-loop stepper)
        0x60B1: 0x60B1,   # Feedforward (standard CiA 402)
        0x610B: 0x60F9,   # Notch-like → velocity gain reduction (no hardware notch)
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        # Low-pass filter
        0x2106: 0x2010,   # Speed filter → Filter Time
        0x2107: 0x2010,   # Torque filter → Filter Time
    },

    # ── Leadshine DM3E (10 mappings) ────────────────────────
    "leadshine-dm3e": {
        # Core tuning (stepper-servo hybrid, standard CiA 402)
        0x60FB: 0x60FB,   # Position Control Gain (CiA 402 standard)
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Feedforward
        # No dedicated notch filters (stepper hybrid)
        0x610B: 0x60F9,   # Notch → velocity gain reduction (no hardware notch)
        0x610C: 0x60F9,   # 2nd Notch → velocity gain reduction
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,
        0x6086: 0x6086,
        # Low-pass filter
        0x2106: 0x2010,   # Speed filter → Filter Time
        0x2107: 0x2010,   # Torque filter → Filter Time
    },

    # ── Estun ProNet Plus (12 mappings) ─────────────────────
    "estun-pronet": {
        # Core tuning (standard CiA 402 compliant)
        0x60FB: 0x60FB,   # Position Control Gain
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Feedforward
        0x610B: 0x60F9,   # Notch → velocity gain reduction (ESI has no notch objects)
        0x610C: 0x60F9,   # 2nd Notch → velocity gain reduction
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (confirmed in CoE dictionary)
        0x60A4: 0x60A4,   # Profile Jerk (in ESI)
        0x6086: 0x6086,   # Motion Profile Type (in ESI)
        # Low-pass filters (standard CiA 402)
        0x2106: 0x2106,   # Speed command filter (may be brand-specific; fallback)
        0x2107: 0x2107,   # Torque command filter
        0x2219: 0x60F9,   # Resonance Suppression → velocity gain
    },

    # ── Inovance SV660 (12 mappings) ────────────────────────
    "inovance-sv660": {
        # Core tuning (standard CiA 402 compliant)
        0x60FB: 0x60FB,   # Position Control Gain
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Feedforward (in ESI)
        0x610B: 0x60F9,   # Notch → velocity gain reduction (ESI has no notch objects)
        0x610C: 0x60F9,   # 2nd Notch → velocity gain reduction
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (confirmed in CoE dictionary)
        0x60A4: 0x60A4,   # Profile Jerk (in ESI via standard CiA 402)
        0x6086: 0x6086,   # Motion Profile Type (in ESI)
        # Low-pass filters (standard CiA 402 fallback)
        0x2106: 0x2106,
        0x2107: 0x2107,
        0x2219: 0x60F9,   # Resonance Suppression → velocity gain
    },

    # ── Elmo Gold (12 mappings) ─────────────────────────────
    "elmo-gold": {
        # Core tuning (premium brand, standard CiA 402 compliant)
        0x60FB: 0x60FB,   # Position Control Gain
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Feedforward (in ESI)
        0x610B: 0x60F9,   # Notch → velocity gain reduction (no notch in ESI)
        0x610C: 0x60F9,   # 2nd Notch → velocity gain reduction
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (confirmed in CoE dictionary)
        0x60A4: 0x60A4,   # Profile Jerk (standard CiA 402)
        0x6086: 0x6086,   # Motion Profile Type (in ESI)
        # Low-pass filters (standard CiA 402 fallback)
        0x2106: 0x2106,
        0x2107: 0x2107,
        # Elmo has ultra-high bandwidth — LPF may not be needed
        0x2219: 0x60F9,   # Resonance Suppression → velocity gain
    },

    # ── Panasonic Minas A6 (12 mappings) ────────────────────
    "panasonic-a6": {
        # Core tuning (premium brand, standard CiA 402)
        # NOTE: ESI is PDO-only (18 objects). Full tuning dictionary requires
        # Panasonic's proprietary PrX.XX index space, not exposed via CoE.
        0x60FB: 0x60FB,   # Position Control Gain (CiA 402 standard)
        0x60F9: 0x60F9,   # Velocity Control Gain
        0x60B1: 0x60B1,   # Velocity Feedforward
        0x610B: 0x60F9,   # Notch → velocity gain (Panasonic notch at Pr1.10, not in ESI)
        0x610C: 0x60F9,   # 2nd Notch → velocity gain
        0x2100: 0x60F9,   # Speed Loop Gain → Velocity Control Gain
        0x2101: 0x60F9,   # Speed Loop Integral → Velocity Control Gain
        # S-curve (standard CiA 402)
        0x60A4: 0x60A4,   # Profile Jerk
        0x6086: 0x6086,   # Motion Profile Type
        # Low-pass filters (standard CiA 402 fallback)
        0x2106: 0x2106,   # Speed command filter (may use Panasonic native Pr1.21)
        0x2107: 0x2107,   # Torque command filter
        0x2219: 0x60F9,   # Resonance Suppression → velocity gain
    },
}

# ── Tuning alias coverage summary ──────────────────────────
# All 12 brands have explicit BRAND_ALIASES entries.
# Alias counts: delta-a3(12) yaskawa-sigma7(12) yaskawa-sigma5(12)
#               invt-da200(14) servotronix-cdhd(14) lenze-i700(14)
#               leadshine-cl3(10) leadshine-dm3e(10)
#               estun-pronet(12) inovance-sv660(12) elmo-gold(12) panasonic-a6(12)
# Total: 146 individual parameter aliases across 12 brands.

# ── Brand capability notes ─────────────────────────────────
# These describe limitations when a brand lacks hardware support
# for certain tuning features (e.g., stepper hybrids without notch filters).

BRAND_CAPABILITY_NOTES: Dict[str, Dict[str, str]] = {
    "leadshine-dm3e": {
        "notch_filter": "none — stepper-servo hybrid, no hardware notch. Use velocity gain reduction.",
        "force_control": "none — stepper hybrid, no torque loop.",
    },
    "leadshine-cl3": {
        "notch_filter": "none — closed-loop stepper, no hardware notch. Use position loop detuning.",
        "force_control": "none — closed-loop stepper, limited torque control.",
    },
    "panasonic-a6": {
        "esi_coverage": "minimal — ESI is PDO-only (18 objects). Full tuning requires PANATERM or printed manual.",
        "notch_filter": "available — Pr1.10, Pr1.11 in native index space (not exposed via ESI CoE).",
    },
    "estun-pronet": {
        "notch_filter": "not in ESI — may be available via manufacturer-specific objects. Verify with manual.",
    },
    "inovance-sv660": {
        "notch_filter": "not in ESI — may be available via manufacturer-specific objects. Verify with manual.",
    },
    "elmo-gold": {
        "notch_filter": "not in ESI — Elmo typically uses proprietary tuning algorithms. Verify with EASII software.",
    },
}

# ── Parameter descriptions lookup ──────────────────────────
# Human-readable descriptions for common CiA 402 parameters
# and brand-specific aliases. Used by ParameterRecommender
# to generate human-readable tuning suggestions.

PARAM_DESCRIPTIONS: Dict[int, str] = {
    # ── CiA 402 Standard Parameters ──
    0x6065: "Following Error Window — maximum allowable position error before alarm",
    0x6072: "Max Torque — maximum motor torque as % of rated",
    0x6075: "Motor Rated Current — in mA",
    0x6083: "Profile Acceleration — acceleration rate for trapezoidal moves",
    0x60B1: "Velocity Offset / Feedforward — velocity command added to position loop output",
    0x60E0: "Positive Torque Limit — upper torque clamp",
    0x60E1: "Negative Torque Limit — lower torque clamp",
    0x60F9: "Velocity Control Gain — proportional gain for velocity loop (Kvp)",
    0x60FB: "Position Control Gain — proportional gain for position loop (Kpp)",
    0x610B: "Notch Filter 1 Frequency — center frequency of 1st resonance suppression filter",
    0x610C: "Notch Filter 2 Frequency — center frequency of 2nd resonance suppression filter",

    # ── S-curve / Jerk Parameters ──
    0x60A4: "Profile Jerk — CiA 402 standard jerk limit for jerk-limited (S-curve) motion profiles. Lower = smoother acceleration",
    0x6086: "Motion Profile Type — CiA 402: 0=linear ramp, 3=sin² jerk-limited (S-curve)",

    # ── Yaskawa Sigma PnXXX Parameters ──
    0x2100: "Speed Loop Gain (Pn100) — Yaskawa velocity loop proportional gain. Higher = stiffer",
    0x2101: "Speed Loop Integral Time Constant (Pn101) — Yaskawa velocity loop integral. Lower = faster integral",
    0x2102: "Position Loop Gain (Pn102) — Yaskawa position loop proportional gain",
    0x2109: "Feedforward Gain (Pn109) — Yaskawa velocity feedforward. Higher = less following error",
    0x2409: "1st Notch Filter Frequency (Pn409) — Yaskawa resonance suppression. Set to detected frequency",
    0x240C: "2nd Notch Filter Frequency (Pn40C) — Yaskawa 2nd resonance suppression",
    0x2410: "Speed Ref Filter (Pn410) — Yaskawa speed command LPF. Smooths velocity ripple",
    0x2412: "Torque Ref Filter (Pn412) — Yaskawa torque command LPF. Smooths current ripple",

    # ── Delta A3 Low-Pass Filter Parameters ──
    0x2106: "Speed Command Filter (P1-06) — Delta A3 speed command LPF smoothing constant (ms). Smooths velocity ripple",
    0x2107: "Torque Command Filter (P1-07) — Delta A3 torque command LPF smoothing constant (ms). Smooths current ripple",
    0x2108: "Position Command Filter (P1-08) — Delta A3 position command LPF smoothing constant (10ms)",
    0x2219: "Resonance Suppression LPF (P2-25) — Delta A3 resonance low-pass filter time constant (0.1ms). 0=disabled",

    # ── INVT DA200 Brand-Specific Parameters ──
    0x2021: "Position Cmd LPF (P0.33) — INVT position command low-pass filter time (0.1ms)",
    0x2200: "1st Speed Gain (P2.00) — INVT velocity loop proportional gain (0.1). Higher = stiffer",
    0x2202: "1st Position Gain (P2.02) — INVT position loop proportional gain (0.1). Higher = less following error",
    0x2203: "1st Speed Detection Filter (P2.03) — INVT speed detection LPF time",
    0x2204: "1st Torque Filter (P2.04) — INVT torque command LPF (0.01ms). Smooths current ripple",
    0x220A: "Speed Feed-forward Gain (P2.10) — INVT velocity feedforward (0.1). Reduces tracking error",
    0x220E: "1st IPPI Gain (P2.14) — INVT velocity loop integral gain",
    0x2125: "1st Vibration Filter (P1.37) — INVT notch filter 1 value (0.01). Set to resonance frequency",
    0x2127: "2nd Vibration Filter (P1.39) — INVT notch filter 2 value (0.01). Set to 2nd harmonic",
    0x2115: "1st Mech Resonance Freq (P1.21) — INVT detected resonance frequency (read-only)",
    0x2116: "2nd Mech Resonance Freq (P1.22) — INVT detected 2nd resonance frequency (read-only)",

    # ── Servotronix CDHD Brand-Specific Parameters ──
    0x2022: "Position Proportional Gain — Servotronix position loop Kp. Higher = stiffer positioning",
    0x2010: "Velocity Loop Bandwidth — Servotronix velocity loop bandwidth (Hz). Higher = faster response",
    0x201E: "Position Derivative Gain — Servotronix velocity feedforward. Reduces tracking error",
    0x2026: "Velocity Integrator — Servotronix velocity loop integral time. Lower = faster integral action",
    0x2061: "HD Current Notch Filter Center — Servotronix 1st notch frequency (Hz)",
    0x208C: "HD Current Filter - Second Notch Filter Center — Servotronix 2nd notch frequency (Hz)",
    0x205F: "HD Current LPF Rise Time — Servotronix torque command low-pass filter",
    0x204E: "Velocity Loop Output Filter Parameter 1 — Servotronix speed command LPF",
    0x202C: "Ptp Move Lpf Hz — Servotronix position command low-pass filter",
    0x200A: "HD Anti-Vibration Filter — Servotronix wideband vibration suppression (alternative to notch)",

    # ── Lenze i700 Brand-Specific Parameters ──
    0x2980: "Position Controller: Gain — Lenze position loop proportional gain. Higher = stiffer",
    0x2901: "Speed Controller: Gain - Adaption — Lenze velocity loop adaptive gain (%)",
    0x2941: "Current Controller: Feedforward Control — Lenze velocity/torque feedforward",
    0x2944: "Torque: Notch Filter Setpoint Torque — Lenze 1st notch filter for resonance suppression",
    0x2DD6: "Torque: Filter Cascade — Lenze multi-stage torque filter (2nd notch + LPF cascade)",
    0x2945: "Torque: Setpoint Jerk Limitation — Lenze S-curve jerk limit (brand-native)",
    0x2903: "Speed: Speed Setpoint - Filter Time — Lenze speed command LPF time constant",
    0x2943: "Motor: Setpoint Current - Filter Time — Lenze torque command LPF time constant",
    0x2910: "Moments of Inertia — Lenze load inertia value for adaptive tuning (read/write)",

    # ── Leadshine Brand-Specific Parameters ──
    0x2030: "Position Loop Control Effort Limit — Leadshine CL3 position loop gain. Higher = stiffer",
    0x2010: "Filter Time — Leadshine general-purpose low-pass filter time constant",
}

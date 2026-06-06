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
# Used when a brand has a non-standard index for a common function.

BRAND_ALIASES: Dict[str, Dict[int, int]] = {
    "yaskawa-sigma7": {
        0x60FB: 0x2102,   # Position loop gain → Pn102
        0x60B1: 0x2109,   # Velocity feedforward → Pn109
        0x610B: 0x2409,   # Notch filter 1 freq → Pn409
        0x610C: 0x240C,   # Notch filter 2 freq → Pn40C
        0x60F9: 0x2100,   # Velocity loop gain → Pn100
        0x2100: 0x2100,   # Speed loop gain (same)
        0x2102: 0x2102,   # Position loop gain (same)
    },
    "yaskawa-sigma5": {
        0x60FB: 0x2102,
        0x60B1: 0x2109,
        0x610B: 0x2409,
        0x610C: 0x240C,
        0x60F9: 0x2100,
    },
    "delta-a3": {
        0x60FB: 0x60FB,   # Standard CiA 402 — same
        0x60B1: 0x60B1,
        0x610B: 0x610B,   # Notch filter 1 (Delta A3 uses CiA 402 standard)
        0x610C: 0x610C,
        0x60F9: 0x60F9,
    },
    # For brands not listed, use CiA 402 standard indices directly
}

# ── Parameter descriptions lookup ──────────────────────────
# Human-readable descriptions for common CiA 402 parameters.

PARAM_DESCRIPTIONS: Dict[int, str] = {
    0x6065: "Following Error Window — maximum allowable position error before alarm",
    0x6072: "Max Torque — maximum motor torque as % of rated",
    0x6075: "Motor Rated Current — in mA",
    0x6083: "Profile Acceleration — acceleration rate for trapezoidal moves",
    0x60B1: "Velocity Offset / Feedforward — velocity command added to position loop output",
    0x60E0: "Positive Torque Limit — upper torque clamp",
    0x60E1: "Negative Torque Limit — lower torque clamp",
    0x60F9: "Velocity Control Gain — proportional gain for velocity loop",
    0x60FB: "Position Control Gain — proportional gain for position loop (Kp)",
    0x610B: "Notch Filter 1 Frequency — center frequency of 1st resonance suppression filter",
    0x610C: "Notch Filter 2 Frequency — center frequency of 2nd resonance suppression filter",
    0x2100: "Speed Loop Gain (Pn100) — Yaskawa velocity loop proportional gain",
    0x2101: "Speed Loop Integral Time Constant (Pn101) — Yaskawa velocity loop integral",
    0x2102: "Position Loop Gain (Pn102) — Yaskawa position loop proportional gain",
    0x2109: "Feedforward Gain (Pn109) — Yaskawa velocity feedforward",
    0x2409: "1st Notch Filter Frequency (Pn409) — Yaskawa resonance suppression",
    0x240C: "2nd Notch Filter Frequency (Pn40C) — Yaskawa 2nd resonance suppression",
}

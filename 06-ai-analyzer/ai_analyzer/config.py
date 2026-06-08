"""
Shared constants for the AI Analyzer module.

Thresholds are derived from Delta A3 servo specifications and validated
against the AI&ML Agent's Solution 02 (servo current anomaly) patterns.
"""

from typing import Dict, List, Tuple

# ── Channel index mapping (CiA 402 object dictionary → scope channel name) ──
CIA402_CHANNEL_MAP: Dict[int, str] = {
    0x6064: "Position",
    0x606C: "Velocity",
    0x6078: "Current",
    0x6077: "Torque",
    0x60F4: "Foll.Err",
    0x60FD: "DIO",
    0x6041: "Status",
    0x6061: "OpMode",
}

CHANNEL_NAME_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate([
        "Position", "Velocity", "Current", "Torque",
        "Foll.Err", "DIO", "Status", "OpMode",
    ])
}

# ── Current anomaly detection thresholds ──
# Derived from Delta A3 rated current = 100% on CiA 402 object 0x6075
# Reference: AI&ML Agent Solution 02 train_servo_regression.py ratio thresholds
CURRENT_ANOMALY = {
    "saturation_threshold": 200.0,      # % rated current — hardware limit
    "warning_threshold": 105.0,         # % rated — above rated continuous
    "mechanical_wear_threshold": 0.35,  # CUSUM accumulated z-score
    "sensor_fault_zscore": 5.0,         # single-sample z-score for sensor fault
    "streaming_window": 200,            # samples for online statistics
    "ensemble_weight_zscore": 0.35,     # weight for z-score detector
    "ensemble_weight_iqr": 0.30,        # weight for IQR detector
    "ensemble_weight_cusum": 0.35,      # weight for CUSUM detector
    "ensemble_vote_threshold": 0.55,    # weighted vote to trigger anomaly
}

# ── Tracking error detection thresholds ──
# Delta A3 default following error window (0x6065) = 1000000 pulses
# Reference: competitive-analysis.md §3 (PANATERM comparison)
TRACKING_ERROR = {
    "dynamic_threshold_sigma": 3.0,     # multiples of running std
    "absolute_max_pulses": 1000000,     # hardware following error limit
    "mechanical_bind_correlation": 0.7,  # current↑ + position↓ correlation
    "gain_deficiency_ratio": 1.8,       # error/velocity ratio threshold
    "window_samples": 500,              # correlation window size
}

# ── Mechanical resonance detection thresholds ──
MECHANICAL_RESONANCE = {
    "fft_window_size": 1024,            # samples for FFT (power of 2)
    "fft_stride": 256,                  # run FFT every N new samples
    "peak_noise_floor_ratio": 3.0,      # peak must exceed 3× noise floor
    "harmonic_ratio_tolerance": 0.05,   # 5% tolerance for harmonic matching
    "min_frequency_hz": 20.0,           # ignore sub-20Hz (below mechanical resonance)
    "max_frequency_hz": 2000.0,         # ignore above 2kHz (EMI, not mechanical)
    "min_harmonics": 1,                 # min peaks to report (1=isolated peak OK)
    "min_harmonics_for_harmonic": 3,    # harmonics needed for 'resonance_harmonic' label
    "strong_peak_snr": 10.0,           # isolated peak with SNR > this -> still reported
}

# ── Severity levels ──
SEVERITY_LEVELS: List[str] = ["info", "warning", "critical"]

ANOMALY_CATEGORIES = {
    "current_saturation": "Current saturation — reduce load or check mechanical bind",
    "current_wear": "Gradual current increase — possible mechanical wear",
    "current_sensor_fault": "Sudden current dropout — sensor or wiring fault",
    "tracking_mechanical_bind": "Following error + current correlation — mechanical bind",
    "tracking_gain_deficiency": "Following error + velocity ratio high — gain tuning needed",
    "tracking_absolute_limit": "Following error exceeded hardware limit — emergency stop risk",
    "resonance_detected": "Mechanical resonance peak detected — consider notch filter",
    "resonance_harmonic": "Harmonic resonance pattern — structural vibration mode",
    "current_ripple": "High-frequency current ripple — torque filter or carrier frequency adjustment needed",
    "velocity_ripple": "High-frequency velocity oscillation — jerk limiting or S-curve profile recommended",
}

# ── Suggestion templates (keyed by category) ──
SUGGESTION_TEMPLATES: Dict[str, str] = {
    "current_saturation": "Reduce acceleration (0x6083) or check for mechanical obstruction",
    "current_wear": "Inspect ballscrew/bearing wear. Review maintenance log.",
    "current_sensor_fault": "Check current sensor wiring and feedback cable shielding",
    "tracking_mechanical_bind": "Inspect guide rails. Increase following error window (0x6065).",
    "tracking_gain_deficiency": "Increase position loop gain (0x60FB) or velocity feedforward (0x60B1)",
    "tracking_absolute_limit": "EMERGENCY: Check mechanical limits. Verify position command range.",
    "resonance_detected": "Set notch filter frequency (0x610B) to detected peak. Reduce velocity loop gain.",
    "resonance_harmonic": "Structural resonance. Consider mechanical damping or multi-notch filter (0x610B-0x6113).",
    "current_ripple": "Enable torque command low-pass filter (brand-specific: Delta P1-07, Yaskawa Pn412). Increase carrier frequency if possible.",
    "velocity_ripple": "Reduce profile jerk (0x60A4). Consider switching to S-curve profile type (0x6086=3). Enable position command filter.",
}

# ── Consecutive detection → severity escalation ──
# (consecutive_count, threshold_multiplier) → severity_level
ESCALATION_RULES: List[Tuple[int, float, str]] = [
    (1,  1.0, "info"),       # first detection
    (3,  1.0, "warning"),    # 3 consecutive at normal threshold
    (1,  2.0, "warning"),    # single detection at 2× threshold
    (10, 1.0, "critical"),   # 10 consecutive — persistent fault
    (3,  2.0, "critical"),   # 3 consecutive at 2× threshold
]

# ── AI&ML Agent relative path ──
AIML_AGENT_RELATIVE_PATH = "../../AI&ML Agent/AI&ML_knowledge_Base/Claude Main"

# ── HITL (Human-in-the-Loop) classification ──────────────────
# Maps each anomaly category to its HITL classification.
#
#   safe:       Informational — no parameter change possible or needed.
#               Engineer sees the annotation; no authorization required.
#   actionable: AI can recommend specific parameter changes, but MUST
#               obtain engineer authorization before execution.
#   ambiguous:  AI detected a symptom but cannot pinpoint the root cause
#               from electrical signals alone. Requires engineer sensory
#               input (visual, auditory, tactile) to narrow the diagnosis.

HITL_CLASSIFICATION: Dict[str, str] = {
    # ── Safe (informational only) ──
    "current_sensor_fault": "safe",       # hardware issue — no parameter fix
    "system_overload": "safe",            # sizing issue — needs redesign

    # ── Actionable (AI can fix, needs auth) ──
    "resonance_detected": "actionable",   # set notch filter — needs auth
    "resonance_harmonic": "actionable",   # multi-notch config — needs auth
    "tracking_gain_deficiency": "actionable",  # increase gains — needs auth
    "tracking_absolute_limit": "actionable",   # emergency window widen — needs auth
    "current_saturation": "actionable",   # reduce torque/accel limits — needs auth

    # ── Ambiguous (needs engineer observation first) ──
    "current_wear": "ambiguous",          # CUSUM drift → coupling? ballscrew? bearing?
    "tracking_mechanical_bind": "ambiguous",  # error+current → guide? ballscrew? interference?

    # ── New: filter/jerk categories ──
    "current_ripple": "actionable",       # HF current ripple → LPF fix available
    "velocity_ripple": "actionable",      # HF velocity oscillation → jerk/S-curve fix available
}

# ── Operations that require explicit engineer authorization ──
# Any ParameterRecommendation with action in this set MUST go through HITL gate.
INVASIVE_ACTIONS = {"increase", "decrease", "set", "write"}

# Read-only actions that can be suggested without authorization.
READONLY_ACTIONS = {"check", "consider", "monitor"}

# ── Cross-Axis Analysis Configuration ──────────────────────────

CROSS_AXIS_CONFIG = {
    "bus_sag": {
        "window": 200,                  # sliding window samples for correlation
        "min_axes": 2,                  # minimum axes for sag detection
        "correlation_threshold": 0.7,   # Pearson-r above which axes are "moving together"
        "drop_pct": 0.30,               # 30% mean current drop from baseline
    },
    "contouring": {
        "axis_pairs": [("X", "Y")],     # axis pairs to monitor (add ("X","Z"), ("Y","Z"))
        "threshold_multiplier": 1.5,    # combined threshold = 1.5 × max individual 3σ
        "min_error_pulses": 10.0,       # noise gate: minimum error before reporting
    },
    "ring_health": {
        "window": 1000,                 # error history window (samples)
        "cascade_threshold": 10,        # consecutive errors to flag cascade
        "sporadic_threshold": 0.1,      # >10% slaves with intermittent errors → EMI warning
    },
    "mechanical_coupling": {
        "coupling_pairs": [("Y", "X")], # (source_vibration, target_position) pairs
        "position_bins": 8,             # position range partitions
        "peak_ratio": 3.0,              # magnitude ratio to flag coupling (3×)
        "window": 500,                  # FFT peak history window
    },
}

# ── Cross-axis anomaly categories ──

CROSS_AXIS_CATEGORIES = {
    "cross_bus_sag":                "Cross-axis current sag — possible PSU overload",
    "cross_contouring_error":       "Multi-axis trajectory contouring deviation",
    "cross_ring_cascade":           "EtherCAT frame error cascade across slaves",
    "cross_ring_emi":               "EtherCAT sporadic errors — possible EMI/RFI",
    "cross_mechanical_coupling":    "Cross-axis mechanical coupling via vibration",
}

# ── Cross-axis HITL classification ──

CROSS_AXIS_HITL_CLASSIFICATION = {
    "cross_bus_sag":                "ambiguous",  # PSU? recabling? staggered accel?
    "cross_contouring_error":       "ambiguous",  # trajectory? mechanical? servo tuning?
    "cross_ring_cascade":           "actionable", # replace cable/reseat connector
    "cross_ring_emi":               "ambiguous",  # shielding? grounding? routing?
    "cross_mechanical_coupling":    "ambiguous",  # alignment? rigidity? bolt torque?
}

# Merge cross-axis categories into main dictionaries
ANOMALY_CATEGORIES.update(CROSS_AXIS_CATEGORIES)
HITL_CLASSIFICATION.update(CROSS_AXIS_HITL_CLASSIFICATION)

# ── LLM Refiner Configuration ────────────────────────────────
LLM_REFINER_CONFIG = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "timeout_seconds": 30,
    "temperature": 0.3,  # low temp for diagnostic accuracy
}

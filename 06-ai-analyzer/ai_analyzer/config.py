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
    "min_harmonics": 2,                 # minimum harmonic peaks to confirm resonance
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

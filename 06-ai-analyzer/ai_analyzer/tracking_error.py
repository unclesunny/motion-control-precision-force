"""
Tracking Error Detector — following error analysis for servo tuning.

Detects three failure modes:
  1. Mechanical bind — current↑ + position↓ correlation (stuck axis)
  2. Gain deficiency — error/velocity ratio high (under-tuned position loop)
  3. Absolute limit — following error exceeds hardware window (0x6065)

Algorithm:
  - Dynamic threshold: 3σ of running following error
  - Correlation: Pearson r between following error and current/velocity
  - Ratio analysis: error magnitude / velocity magnitude

Reference: Delta A3 following error window (0x6065) defaults to 1000000 pulses.
           Diagnosis patterns from ASDA-Soft manual §7.3 (Following Error Alarms).
"""

from collections import deque
from typing import Deque, Dict, List

import numpy as np

try:
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .config import TRACKING_ERROR, CHANNEL_NAME_INDEX
except ImportError:
    from analyzer_base import AIAnnotation, AnalyzerBase
    from config import TRACKING_ERROR, CHANNEL_NAME_INDEX


class TrackingErrorDetector(AnalyzerBase):
    """Detects excessive following error and classifies root cause."""

    def __init__(self, name: str = "TrackingError", enabled: bool = True):
        super().__init__(name=name, enabled=enabled)
        cfg = TRACKING_ERROR
        self._sigma_threshold = cfg["dynamic_threshold_sigma"]
        self._absolute_max = cfg["absolute_max_pulses"]
        self._bind_correlation = cfg["mechanical_bind_correlation"]
        self._gain_ratio = cfg["gain_deficiency_ratio"]

        window = cfg["window_samples"]
        self._error_window: Deque[float] = deque(maxlen=window)
        self._current_window: Deque[float] = deque(maxlen=window)
        self._velocity_window: Deque[float] = deque(maxlen=window)
        self._consecutive_count = 0

    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        self._sample_count += 1

        # Locate channel indices
        try:
            err_idx = channel_names.index("Foll.Err")
        except ValueError:
            return []

        current_idx = channel_names.index("Current") if "Current" in channel_names else -1
        velocity_idx = channel_names.index("Velocity") if "Velocity" in channel_names else -1

        error_val = abs(values[err_idx]) if err_idx < len(values) else 0.0
        current_val = abs(values[current_idx]) if current_idx >= 0 and current_idx < len(values) else 0.0
        velocity_val = abs(values[velocity_idx]) if velocity_idx >= 0 and velocity_idx < len(values) else 0.0

        # Update sliding windows
        self._error_window.append(error_val)
        if current_idx >= 0:
            self._current_window.append(current_val)
        if velocity_idx >= 0:
            self._velocity_window.append(velocity_val)

        annotations: List[AIAnnotation] = []

        # ── Hard rule: absolute hardware limit (instant, no window needed) ──
        if error_val > self._absolute_max:
            self._consecutive_count += 1
            return [AIAnnotation(
                timestamp=0.0,
                channel="Foll.Err",
                category="tracking_absolute_limit",
                severity="critical",
                confidence=1.0,
                message=f"Following error {error_val:.0f} exceeds hardware limit {self._absolute_max:.0f} pulses",
                value=error_val,
                metadata={"limit": self._absolute_max},
            )]

        # Need minimum window for statistical analysis
        if len(self._error_window) < 30:
            return []

        err_mean = np.mean(self._error_window)
        err_std = np.std(self._error_window)
        dynamic_threshold = err_mean + self._sigma_threshold * err_std

        # ── Dynamic threshold check ──
        if error_val <= dynamic_threshold:
            self._consecutive_count = max(0, self._consecutive_count - 1)
            return []

        self._consecutive_count += 1

        # ── Root cause classification ──
        # Check for mechanical bind: current rises while velocity drops → stuck axis
        if len(self._current_window) >= 30 and len(self._velocity_window) >= 30:
            # Compute correlation between recent error and current/velocity
            err_arr = np.array(self._error_window)
            cur_arr = np.array(self._current_window)
            vel_arr = np.array(self._velocity_window)

            # Pearson correlation
            err_cur_corr = _pearson_r(err_arr, cur_arr) if np.std(cur_arr) > 1e-6 else 0.0
            err_vel_corr = _pearson_r(err_arr, vel_arr) if np.std(vel_arr) > 1e-6 else 0.0

            if err_cur_corr > self._bind_correlation:
                # High error + high current correlation → mechanical bind
                category = "tracking_mechanical_bind"
                message = (
                    f"Mechanical bind suspected: error-current correlation r={err_cur_corr:.2f}. "
                    f"Following error {error_val:.0f} > {dynamic_threshold:.0f} pulses (threshold)."
                )
                metadata = {"err_cur_corr": err_cur_corr, "err_vel_corr": err_vel_corr}
            elif velocity_val > 0 and (error_val / max(velocity_val, 1.0)) > self._gain_ratio:
                # High error/velocity ratio → gain deficiency
                ratio = error_val / max(velocity_val, 1.0)
                category = "tracking_gain_deficiency"
                message = (
                    f"Position loop gain appears low: error/velocity ratio {ratio:.1f} > {self._gain_ratio}. "
                    f"Consider increasing Kp (0x60FB)."
                )
                metadata = {"err_vel_ratio": ratio, "err_cur_corr": err_cur_corr}
            else:
                category = "tracking_gain_deficiency"
                message = (
                    f"Following error {error_val:.0f} exceeds dynamic threshold {dynamic_threshold:.0f} "
                    f"(μ={err_mean:.0f}, σ={err_std:.0f}). Verify position loop tuning."
                )
                metadata = {"err_cur_corr": err_cur_corr, "err_vel_corr": err_vel_corr}
        else:
            category = "tracking_gain_deficiency"
            message = f"Following error {error_val:.0f} exceeds threshold {dynamic_threshold:.0f} (μ={err_mean:.0f})"
            metadata = {}

        confidence = min(1.0, (error_val - dynamic_threshold) / max(dynamic_threshold, 1.0) + 0.3)

        annotations.append(AIAnnotation(
            timestamp=0.0,
            channel="Foll.Err",
            category=category,
            severity="info",
            confidence=confidence,
            message=message,
            value=error_val,
            metadata=metadata,
        ))

        return annotations

    def reset(self):
        super().reset()
        self._consecutive_count = 0
        self._error_window.clear()
        self._current_window.clear()
        self._velocity_window.clear()


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Pearson correlation coefficient between two arrays."""
    n = len(x)
    if n < 3:
        return 0.0
    xm, ym = np.mean(x), np.mean(y)
    xs, ys = x - xm, y - ym
    num = np.sum(xs * ys)
    den = np.sqrt(np.sum(xs ** 2) * np.sum(ys ** 2))
    if den < 1e-10:
        return 0.0
    return float(num / den)

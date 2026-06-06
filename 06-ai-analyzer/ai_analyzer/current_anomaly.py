"""
Current Anomaly Detector — ML-based servo current monitoring.

Detects three anomaly types using ensemble streaming detection:
  1. Current saturation — exceeds hardware rated limit
  2. Mechanical wear — gradual CUSUM drift over time
  3. Sensor fault — sudden dropout or spike (single-sample z-score)

Algorithm references (per CONSTITUTION.md Article 3):
  - AI&ML Agent Solution 02: linear regression + logistic threshold pattern
    (train_servo_regression.py: I_theory = w0*Speed + w1*Torque + w2*Runtime + Bias)
  - AI&ML Agent streaming_anomaly_detector.py: adaptive z-score + IQR + CUSUM ensemble
  - AI&ML Agent plc_feature_extraction.py: PLCCUSUM, PLCThreeSigma, PLCIQRCheck

Key design decision: ALL streaming statistics are computed inline (Welford algorithm)
rather than imported at runtime. The oscilloscope runs at 1 kHz and cross-module
import overhead per sample is unacceptable. The algorithm patterns are referenced
from AI&ML Agent; the implementation is local for performance.
"""

from collections import deque
from typing import Deque, Dict, List, Optional

import numpy as np

try:
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .config import CURRENT_ANOMALY, CHANNEL_NAME_INDEX
except ImportError:
    from analyzer_base import AIAnnotation, AnalyzerBase
    from config import CURRENT_ANOMALY, CHANNEL_NAME_INDEX


class OnlineStats:
    """Welford's online algorithm for streaming mean and variance.

    O(1) per update, numerically stable. Used by all three sub-detectors.
    Reference: B. P. Welford (1962), "Note on a Method for Calculating
    Corrected Sums of Squares and Products"
    """

    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0  # sum of squared differences from current mean

    def update(self, value: float):
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        return self.m2 / max(self.count - 1, 1)

    @property
    def std(self) -> float:
        return np.sqrt(self.variance)

    def zscore(self, value: float) -> float:
        """Z-score of value relative to current distribution."""
        if self.std < 1e-10:
            return 0.0
        return (value - self.mean) / self.std

    def reset(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0


class ZScoreDetector:
    """Adaptive z-score detector with online statistics."""

    def __init__(self, threshold: float = 3.0, window: int = 200):
        self.threshold = threshold
        self.stats = OnlineStats()
        self._window: Deque[float] = deque(maxlen=window)

    def score(self, value: float) -> float:
        self._window.append(value)
        self.stats.update(value)
        if self.stats.count < 20:
            return 0.0
        return abs(self.stats.zscore(value))

    def is_anomaly(self, value: float) -> float:
        """Returns anomaly score 0.0-1.0."""
        z = self.score(value)
        if z >= self.threshold:
            return min(1.0, (z - self.threshold) / (self.threshold * 2) + 0.5)
        return 0.0

    def reset(self):
        self.stats.reset()
        self._window.clear()


class IQRDetector:
    """Inter-quartile range outlier detector on streaming window."""

    def __init__(self, window: int = 200, multiplier: float = 1.5):
        self._window: Deque[float] = deque(maxlen=window)
        self.multiplier = multiplier

    def score(self, value: float) -> float:
        self._window.append(value)
        if len(self._window) < 30:
            return 0.0
        arr = np.array(self._window)
        q1, q3 = np.percentile(arr, [25, 75])
        iqr = q3 - q1
        if iqr < 1e-10:
            return 0.0
        lower, upper = q1 - self.multiplier * iqr, q3 + self.multiplier * iqr
        if value < lower:
            return min(1.0, (lower - value) / iqr)
        elif value > upper:
            return min(1.0, (value - upper) / iqr)
        return 0.0

    def reset(self):
        self._window.clear()


class CUSUMDetector:
    """Cumulative Sum detector for gradual drift detection.

    Detects sustained positive shift from baseline mean.
    Reference: Page (1954), "Continuous Inspection Schemes"
    """

    def __init__(self, window: int = 200, drift_sensitivity: float = 0.5,
                 decision_interval: float = 5.0):
        self._window: Deque[float] = deque(maxlen=window)
        self.drift_sensitivity = drift_sensitivity  # k in CUSUM literature
        self.decision_interval = decision_interval   # h in CUSUM literature
        self._cplus = 0.0   # upper CUSUM
        self._cminus = 0.0  # lower CUSUM
        self._baseline_mean = 0.0

    def score(self, value: float) -> float:
        self._window.append(value)
        if len(self._window) < 30:
            return 0.0

        self._baseline_mean = np.mean(self._window)
        std = np.std(self._window)
        if std < 1e-10:
            return 0.0

        normalized = (value - self._baseline_mean) / std
        self._cplus = max(0, self._cplus + normalized - self.drift_sensitivity)
        self._cminus = max(0, self._cminus - normalized - self.drift_sensitivity)

        if self._cplus > self.decision_interval:
            return min(1.0, self._cplus / (self.decision_interval * 2))
        if self._cminus > self.decision_interval:
            return min(1.0, self._cminus / (self.decision_interval * 2))
        return 0.0

    def reset(self):
        self._window.clear()
        self._cplus = 0.0
        self._cminus = 0.0
        self._baseline_mean = 0.0


class CurrentAnomalyDetector(AnalyzerBase):
    """Ensemble detector for servo motor current anomalies.

    Combines three streaming detection methods with weighted voting:
      - Z-Score:    35% weight — catches sudden spikes/dropouts
      - IQR:        30% weight — robust to non-normal distributions
      - CUSUM:      35% weight — detects gradual mechanical wear drift

    The ensemble vote threshold (0.55) means at least two methods must
    agree, or one method with very high confidence.
    """

    def __init__(self, name: str = "CurrentAnomaly", enabled: bool = True):
        super().__init__(name=name, enabled=enabled)
        cfg = CURRENT_ANOMALY
        self._saturation_threshold = cfg["saturation_threshold"]
        self._warning_threshold = cfg["warning_threshold"]
        self._sensor_fault_zscore = cfg["sensor_fault_zscore"]
        self._ensemble_weights = {
            "zscore": cfg["ensemble_weight_zscore"],
            "iqr": cfg["ensemble_weight_iqr"],
            "cusum": cfg["ensemble_weight_cusum"],
        }
        self._vote_threshold = cfg["ensemble_vote_threshold"]

        window = cfg["streaming_window"]
        self._zscore_detector = ZScoreDetector(threshold=3.0, window=window)
        self._iqr_detector = IQRDetector(window=window, multiplier=1.5)
        self._cusum_detector = CUSUMDetector(
            window=window,
            drift_sensitivity=cfg["mechanical_wear_threshold"],
            decision_interval=5.0,
        )

        # Track consecutive anomaly count for severity escalation
        self._consecutive_count = 0
        self._current_channel_index = CHANNEL_NAME_INDEX.get("Current", 2)

    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        self._sample_count += 1

        # Find the current channel
        try:
            ci = channel_names.index("Current")
        except ValueError:
            return []

        current_val = abs(values[ci]) if ci < len(values) else 0.0
        if current_val == 0.0 and self._sample_count > 100:
            return []  # motor stopped

        annotations: List[AIAnnotation] = []

        # ── Hard rule: absolute saturation (instant detection) ──
        if current_val > self._saturation_threshold:
            self._consecutive_count += 1
            annotations.append(AIAnnotation(
                timestamp=0.0,  # filled by pipeline
                channel="Current",
                category="current_saturation",
                severity="critical",
                confidence=1.0,
                message=f"Current {current_val:.0f}% exceeds saturation limit {self._saturation_threshold:.0f}%",
                value=current_val,
            ))
            return annotations  # saturation overrides ensemble

        # ── Hard rule: sensor fault (extreme single-sample z-score) ──
        self._zscore_detector.score(current_val)
        z = self._zscore_detector.stats.zscore(current_val)
        if abs(z) > self._sensor_fault_zscore:
            self._consecutive_count += 1
            annotations.append(AIAnnotation(
                timestamp=0.0,
                channel="Current",
                category="current_sensor_fault",
                severity="warning",
                confidence=min(1.0, abs(z) / (self._sensor_fault_zscore * 2)),
                message=f"Current sensor anomaly: z={z:.1f}, value={current_val:.1f}%",
                value=current_val,
                metadata={"zscore": z},
            ))
            return annotations

        # ── Ensemble detection ──
        votes = {
            "zscore": self._zscore_detector.is_anomaly(current_val),
            "iqr": self._iqr_detector.score(current_val),
            "cusum": self._cusum_detector.score(current_val),
        }

        weighted_score = sum(
            votes[m] * self._ensemble_weights[m] for m in votes
        )

        if weighted_score >= self._vote_threshold:
            self._consecutive_count += 1
            # Determine dominant detector for message
            dominant = max(votes, key=votes.get)

            if dominant == "cusum" and self._consecutive_count >= 5:
                category = "current_wear"
                message = f"Gradual current drift detected ({self._consecutive_count} samples). "
                message += f"Mean: {self._cusum_detector._baseline_mean:.1f}%, "
                message += f"Current: {current_val:.1f}%"
            elif current_val > self._warning_threshold:
                category = "current_saturation"
                message = f"Current {current_val:.0f}% exceeds rated continuous {self._warning_threshold:.0f}%"
            else:
                category = "current_wear"
                message = f"Current anomaly ensemble score: {weighted_score:.2f} (dominant: {dominant})"

            annotations.append(AIAnnotation(
                timestamp=0.0,
                channel="Current",
                category=category,
                severity="info",  # escalated by AIAnnotator
                confidence=min(1.0, weighted_score),
                message=message,
                value=current_val,
                metadata={"votes": votes, "dominant": dominant, "consecutive": self._consecutive_count},
            ))
        else:
            self._consecutive_count = max(0, self._consecutive_count - 1)

        return annotations

    def reset(self):
        super().reset()
        self._consecutive_count = 0
        self._zscore_detector.reset()
        self._iqr_detector.reset()
        self._cusum_detector.reset()

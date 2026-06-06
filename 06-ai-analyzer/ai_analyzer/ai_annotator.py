"""
AI Annotator — confidence calibration and severity escalation.

Post-processes raw detector outputs:
  1. Confidence calibration: raw scores → calibrated 0-1 confidence
  2. Severity escalation: consecutive detections escalate info→warning→critical
  3. Suggestion generation: maps anomaly category → actionable recommendation

Separated from the pipeline to allow independent testing of
calibration and escalation logic.
"""

from typing import Dict, List

try:
    from .analyzer_base import AIAnnotation
    from .config import ESCALATION_RULES, SEVERITY_LEVELS, SUGGESTION_TEMPLATES
except ImportError:
    from analyzer_base import AIAnnotation
    from config import ESCALATION_RULES, SEVERITY_LEVELS, SUGGESTION_TEMPLATES


class AIAnnotator:
    """Calibrates confidence scores and escalates severity for AI annotations."""

    def __init__(self):
        # Track consecutive detections per (channel, category) for escalation
        self._consecutive: Dict[str, int] = {}
        # Track last severity per key
        self._last_severity: Dict[str, str] = {}

    def calibrate(self, annotations: List[AIAnnotation]) -> List[AIAnnotation]:
        """Apply confidence calibration and severity escalation.

        Args:
            annotations: Raw annotations from detectors (confidence may be
                        uncalibrated, severity defaults to "info").

        Returns:
            Calibrated annotations with adjusted severity and suggestions.
        """
        calibrated = []
        for ann in annotations:
            key = f"{ann.channel}:{ann.category}"

            # Update consecutive count
            self._consecutive[key] = self._consecutive.get(key, 0) + 1
            consecutive = self._consecutive[key]

            # ── Confidence calibration ──
            # Sigmoid-like calibration: raw score passes through logistic
            # to produce well-distributed confidence values
            raw = ann.confidence
            calibrated_conf = self._calibrate_confidence(raw)

            # ── Severity escalation ──
            severity = self._escalate(consecutive, ann.value, ann.metadata)

            # ── Suggestion generation ──
            suggestion = SUGGESTION_TEMPLATES.get(
                ann.category,
                "Review relevant parameters and check mechanical condition."
            )

            ann.confidence = calibrated_conf
            ann.severity = severity
            ann.suggestion = suggestion
            calibrated.append(ann)

        # Decay non-triggered keys
        for key in list(self._consecutive.keys()):
            if not any(f"{ann.channel}:{ann.category}" == key for ann in annotations):
                self._consecutive[key] = max(0, self._consecutive[key] - 1)
                if self._consecutive[key] == 0:
                    del self._consecutive[key]

        return calibrated

    @staticmethod
    def _calibrate_confidence(raw: float) -> float:
        """Calibrate raw detector score to well-distributed confidence [0, 1].

        Uses a logistic sigmoid centered at 0.5 with steepness 8.
        This maps:
          - raw 0.00 → ~0.02 (almost certainly nothing)
          - raw 0.25 → ~0.12
          - raw 0.50 → ~0.50
          - raw 0.75 → ~0.88
          - raw 1.00 → ~0.98
        """
        import numpy as np
        # Clamp raw to valid range
        raw = max(0.0, min(1.0, raw))
        # Logistic calibration
        calibrated = 1.0 / (1.0 + np.exp(-8.0 * (raw - 0.5)))
        return float(calibrated)

    def _escalate(
        self, consecutive: int, value: float, metadata: dict
    ) -> str:
        """Determine severity based on consecutive count and threshold multiplier.

        All matching rules are evaluated; the highest severity wins.
        """
        # Check for threshold multiplier from metadata
        threshold_mult = metadata.get("threshold_multiplier", 1.0)

        best_severity = "info"
        sev_order = {"info": 0, "warning": 1, "critical": 2}

        for min_count, min_mult, severity in ESCALATION_RULES:
            if consecutive >= min_count and threshold_mult >= min_mult:
                if sev_order.get(severity, 0) > sev_order.get(best_severity, 0):
                    best_severity = severity
        return best_severity

    def reset(self):
        """Reset escalation state."""
        self._consecutive.clear()
        self._last_severity.clear()

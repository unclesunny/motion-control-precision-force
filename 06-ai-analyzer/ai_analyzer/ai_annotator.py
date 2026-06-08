"""
AI Annotator — Free shell.

Pro license required for Sigmoid confidence calibration, severity escalation,
and annotation deduplication.
"""


class AIAnnotator:
    """Annotation post-processor (Pro license required)."""

    def __init__(self):
        pass

    def annotate(self, raw_events: list) -> list:
        """Returns events unchanged — Pro license required for calibration."""
        return raw_events

    def calibrate_confidence(self, confidence: float) -> float:
        """Returns input unchanged."""
        return confidence

    def escalate_severity(self, events: list) -> list:
        """Returns events unchanged."""
        return events

"""
Current Anomaly Detector — Free shell.

Pro license required for the full z-score + IQR + CUSUM ensemble detector.
This stub returns empty results (no anomalies detected).
"""

try:
    from .analyzer_base import AnalyzerBase, AIAnnotation
except ImportError:
    from analyzer_base import AnalyzerBase, AIAnnotation


class CurrentAnomalyDetector(AnalyzerBase):
    """Current anomaly detection (Pro license required for full ML ensemble)."""

    def __init__(self, sample_rate_hz: float = 1000.0):
        super().__init__(name="CurrentAnomaly", enabled=True)

    def analyze(self, values, channel_names, buffer_stats):
        """Return empty — Pro license required for z-score+IQR+CUSUM detection."""
        return []

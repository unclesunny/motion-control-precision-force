"""
Tracking Error Detector — Free shell.

Pro license required for the full Pearson correlation + dynamic 3σ detector.
This stub returns empty results (no tracking anomalies detected).
"""

try:
    from .analyzer_base import AnalyzerBase, AIAnnotation
except ImportError:
    from analyzer_base import AnalyzerBase, AIAnnotation


class TrackingErrorDetector(AnalyzerBase):
    """Tracking error detection (Pro license required for full analysis)."""

    def __init__(self, sample_rate_hz: float = 1000.0):
        super().__init__(name="TrackingError", enabled=True)

    def analyze(self, values, channel_names, buffer_stats):
        """Return empty — Pro license required for Pearson+3σ detection."""
        return []

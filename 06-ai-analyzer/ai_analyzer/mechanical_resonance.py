"""
Mechanical Resonance Detector — Free shell.

Pro license required for the full 1024-pt Hann FFT + harmonic matching detector.
This stub returns empty results (no resonance peaks detected).
"""

try:
    from .analyzer_base import AnalyzerBase, AIAnnotation
except ImportError:
    from analyzer_base import AnalyzerBase, AIAnnotation


class MechanicalResonanceDetector(AnalyzerBase):
    """Mechanical resonance detection (Pro license required for FFT analysis)."""

    def __init__(self, sample_rate_hz: float = 1000.0):
        super().__init__(name="MechanicalResonance", enabled=True)

    def analyze(self, values, channel_names, buffer_stats):
        """Return empty — Pro license required for FFT+harmonic detection."""
        return []

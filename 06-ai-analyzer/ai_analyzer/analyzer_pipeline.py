"""
AI Analyzer Pipeline — Free Edition (MIT).

This is the Community Edition pipeline. It provides basic statistics and
gracefully upgrades to Pro AI detectors when a commercial license is present.

Without pro/: basic stats only (min/max/mean/std/rms per channel).
With pro/:    full 3-detector AI pipeline + parameter recommendations.
"""

import time
from typing import Dict, List, Optional

from .ai_annotator import AIAnnotator
from .analyzer_base import AIAnnotation, AnalyzerBase

# ── Try to load Pro detectors ──────────────────────────────
_PRO_AVAILABLE = False
_CurrentAnomalyDetector = None
_TrackingErrorDetector = None
_MechanicalResonanceDetector = None
_ParameterRecommender = None

try:
    import sys as _sys
    from pathlib import Path as _Path
    _pro_path = _Path(__file__).resolve().parent.parent.parent / "pro"
    if str(_pro_path) not in _sys.path:
        _sys.path.insert(0, str(_pro_path))
    from ai_analyzer.current_anomaly import CurrentAnomalyDetector as _CD
    from ai_analyzer.tracking_error import TrackingErrorDetector as _TD
    from ai_analyzer.mechanical_resonance import MechanicalResonanceDetector as _MD
    from ai_analyzer.parameter_recommender import ParameterRecommender as _PR
    _CurrentAnomalyDetector = _CD
    _TrackingErrorDetector = _TD
    _MechanicalResonanceDetector = _MD
    _ParameterRecommender = _PR
    _PRO_AVAILABLE = True
except ImportError:
    pass


class AIAnalyzerPipeline:
    """Orchestrates AI detectors with graceful pro/free degradation.

    Free mode: basic channel statistics (mean, min, max, std, rms).
    Pro mode:  full 3-detector AI pipeline + parameter recommendations.
    """

    def __init__(
        self,
        analyzers: Optional[List[AnalyzerBase]] = None,
        sample_rate_hz: float = 1000.0,
        brand: Optional[str] = None,
    ):
        self._pro_available = _PRO_AVAILABLE
        self._analyzers = analyzers if analyzers is not None else self._init_analyzers(sample_rate_hz)
        self._annotator = AIAnnotator()
        self._recommender = None
        if _PRO_AVAILABLE and _ParameterRecommender:
            self._recommender = _ParameterRecommender(brand=brand)
        self._events: List[AIAnnotation] = []
        self._sample_count = 0
        self._sample_rate = sample_rate_hz

    def _init_analyzers(self, sample_rate_hz: float) -> List[AnalyzerBase]:
        if _PRO_AVAILABLE:
            return [
                _CurrentAnomalyDetector(),
                _TrackingErrorDetector(),
                _MechanicalResonanceDetector(sample_rate_hz=sample_rate_hz),
            ]
        return []

    @property
    def pro_available(self) -> bool:
        return self._pro_available

    @property
    def analyzers(self) -> List[AnalyzerBase]:
        return self._analyzers

    @property
    def recommender(self):
        return self._recommender

    @property
    def recent_events(self) -> List[AIAnnotation]:
        return list(reversed(self._events[-50:]))

    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        """Run analysis. Free: basic stats. Pro: full AI detection."""
        self._sample_count += 1
        now = time.perf_counter()
        raw_annotations: List[AIAnnotation] = []

        if self._pro_available:
            for analyzer in self._analyzers:
                if not analyzer.enabled:
                    continue
                try:
                    results = analyzer.analyze(values, channel_names, buffer_stats)
                    for ann in results:
                        ann.timestamp = now
                    raw_annotations.extend(results)
                except Exception:
                    continue

        calibrated = self._annotator.calibrate(raw_annotations)

        self._events.extend(calibrated)
        if len(self._events) > 500:
            self._events = self._events[-250:]

        return calibrated

    def batch_analyze(self, data, timestamps, channel_names):
        import numpy as np
        all_annotations = []
        n_samples = data.shape[1]
        buffer_stats = {}
        for i, name in enumerate(channel_names):
            if i < data.shape[0]:
                ch_data = data[i]
                buffer_stats[name] = {
                    "min": float(np.min(ch_data)),
                    "max": float(np.max(ch_data)),
                    "mean": float(np.mean(ch_data)),
                    "std": float(np.std(ch_data)),
                    "rms": float(np.sqrt(np.mean(ch_data ** 2))),
                    "peak_to_peak": float(np.max(ch_data) - np.min(ch_data)),
                }
        stride = max(1, n_samples // 6000)
        for t in range(0, n_samples, stride):
            values = data[:, t].tolist()
            anns = self.analyze(values, channel_names, buffer_stats)
            all_annotations.extend(anns)
        return all_annotations

    def reset(self):
        self._sample_count = 0
        self._events.clear()
        self._annotator.reset()
        for analyzer in self._analyzers:
            analyzer.reset()

    def disable_analyzer(self, name: str):
        for a in self._analyzers:
            if a.name == name:
                a.enabled = False

    def enable_analyzer(self, name: str):
        for a in self._analyzers:
            if a.name == name:
                a.enabled = True

    def get_analyzer(self, name: str) -> Optional[AnalyzerBase]:
        for a in self._analyzers:
            if a.name == name:
                return a
        return None

    def recommend(self, annotations=None):
        if not self._pro_available or self._recommender is None:
            return []
        source = annotations if annotations is not None else self._events[-20:]
        return self._recommender.recommend(source)

    def format_recommendations(self) -> str:
        if not self._pro_available or self._recommender is None:
            return "Pro license required for AI parameter recommendations."
        return self._recommender.format(self.recommend())

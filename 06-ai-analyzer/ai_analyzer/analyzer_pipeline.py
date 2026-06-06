"""
AI Analyzer Pipeline — orchestrates all detectors and post-processing.

The main entry point for scope_engine.py integration. Replaces the
hardcoded ANOMALY_RULES list with a pluggable pipeline of ML-based detectors.

Usage:
    from ai_analyzer import AIAnalyzerPipeline

    pipeline = AIAnalyzerPipeline()
    annotations = pipeline.analyze(values, channel_names, buffer_stats)

Architecture:
    values → [CurrentAnomalyDetector] ─┐
            [TrackingErrorDetector]   ─┤→ AIAnnotator → AIAnnotation[]
            [MechanicalResonanceDetector]┘
"""

import time
from typing import Dict, List, Optional

try:
    from .ai_annotator import AIAnnotator
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .analyzer_bridge import AIAnalyzerBridge
    from .current_anomaly import CurrentAnomalyDetector
    from .mechanical_resonance import MechanicalResonanceDetector
    from .parameter_recommender import ParameterRecommender, ParameterRecommendation
    from .tracking_error import TrackingErrorDetector
except ImportError:
    from ai_annotator import AIAnnotator
    from analyzer_base import AIAnnotation, AnalyzerBase
    from analyzer_bridge import AIAnalyzerBridge
    from current_anomaly import CurrentAnomalyDetector
    from mechanical_resonance import MechanicalResonanceDetector
    from parameter_recommender import ParameterRecommender, ParameterRecommendation
    from tracking_error import TrackingErrorDetector


class AIAnalyzerPipeline:
    """Orchestrates all AI detectors with post-processing.

    Parameters:
        analyzers: Custom list of AnalyzerBase instances. If None, uses
                  default set: [CurrentAnomaly, TrackingError, MechanicalResonance].
        bridge: AIAnalyzerBridge instance for AI&ML Agent integration.
               If None, auto-creates with default paths.
        sample_rate_hz: Sample rate for FFT-based detectors (default 1000).
    """

    def __init__(
        self,
        analyzers: Optional[List[AnalyzerBase]] = None,
        bridge: Optional[AIAnalyzerBridge] = None,
        sample_rate_hz: float = 1000.0,
        brand: Optional[str] = None,
    ):
        self._analyzers = analyzers if analyzers is not None else self._default_analyzers(sample_rate_hz)
        self._annotator = AIAnnotator()
        self._bridge = bridge if bridge is not None else AIAnalyzerBridge()
        self._recommender = ParameterRecommender(brand=brand)
        self._events: List[AIAnnotation] = []
        self._sample_count = 0
        self._sample_rate = sample_rate_hz

    @staticmethod
    def _default_analyzers(sample_rate_hz: float = 1000.0) -> List[AnalyzerBase]:
        """Create the default set of three detectors."""
        return [
            CurrentAnomalyDetector(),
            TrackingErrorDetector(),
            MechanicalResonanceDetector(sample_rate_hz=sample_rate_hz),
        ]

    @property
    def analyzers(self) -> List[AnalyzerBase]:
        return self._analyzers

    @property
    def bridge(self) -> AIAnalyzerBridge:
        return self._bridge

    @property
    def recommender(self) -> ParameterRecommender:
        return self._recommender

    @property
    def recent_events(self) -> List[AIAnnotation]:
        """Get recent AI annotations (last 50 events, newest first)."""
        return list(reversed(self._events[-50:]))

    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        """Run all enabled analyzers on one sample frame.

        Called by ScopeEngine._run_ai() every N samples (default N=10).

        Args:
            values: Current channel values in channel_names order.
            channel_names: Active channel names.
            buffer_stats: Per-channel statistics from RingBuffer.

        Returns:
            List of AIAnnotation events for this sample frame.
        """
        self._sample_count += 1
        now = time.perf_counter()

        raw_annotations: List[AIAnnotation] = []

        for analyzer in self._analyzers:
            if not analyzer.enabled:
                continue
            try:
                results = analyzer.analyze(values, channel_names, buffer_stats)
                # Stamp timestamp (detectors set to 0.0 — filled here)
                for ann in results:
                    ann.timestamp = now
                raw_annotations.extend(results)
            except Exception:
                # Single detector failure should not block others
                continue

        # ── Post-processing: confidence calibration + severity escalation ──
        calibrated = self._annotator.calibrate(raw_annotations)

        # ── Store events ──
        self._events.extend(calibrated)
        if len(self._events) > 500:
            self._events = self._events[-250:]

        return calibrated

    def batch_analyze(
        self,
        data: "np.ndarray",        # shape (n_channels, n_samples)
        timestamps: "np.ndarray",  # shape (n_samples,)
        channel_names: List[str],
    ) -> List[AIAnnotation]:
        """Offline batch analysis of captured buffer data.

        Runs all analyzers on every sample in the buffer. Useful for
        post-capture diagnostics and report generation.

        Returns aggregated, deduplicated annotations.
        """
        import numpy as np

        all_annotations: List[AIAnnotation] = []
        n_samples = data.shape[1]

        # Compute buffer-level stats once (used by all analyzers)
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

        # Analyze every Nth sample (stride=10 for efficiency on large buffers)
        stride = max(1, n_samples // 6000)  # target ~6000 analyses max
        for t in range(0, n_samples, stride):
            values = data[:, t].tolist()
            annotations = self.analyze(values, channel_names, buffer_stats)
            all_annotations.extend(annotations)

        # Deduplicate: merge annotations with same category+channel within 1 second
        deduped = self._deduplicate(all_annotations)
        return deduped

    def _deduplicate(
        self, annotations: List[AIAnnotation], time_window: float = 1.0
    ) -> List[AIAnnotation]:
        """Merge duplicate annotations within a time window."""
        if not annotations:
            return []

        annotations.sort(key=lambda a: a.timestamp)
        merged: List[AIAnnotation] = []
        current_group: List[AIAnnotation] = []

        for ann in annotations:
            key = f"{ann.channel}:{ann.category}"
            if current_group:
                first = current_group[0]
                first_key = f"{first.channel}:{first.category}"
                if key == first_key and (ann.timestamp - first.timestamp) < time_window:
                    current_group.append(ann)
                else:
                    merged.append(self._merge_group(current_group))
                    current_group = [ann]
            else:
                current_group = [ann]

        if current_group:
            merged.append(self._merge_group(current_group))

        return merged

    @staticmethod
    def _merge_group(group: List[AIAnnotation]) -> AIAnnotation:
        """Merge a group of similar annotations: keep highest severity+confidence."""
        best = max(group, key=lambda a: (
            {"critical": 3, "warning": 2, "info": 1}.get(a.severity, 0),
            a.confidence,
        ))
        best.metadata["merged_count"] = len(group)
        return best

    def reset(self):
        """Reset all analyzers and internal state."""
        self._sample_count = 0
        self._events.clear()
        self._annotator.reset()
        for analyzer in self._analyzers:
            analyzer.reset()

    def disable_analyzer(self, name: str):
        """Disable a specific analyzer by name."""
        for analyzer in self._analyzers:
            if analyzer.name == name:
                analyzer.enabled = False
                return

    def enable_analyzer(self, name: str):
        """Enable a specific analyzer by name."""
        for analyzer in self._analyzers:
            if analyzer.name == name:
                analyzer.enabled = True
                return

    def get_analyzer(self, name: str) -> Optional[AnalyzerBase]:
        """Get an analyzer by name for direct inspection."""
        for analyzer in self._analyzers:
            if analyzer.name == name:
                return analyzer
        return None

    def recommend(self, annotations: Optional[List[AIAnnotation]] = None
                  ) -> List[ParameterRecommendation]:
        """Generate tuning parameter recommendations from recent annotations.

        Args:
            annotations: Optional list of annotations. If None, uses recent events.

        Returns:
            List of ParameterRecommendation, sorted by priority.
        """
        source = annotations if annotations is not None else self._events[-20:]
        return self._recommender.recommend(source)

    def format_recommendations(self) -> str:
        """Get formatted tuning report string."""
        params = self.recommend()
        return self._recommender.format(params)

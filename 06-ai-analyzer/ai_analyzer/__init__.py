"""
AI Analyzer — Machine Learning-based servo signal analysis for the oscilloscope.

Public API:
    AIAnalyzerPipeline  — main orchestrator (replaces hardcoded ANOMALY_RULES)
    AIAnalyzerBridge    — lazy bridge to AI&ML Agent sibling project
    AIAnnotation        — dataclass for anomaly events
    AnalyzerBase        — ABC for custom analyzer development

Individual detectors:
    CurrentAnomalyDetector      — current saturation, wear, sensor fault
    TrackingErrorDetector       — following error root cause classification
    MechanicalResonanceDetector — FFT-based resonance peak detection

Quickstart:
    from ai_analyzer import AIAnalyzerPipeline

    pipeline = AIAnalyzerPipeline()
    annotations = pipeline.analyze(values, channel_names, buffer_stats)

    for ann in annotations:
        print(f"{ann.severity}: {ann.message} → {ann.suggestion}")
"""

try:
    from .ai_annotator import AIAnnotator
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .analyzer_bridge import AIAnalyzerBridge
    from .analyzer_pipeline import AIAnalyzerPipeline
    from .current_anomaly import CurrentAnomalyDetector
    from .mechanical_resonance import MechanicalResonanceDetector
    from .parameter_recommender import ParameterRecommender, ParameterRecommendation
    from .tracking_error import TrackingErrorDetector
except ImportError:
    from ai_annotator import AIAnnotator
    from analyzer_base import AIAnnotation, AnalyzerBase
    from analyzer_bridge import AIAnalyzerBridge
    from analyzer_pipeline import AIAnalyzerPipeline
    from current_anomaly import CurrentAnomalyDetector
    from mechanical_resonance import MechanicalResonanceDetector
    from parameter_recommender import ParameterRecommender, ParameterRecommendation
    from tracking_error import TrackingErrorDetector

__all__ = [
    "AIAnalyzerPipeline",
    "AIAnalyzerBridge",
    "AIAnnotation",
    "AnalyzerBase",
    "CurrentAnomalyDetector",
    "TrackingErrorDetector",
    "MechanicalResonanceDetector",
    "AIAnnotator",
    "ParameterRecommender",
    "ParameterRecommendation",
]

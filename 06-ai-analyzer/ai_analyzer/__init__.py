"""
AI Analyzer — Free Community Edition (MIT).

This package provides the public API for the AI analyzer. The advanced
detection algorithms (current anomaly, tracking error, mechanical resonance,
parameter recommendation) require a Pro commercial license and are not
included in this repository.

Free:    AIAnnotation, AnalyzerBase, AIAnnotator, AIAnalyzerPipeline (basic stats)
Pro:     CurrentAnomalyDetector, TrackingErrorDetector, MechanicalResonanceDetector,
         ParameterRecommender, tuning_rules, analyzer_bridge
"""

from .ai_annotator import AIAnnotator
from .analyzer_base import AIAnnotation, AnalyzerBase
from .analyzer_pipeline import AIAnalyzerPipeline

__all__ = [
    "AIAnalyzerPipeline",
    "AIAnnotation",
    "AnalyzerBase",
    "AIAnnotator",
]

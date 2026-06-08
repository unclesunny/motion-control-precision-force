"""
AI Analyzer — Machine Learning-based servo signal analysis for the oscilloscope.

Public API:
    AIAnalyzerPipeline    — main orchestrator (replaces hardcoded ANOMALY_RULES)
    AIAnalyzerBridge      — lazy bridge to AI&ML Agent sibling project
    AIAnnotation          — dataclass for anomaly events
    AnalyzerBase          — ABC for custom analyzer development

HITL (Human-in-the-Loop):
    HITLGate            — safety gate: classify, prompt, authorize
    EngineerPrompt      — AI question to engineer with diagnostic checklist
    EngineerFeedback    — engineer's multi-modal response (text/image/audio/video)
    AuthorizedAction    — parameter change approved by engineer
    ActionLogger        — immutable audit trail for compliance

Single-axis detectors:
    CurrentAnomalyDetector      — current saturation, wear, sensor fault
    TrackingErrorDetector       — following error root cause classification
    MechanicalResonanceDetector — FFT-based resonance peak detection

Cross-axis detector (multi-axis):
    CrossAxisAnalyzer      — 4th detector: bus sag, contouring, ring health,
                              mechanical coupling
    AxisSnapshot           — aggregated per-axis state for cross-axis analysis

Quickstart:
    from ai_analyzer import AIAnalyzerPipeline

    pipeline = AIAnalyzerPipeline()
    annotations = pipeline.analyze(values, channel_names, buffer_stats)

    for ann in annotations:
        print(f"{ann.severity}: {ann.message} → {ann.suggestion}")

    # Multi-axis analysis:
    from ai_analyzer import CrossAxisAnalyzer, AxisSnapshot
    cross = CrossAxisAnalyzer()
    snapshots = {
        "X": AxisSnapshot("X", 0, values_x, ch_names, stats_x),
        "Y": AxisSnapshot("Y", 1, values_y, ch_names, stats_y),
    }
    cross_annotations = cross.analyze(snapshots)

    # HITL workflow:
    prompts = pipeline.prompt_engineer(annotations)
    for p in prompts:
        print(f"Question: {p.question}")
        for check in p.suggested_checks:
            print(f"  - {check}")
        # ... engineer responds ...
        # feedback = EngineerFeedback(prompt_id=p.prompt_id, ...)
        # pipeline.process_engineer_feedback(p.prompt_id, feedback)
"""

try:
    from .action_logger import ActionLogger
    from .ai_annotator import AIAnnotator
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .analyzer_bridge import AIAnalyzerBridge
    from .analyzer_pipeline import AIAnalyzerPipeline
    from .current_anomaly import CurrentAnomalyDetector
    from .codegen_st import CodegenST
    from .cross_axis import CrossAxisAnalyzer, AxisSnapshot, cross_annotation
    from .hitl_gate import HITLGate
    from .hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
    from .llm_refiner import LLMDiagnosisRefiner
    from .mechanical_resonance import MechanicalResonanceDetector
    from .parameter_recommender import ParameterRecommender, ParameterRecommendation
    from .tracking_error import TrackingErrorDetector
except ImportError:
    from action_logger import ActionLogger
    from ai_annotator import AIAnnotator
    from analyzer_base import AIAnnotation, AnalyzerBase
    from analyzer_bridge import AIAnalyzerBridge
    from analyzer_pipeline import AIAnalyzerPipeline
    from current_anomaly import CurrentAnomalyDetector
    from cross_axis import CrossAxisAnalyzer, AxisSnapshot, cross_annotation
    from hitl_gate import HITLGate
    from hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
    from llm_refiner import LLMDiagnosisRefiner
    from mechanical_resonance import MechanicalResonanceDetector
    from parameter_recommender import ParameterRecommender, ParameterRecommendation
    from tracking_error import TrackingErrorDetector

__all__ = [
    # Pipeline
    "AIAnalyzerPipeline",
    "AIAnalyzerBridge",
    "AIAnnotator",
    # Base types
    "AIAnnotation",
    "AnalyzerBase",
    # Single-axis detectors
    "CurrentAnomalyDetector",
    "TrackingErrorDetector",
    "MechanicalResonanceDetector",
    # Cross-axis detector
    "CrossAxisAnalyzer",
    "AxisSnapshot",
    "cross_annotation",
    # Parameter engine
    "ParameterRecommender",
    "ParameterRecommendation",
    # HITL (Human-in-the-Loop)
    "HITLGate",
    "EngineerPrompt",
    "EngineerFeedback",
    "AuthorizedAction",
    "ActionLogger",
    # LLM Refiner
    "LLMDiagnosisRefiner",
    # CODESYS Code Generator
    "CodegenST",
]

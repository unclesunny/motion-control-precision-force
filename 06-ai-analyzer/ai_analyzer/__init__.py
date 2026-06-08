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

# ── Pro detection: override Free shells with Pro implementations ──
import importlib.util as _importlib_util
from pathlib import Path as _Path

_PRO_DIR = _Path(__file__).resolve().parent.parent.parent / "pro" / "ai_analyzer"
_PRO_AVAILABLE = _PRO_DIR.exists() and any(
    _PRO_DIR.joinpath(f).exists() for f in
    ["current_anomaly.py", "tracking_error.py", "mechanical_resonance.py"])

_pro_overrides = {}

if _PRO_AVAILABLE:
    for _mod_name, _class_names in [
        ("current_anomaly", ["CurrentAnomalyDetector"]),
        ("tracking_error", ["TrackingErrorDetector"]),
        ("mechanical_resonance", ["MechanicalResonanceDetector"]),
        ("cross_axis", ["CrossAxisAnalyzer", "AxisSnapshot"]),
        ("hitl_gate", ["HITLGate"]),
        ("hitl_types", ["EngineerPrompt", "EngineerFeedback", "AuthorizedAction"]),
        ("action_logger", ["ActionLogger"]),
        ("llm_refiner", ["LLMDiagnosisRefiner"]),
        ("parameter_recommender", ["ParameterRecommender", "ParameterRecommendation"]),
        ("tuning_rules", []),  # replaces BRAND_ALIASES, PARAM_DESCRIPTIONS, etc.
    ]:
        try:
            spec = _importlib_util.spec_from_file_location(
                f"pro_ai_analyzer.{_mod_name}",
                _PRO_DIR / f"{_mod_name}.py")
            if spec is None:
                continue
            mod = _importlib_util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for _name in _class_names:
                cls = getattr(mod, _name, None)
                if cls is not None:
                    _pro_overrides[_name] = cls
            # For tuning_rules, override module-level dicts
            if _mod_name == "tuning_rules":
                for _attr in ["BRAND_ALIASES", "PARAM_DESCRIPTIONS",
                              "BRAND_CAPABILITY_NOTES", "LPF_ALIASES",
                              "SCURVE_ALIASES", "CIA402_STANDARD_NAMES"]:
                    val = getattr(mod, _attr, None)
                    if val is not None:
                        _pro_overrides[_attr] = val
        except Exception:
            pass

# ── Import Free shells (always available) ──
from .action_logger import ActionLogger
from .ai_annotator import AIAnnotator
from .analyzer_base import AIAnnotation, AnalyzerBase
from .analyzer_bridge import AIAnalyzerBridge
from .analyzer_pipeline import AIAnalyzerPipeline
from .current_anomaly import CurrentAnomalyDetector
from .codegen_st import CodegenST
from .cross_axis import CrossAxisAnalyzer, AxisSnapshot
from .hitl_gate import HITLGate
from .hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
from .llm_refiner import LLMDiagnosisRefiner
from .mechanical_resonance import MechanicalResonanceDetector
from .parameter_recommender import ParameterRecommender, ParameterRecommendation
from .tracking_error import TrackingErrorDetector

# ── Apply Pro overrides ──
if _pro_overrides:
    for _name, _cls in _pro_overrides.items():
        if _name in globals() or not _name.startswith("_"):
            globals()[_name] = _cls

# Re-export cross_annotation for backwards compat
cross_annotation = None  # Pro feature, not in Free

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

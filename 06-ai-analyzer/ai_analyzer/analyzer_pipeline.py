"""
AI Analyzer Pipeline — Free shell.

Pro license required for the full multi-detector pipeline with:
  - 3 single-axis ML detectors (Current/Tracking/Resonance)
  - Cross-axis analysis (4 detectors)
  - HITL safety gate (classify → prompt → authorize)
  - LLM diagnosis refinement
  - Brand-aware parameter recommendation
  - Immutable audit trail

This Free shell provides the same public API with safe no-op defaults.
All scope integration continues to work — just without AI analysis.
"""

import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

# ── Pro detection ──────────────────────────────────────────
_PRO_DIR = Path(__file__).resolve().parent.parent.parent / "pro" / "ai_analyzer"
_PRO_AVAILABLE = _PRO_DIR.exists()

# Import Free shells
from .action_logger import ActionLogger
from .ai_annotator import AIAnnotator
from .analyzer_base import AIAnnotation, AnalyzerBase
from .analyzer_bridge import AIAnalyzerBridge
from .current_anomaly import CurrentAnomalyDetector
from .hitl_gate import HITLGate
from .hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
from .mechanical_resonance import MechanicalResonanceDetector
from .parameter_recommender import ParameterRecommender, ParameterRecommendation
from .tracking_error import TrackingErrorDetector


class AIAnalyzerPipeline:
    """AI analysis pipeline (Pro license required for ML-based analysis).

    Free edition: returns empty annotations. The scope continues to function
    with legacy threshold rules as a fallback.
    """

    def __init__(self, sample_rate_hz: float = 1000.0,
                 analyzers: list = None, brand: str = None,
                 enable_hitl: bool = True, hitl_gate=None,
                 action_logger=None, axis_id: str = "",
                 slave_position: int = -1):
        self.sample_rate_hz = sample_rate_hz
        self.brand = brand
        self.enable_hitl = enable_hitl
        self.axis_id = axis_id
        self.slave_position = slave_position
        self._sample_count = 0

        # Detectors (Free: empty to avoid exposing architecture)
        self._analyzers = analyzers if analyzers is not None else []
        self.analyzers = self._analyzers

        # Free shells — no real functionality
        self._annotator = AIAnnotator()
        self._bridge = AIAnalyzerBridge()
        self._hitl_gate = hitl_gate if hitl_gate is not None else HITLGate()
        self._action_logger = action_logger if action_logger is not None else ActionLogger()
        self._recommender = ParameterRecommender()
        self._events: list = []

    @property
    def hitl_gate(self):
        return self._hitl_gate

    @property
    def action_logger(self):
        return self._action_logger

    @property
    def recommender(self):
        return self._recommender

    @property
    def recent_events(self) -> list:
        return self._events[-20:] if self._events else []

    @property
    def last_recommendations(self) -> list:
        return []

    def analyze(self, values: list, channel_names: list,
                buffer_stats: dict = None) -> list:
        """Returns empty — Pro license required for ML-based analysis."""
        self._sample_count += 1
        return []

    def enable_analyzer(self, name: str):
        pass

    def disable_analyzer(self, name: str):
        pass

    def prompt_engineer(self, annotations: list = None) -> list:
        """Returns empty — Pro license required for HITL prompts."""
        return []

    def process_engineer_feedback(self, prompt_id: str, feedback) -> list:
        """Returns empty — Pro license required for feedback processing."""
        return []

    def get_authorized_actions(self) -> list:
        """Returns empty."""
        return []

    def get_pending_prompts(self) -> list:
        """Returns empty."""
        return []

    def get_hitl_summary(self) -> str:
        return "Free edition — no HITL"

    def reset(self):
        self._sample_count = 0
        self._events.clear()


# ── Pro override (if pro/ai_analyzer/ exists) ──────────────
if _PRO_AVAILABLE:
    try:
        spec = importlib.util.spec_from_file_location(
            "pro_analyzer_pipeline",
            _PRO_DIR / "analyzer_pipeline.py")
        if spec is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            AIAnalyzerPipeline = getattr(mod, "AIAnalyzerPipeline", AIAnalyzerPipeline)
    except Exception:
        pass

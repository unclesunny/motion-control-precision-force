"""
AI Analyzer Pipeline — orchestrates all detectors and post-processing.

The main entry point for scope_engine.py integration. Replaces the
hardcoded ANOMALY_RULES list with a pluggable pipeline of ML-based detectors.

Usage:
    from ai_analyzer import AIAnalyzerPipeline

    pipeline = AIAnalyzerPipeline()
    annotations = pipeline.analyze(values, channel_names, buffer_stats)

    # HITL (Human-in-the-Loop) workflow:
    prompts = pipeline.prompt_engineer(annotations)
    # ... show prompts to engineer, collect feedback ...
    refined = pipeline.process_engineer_feedback(prompt_id, feedback)
    actions = pipeline.get_authorized_actions()

Architecture:
    values → [CurrentAnomalyDetector] ─┐
            [TrackingErrorDetector]   ─┤→ AIAnnotator → HITLGate → AIAnnotation[]
            [MechanicalResonanceDetector]┘       │
                                                 ├─ [safe] → direct output
                                                 ├─ [actionable] → prompt → auth → action
                                                 └─ [ambiguous] → prompt → feedback → refine

Pro/Free: Free shells are imported first. If pro/ai_analyzer/ exists (commercial
license), the Pro implementations override the shells automatically.
"""

import importlib.util
import time
from pathlib import Path
from typing import Dict, List, Optional

# ── Pro detection ──────────────────────────────────────────
_PRO_DIR = Path(__file__).resolve().parent.parent.parent / "pro" / "ai_analyzer"
_PRO_AVAILABLE = _PRO_DIR.exists() and any(
    _PRO_DIR.joinpath(f).exists() for f in
    ["current_anomaly.py", "tracking_error.py", "mechanical_resonance.py"])


def _load_pro_module(module_name: str, class_names: List[str]) -> dict:
    """Load classes from pro/ai_analyzer/ if available.

    Returns dict {class_name: class} for successfully loaded classes.
    Falls back gracefully — returns empty dict if pro/ not found.
    """
    result = {}
    if not _PRO_AVAILABLE:
        return result
    try:
        spec = importlib.util.spec_from_file_location(
            f"pro_ai_analyzer.{module_name}",
            _PRO_DIR / f"{module_name}.py")
        if spec is None:
            return result
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in class_names:
            cls = getattr(mod, name, None)
            if cls is not None:
                result[name] = cls
    except Exception:
        pass
    return result


# ── Import Free shells (always available) ──────────────────
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

# ── Override with Pro implementations if available ─────────
_pro_overrides = {}
_pro_overrides.update(_load_pro_module(
    "current_anomaly", ["CurrentAnomalyDetector"]))
_pro_overrides.update(_load_pro_module(
    "tracking_error", ["TrackingErrorDetector"]))
_pro_overrides.update(_load_pro_module(
    "mechanical_resonance", ["MechanicalResonanceDetector"]))
_pro_overrides.update(_load_pro_module(
    "hitl_gate", ["HITLGate"]))
_pro_overrides.update(_load_pro_module(
    "parameter_recommender", ["ParameterRecommender", "ParameterRecommendation"]))
_pro_overrides.update(_load_pro_module(
    "action_logger", ["ActionLogger"]))
_pro_overrides.update(_load_pro_module(
    "tuning_rules", []))

if _pro_overrides:
    if "CurrentAnomalyDetector" in _pro_overrides:
        CurrentAnomalyDetector = _pro_overrides["CurrentAnomalyDetector"]
    if "TrackingErrorDetector" in _pro_overrides:
        TrackingErrorDetector = _pro_overrides["TrackingErrorDetector"]
    if "MechanicalResonanceDetector" in _pro_overrides:
        MechanicalResonanceDetector = _pro_overrides["MechanicalResonanceDetector"]
    if "HITLGate" in _pro_overrides:
        HITLGate = _pro_overrides["HITLGate"]
    if "ParameterRecommender" in _pro_overrides:
        ParameterRecommender = _pro_overrides["ParameterRecommender"]
    if "ParameterRecommendation" in _pro_overrides:
        ParameterRecommendation = _pro_overrides["ParameterRecommendation"]
    if "ActionLogger" in _pro_overrides:
        ActionLogger = _pro_overrides["ActionLogger"]


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
        hitl_gate: Optional[HITLGate] = None,
        action_logger: Optional[ActionLogger] = None,
        enable_hitl: bool = True,
        llm_api_key: Optional[str] = None,
        axis_id: str = "",
        slave_position: int = -1,
    ):
        self._analyzers = analyzers if analyzers is not None else self._default_analyzers(sample_rate_hz)
        self._annotator = AIAnnotator()
        self._bridge = bridge if bridge is not None else AIAnalyzerBridge()
        self._recommender = ParameterRecommender(brand=brand)
        self._axis_id = axis_id
        self._slave_position = slave_position

        # LLM refiner (lazy imports inside HITLGate)
        try:
            from .llm_refiner import LLMDiagnosisRefiner
            _llm = LLMDiagnosisRefiner(api_key=llm_api_key)
        except Exception:
            _llm = None
        self._hitl_gate = hitl_gate if hitl_gate is not None else HITLGate(brand=brand, llm_refiner=_llm)
        self._action_logger = action_logger if action_logger is not None else ActionLogger(brand=brand)
        self._enable_hitl = enable_hitl
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
    def hitl_gate(self) -> HITLGate:
        return self._hitl_gate

    @property
    def action_logger(self) -> ActionLogger:
        return self._action_logger

    @property
    def enable_hitl(self) -> bool:
        return self._enable_hitl

    @enable_hitl.setter
    def enable_hitl(self, value: bool):
        self._enable_hitl = value

    @property
    def axis_id(self) -> str:
        return self._axis_id

    @property
    def slave_position(self) -> int:
        return self._slave_position

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

        # ── Stamp axis identity on every annotation ──
        for ann in calibrated:
            ann.axis_id = self._axis_id
            ann.slave_position = self._slave_position

        # ── HITL classification (when enabled) ──
        if self._enable_hitl:
            for ann in calibrated:
                self._hitl_gate.classify(ann)
                self._action_logger.log_annotation(ann)

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
        self._hitl_gate.reset()
        self._action_logger.reset()
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

    # ── HITL (Human-in-the-Loop) Methods ─────────────────────────

    def prompt_engineer(
        self, annotations: Optional[List[AIAnnotation]] = None
    ) -> List[EngineerPrompt]:
        """Generate engineer prompts for actionable/ambiguous annotations.

        Safe annotations are skipped. Actionable annotations get authorization
        prompts. Ambiguous annotations get multi-modal diagnostic checklists.

        Args:
            annotations: Optional list of annotations. If None, uses recent events.

        Returns:
            List of EngineerPrompt for display in the UI.
        """
        source = annotations if annotations is not None else self._events[-20:]
        if not self._enable_hitl:
            return []

        prompts = self._hitl_gate.generate_prompts(source)

        # Attach parameter previews for actionable prompts
        for prompt in prompts:
            if prompt.classification == "actionable":
                # Find the matching annotation to get recommendations
                matching = [a for a in source if a.category == prompt.category]
                if matching:
                    preview_params = self._recommender.recommend(matching)
                    prompt.parameter_preview = preview_params
            self._action_logger.log_prompt(prompt)

        return prompts

    def process_engineer_feedback(
        self, prompt_id: str, feedback: EngineerFeedback
    ) -> List[AIAnnotation]:
        """Process engineer feedback and refine the diagnosis.

        For ambiguous prompts: refines the generic diagnosis → specific sub-category.
        For actionable prompts: if approved, generates AuthorizedAction entries.

        Args:
            prompt_id: The prompt ID this feedback responds to.
            feedback: EngineerFeedback with observations and authorization.

        Returns:
            Refined AIAnnotation list, or empty if rejected.
        """
        if not self._enable_hitl:
            return []

        self._action_logger.log_feedback(feedback)

        prompt = self._hitl_gate.get_prompt(prompt_id)
        if prompt is None:
            # Prompt may have been resolved already
            return []

        if prompt.classification == "ambiguous":
            refined = self._hitl_gate.process_feedback(prompt, feedback)
            for ann in refined:
                self._action_logger.log_annotation(ann)
            return refined

        elif prompt.classification == "actionable":
            if feedback.is_approved:
                recs = prompt.parameter_preview if prompt.parameter_preview else []
                if not recs:
                    # Generate recommendations if not previewed
                    matching = [
                        a for a in self._events if a.category == prompt.category
                    ]
                    recs = self._recommender.recommend(matching[-3:])
                authorized = self._hitl_gate.authorize(recs, feedback)
                for action in authorized:
                    self._action_logger.log_authorized(action)
            else:
                for rec in prompt.parameter_preview:
                    self._action_logger.log_rejected(
                        rec, feedback, feedback.notes or "Engineer rejected"
                    )
            return []

        return []

    def get_authorized_actions(self) -> List[AuthorizedAction]:
        """Get all authorized (ready-to-execute) parameter actions.

        These actions have been approved by the engineer and can be
        safely written to the drive. Each action includes a rollback plan.

        Returns:
            List of AuthorizedAction, most recent first.
        """
        return self._hitl_gate.get_authorized_actions()

    def get_pending_prompts(self) -> List[EngineerPrompt]:
        """Get prompts waiting for engineer response."""
        return self._hitl_gate.pending_prompts

    def get_hitl_summary(self) -> str:
        """Get a human-readable HITL session summary."""
        return self._action_logger.summary()

    def recommend(self, annotations: Optional[List[AIAnnotation]] = None,
                  require_authorization: bool = True
                  ) -> List[ParameterRecommendation]:
        """Generate tuning parameter recommendations from recent annotations.

        When require_authorization=True (default), annotations classified as
        'actionable' or 'ambiguous' are flagged with requires_authorization=True
        and their recommendations should be routed through the HITL gate before
        execution. The returned ParameterRecommendation list is a READ-ONLY
        preview — it does NOT authorize any parameter write.

        Args:
            annotations: Optional list of annotations. If None, uses recent events.
            require_authorization: If True, invasive parameter changes require
                                  engineer approval via the HITL gate.

        Returns:
            List of ParameterRecommendation, sorted by priority.
        """
        source = annotations if annotations is not None else self._events[-20:]

        if require_authorization and self._enable_hitl:
            # Only recommend for safe annotations or already-authorized ones
            safe_annotations = [
                a for a in source
                if a.hitl_classification == "safe" or not a.requires_authorization
            ]
            if safe_annotations:
                return self._recommender.recommend(safe_annotations)
            # For actionable/ambiguous: return empty — engineer must authorize first
            return []

        return self._recommender.recommend(source)

    def format_recommendations(self) -> str:
        """Get formatted tuning report string."""
        params = self.recommend()
        return self._recommender.format(params)

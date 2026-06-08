"""
HITL (Human-in-the-Loop) Gate — safety barrier between AI detection and action.

The gate classifies every AI annotation into one of three categories:

    safe        — Informational only. No action possible or needed.
                  Example: current_sensor_fault (hardware issue).

    actionable  — AI knows the fix, but MUST obtain engineer authorization.
                  Example: resonance_detected → set notch filter at 320 Hz.

    ambiguous   — AI detected a symptom but cannot pinpoint root cause from
                  electrical signals alone. Needs engineer sensory input.
                  Example: current_wear → coupling? ballscrew? bearing?

Design principle (per user requirement):
    "No authorization = no invasive code operation. All AI work is
     suggestions and guidance. Without authorization, no invasive
     parameter writes are permitted."

Usage:
    from hitl_gate import HITLGate

    gate = HITLGate(brand="yaskawa-sigma7")
    classification = gate.classify(annotation)
    if classification in ("actionable", "ambiguous"):
        prompt = gate.generate_prompt(annotation)
        # ... show prompt to engineer, wait for feedback ...
        if classification == "ambiguous":
            refined_annotations = gate.process_feedback(prompt, feedback)
        elif classification == "actionable":
            actions = gate.authorize(recommendations, feedback)
"""

import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from .analyzer_base import AIAnnotation
    from .config import HITL_CLASSIFICATION, INVASIVE_ACTIONS
    from .engineer_prompts import (
        AMBIGUOUS_PROMPTS,
        ACTIONABLE_PROMPTS,
        format_authorization_text,
        format_context,
        get_classification,
        get_prompt_template,
    )
    from .hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
    from .llm_refiner import LLMDiagnosisRefiner
except ImportError:
    from analyzer_base import AIAnnotation
    from config import HITL_CLASSIFICATION, INVASIVE_ACTIONS
    from engineer_prompts import (
        AMBIGUOUS_PROMPTS,
        ACTIONABLE_PROMPTS,
        format_authorization_text,
        format_context,
        get_classification,
        get_prompt_template,
    )
    from hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
    from llm_refiner import LLMDiagnosisRefiner


class HITLGate:
    """Safety gate for AI-to-action pipeline.

    Ensures no invasive parameter operation occurs without explicit
    engineer authorization. For ambiguous detections, generates
    multi-modal diagnostic prompts and refines the diagnosis based
    on engineer feedback.

    Parameters:
        brand: Servo brand key (e.g. "yaskawa-sigma7", "delta-a3").
              Used for brand-specific parameter indexing in prompts.
        require_auth_for_all: If True, even "safe" annotations require
                             acknowledgment before proceeding.
    """

    def __init__(self, brand: Optional[str] = None, require_auth_for_all: bool = False,
                 llm_refiner: Optional[LLMDiagnosisRefiner] = None):
        self.brand = brand
        self.require_auth_for_all = require_auth_for_all
        self._llm = llm_refiner  # None → auto-create if API key available
        self._pending_prompts: Dict[str, EngineerPrompt] = {}
        self._feedback_history: List[EngineerFeedback] = []
        self._authorized_actions: List[AuthorizedAction] = []
        self._rejected_actions: List[Tuple[Any, EngineerFeedback]] = []

    @property
    def llm_available(self) -> bool:
        """Check if LLM-powered refinement is available."""
        if self._llm is None:
            try:
                self._llm = LLMDiagnosisRefiner()
            except Exception:
                return False
        return self._llm.available

    # ── Classification ─────────────────────────────────────────────

    def classify(self, annotation: AIAnnotation) -> str:
        """Classify an annotation as safe, actionable, or ambiguous.

        Args:
            annotation: AIAnnotation from any detector.

        Returns:
            "safe" | "actionable" | "ambiguous"
        """
        classification = HITL_CLASSIFICATION.get(annotation.category, "safe")

        # Override: if require_auth_for_all, everything needs authorization
        if self.require_auth_for_all and classification == "safe":
            return "actionable"

        # Update the annotation's HITL fields
        annotation.hitl_classification = classification
        annotation.requires_authorization = classification in ("actionable", "ambiguous")

        return classification

    def classify_all(self, annotations: List[AIAnnotation]) -> Dict[str, List[AIAnnotation]]:
        """Classify a batch of annotations into groups.

        Returns:
            {"safe": [...], "actionable": [...], "ambiguous": [...]}
        """
        groups: Dict[str, List[AIAnnotation]] = {
            "safe": [], "actionable": [], "ambiguous": [],
        }
        for ann in annotations:
            c = self.classify(ann)
            groups[c].append(ann)
        return groups

    # ── Prompt Generation ──────────────────────────────────────────

    def generate_prompt(self, annotation: AIAnnotation) -> Optional[EngineerPrompt]:
        """Generate an engineer prompt for an actionable or ambiguous annotation.

        Args:
            annotation: AIAnnotation classified as actionable or ambiguous.

        Returns:
            EngineerPrompt with question, context, checklist, and modalities.
            None if the category has no prompt template defined.
        """
        template = get_prompt_template(annotation.category)
        if not template:
            return None

        classification = annotation.hitl_classification or self.classify(annotation)
        context = format_context(
            template.get("context_template", ""),
            annotation.metadata,
            annotation.value,
            annotation.confidence,
        )
        urgency_map = template.get("urgency_map", {})
        urgency = urgency_map.get(annotation.severity, "routine")

        # Default question from template
        question = template.get("question", f"检测到 {annotation.category} — 请确认：")

        # Build authorization preview text for actionable prompts
        if classification == "actionable":
            auth_text = format_authorization_text(
                template.get("authorization_prompt", ""),
                annotation.metadata,
                annotation.value,
            )
            question += "\n\n" + auth_text

        prompt = EngineerPrompt(
            category=annotation.category,
            classification=classification,
            question=question or template.get("question", ""),
            context=context,
            suggested_checks=list(template.get("suggested_checks", [])),
            expected_modalities=list(template.get("expected_modalities", ["text"])),
            urgency=urgency,
            metadata={
                "annotation_severity": annotation.severity,
                "annotation_confidence": annotation.confidence,
                "annotation_value": annotation.value,
                "annotation_message": annotation.message,
                "annotation_suggestion": annotation.suggestion,
            },
        )

        # Register pending
        self._pending_prompts[prompt.prompt_id] = prompt
        return prompt

    def generate_prompts(self, annotations: List[AIAnnotation]) -> List[EngineerPrompt]:
        """Generate prompts for all annotations that need engineer interaction.

        Safe annotations are skipped (they don't need prompts).
        """
        prompts = []
        for ann in annotations:
            if ann.hitl_classification in ("actionable", "ambiguous"):
                prompt = self.generate_prompt(ann)
                if prompt:
                    prompts.append(prompt)
        return prompts

    # ── Feedback Processing ────────────────────────────────────────

    def process_feedback(
        self, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> List[AIAnnotation]:
        """Process engineer feedback for an ambiguous diagnostic prompt.

        When the engineer reports their observations, this method refines
        the generic diagnosis into a more specific one.

        Args:
            prompt: The original EngineerPrompt.
            feedback: Engineer's response with observations.

        Returns:
            Refined list of AIAnnotation with more specific categories.
            E.g., "current_wear" → "current_wear_coupling" or
            "current_wear_ballscrew".
        """
        self._feedback_history.append(feedback)

        # Remove from pending
        self._pending_prompts.pop(prompt.prompt_id, None)

        if feedback.is_rejected:
            return []

        # Build refined annotations based on feedback
        # Try LLM first, fall back to keyword matching
        refined = self._refine_diagnosis(prompt, feedback)
        return refined

    def _refine_diagnosis(
        self, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> List[AIAnnotation]:
        """Refine an ambiguous diagnosis — LLM first, keyword fallback."""
        # ── Try LLM-powered refinement ──
        if self.llm_available:
            try:
                result = self._llm.refine(prompt, feedback)
                if result:
                    return [self._build_annotation_from_llm(result, prompt, feedback)]
            except Exception:
                pass  # fall through to keyword matching

        # ── Fallback: keyword-based refinement ──
        return self._refine_diagnosis_keyword(prompt, feedback)

    def _build_annotation_from_llm(
        self, result: dict, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> AIAnnotation:
        """Convert an LLM refinement result into an AIAnnotation."""
        refined_category = result.get("refined_category", prompt.category)
        diagnosis = result.get("diagnosis", "")
        recommendation = result.get("recommendation", "")
        confidence = result.get("confidence", 0.85)
        requires_parts = result.get("requires_parts", [])
        urgency = result.get("urgency", "routine")
        additional_checks = result.get("additional_checks", [])
        param_adjustment = result.get("parameter_adjustment", "")

        # Build rich message
        message_parts = [f"LLM 精化诊断: {diagnosis}"]
        if recommendation:
            message_parts.append(f"建议: {recommendation}")
        if requires_parts:
            message_parts.append(f"需采购: {', '.join(requires_parts)}")
        if param_adjustment:
            message_parts.append(f"临时参数补偿: {param_adjustment}")

        severity_map = {"routine": "info", "soon": "warning", "immediate": "critical"}
        severity = severity_map.get(urgency, prompt.metadata.get("annotation_severity", "warning"))

        ann = AIAnnotation(
            timestamp=time.time(),
            channel=prompt.metadata.get("annotation_severity", "info"),
            category=refined_category,
            severity=severity,
            confidence=float(confidence),
            message="\n".join(message_parts),
            suggestion=recommendation,
            value=prompt.metadata.get("annotation_value", 0.0),
            metadata={
                "original_category": prompt.category,
                "engineer_observation": feedback.response_text or feedback.selected_observation,
                "feedback_media_paths": feedback.media_paths,
                "refined_by": "llm_refiner",
                "llm_model": result.get("_model", "unknown"),
                "requires_parts": requires_parts,
                "additional_checks": additional_checks,
                "parameter_adjustment": param_adjustment,
                "llm_confidence": confidence,
            },
        )
        ann.hitl_classification = "actionable"
        ann.requires_authorization = True
        return ann

    def _refine_diagnosis_keyword(
        self, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> List[AIAnnotation]:
        """Fallback: keyword-based diagnosis refinement.

        Maps engineer observations to more specific sub-categories.
        Used when LLM is unavailable or API call fails.
        """
        original_category = prompt.category
        obs = feedback.selected_observation or feedback.response_text
        observation_lower = obs.lower()

        refined_category = original_category
        refined_message = ""

        if original_category == "current_wear":
            if any(w in observation_lower for w in ["联轴器", "coupling", "橡胶", "rubber", "偏摆"]):
                refined_category = "current_wear_coupling"
                refined_message = (
                    f"工程师确认：联轴器磨损/不对中。反馈：{obs[:200]}。"
                    f"建议：更换联轴器弹性体，重新对中。"
                )
            elif any(w in observation_lower for w in ["丝杆", "ball.?screw", "滚珠", "异响", "noise"]):
                refined_category = "current_wear_ballscrew"
                refined_message = (
                    f"工程师确认：丝杆/滚珠丝杆磨损。反馈：{obs[:200]}。"
                    f"建议：检查丝杆间隙，必要时更换丝杆螺母副。"
                )
            elif any(w in observation_lower for w in ["轴承", "bearing", "温度", "temp", "热"]):
                refined_category = "current_wear_bearing"
                refined_message = (
                    f"工程师确认：轴承磨损/异常温升。反馈：{obs[:200]}。"
                    f"建议：更换轴承，检查润滑。"
                )
            elif any(w in observation_lower for w in ["皮带", "belt", "张力"]):
                refined_category = "current_wear_belt"
                refined_message = (
                    f"工程师确认：皮带磨损/张力异常。反馈：{obs[:200]}。"
                    f"建议：更换皮带并重新调整张力。"
                )
            elif any(w in observation_lower for w in ["导轨", "guide", "rail", "卡", "爬行"]):
                refined_category = "current_wear_guide"
                refined_message = (
                    f"工程师确认：导轨卡滞/磨损。反馈：{obs[:200]}。"
                    f"建议：检查导轨润滑，必要时更换滑块。"
                )
            else:
                refined_message = (
                    f"工程师反馈：{obs[:200]}。"
                    f"无法自动精化诊断，请继续观察电流趋势并结合定期维护检查。"
                )
        elif original_category == "tracking_mechanical_bind":
            if any(w in observation_lower for w in ["导轨", "guide", "rail", "润滑", "干涩"]):
                refined_category = "tracking_bind_guide"
                refined_message = (
                    f"工程师确认：导轨润滑不足/卡滞。反馈：{obs[:200]}。"
                    f"建议：清洁导轨并重新润滑。"
                )
            elif any(w in observation_lower for w in ["丝杆", "间隙", "backlash", "千分表"]):
                refined_category = "tracking_bind_backlash"
                refined_message = (
                    f"工程师确认：丝杆反向间隙过大。反馈：{obs[:200]}。"
                    f"建议：调整丝杆预压或更换螺母副。"
                )
            elif any(w in observation_lower for w in ["防护罩", "干涉", "线槽", "刮擦"]):
                refined_category = "tracking_bind_interference"
                refined_message = (
                    f"工程师确认：防护罩/线槽干涉。反馈：{obs[:200]}。"
                    f"建议：调整防护罩或线槽位置，消除干涉。"
                )
            elif any(w in observation_lower for w in ["异物", "切屑", "卡住"]):
                refined_category = "tracking_bind_debris"
                refined_message = (
                    f"工程师确认：异物卡滞。反馈：{obs[:200]}。"
                    f"建议：清除异物，检查防护罩密封。"
                )
            else:
                refined_message = (
                    f"工程师反馈：{obs[:200]}。"
                    f"无法自动精化诊断，建议继续监控并排查机械干涉源。"
                )

        refined_ann = AIAnnotation(
            timestamp=time.time(),
            channel=prompt.metadata.get("annotation_severity", "info"),
            category=refined_category,
            severity=prompt.metadata.get("annotation_severity", "warning"),
            confidence=0.75,  # lower confidence for keyword-based
            message=refined_message,
            suggestion=refined_message,
            value=prompt.metadata.get("annotation_value", 0.0),
            metadata={
                "original_category": original_category,
                "engineer_observation": obs,
                "feedback_media_paths": feedback.media_paths,
                "refined_by": "hitl_gate.keyword",
            },
        )
        refined_ann.hitl_classification = "actionable"
        refined_ann.requires_authorization = True

        return [refined_ann]

    # ── Authorization ──────────────────────────────────────────────

    def authorize(
        self,
        recommendations: List[Any],
        feedback: EngineerFeedback,
    ) -> List[AuthorizedAction]:
        """Authorize parameter recommendations based on engineer feedback.

        This is the FINAL gate before any parameter write. Only
        AuthorizedAction instances (not raw ParameterRecommendation)
        should be passed to hardware-write functions.

        Args:
            recommendations: List of ParameterRecommendation from recommender.
            feedback: EngineerFeedback with authorization="approved".

        Returns:
            List of AuthorizedAction. Empty if feedback is rejected.
        """
        self._feedback_history.append(feedback)
        self._pending_prompts.pop(feedback.prompt_id, None)

        if not feedback.is_approved:
            for rec in recommendations:
                self._rejected_actions.append((rec, feedback))
            return []

        authorized = []
        for rec in recommendations:
            action_type = getattr(rec, "action", "")
            is_invasive = action_type in INVASIVE_ACTIONS

            # Build rollback plan based on action type
            rollback = self._build_rollback_plan(rec)

            auth_action = AuthorizedAction(
                recommendation=rec,
                authorization=feedback,
                safety_acknowledged=feedback.is_approved,
                rollback_plan=rollback,
            )
            authorized.append(auth_action)
            self._authorized_actions.append(auth_action)

        return authorized

    @staticmethod
    def _build_rollback_plan(recommendation) -> str:
        """Build a human-readable rollback plan for a parameter change."""
        action = getattr(recommendation, "action", "")
        index_hex = getattr(recommendation, "index_hex", "0x????")
        if hasattr(recommendation, "index_hex") and not isinstance(recommendation.index_hex, str):
            index_hex = f"0x{recommendation.index:04X}" if hasattr(recommendation, "index") else "0x????"
        elif hasattr(recommendation, "index"):
            index_hex = f"0x{recommendation.index:04X}"

        current_val = getattr(recommendation, "current_value", None)
        step_pct = getattr(recommendation, "step_pct", 0.0)

        if action == "set" and current_val is not None:
            return f"将 {index_hex} 从当前值设回原值 {current_val}。"
        elif action in ("increase", "decrease"):
            reverse = "decrease" if action == "increase" else "increase"
            return f"反向操作：将 {index_hex} {reverse} {abs(step_pct):.0f}%（或恢复保存的原值）。"
        else:
            return f"将 {index_hex} 恢复为修改前的值（建议操作前保存参数快照）。"

    # ── Status & History ────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """Number of prompts waiting for engineer response."""
        return len(self._pending_prompts)

    @property
    def pending_prompts(self) -> List[EngineerPrompt]:
        """All prompts currently waiting for engineer feedback."""
        return list(self._pending_prompts.values())

    def get_prompt(self, prompt_id: str) -> Optional[EngineerPrompt]:
        """Get a specific pending prompt by ID."""
        return self._pending_prompts.get(prompt_id)

    def get_history(self) -> List[EngineerFeedback]:
        """Get all feedback received in this session."""
        return list(self._feedback_history)

    def get_authorized_actions(self) -> List[AuthorizedAction]:
        """Get all authorized actions in this session."""
        return list(self._authorized_actions)

    def get_rejected_actions(self) -> List[Tuple[Any, EngineerFeedback]]:
        """Get all rejected recommendations."""
        return list(self._rejected_actions)

    def reset(self):
        """Reset all HITL state for a new session."""
        self._pending_prompts.clear()
        self._feedback_history.clear()
        self._authorized_actions.clear()
        self._rejected_actions.clear()

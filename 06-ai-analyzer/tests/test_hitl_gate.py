"""Unit tests for HITL Gate and engineer prompts."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from analyzer_base import AIAnnotation
from hitl_gate import HITLGate
from hitl_types import EngineerFeedback, EngineerPrompt, AuthorizedAction
from engineer_prompts import (
    AMBIGUOUS_PROMPTS, ACTIONABLE_PROMPTS,
    get_prompt_template, get_classification,
    format_context, format_authorization_text,
)
from parameter_recommender import ParameterRecommender, ParameterRecommendation


def make_annotation(category, severity="warning", confidence=0.9,
                    value=100.0, **metadata):
    """Helper to create test annotations."""
    return AIAnnotation(
        timestamp=time.time(), channel="Current", category=category,
        severity=severity, confidence=confidence,
        message=f"Test {category}", suggestion="",
        value=value, metadata=metadata,
    )


class TestHITLClassification:
    """Test HITLGate.classify() for all anomaly categories."""

    @pytest.fixture
    def gate(self):
        return HITLGate()

    def test_safe_categories(self, gate):
        """sensor_fault and system_overload are safe."""
        assert gate.classify(make_annotation("current_sensor_fault")) == "safe"
        assert gate.classify(make_annotation("system_overload")) == "safe"

    def test_actionable_categories(self, gate):
        """resonance, gain, saturation are actionable."""
        actionable = [
            "resonance_detected", "resonance_harmonic",
            "tracking_gain_deficiency", "tracking_absolute_limit",
            "current_saturation",
        ]
        for cat in actionable:
            ann = make_annotation(cat)
            assert gate.classify(ann) == "actionable", f"{cat} should be actionable"
            assert ann.requires_authorization is True
            assert ann.hitl_classification == "actionable"

    def test_ambiguous_categories(self, gate):
        """current_wear and tracking_mechanical_bind are ambiguous."""
        ambiguous = ["current_wear", "tracking_mechanical_bind"]
        for cat in ambiguous:
            ann = make_annotation(cat)
            assert gate.classify(ann) == "ambiguous", f"{cat} should be ambiguous"
            assert ann.requires_authorization is True
            assert ann.hitl_classification == "ambiguous"

    def test_unknown_category_defaults_to_safe(self, gate):
        """Unknown categories default to safe."""
        ann = make_annotation("nonexistent_category")
        assert gate.classify(ann) == "safe"
        assert ann.requires_authorization is False

    def test_classify_all_groups_correctly(self, gate):
        """Batch classification groups annotations."""
        anns = [
            make_annotation("current_sensor_fault"),
            make_annotation("resonance_detected", value=320.0, fundamental_hz=320.0),
            make_annotation("current_wear", value=120.0),
        ]
        groups = gate.classify_all(anns)
        assert len(groups["safe"]) == 1
        assert len(groups["actionable"]) == 1
        assert len(groups["ambiguous"]) == 1

    def test_require_auth_for_all_overrides_safe(self):
        """When require_auth_for_all=True, safe → actionable."""
        gate = HITLGate(require_auth_for_all=True)
        ann = make_annotation("current_sensor_fault")
        assert gate.classify(ann) == "actionable"


class TestEngineerPrompts:
    """Test prompt template resolution and context formatting."""

    def test_all_ambiguous_categories_have_templates(self):
        """Every ambiguous category in config must have a prompt template."""
        from config import HITL_CLASSIFICATION
        for cat, cls in HITL_CLASSIFICATION.items():
            if cls == "ambiguous":
                assert cat in AMBIGUOUS_PROMPTS, f"Missing prompt for ambiguous: {cat}"

    def test_all_actionable_categories_have_templates(self):
        """Every actionable category in config must have a prompt template."""
        from config import HITL_CLASSIFICATION
        for cat, cls in HITL_CLASSIFICATION.items():
            if cls == "actionable":
                assert cat in ACTIONABLE_PROMPTS, f"Missing prompt for actionable: {cat}"

    def test_current_wear_prompt_has_multimodal_checks(self):
        """current_wear prompt must suggest visual, audio, video checks."""
        tmpl = AMBIGUOUS_PROMPTS["current_wear"]
        assert "question" in tmpl
        assert len(tmpl["suggested_checks"]) >= 5  # at least 5 check items
        assert "image" in tmpl["expected_modalities"]
        assert "audio" in tmpl["expected_modalities"]
        assert "video" in tmpl["expected_modalities"]

    def test_mechanical_bind_prompt_has_checks(self):
        """tracking_mechanical_bind must have check items."""
        tmpl = AMBIGUOUS_PROMPTS["tracking_mechanical_bind"]
        assert len(tmpl["suggested_checks"]) >= 4

    def test_resonance_prompt_has_authorization(self):
        """Actionable prompts must include authorization_prompt."""
        tmpl = ACTIONABLE_PROMPTS["resonance_detected"]
        assert "authorization_prompt" in tmpl

    def test_format_context_with_metadata(self):
        """Context template is filled with annotation metadata."""
        tmpl = AMBIGUOUS_PROMPTS["current_wear"]
        ctx = format_context(
            tmpl["context_template"],
            {"baseline_mean": 80.0, "consecutive": 5},
            annotation_value=160.0,
            annotation_confidence=0.85,
        )
        assert "80" in ctx
        assert "160" in ctx
        assert "5" in ctx
        assert "85%" in ctx or "0.85" in ctx

    def test_format_context_graceful_missing_keys(self):
        """Missing template keys don't crash."""
        tmpl = AMBIGUOUS_PROMPTS["current_wear"]
        ctx = format_context(tmpl["context_template"], {}, 100.0, 0.9)
        assert len(ctx) > 10  # some fallback text generated

    def test_format_authorization_text(self):
        """Authorization template is filled with frequency info."""
        tmpl = ACTIONABLE_PROMPTS["resonance_detected"]
        text = format_authorization_text(
            tmpl["authorization_prompt"],
            {"fundamental_hz": 320.0},
            annotation_value=320.0,
        )
        assert "320" in text

    def test_get_prompt_template_returns_empty_for_unknown(self):
        """Unknown categories return empty dict."""
        assert get_prompt_template("nonexistent") == {}

    def test_get_classification_accurate(self):
        """get_classification matches prompt templates."""
        assert get_classification("current_wear") == "ambiguous"
        assert get_classification("resonance_detected") == "actionable"
        assert get_classification("current_sensor_fault") == "safe"


class TestHITLGatePromptGeneration:
    """Test EngineerPrompt generation from annotations."""

    @pytest.fixture
    def gate(self):
        return HITLGate()

    def test_generate_prompt_for_ambiguous(self, gate):
        """Ambiguous annotations generate multi-modal diagnostic prompts."""
        ann = make_annotation("current_wear", value=160.0,
                             baseline_mean=80.0, consecutive=5)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert prompt is not None
        assert prompt.classification == "ambiguous"
        assert len(prompt.suggested_checks) >= 5
        assert "image" in prompt.expected_modalities
        assert prompt.prompt_id.startswith("hitl-")

    def test_generate_prompt_for_actionable(self, gate):
        """Actionable annotations generate authorization prompts."""
        ann = make_annotation("resonance_detected", value=320.0,
                             fundamental_hz=320.0, snr=15.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert prompt is not None
        assert prompt.classification == "actionable"
        assert "320" in prompt.question

    def test_generate_prompt_for_safe_returns_none(self, gate):
        """Safe annotations don't generate prompts."""
        ann = make_annotation("current_sensor_fault")
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert prompt is None

    def test_generate_prompts_batch(self, gate):
        """Batch prompt generation skips safe annotations."""
        anns = [
            make_annotation("current_sensor_fault"),
            make_annotation("current_wear", value=160.0, baseline_mean=80.0),
            make_annotation("resonance_detected", value=320.0, fundamental_hz=320.0),
        ]
        for a in anns:
            gate.classify(a)
        prompts = gate.generate_prompts(anns)
        assert len(prompts) == 2  # safe skipped

    def test_prompt_registered_as_pending(self, gate):
        """Generated prompts are tracked as pending."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert gate.pending_count == 1
        assert gate.get_prompt(prompt.prompt_id) is not None


class TestHITLGateFeedbackProcessing:
    """Test engineer feedback processing and diagnosis refinement."""

    @pytest.fixture
    def gate(self):
        return HITLGate()

    def test_ambiguous_feedback_refines_diagnosis_coupling(self, gate):
        """Engineer confirms coupling wear → refined to current_wear_coupling."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="联轴器有橡胶粉尘，明显偏摆",
            selected_observation="联轴器：是否有橡胶粉尘",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear_coupling"
        assert "联轴器" in refined[0].message
        assert refined[0].hitl_classification == "actionable"

    def test_ambiguous_feedback_refines_diagnosis_ballscrew(self, gate):
        """Engineer confirms ballscrew noise → refined to current_wear_ballscrew."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="丝杆运动时有咯噔异响",
            selected_observation="丝杆/滚珠丝杆",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear_ballscrew"

    def test_ambiguous_feedback_refines_diagnosis_bearing(self, gate):
        """Engineer confirms bearing heat → refined to current_wear_bearing."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="轴承温度75度，烫手",
            selected_observation="轴承温度",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear_bearing"

    def test_ambiguous_feedback_refines_diagnosis_belt(self, gate):
        """Engineer confirms belt wear → refined to current_wear_belt."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="皮带齿面磨损严重",
            selected_observation="皮带张力",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear_belt"

    def test_ambiguous_feedback_refines_diagnosis_guide(self, gate):
        """Engineer confirms guide rail issue → refined to current_wear_guide."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="导轨爬行现象明显",
            selected_observation="导轨",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear_guide"

    def test_ambiguous_feedback_unknown_observation(self, gate):
        """Generic observation → no keyword match, generic refinement."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="一切看起来正常",
            selected_observation="",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "current_wear"  # unchanged

    def test_rejected_feedback_returns_empty(self, gate):
        """Rejected feedback returns no annotations."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="这不是机械磨损，是负载变化",
            authorization="rejected",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert refined == []

    def test_mecanical_bind_refinement_guide(self, gate):
        """tracking_mechanical_bind → guide lube issue."""
        ann = make_annotation("tracking_mechanical_bind", value=5000.0,
                             correlation=0.85, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="导轨干涩，润滑脂干了",
            selected_observation="导轨润滑状态",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "tracking_bind_guide"

    def test_mecanical_bind_refinement_backlash(self, gate):
        """tracking_mechanical_bind → backlash issue."""
        ann = make_annotation("tracking_mechanical_bind", value=5000.0,
                             correlation=0.85, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            response_text="千分表测量反向间隙50μm",
            selected_observation="丝杆间隙",
            authorization="pending",
            authorized_by="test-engineer",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) >= 1
        assert refined[0].category == "tracking_bind_backlash"


class TestHITLGateAuthorization:
    """Test the authorization gate for actionable recommendations."""

    @pytest.fixture
    def gate(self):
        return HITLGate()

    def make_rec(self, index=0x610B, action="set", target_value=320.0,
                 step_pct=0.0, reason="Resonance suppression", safety="Test carefully",
                 priority=1, triggered_by="resonance_detected"):
        return ParameterRecommendation(
            index=index, subindex=0, name="Notch Filter",
            action=action, target_value=target_value,
            step_pct=step_pct,
            reason=reason, safety=safety, priority=priority,
            triggered_by=triggered_by,
        )

    def test_approved_authorization_generates_actions(self, gate):
        """Approved feedback generates AuthorizedAction entries."""
        recs = [self.make_rec()]
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="test-engineer",
        )
        actions = gate.authorize(recs, feedback)
        assert len(actions) == 1
        assert isinstance(actions[0], AuthorizedAction)
        assert actions[0].safety_acknowledged is True
        assert len(actions[0].rollback_plan) > 0

    def test_rejected_authorization_returns_empty(self, gate):
        """Rejected feedback returns no authorized actions."""
        recs = [self.make_rec()]
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="rejected",
            authorized_by="test-engineer",
        )
        actions = gate.authorize(recs, feedback)
        assert actions == []
        assert len(gate.get_rejected_actions()) == 1

    def test_multiple_recommendations_all_authorized(self, gate):
        """All recommendations in a batch are authorized together."""
        recs = [
            self.make_rec(index=0x610B, action="set"),
            self.make_rec(index=0x60F9, action="decrease"),
        ]
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="test-engineer",
        )
        actions = gate.authorize(recs, feedback)
        assert len(actions) == 2

    def test_rollback_plan_for_set_action(self, gate):
        """set action → rollback mentions restoring original value."""
        rec = self.make_rec(action="set")
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="test-engineer",
        )
        actions = gate.authorize([rec], feedback)
        assert "原值" in actions[0].rollback_plan or "0x610B" in actions[0].rollback_plan

    def test_rollback_plan_for_increase_action(self, gate):
        """increase action → rollback mentions reverse direction."""
        rec = self.make_rec(index=0x60FB, action="increase", step_pct=25)
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="test-engineer",
        )
        actions = gate.authorize([rec], feedback)
        assert "decrease" in actions[0].rollback_plan.lower() or "反向" in actions[0].rollback_plan

    def test_authorized_actions_tracked(self, gate):
        """Authorized actions are stored and retrievable."""
        recs = [self.make_rec()]
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="test-engineer",
        )
        gate.authorize(recs, feedback)
        assert len(gate.get_authorized_actions()) == 1

    def test_prompt_cleared_after_feedback(self, gate):
        """Pending prompt is removed after feedback."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert gate.pending_count == 1

        feedback = EngineerFeedback(
            prompt_id=prompt.prompt_id,
            authorization="pending",
            authorized_by="test",
        )
        gate.process_feedback(prompt, feedback)
        assert gate.get_prompt(prompt.prompt_id) is None


class TestHITLGateState:
    """Test state management: reset, history, pending tracking."""

    @pytest.fixture
    def gate(self):
        return HITLGate()

    def test_reset_clears_all_state(self, gate):
        """reset() clears pending, history, authorized, rejected."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        gate.generate_prompt(ann)

        assert gate.pending_count > 0
        gate.reset()
        assert gate.pending_count == 0
        assert len(gate.get_history()) == 0
        assert len(gate.get_authorized_actions()) == 0
        assert len(gate.get_rejected_actions()) == 0

    def test_pending_prompts_list(self, gate):
        """pending_prompts property returns all pending."""
        ann = make_annotation("current_wear", value=160.0, baseline_mean=80.0)
        gate.classify(ann)
        gate.generate_prompt(ann)

        ann2 = make_annotation("resonance_detected", value=320.0, fundamental_hz=320.0)
        gate.classify(ann2)
        gate.generate_prompt(ann2)

        pending = gate.pending_prompts
        assert len(pending) == 2


class TestHITLTypes:
    """Test EngineerPrompt, EngineerFeedback, AuthorizedAction dataclasses."""

    def test_engineer_prompt_defaults(self):
        p = EngineerPrompt()
        assert p.prompt_id.startswith("hitl-")
        assert p.timestamp > 0
        assert p.expected_modalities == ["text"]

    def test_engineer_prompt_to_dict(self):
        p = EngineerPrompt(
            category="current_wear",
            classification="ambiguous",
            question="Test question",
            suggested_checks=["check 1", "check 2"],
        )
        d = p.to_dict()
        assert d["category"] == "current_wear"
        assert d["classification"] == "ambiguous"
        assert len(d["suggested_checks"]) == 2

    def test_engineer_feedback_defaults(self):
        f = EngineerFeedback()
        assert f.authorization == "pending"
        assert f.timestamp > 0
        assert f.is_approved is False
        assert f.is_rejected is False
        assert f.has_media is False

    def test_engineer_feedback_approval_flags(self):
        f = EngineerFeedback(authorization="approved")
        assert f.is_approved is True

        f2 = EngineerFeedback(authorization="rejected")
        assert f2.is_rejected is True

    def test_engineer_feedback_has_media(self):
        f = EngineerFeedback(media_paths=["/tmp/photo.jpg", "/tmp/audio.wav"])
        assert f.has_media is True

    def test_authorized_action_defaults(self):
        a = AuthorizedAction()
        assert a.safety_acknowledged is False
        assert a.executed is False
        assert a.rollback_plan == ""

    def test_authorized_action_to_dict(self):
        a = AuthorizedAction(
            safety_acknowledged=True,
            rollback_plan="Restore original value",
            executed=True,
            result="OK",
        )
        d = a.to_dict()
        assert d["safety_acknowledged"] is True
        assert d["rollback_plan"] == "Restore original value"
        assert d["executed"] is True
        assert d["result"] == "OK"

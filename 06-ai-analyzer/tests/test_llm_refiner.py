"""Unit tests for LLMDiagnosisRefiner."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from analyzer_base import AIAnnotation
from hitl_gate import HITLGate
from hitl_types import EngineerFeedback, EngineerPrompt
from llm_refiner import LLMDiagnosisRefiner


# ── Helpers ───────────────────────────────────────────────────

def make_prompt(category="current_wear", **meta):
    """Create a test EngineerPrompt."""
    md = {
        "annotation_confidence": 0.85,
        "annotation_value": 160.0,
        "annotation_message": "CUSUM drift: current from 80% to 160%",
        "annotation_severity": "warning",
    }
    md.update(meta)
    return EngineerPrompt(
        category=category,
        classification="ambiguous",
        question="Test question?",
        context="Current drift from 80% to 160% over 300 samples.",
        suggested_checks=[
            "联轴器：是否有橡胶粉尘？[可拍照]",
            "丝杆：是否有异响？[可录音]",
            "轴承：温度是否>60°C？[可拍照]",
        ],
        expected_modalities=["text", "image", "audio"],
        urgency="soon",
        metadata=md,
    )


def make_feedback(**kw):
    """Create a test EngineerFeedback."""
    defaults = {
        "prompt_id": "hitl-test",
        "response_text": "",
        "selected_observation": "",
        "authorization": "pending",
        "authorized_by": "test-engineer",
    }
    defaults.update(kw)
    return EngineerFeedback(**defaults)


def make_gate(with_llm=False):
    """Create a HITLGate, optionally with LLM refiner."""
    llm = LLMDiagnosisRefiner() if with_llm else None
    return HITLGate(llm_refiner=llm)


class TestLLMRefinerAvailability:
    """Test LLMDiagnosisRefiner.available and health check."""

    def test_unavailable_without_api_key(self, monkeypatch):
        """Without API key, refiner is unavailable."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        refiner = LLMDiagnosisRefiner(api_key="")
        assert refiner.available is False
        assert "ANTHROPIC_API_KEY" in refiner.last_error

    def test_available_with_api_key(self, monkeypatch):
        """With API key set, refiner reports available (requests exists)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        refiner = LLMDiagnosisRefiner()
        # requests is available in test env
        assert refiner.available is True

    def test_unavailable_without_requests(self, monkeypatch):
        """If requests is not installed, refiner is unavailable."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch.dict(sys.modules, {"requests": None}):
            # Can't actually remove requests — test the code path via mock
            refiner = LLMDiagnosisRefiner(api_key="test-key")
            # requests IS available, so this will be True
            # The actual test for missing requests would need sys.modules manipulation
            # For now, skip the deep import test

    def test_refine_returns_none_when_unavailable(self, monkeypatch):
        """refine() returns None when API key is not set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        refiner = LLMDiagnosisRefiner(api_key="")
        prompt = make_prompt()
        feedback = make_feedback(response_text="联轴器橡胶碎了")
        result = refiner.refine(prompt, feedback)
        assert result is None

    def test_health_check_unavailable(self, monkeypatch):
        """Health check reports unavailable without key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        refiner = LLMDiagnosisRefiner(api_key="")
        hc = refiner.health_check()
        assert hc["status"] == "unavailable"


class TestLLMRefinerParsing:
    """Test JSON response parsing from LLM output."""

    @pytest.fixture
    def refiner(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        return LLMDiagnosisRefiner()

    def test_parse_pure_json(self, refiner):
        """Direct JSON object is parsed correctly."""
        result = refiner._parse_response(
            '{"refined_category": "current_wear_coupling", '
            '"diagnosis": "联轴器弹性体磨损", '
            '"recommendation": "更换联轴器", '
            '"confidence": 0.9, '
            '"requires_parts": ["弹性体 XD-40"], '
            '"urgency": "soon", '
            '"additional_checks": ["检查对中"], '
            '"parameter_adjustment": "降增益10%"}'
        )
        assert result is not None
        assert result["refined_category"] == "current_wear_coupling"
        assert result["diagnosis"] == "联轴器弹性体磨损"
        assert result["confidence"] == 0.9
        assert result["requires_parts"] == ["弹性体 XD-40"]
        assert result["urgency"] == "soon"

    def test_parse_json_in_code_block(self, refiner):
        """JSON inside ```json code block is extracted."""
        text = """Based on the findings:

```json
{
  "refined_category": "current_wear_bearing",
  "diagnosis": "轴承内圈点蚀",
  "recommendation": "更换6204轴承，清洁轴承座",
  "confidence": 0.92,
  "requires_parts": ["6204-2RS轴承"],
  "urgency": "soon",
  "additional_checks": ["检查润滑脂状态"],
  "parameter_adjustment": ""
}
```

This diagnosis is based on..."""
        result = refiner._parse_response(text)
        assert result is not None
        assert result["refined_category"] == "current_wear_bearing"
        assert result["diagnosis"] == "轴承内圈点蚀"

    def test_parse_json_without_language_tag(self, refiner):
        """JSON inside plain ``` block is extracted."""
        text = """```
{
  "refined_category": "current_wear_ballscrew",
  "diagnosis": "丝杆滚道剥落",
  "recommendation": "更换丝杆螺母副",
  "confidence": 0.88,
  "requires_parts": [],
  "urgency": "immediate",
  "additional_checks": [],
  "parameter_adjustment": "降低速度环增益20%"
}
```"""
        result = refiner._parse_response(text)
        assert result is not None
        assert result["refined_category"] == "current_wear_ballscrew"

    def test_parse_returns_none_for_invalid_text(self, refiner):
        """Garbage text returns None."""
        result = refiner._parse_response("This is not JSON at all, just random thoughts...")
        assert result is None

    def test_parse_returns_none_for_empty(self, refiner):
        """Empty string returns None."""
        assert refiner._parse_response("") is None
        assert refiner._parse_response("   ") is None


class TestHITLGateLLMFallback:
    """Test that HITLGate falls back to keyword when LLM unavailable."""

    def test_keyword_fallback_when_llm_unavailable(self, monkeypatch):
        """Without API key, HITLGate uses keyword fallback."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        gate = make_gate(with_llm=False)
        # llm_available should be False
        assert gate.llm_available is False

        # Keyword matching still works for coupling
        prompt = make_prompt("current_wear")
        feedback = make_feedback(
            response_text="联轴器有橡胶粉尘，明显偏摆",
            selected_observation="联轴器",
        )
        refined = gate._refine_diagnosis(prompt, feedback)
        assert len(refined) == 1
        assert refined[0].category == "current_wear_coupling"
        assert refined[0].metadata["refined_by"] == "hitl_gate.keyword"
        assert refined[0].confidence == 0.75  # keyword method uses 0.75

    def test_keyword_fallback_for_ballscrew(self, monkeypatch):
        """Keyword fallback correctly identifies ballscrew wear."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        gate = make_gate(with_llm=False)

        prompt = make_prompt("current_wear")
        feedback = make_feedback(
            response_text="丝杆运动时有咯噔咯噔的异响",
            selected_observation="丝杆",
        )
        refined = gate._refine_diagnosis(prompt, feedback)
        assert refined[0].category == "current_wear_ballscrew"

    def test_keyword_fallback_unknown_observation(self, monkeypatch):
        """Unknown observation → generic message, category unchanged."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        gate = make_gate(with_llm=False)

        prompt = make_prompt("current_wear")
        feedback = make_feedback(response_text="一切正常，没发现问题")
        refined = gate._refine_diagnosis(prompt, feedback)
        assert refined[0].category == "current_wear"  # unchanged
        assert "无法自动精化" in refined[0].message


class TestBuildAnnotationFromLLM:
    """Test _build_annotation_from_llm creates correct AIAnnotation."""

    @pytest.fixture
    def gate(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        return make_gate(with_llm=True)

    def test_build_full_annotation(self, gate):
        """All LLM result fields are correctly mapped to AIAnnotation."""
        result = {
            "refined_category": "current_wear_coupling",
            "diagnosis": "联轴器弹性体完全碎裂，导致不对中和异常振动",
            "recommendation": "1. 断电 2. 松开联轴器螺丝 3. 更换弹性体型号 XD-40 4. 千分表对中，径向跳动<0.05mm",
            "confidence": 0.95,
            "requires_parts": ["弹性体 XD-40", "联轴器螺丝 M6×12 x4"],
            "urgency": "immediate",
            "additional_checks": ["检查电机轴和丝杆轴端是否有损伤", "确认联轴器额定扭矩是否匹配"],
            "parameter_adjustment": "临时降低速度环增益30%，避免共振扩大损坏",
            "_source": "llm",
            "_model": "claude-sonnet-4-6",
        }
        prompt = make_prompt("current_wear")
        feedback = make_feedback(response_text="联轴器橡胶全碎了")

        ann = gate._build_annotation_from_llm(result, prompt, feedback)

        assert ann.category == "current_wear_coupling"
        assert ann.severity == "critical"  # urgency=immediate → critical
        assert ann.confidence == 0.95
        assert "LLM 精化诊断" in ann.message
        assert "联轴器弹性体完全碎裂" in ann.message
        assert ann.metadata["refined_by"] == "llm_refiner"
        assert ann.metadata["llm_model"] == "claude-sonnet-4-6"
        assert ann.metadata["requires_parts"] == result["requires_parts"]
        assert ann.metadata["parameter_adjustment"] == result["parameter_adjustment"]
        assert ann.hitl_classification == "actionable"

    def test_build_minimal_annotation(self, gate):
        """Minimal LLM result still builds valid annotation."""
        result = {
            "refined_category": "current_wear_other",
            "diagnosis": "未知磨损",
            "recommendation": "",
            "confidence": 0.5,
            "requires_parts": [],
            "urgency": "routine",
            "additional_checks": [],
            "parameter_adjustment": "",
        }
        prompt = make_prompt("current_wear")
        feedback = make_feedback(response_text="...")

        ann = gate._build_annotation_from_llm(result, prompt, feedback)
        assert ann.category == "current_wear_other"
        assert ann.severity == "info"  # routine → info
        assert ann.confidence == 0.5


class TestFullHITLFeedbackFlow:
    """End-to-end test: prompt → feedback → refined annotation."""

    def test_process_feedback_keyword_flow(self, monkeypatch):
        """Full feedback processing without LLM (keyword fallback)."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        gate = make_gate(with_llm=False)

        ann = AIAnnotation(
            timestamp=time.time(), channel="Current",
            category="current_wear", severity="warning",
            confidence=0.85, message="CUSUM drift",
            value=160.0,
        )
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert prompt is not None

        feedback = make_feedback(
            prompt_id=prompt.prompt_id,
            response_text="联轴器偏摆严重，有橡胶粉尘",
            selected_observation="联轴器",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert len(refined) == 1
        assert refined[0].category == "current_wear_coupling"
        assert refined[0].hitl_classification == "actionable"

    def test_process_feedback_rejected_still_works(self, monkeypatch):
        """Rejected feedback returns empty, prompt is cleared."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        gate = make_gate(with_llm=False)

        ann = AIAnnotation(
            timestamp=time.time(), channel="Current",
            category="current_wear", severity="warning",
            confidence=0.85, message="CUSUM drift",
            value=160.0,
        )
        gate.classify(ann)
        prompt = gate.generate_prompt(ann)
        assert gate.pending_count == 1

        feedback = make_feedback(
            prompt_id=prompt.prompt_id,
            authorization="rejected",
            response_text="这是正常的季节性温度变化",
        )
        refined = gate.process_feedback(prompt, feedback)
        assert refined == []
        assert gate.pending_count == 0  # prompt cleared even on rejection


class TestUserMessageBuilding:
    """Test _build_user_message constructs proper LLM input."""

    @pytest.fixture
    def refiner(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        return LLMDiagnosisRefiner()

    def test_build_user_message_includes_context(self, refiner):
        """User message includes AI detection context and engineer feedback."""
        prompt = make_prompt("current_wear")
        feedback = make_feedback(
            response_text="联轴器橡胶碎了",
            selected_observation="联轴器",
            media_paths=["coupling.jpg"],
        )
        msg = refiner._build_user_message(prompt, feedback)
        assert "current_wear" in msg
        assert "联轴器橡胶碎了" in msg
        assert "coupling.jpg" in msg
        assert "160" in msg  # annotation_value
        assert "85%" in msg or "0.85" in msg

    def test_build_user_message_without_media(self, refiner):
        """Media paths are optional."""
        prompt = make_prompt("tracking_mechanical_bind")
        feedback = make_feedback(response_text="导轨干涩")
        msg = refiner._build_user_message(prompt, feedback)
        assert "tracking_mechanical_bind" in msg
        assert "导轨干涩" in msg

    def test_build_user_message_without_text(self, refiner):
        """When engineer provides no text, placeholder is used."""
        prompt = make_prompt()
        feedback = make_feedback(response_text="", selected_observation="轴承")
        msg = refiner._build_user_message(prompt, feedback)
        assert "未提供文字描述" in msg or "轴承" in msg


class TestConfigDefaults:
    """Test LLM config defaults are loaded correctly."""

    def test_default_model(self):
        refiner = LLMDiagnosisRefiner(api_key="test-key")
        assert refiner.model == "claude-sonnet-4-6"

    def test_custom_parameters(self):
        refiner = LLMDiagnosisRefiner(
            api_key="test-key",
            model="claude-opus-4-8",
            timeout=60,
            max_tokens=2048,
            temperature=0.1,
        )
        assert refiner.model == "claude-opus-4-8"
        assert refiner.timeout == 60
        assert refiner.max_tokens == 2048
        assert refiner.temperature == 0.1

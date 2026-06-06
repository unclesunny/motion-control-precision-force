"""Unit tests for AIAnnotator (confidence calibration + severity escalation)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from ai_annotator import AIAnnotator
from analyzer_base import AIAnnotation


class TestAIAnnotator:
    @pytest.fixture
    def annotator(self):
        return AIAnnotator()

    def make_annotation(self, **overrides) -> AIAnnotation:
        defaults = {
            "timestamp": 0.0,
            "channel": "Current",
            "category": "current_saturation",
            "severity": "info",
            "confidence": 0.8,
            "message": "Test message",
            "suggestion": "",
            "value": 250.0,
            "metadata": {},
        }
        defaults.update(overrides)
        return AIAnnotation(**defaults)

    def test_confidence_calibration(self, annotator):
        """Confidence should be calibrated through sigmoid."""
        ann = self.make_annotation(confidence=0.5)
        result = annotator.calibrate([ann])
        # 0.5 raw → ~0.5 calibrated (center of sigmoid)
        assert 0.4 <= result[0].confidence <= 0.6

    def test_low_confidence_suppressed(self, annotator):
        """Very low raw confidence should map to near-zero calibrated."""
        ann = self.make_annotation(confidence=0.05)
        result = annotator.calibrate([ann])
        assert result[0].confidence < 0.1

    def test_high_confidence_preserved(self, annotator):
        """Very high raw confidence should map to near-1.0 calibrated."""
        ann = self.make_annotation(confidence=0.99)
        result = annotator.calibrate([ann])
        assert result[0].confidence > 0.8

    def test_severity_escalation_consecutive(self, annotator):
        """Three consecutive same-category annotations should escalate to warning."""
        ch_names = ["Current"]
        cat = "current_saturation"

        # First: info
        r1 = annotator.calibrate([self.make_annotation(channel="Current", category=cat)])
        assert r1[0].severity == "info"

        # Second: still info (consecutive=2)
        r2 = annotator.calibrate([self.make_annotation(channel="Current", category=cat)])
        assert r2[0].severity == "info"

        # Third: escalates to warning
        r3 = annotator.calibrate([self.make_annotation(channel="Current", category=cat)])
        assert r3[0].severity == "warning"

    def test_severity_escalation_critical(self, annotator):
        """Ten consecutive should escalate to critical."""
        cat = "current_wear"
        severity = "info"
        for i in range(12):
            results = annotator.calibrate([self.make_annotation(category=cat)])
            severity = results[0].severity
        assert severity == "critical"

    def test_suggestion_populated(self, annotator):
        """Annotation should get a suggestion from templates."""
        ann = self.make_annotation(category="current_saturation")
        result = annotator.calibrate([ann])
        assert len(result[0].suggestion) > 0
        assert "acceleration" in result[0].suggestion.lower() or "load" in result[0].suggestion.lower()

    def test_different_channels_independent(self, annotator):
        """Consecutive count should be per (channel, category) key."""
        # 3 warnings on Current
        for _ in range(3):
            annotator.calibrate([self.make_annotation(channel="Current", category="current_saturation")])
        # 1 annotation on Foll.Err — should start fresh
        r = annotator.calibrate([self.make_annotation(channel="Foll.Err", category="tracking_gain_deficiency")])
        assert r[0].severity == "info"

    def test_decay_on_non_detection(self, annotator):
        """Consecutive count should decay when no annotation for a key."""
        cat = "current_saturation"
        # Build up 2 consecutive
        for _ in range(2):
            annotator.calibrate([self.make_annotation(category=cat)])
        # One empty frame (no annotation for this key)
        annotator.calibrate([])
        # Next should have consecutive=1 again (decayed)
        r = annotator.calibrate([self.make_annotation(category=cat)])
        assert r[0].severity == "info"

    def test_reset(self, annotator):
        for _ in range(5):
            annotator.calibrate([self.make_annotation()])
        annotator.reset()
        r = annotator.calibrate([self.make_annotation()])
        assert r[0].severity == "info"

"""Unit tests for ParameterRecommender."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from analyzer_base import AIAnnotation
from parameter_recommender import ParameterRecommender, ParameterRecommendation


class TestParameterRecommender:
    @pytest.fixture
    def recommender(self):
        return ParameterRecommender(brand=None)  # CiA 402 standard

    @pytest.fixture
    def recommender_yaskawa(self):
        return ParameterRecommender(brand="yaskawa-sigma7")

    def make_annotation(self, category, **metadata):
        return AIAnnotation(
            timestamp=0.0, channel="Velocity", category=category,
            severity="warning", confidence=0.9,
            message=f"Test {category}", suggestion="Test",
            value=75.0, metadata=metadata,
        )

    # ── Basic mapping ─────────────────────────────────────

    def test_resonance_to_notch_filter(self, recommender):
        """Resonance detection → notch filter configuration."""
        ann = self.make_annotation("resonance_detected", fundamental_hz=75.0)
        params = recommender.recommend([ann])
        assert len(params) >= 2  # notch filter + velocity gain reduction

        notch_params = [p for p in params if p.index == 0x610B]
        assert len(notch_params) == 1
        assert notch_params[0].action == "set"
        assert notch_params[0].target_value == 75.0

    def test_resonance_yaskawa_brand(self, recommender_yaskawa):
        """Yaskawa brand → uses Pn409 (0x2409) instead of 0x610B."""
        ann = self.make_annotation("resonance_detected", fundamental_hz=75.0)
        params = recommender_yaskawa.recommend([ann])
        assert len(params) >= 2

        # Should include Yaskawa-specific notch index
        yaskawa_notch = [p for p in params if p.index == 0x2409]
        assert len(yaskawa_notch) == 1
        assert yaskawa_notch[0].target_value == 75.0

    # ── Tracking error ─────────────────────────────────────

    def test_gain_deficiency_recommends_increase(self, recommender):
        """Tracking gain deficiency → increase position gain."""
        ann = self.make_annotation("tracking_gain_deficiency")
        params = recommender.recommend([ann])
        assert len(params) >= 1

        gain_params = [p for p in params if p.index == 0x60FB]
        assert len(gain_params) == 1
        assert gain_params[0].action == "increase"

    def test_mechanical_bind_dual_recommendation(self, recommender):
        """Mechanical bind → widen window AND increase gain."""
        ann = self.make_annotation("tracking_mechanical_bind")
        params = recommender.recommend([ann])

        window_params = [p for p in params if p.index == 0x6065]
        gain_params = [p for p in params if p.index == 0x60FB]
        assert len(window_params) == 1
        assert len(gain_params) == 1

    # ── Current anomalies ──────────────────────────────────

    def test_saturation_recommends_reduce_load(self, recommender):
        """Current saturation → reduce torque limit + acceleration."""
        ann = self.make_annotation("current_saturation")
        params = recommender.recommend([ann])
        assert len(params) >= 2

        torque_params = [p for p in params if p.index == 0x6072]
        accel_params = [p for p in params if p.index == 0x6083]
        assert len(torque_params) == 1
        assert len(accel_params) == 1
        assert torque_params[0].action == "decrease"
        assert accel_params[0].action == "decrease"

    def test_sensor_fault_no_parameter_fix(self, recommender):
        """Sensor fault → no parameter fix (hardware issue)."""
        ann = self.make_annotation("current_sensor_fault")
        params = recommender.recommend([ann])
        assert params == []  # hardware issue, no tuning fix

    # ── Priority ordering ──────────────────────────────────

    def test_priority_ordering(self, recommender):
        """Multiple anomalies → sorted by priority."""
        anns = [
            self.make_annotation("tracking_gain_deficiency"),
            self.make_annotation("resonance_detected", fundamental_hz=75.0),
            self.make_annotation("current_saturation"),
        ]
        params = recommender.recommend(anns)
        priorities = [p.priority for p in params]
        assert priorities == sorted(priorities), f"Not sorted: {priorities}"

    # ── Deduplication ──────────────────────────────────────

    def test_deduplicate_same_index_category(self, recommender):
        """Same index + same category → only one recommendation."""
        ann1 = self.make_annotation("resonance_detected", fundamental_hz=75.0)
        ann2 = self.make_annotation("resonance_detected", fundamental_hz=80.0)
        params = recommender.recommend([ann1, ann2])

        notch_count = sum(1 for p in params if p.index == 0x610B)
        assert notch_count == 1  # deduplicated

    # ── Empty input ────────────────────────────────────────

    def test_empty_annotations(self, recommender):
        assert recommender.recommend([]) == []

    # ── format ─────────────────────────────────────────────

    def test_format_output(self, recommender):
        ann = self.make_annotation("resonance_detected", fundamental_hz=75.0)
        params = recommender.recommend([ann])
        output = recommender.format(params)
        assert "0x610B" in output
        assert "Notch" in output or "notch" in output.lower()

    # ── ParameterRecommendation dataclass ──────────────────

    def test_recommendation_dataclass(self):
        rec = ParameterRecommendation(
            index=0x610B, subindex=0, name="Notch Filter",
            action="set", target_value=75.0, reason="Resonance",
            safety="Test safety", priority=1, triggered_by="resonance_detected",
        )
        assert rec.index_hex == "0x610B"
        d = rec.to_dict()
        assert d["index"] == "0x610B"
        assert d["action"] == "set"
        assert d["target_value"] == 75.0

    # ── Cross-brand parameter resolution ───────────────────

    def test_delta_a3_uses_standard_indices(self):
        """Delta A3 uses CiA 402 standard indices (no aliases needed)."""
        rec = ParameterRecommender(brand="delta-a3")
        ann = AIAnnotation(
            timestamp=0.0, channel="Velocity", category="resonance_detected",
            severity="warning", confidence=0.9,
            message="Resonance at 75Hz", suggestion="Set notch",
            value=75.0, metadata={"fundamental_hz": 75.0},
        )
        params = rec.recommend([ann])
        notch = [p for p in params if p.index == 0x610B]
        assert len(notch) == 1  # Delta uses standard CiA 402 notch index
        assert notch[0].target_value == 75.0

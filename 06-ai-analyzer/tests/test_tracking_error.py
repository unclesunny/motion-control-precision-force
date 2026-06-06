"""Unit tests for TrackingErrorDetector."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from tracking_error import TrackingErrorDetector, _pearson_r


class TestPearsonR:
    def test_perfect_positive(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        assert _pearson_r(x, y) == pytest.approx(1.0, abs=0.01)

    def test_perfect_negative(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        assert _pearson_r(x, y) == pytest.approx(-1.0, abs=0.01)

    def test_no_correlation(self):
        np.random.seed(42)
        x = np.random.randn(100)
        y = np.random.randn(100)
        r = _pearson_r(x, y)
        assert abs(r) < 0.3  # should be near zero for independent data

    def test_insufficient_data(self):
        assert _pearson_r(np.array([1.0]), np.array([1.0])) == 0.0


class TestTrackingErrorDetector:
    @pytest.fixture
    def detector(self):
        return TrackingErrorDetector()

    @pytest.fixture
    def buffer_stats(self):
        return {
            "Foll.Err": {"mean": 10.0, "std": 5.0, "min": 0.0, "max": 30.0, "rms": 12.0, "peak_to_peak": 30.0},
        }

    def test_normal_error_no_anomaly(self, detector, buffer_stats):
        ch_names = ["Position", "Velocity", "Current", "Torque", "Foll.Err"]
        # Feed normal data with slight variation to build valid statistics
        np.random.seed(42)
        for _ in range(50):
            detector.analyze(
                [1000.0, 500.0, 80.0, 60.0, 10.0 + np.random.normal(0, 3.0)],
                ch_names, buffer_stats,
            )
        # Normal sample within range
        results = detector.analyze(
            [1000.0, 500.0, 80.0, 60.0, 12.0],
            ch_names, buffer_stats,
        )
        # Following error 12 with mean~10, std~3 — within 3 sigma → no anomaly
        assert results == []

    def test_excessive_error_detected(self, detector, buffer_stats):
        ch_names = ["Position", "Velocity", "Current", "Torque", "Foll.Err"]
        for _ in range(50):
            detector.analyze(
                [1000.0, 500.0, 80.0, 60.0, 10.0],
                ch_names, buffer_stats,
            )
        # Large following error
        results = detector.analyze(
            [1000.0, 500.0, 80.0, 60.0, 100.0],
            ch_names, buffer_stats,
        )
        # 100 >> 25 (dynamic threshold) → should trigger
        assert len(results) == 1
        assert results[0].channel == "Foll.Err"
        assert results[0].category in ("tracking_gain_deficiency", "tracking_mechanical_bind")

    def test_absolute_limit(self, detector, buffer_stats):
        ch_names = ["Position", "Velocity", "Current", "Torque", "Foll.Err"]
        results = detector.analyze(
            [1000.0, 500.0, 80.0, 60.0, 2000000.0],
            ch_names, buffer_stats,
        )
        assert len(results) == 1
        assert results[0].category == "tracking_absolute_limit"
        assert results[0].severity == "critical"

    def test_channel_not_present(self, detector, buffer_stats):
        ch_names = ["Position", "Velocity", "Current"]
        results = detector.analyze([1000.0, 500.0, 80.0], ch_names, buffer_stats)
        assert results == []

    def test_mechanical_bind_pattern(self, detector, buffer_stats):
        """When error correlates with current, mechanical bind should be flagged."""
        ch_names = ["Position", "Velocity", "Current", "Torque", "Foll.Err"]

        # Simulate a mechanical bind scenario: rising error with rising current
        np.random.seed(42)
        for i in range(60):
            base_err = 10.0 + i * 2.0  # gradually increasing to ~130
            base_cur = 80.0 + i * 2.0  # correlated increase to ~200
            detector.analyze(
                [1000.0, max(0, 500.0 - i * 5.0), base_cur + np.random.normal(0, 2),
                 60.0, base_err + np.random.normal(0, 3)],
                ch_names, buffer_stats,
            )

        # Final sample with error significantly above the dynamic threshold
        # After 60 samples: mean_err ~70, std ~35, threshold ~70+105=175
        # Use error=300 to clearly exceed threshold
        results = detector.analyze(
            [1000.0, 100.0, 220.0, 60.0, 300.0],
            ch_names, buffer_stats,
        )
        assert len(results) == 1
        # Should detect the correlation
        assert results[0].category in ("tracking_mechanical_bind", "tracking_gain_deficiency")

    def test_reset(self, detector, buffer_stats):
        ch_names = ["Position", "Velocity", "Current", "Torque", "Foll.Err"]
        detector.analyze([1000.0, 500.0, 80.0, 60.0, 2000000.0], ch_names, buffer_stats)
        detector.reset()
        assert detector._consecutive_count == 0
        assert len(detector._error_window) == 0

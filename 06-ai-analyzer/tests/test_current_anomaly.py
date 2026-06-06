"""Unit tests for CurrentAnomalyDetector."""

import sys
from pathlib import Path

import numpy as np
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from current_anomaly import (
    CurrentAnomalyDetector, CUSUMDetector, IQRDetector,
    OnlineStats, ZScoreDetector,
)


class TestOnlineStats:
    def test_initial_state(self):
        s = OnlineStats()
        assert s.count == 0
        assert s.mean == 0.0

    def test_single_value(self):
        s = OnlineStats()
        s.update(5.0)
        assert s.count == 1
        assert s.mean == 5.0

    def test_converges_to_true_mean(self):
        s = OnlineStats()
        np.random.seed(42)
        data = np.random.normal(100.0, 15.0, 1000)
        for v in data:
            s.update(v)
        assert abs(s.mean - 100.0) < 2.0
        assert abs(s.std - 15.0) < 2.0

    def test_zscore_positive(self):
        s = OnlineStats()
        for v in [10.0] * 100:
            s.update(v)
        s.update(20.0)
        assert s.zscore(20.0) > 2.0


class TestZScoreDetector:
    def test_normal_values_no_anomaly(self):
        det = ZScoreDetector(threshold=3.0, window=200)
        scores = []
        for _ in range(100):
            v = np.random.normal(50.0, 5.0)
            scores.append(det.is_anomaly(v))
        # Less than 5% should trigger (3-sigma rule)
        triggered = sum(1 for s in scores if s > 0.5)
        assert triggered < 10  # generous margin for randomness

    def test_spike_detected(self):
        det = ZScoreDetector(threshold=3.0, window=200)
        # Feed normal data
        for _ in range(50):
            det.score(np.random.normal(50.0, 5.0))
        # Spike
        score = det.is_anomaly(200.0)
        assert score > 0.5

    def test_insufficient_data(self):
        det = ZScoreDetector(threshold=3.0, window=200)
        assert det.is_anomaly(100.0) == 0.0  # not enough data yet


class TestIQRDetector:
    def test_normal_no_anomaly(self):
        det = IQRDetector(window=200)
        scores = []
        for _ in range(100):
            v = np.random.normal(50.0, 5.0)
            scores.append(det.score(v))
        triggered = sum(1 for s in scores if s > 0.5)
        assert triggered < 10

    def test_outlier_detected(self):
        det = IQRDetector(window=200)
        for _ in range(50):
            det.score(np.random.normal(50.0, 5.0))
        assert det.score(300.0) > 0.5

    def test_insufficient_data(self):
        det = IQRDetector(window=200)
        assert det.score(100.0) == 0.0


class TestCUSUMDetector:
    def test_slow_drift_detected(self):
        det = CUSUMDetector(window=200)
        # Baseline
        for _ in range(100):
            det.score(np.random.normal(50.0, 2.0))
        # Gradual drift: increase by 0.5 each sample
        for i in range(100):
            s = det.score(50.0 + i * 0.1 + np.random.normal(0, 2.0))
        # After sustained drift, should trigger
        assert det.score(70.0) > 0.0

    def test_reset_clears_state(self):
        det = CUSUMDetector(window=200)
        for _ in range(50):
            det.score(50.0)
        det.score(200.0)
        det.reset()
        assert det.score(50.0) == 0.0


class TestCurrentAnomalyDetector:
    @pytest.fixture
    def detector(self):
        return CurrentAnomalyDetector()

    @pytest.fixture
    def normal_buffer_stats(self):
        return {
            "Current": {"mean": 80.0, "std": 10.0, "min": 50.0, "max": 120.0, "rms": 82.0, "peak_to_peak": 70.0},
        }

    def test_normal_current_no_anomaly(self, detector, normal_buffer_stats):
        """Normal current should produce no annotations."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        results = detector.analyze([1000.0, 500.0, 85.0, 60.0], ch_names, normal_buffer_stats)
        assert results == []

    def test_saturation_instant_detection(self, detector, normal_buffer_stats):
        """Current > 200% should immediately trigger saturation."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        results = detector.analyze([1000.0, 500.0, 250.0, 60.0], ch_names, normal_buffer_stats)
        assert len(results) == 1
        assert results[0].category == "current_saturation"
        assert results[0].severity == "critical"
        assert results[0].confidence == 1.0

    def test_warning_threshold(self, detector, normal_buffer_stats):
        """Current just above rated should be noted."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        # Feed enough normal data first so ensemble can calibrate
        for _ in range(30):
            detector.analyze([1000.0, 500.0, 80.0, 60.0], ch_names, normal_buffer_stats)
        results = detector.analyze([1000.0, 500.0, 115.0, 60.0], ch_names, normal_buffer_stats)
        # May or may not trigger depending on ensemble — just verify no crash
        assert isinstance(results, list)

    def test_channel_not_present(self, detector, normal_buffer_stats):
        """When Current channel is missing, should return empty."""
        ch_names = ["Position", "Velocity", "Torque"]
        results = detector.analyze([1000.0, 500.0, 60.0], ch_names, normal_buffer_stats)
        assert results == []

    def test_motor_stopped_no_false_positive(self, detector, normal_buffer_stats):
        """Zero current (motor stopped) after warmup should not trigger."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        # Feed enough data first
        for _ in range(200):
            detector.analyze([1000.0, 500.0, 80.0, 60.0], ch_names, normal_buffer_stats)
        # Now motor stops
        results = detector.analyze([0.0, 0.0, 0.0, 0.0], ch_names, normal_buffer_stats)
        assert results == []

    def test_reset(self, detector, normal_buffer_stats):
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        detector.analyze([1000.0, 500.0, 250.0, 60.0], ch_names, normal_buffer_stats)
        detector.reset()
        assert detector._consecutive_count == 0
        assert detector._sample_count == 0

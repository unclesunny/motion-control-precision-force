"""
Tests for CrossAxisAnalyzer — the 4th detector for multi-axis analysis.

Verifies all four sub-detectors with synthetic multi-axis data:
  1. BusSagDetector — simultaneous current drop across 3 axes
  2. ContouringDetector — XY combined following error > threshold
  3. RingHealthDetector — WKC cascade across slave positions
  4. MechanicalCouplingDetector — vibration vs partner position bins
"""

import math
import time

import numpy as np
import pytest

from ai_analyzer import CrossAxisAnalyzer, AxisSnapshot
from ai_analyzer.config import CROSS_AXIS_CONFIG


# ── Helpers ──────────────────────────────────────────────────────

CH_NAMES = ["Position", "Velocity", "Current", "Torque",
            "Foll.Err", "DIO", "Status", "OpMode"]


def make_snapshot(axis_id: str, slave: int, values: list,
                  stats: dict = None, annotations: list = None) -> AxisSnapshot:
    """Quick AxisSnapshot builder."""
    return AxisSnapshot(
        axis_id=axis_id,
        slave_position=slave,
        values=values,
        channel_names=CH_NAMES,
        buffer_stats=stats or {},
        annotations=annotations or [],
        timestamp=time.time(),
    )


def make_normal_axes() -> dict:
    """3-axis system with normal operation values."""
    return {
        "X": make_snapshot("X", 0, [1000.0, 500.0, 80.0, 60.0, 5.0, 0.0, 0x0237, 1.0]),
        "Y": make_snapshot("Y", 1, [2000.0, 300.0, 75.0, 55.0, 3.0, 0.0, 0x0237, 1.0]),
        "Z": make_snapshot("Z", 2, [500.0, 200.0, 85.0, 50.0, 4.0, 0.0, 0x0237, 1.0]),
    }


# ══════════════════════════════════════════════════════════════════
# BusSagDetector
# ══════════════════════════════════════════════════════════════════

class TestBusSagDetector:
    """Verify power bus sag detection across multiple axes."""

    def test_normal_operation_no_sag(self):
        analyzer = CrossAxisAnalyzer()
        axes = make_normal_axes()
        results = []
        for _ in range(50):
            results = analyzer.analyze(axes)
        sag_annotations = [a for a in results if a.category == "cross_bus_sag"]
        assert len(sag_annotations) == 0, "No sag expected during normal operation"

    def test_simultaneous_current_drop_triggers_sag(self):
        """When all 3 axes drop current together, bus sag fires."""
        analyzer = CrossAxisAnalyzer()

        # Prime with normal data (80% current) — fills first third of window
        cur_idx = CH_NAMES.index("Current")
        for _ in range(60):
            analyzer.analyze(make_normal_axes())

        # Inject simultaneous severe current drop — from 80% → 20% (75% drop)
        axes_sag = make_normal_axes()
        for aid in axes_sag:
            vals = list(axes_sag[aid].values)
            vals[cur_idx] = 20.0
            axes_sag[aid] = make_snapshot(aid, axes_sag[aid].slave_position, vals)

        # Feed sag until window comparison fires
        results = []
        for _ in range(100):
            results = analyzer.analyze(axes_sag)

        sag_annotations = [a for a in results if a.category == "cross_bus_sag"]
        assert len(sag_annotations) > 0, (
            f"Expected bus sag detection after sustained 75% current drop. "
            f"Got categories: {[a.category for a in results]}"
        )

    def test_single_axis_drop_no_sag(self):
        """Only one axis dropping should NOT trigger bus sag."""
        analyzer = CrossAxisAnalyzer()

        for _ in range(60):
            analyzer.analyze(make_normal_axes())

        # Only Axis X drops
        axes = make_normal_axes()
        cur_idx = CH_NAMES.index("Current")
        vals = list(axes["X"].values)
        vals[cur_idx] = 35.0
        axes["X"] = make_snapshot("X", 0, vals)

        results = []
        for _ in range(80):
            results = analyzer.analyze(axes)

        sag = [a for a in results if a.category == "cross_bus_sag"]
        assert len(sag) == 0, "Single axis drop should not trigger bus sag"

    def test_metadata_has_involved_axes(self):
        """Cross-axis annotations must include involved_axes for HITL routing."""
        analyzer = CrossAxisAnalyzer()

        for _ in range(60):
            analyzer.analyze(make_normal_axes())

        axes_sag = make_normal_axes()
        cur_idx = CH_NAMES.index("Current")
        for aid in axes_sag:
            vals = list(axes_sag[aid].values)
            vals[cur_idx] = 42.0
            axes_sag[aid] = make_snapshot(aid, axes_sag[aid].slave_position, vals)

        for _ in range(80):
            results = analyzer.analyze(axes_sag)

        for a in results:
            if a.category.startswith("cross_"):
                assert a.metadata.get("cross_axis") is True
                assert "involved_axes" in a.metadata


# ══════════════════════════════════════════════════════════════════
# ContouringDetector
# ══════════════════════════════════════════════════════════════════

class TestContouringDetector:
    """Verify multi-axis trajectory contouring error detection."""

    def test_normal_trajectory_no_contouring_error(self):
        analyzer = CrossAxisAnalyzer()
        # Only enable contouring
        analyzer.disable_detector("bus_sag")
        analyzer.disable_detector("ring_health")
        analyzer.disable_detector("mechanical_coupling")

        for _ in range(50):
            results = analyzer.analyze(make_normal_axes())

        contouring = [a for a in results if a.category == "cross_contouring_error"]
        assert len(contouring) == 0

    def test_combined_xy_error_triggers_contouring(self):
        """When X and Y foll.err spike above the normal dynamic threshold,
        combined orthogonal deviation triggers contouring error.

        The detector's sliding window needs the baseline to stay low.
        We prime with 100 normal samples (foll.err ≈ 5), then inject
        a single spike at 500 — the window is still mostly normal data,
        so 3σ threshold ≈ 15, combined threshold ≈ 22.5, spike=707 → fire.
        """
        analyzer = CrossAxisAnalyzer()
        analyzer.disable_detector("bus_sag")
        analyzer.disable_detector("ring_health")
        analyzer.disable_detector("mechanical_coupling")

        ferr_idx = CH_NAMES.index("Foll.Err")

        # Prime with 100 normal samples — window stats: μ≈5, σ≈0
        for _ in range(100):
            analyzer.analyze(make_normal_axes())

        # Inject 1 spike, then go back to normal. The spike should fire
        # before the window adapts to the new mean.
        axes_spike = make_normal_axes()
        vals_x = list(axes_spike["X"].values)
        vals_x[ferr_idx] = 500.0
        axes_spike["X"] = make_snapshot("X", 0, vals_x)

        vals_y = list(axes_spike["Y"].values)
        vals_y[ferr_idx] = 500.0
        axes_spike["Y"] = make_snapshot("Y", 1, vals_y)

        results = []
        # Interleave: 1 spike, then 5 normal, repeat — keeps window stats low
        for _ in range(10):
            results.extend(analyzer.analyze(axes_spike))
            for _ in range(5):
                results.extend(analyzer.analyze(make_normal_axes()))

        contouring = [a for a in results if a.category == "cross_contouring_error"]
        assert len(contouring) > 0, (
            f"Expected contouring error for high combined XY deviation. "
            f"Categories: {[a.category for a in results]}"
        )

    def test_contouring_metadata_has_axis_pair(self):
        analyzer = CrossAxisAnalyzer()
        analyzer.disable_detector("bus_sag")
        analyzer.disable_detector("ring_health")
        analyzer.disable_detector("mechanical_coupling")

        for _ in range(40):
            analyzer.analyze(make_normal_axes())

        ferr_idx = CH_NAMES.index("Foll.Err")
        axes = make_normal_axes()
        for aid in ["X", "Y"]:
            vals = list(axes[aid].values)
            vals[ferr_idx] = 80.0
            axes[aid] = make_snapshot(aid, axes[aid].slave_position, vals)

        for _ in range(60):
            results = analyzer.analyze(axes)

        for a in results:
            if a.category == "cross_contouring_error":
                assert "axis_pair" in a.metadata
                assert a.metadata["axis_pair"] == ["X", "Y"]


# ══════════════════════════════════════════════════════════════════
# RingHealthDetector
# ══════════════════════════════════════════════════════════════════

class TestRingHealthDetector:
    """Verify EtherCAT ring error cascade detection."""

    def test_healthy_ring_no_errors(self):
        analyzer = CrossAxisAnalyzer()
        healthy = {0: False, 1: False, 2: False, 3: False}
        for _ in range(30):
            results = analyzer.analyze(make_normal_axes(), slave_errors=healthy)
        ring = [a for a in results if a.category.startswith("cross_ring")]
        assert len(ring) == 0

    def test_cascade_from_slave_1_detected(self):
        """Slave 1 errors, then slave 2 errors, slave 3 errors → cascade."""
        analyzer = CrossAxisAnalyzer()

        # Prime with healthy state
        healthy = {0: False, 1: False, 2: False, 3: False}
        for _ in range(30):
            analyzer.analyze(make_normal_axes(), slave_errors=healthy)

        # Cascade: slave 1 fails → 2 and 3 also fail
        cascade = {0: False, 1: True, 2: True, 3: True}
        results = []
        for _ in range(20):
            results = analyzer.analyze(make_normal_axes(), slave_errors=cascade)

        ring = [a for a in results if a.category == "cross_ring_cascade"]
        assert len(ring) > 0, (
            f"Expected ring cascade detection. "
            f"Categories: {[a.category for a in results]}"
        )

        if ring:
            metadata = ring[0].metadata
            assert metadata["first_error_slave"] == 1
            assert metadata["cascade_depth"] >= 2

    def test_isolated_error_no_cascade(self):
        """A single slave erroring while others healthy → NO cascade alarm."""
        analyzer = CrossAxisAnalyzer()

        healthy = {0: False, 1: False, 2: False, 3: False}
        for _ in range(30):
            analyzer.analyze(make_normal_axes(), slave_errors=healthy)

        # Only slave 2 has occasional errors
        isolated = {0: False, 1: False, 2: True, 3: False}
        results = []
        for _ in range(20):
            results = analyzer.analyze(make_normal_axes(), slave_errors=isolated)

        cascade = [a for a in results if a.category == "cross_ring_cascade"]
        assert len(cascade) == 0, "Isolated error should not trigger cascade"

    def test_sporadic_errors_emi_warning(self):
        """Multiple slaves with occasional errors → EMI/RFI warning."""
        analyzer = CrossAxisAnalyzer()

        # Prime
        healthy = {0: False, 1: False, 2: False, 3: False, 4: False}
        for _ in range(30):
            analyzer.analyze(make_normal_axes(), slave_errors=healthy)

        # Intermittent errors across random slaves
        import random
        random.seed(42)
        results = []
        for _ in range(30):
            sporadic = {
                i: (random.random() < 0.15)  # 15% error rate per slave
                for i in range(5)
            }
            results = analyzer.analyze(make_normal_axes(), slave_errors=sporadic)

        emi = [a for a in results if a.category == "cross_ring_emi"]
        # May or may not trigger depending on random seed — just verify no crash


# ══════════════════════════════════════════════════════════════════
# MechanicalCouplingDetector
# ══════════════════════════════════════════════════════════════════

class TestMechanicalCouplingDetector:
    """Verify cross-axis mechanical coupling via vibration correlation."""

    def test_uncoupled_axes_no_detection(self):
        analyzer = CrossAxisAnalyzer()
        for _ in range(30):
            results = analyzer.analyze(make_normal_axes())
        coupling = [a for a in results if a.category == "cross_mechanical_coupling"]
        assert len(coupling) == 0

    def test_position_dependent_vibration_triggers_coupling(self):
        """When Axis Y vibration magnitude changes with Axis X position,
        mechanical coupling is detected.

        Default coupling pair: ("Y", "X") → source=Y, target=X.
        Y's Velocity FFT peak is position-dependent on X's position.
        """
        analyzer = CrossAxisAnalyzer()

        n_bins = 8
        positions = np.linspace(-500, 500, n_bins)
        # Bin 3 (middle) has high vibration, others low
        high_bin = 3

        for cycle in range(200):
            bin_idx = cycle % n_bins
            pos_x = positions[bin_idx]

            # Y's Velocity FFT peak magnitude depends on X's position
            fft_mag = 50.0 if bin_idx == high_bin else 5.0

            # Source = Y: has Velocity FFT stats
            stats_y = {
                "Velocity": {"fft_peak_magnitude": fft_mag, "fft_peak_hz": 75.0},
            }
            # Target = X: has Position range
            stats_x = {
                "Position": {"min": -500.0, "max": 500.0},
            }

            axes = {
                "X": make_snapshot("X", 0,
                                   [pos_x, 500.0, 80.0, 60.0, 5.0, 0.0, 0x0237, 1.0],
                                   stats=stats_x),
                "Y": make_snapshot("Y", 1,
                                   [2000.0, 300.0, 75.0, 55.0, 3.0, 0.0, 0x0237, 1.0],
                                   stats=stats_y),
            }
            results = analyzer.analyze(axes)

        coupling = [a for a in results if a.category == "cross_mechanical_coupling"]
        assert len(coupling) > 0, (
            f"Expected mechanical coupling detection with 10× position-dependent vibration. "
            f"Categories: {[a.category for a in results]}"
        )


# ══════════════════════════════════════════════════════════════════
# CrossAxisAnalyzer — Integration
# ══════════════════════════════════════════════════════════════════

class TestCrossAxisAnalyzerIntegration:
    """Verify the unified CrossAxisAnalyzer interface."""

    def test_detector_enable_disable(self):
        analyzer = CrossAxisAnalyzer()
        assert analyzer.is_detector_enabled("bus_sag") is True

        analyzer.disable_detector("bus_sag")
        assert analyzer.is_detector_enabled("bus_sag") is False

        analyzer.enable_detector("bus_sag")
        assert analyzer.is_detector_enabled("bus_sag") is True

    def test_disabled_detector_produces_no_annotations(self):
        analyzer = CrossAxisAnalyzer()
        analyzer.disable_detector("bus_sag")
        analyzer.disable_detector("contouring")
        analyzer.disable_detector("ring_health")
        analyzer.disable_detector("mechanical_coupling")

        for _ in range(50):
            results = analyzer.analyze(make_normal_axes())
        assert len(results) == 0, "All detectors disabled → no annotations"

    def test_reset_clears_all_state(self):
        analyzer = CrossAxisAnalyzer()

        # Feed some data to build internal state
        for _ in range(30):
            analyzer.analyze(make_normal_axes())

        # Verify busses have data
        assert len(analyzer._bus_sag._current_windows) > 0

        analyzer.reset()
        assert len(analyzer._bus_sag._current_windows) == 0
        assert len(analyzer._contouring._pair_buffers) == 0
        assert len(analyzer._ring_health._error_history) == 0
        assert len(analyzer._mechanical_coupling._pair_data) == 0

    def test_status_report(self):
        analyzer = CrossAxisAnalyzer()
        status = analyzer.status()
        assert status["name"] == "CrossAxisAnalyzer"
        assert status["enabled"] is True
        assert "bus_sag" in status["detectors"]
        assert len(status["contouring_pairs"]) > 0

    def test_build_snapshots(self):
        analyzer = CrossAxisAnalyzer()
        per_axis = {
            "X": {"values": [1.0] * 8, "stats": {}, "annotations": [], "slave": 0},
            "Y": {"values": [2.0] * 8, "stats": {}, "annotations": [], "slave": 1},
        }
        snapshots = analyzer.build_snapshots(per_axis, CH_NAMES)
        assert len(snapshots) == 2
        assert snapshots["X"].axis_id == "X"
        assert snapshots["X"].slave_position == 0
        assert snapshots["X"].get("Position") == 1.0
        assert snapshots["Y"].slave_position == 1

    def test_all_categories_in_config(self):
        """Verify cross-axis categories are merged into global config."""
        from ai_analyzer.config import ANOMALY_CATEGORIES, HITL_CLASSIFICATION
        for cat in ["cross_bus_sag", "cross_contouring_error",
                     "cross_ring_cascade", "cross_ring_emi",
                     "cross_mechanical_coupling"]:
            assert cat in ANOMALY_CATEGORIES, f"{cat} missing from ANOMALY_CATEGORIES"
            assert cat in HITL_CLASSIFICATION, f"{cat} missing from HITL_CLASSIFICATION"


# ══════════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_empty_axes_dict(self):
        analyzer = CrossAxisAnalyzer()
        results = analyzer.analyze({})
        assert len(results) == 0

    def test_single_axis_no_cross_axis_events(self):
        """Cross-axis detectors need ≥2 axes; single axis should produce nothing."""
        analyzer = CrossAxisAnalyzer()
        axis = {"X": make_snapshot("X", 0, [1000.0] * 8)}
        for _ in range(50):
            results = analyzer.analyze(axis)
        assert len(results) == 0

    def test_missing_channel_graceful_degradation(self):
        """If an axis has no 'Current' channel, bus sag should skip it."""
        analyzer = CrossAxisAnalyzer()
        # Axis X missing Current channel
        short_channels = ["Position", "Velocity"]  # no Current, no Foll.Err
        snap = AxisSnapshot("X", 0, [1000.0, 500.0], short_channels, {}, [], time.time())
        axes = {"X": snap, "Y": make_snapshot("Y", 1, [2000.0, 300.0, 75.0, 55.0, 3.0, 0.0, 0x0237, 1.0])}

        for _ in range(60):
            results = analyzer.analyze(axes)
        # Should not crash — bus sag just skips X
        assert True  # no exception = pass

    def test_detector_failure_isolation(self):
        """One detector crashing should not affect others."""
        analyzer = CrossAxisAnalyzer()

        # Force bus_sag detector into bad state
        analyzer._bus_sag._current_windows = None  # will cause AttributeError on analyze

        axes = make_normal_axes()
        # Should not raise — bus sag is caught, contouring still runs
        results = analyzer.analyze(axes)
        # contouring may or may not fire, just assert no crash
        assert isinstance(results, list)

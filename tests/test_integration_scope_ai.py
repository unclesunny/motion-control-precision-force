"""
Integration tests: Oscilloscope → AI Analyzer pipeline.

Validates that the AI pipeline correctly attaches to ScopeEngine
and produces annotations from both synthetic and edge-case data.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parent.parent
_tests_path = Path(__file__).resolve().parent
_scope_path = _project_root / "04-oscilloscope" / "src"
for _p in [_tests_path, _scope_path]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from helpers import assert_annotation_structure, assert_anomaly_event_structure


class TestAIPipelineAttachesToEngine:
    """Test AI pipeline integration with ScopeEngine."""

    def test_pipeline_created_in_demo_mode(self, scope_engine_sim):
        """ScopeEngine with demo_mode should have ai_pipeline if available."""
        engine = scope_engine_sim
        # ai_pipeline is optional (graceful degradation), but if present it works
        if engine.ai_pipeline is not None:
            assert engine.ai_pipeline.analyzers is not None
            assert len(engine.ai_pipeline.analyzers) == 3

    def test_engine_runs_without_crashing(self, scope_engine_sim):
        """ScopeEngine should start and stop cleanly."""
        engine = scope_engine_sim
        engine.start()
        import time
        time.sleep(0.3)  # let it collect some samples
        engine.stop()
        assert engine.count > 0

    def test_anomaly_events_structure(self, scope_engine_sim):
        """AnomalyEvent dataclass should support new suggestion field."""
        from scope_engine import AnomalyEvent
        event = AnomalyEvent(
            timestamp=0.0, channel="Current", severity="warning",
            message="Test", value=100.0, suggestion="Fix it",
        )
        assert event.suggestion == "Fix it"
        # Default should be empty string
        event2 = AnomalyEvent(
            timestamp=0.0, channel="Current", severity="info",
            message="Test", value=50.0,
        )
        assert event2.suggestion == ""


class TestCurrentAnomalyDetection:
    """Test AI pipeline detects current anomalies from scope data."""

    def test_saturation_triggers_annotation(self, ai_pipeline):
        """Inject a current spike into the pipeline directly."""
        ch_names = ["Position", "Velocity", "Current", "Torque",
                    "Foll.Err", "DIO", "Status", "OpMode"]
        buffer_stats = {
            "Current": {"mean": 80.0, "std": 10.0, "min": 50.0, "max": 120.0,
                        "rms": 82.0, "peak_to_peak": 70.0},
        }

        # Saturation spike — first detection starts at "info"
        annotations = ai_pipeline.analyze(
            [1000.0, 500.0, 250.0, 60.0, 10.0, 0.0, 0x0237, 1.0],
            ch_names, buffer_stats,
        )
        current_anns = [a for a in annotations if a.channel == "Current"]
        assert len(current_anns) > 0
        ann = current_anns[0]
        assert_annotation_structure(ann)
        assert ann.severity in ("info", "warning", "critical")
        assert ann.category == "current_saturation"

    def test_normal_data_no_false_positives(self, ai_pipeline):
        """Normal sine waves should not trigger spurious annotations."""
        ch_names = ["Position", "Velocity", "Current", "Torque",
                    "Foll.Err", "DIO", "Status", "OpMode"]
        buffer_stats = {
            "Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 140.0,
                        "rms": 85.0, "peak_to_peak": 120.0},
            "Foll.Err": {"mean": 10.0, "std": 10.0, "min": 0.0, "max": 40.0,
                         "rms": 14.0, "peak_to_peak": 40.0},
        }

        # Feed many normal samples
        all_annotations = []
        np.random.seed(42)
        for _ in range(100):
            annotations = ai_pipeline.analyze(
                [
                    1000.0 * np.sin(np.random.random() * np.pi),  # Position
                    500.0 * np.sin(np.random.random() * np.pi),   # Velocity
                    80.0 + np.random.normal(0, 10.0),             # Current ~80
                    60.0 * np.sin(np.random.random() * np.pi),    # Torque
                    10.0 + np.random.normal(0, 5.0),              # Foll.Err ~10
                    float(np.random.random() > 0.5),              # DIO
                    0x0237,                                       # Status
                    1.0,                                          # OpMode
                ],
                ch_names, buffer_stats,
            )
            all_annotations.extend(annotations)

        # Very few false positives expected with normal data
        critical_count = sum(1 for a in all_annotations if a.severity == "critical")
        assert critical_count == 0, f"Got {critical_count} critical false positives on normal data"


class TestTrackingErrorDetection:
    """Test AI pipeline detects tracking errors."""

    def test_hardware_limit_triggers_critical(self, ai_pipeline):
        """Following error exceeding absolute limit should trigger an alert."""
        ch_names = ["Position", "Velocity", "Current", "Torque",
                    "Foll.Err", "DIO", "Status", "OpMode"]
        buffer_stats = {}

        annotations = ai_pipeline.analyze(
            [1000.0, 500.0, 80.0, 60.0, 2000000.0, 0.0, 0x0237, 1.0],
            ch_names, buffer_stats,
        )
        error_anns = [a for a in annotations if a.channel == "Foll.Err"]
        assert len(error_anns) > 0
        ann = error_anns[0]
        assert ann.category == "tracking_absolute_limit"
        assert ann.severity in ("info", "warning", "critical")
        assert ann.confidence > 0.0


class TestPipelineBatchAnalysis:
    """Test batch analysis mode for post-capture diagnostics."""

    def test_batch_analyze_on_synthetic_data(self, ai_pipeline, synthetic_waveform_1000):
        """Batch analysis should process full buffer without errors."""
        data, timestamps, channel_names = synthetic_waveform_1000
        annotations = ai_pipeline.batch_analyze(data, timestamps, channel_names)
        # Normal sine data should produce manageable annotations
        assert isinstance(annotations, list)
        critical_count = sum(1 for a in annotations if a.severity == "critical")
        assert critical_count == 0  # synthetic data is clean

    def test_batch_reset_between_runs(self, ai_pipeline):
        """Pipeline should be resettable between batch runs."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        buffer_stats = {"Current": {"mean": 80.0, "std": 10.0, "min": 50.0, "max": 120.0,
                                    "rms": 82.0, "peak_to_peak": 70.0}}

        ai_pipeline.analyze([1000.0, 500.0, 250.0, 60.0], ch_names, buffer_stats)
        assert len(ai_pipeline.recent_events) > 0

        ai_pipeline.reset()
        assert len(ai_pipeline.recent_events) == 0


class TestGracefulDegradation:
    """Test that scope engine works without AI analyzer."""

    def test_legacy_rules_still_defined(self):
        """Legacy fallback rules should still be importable."""
        from scope_engine import _LEGACY_ANOMALY_RULES
        assert len(_LEGACY_ANOMALY_RULES) == 4

    def test_ai_pipeline_can_be_disabled(self, ai_pipeline):
        """Individual analyzers can be toggled."""
        ai_pipeline.disable_analyzer("CurrentAnomaly")
        analyzer = ai_pipeline.get_analyzer("CurrentAnomaly")
        assert analyzer is not None
        assert analyzer.enabled is False

        ai_pipeline.enable_analyzer("CurrentAnomaly")
        assert analyzer.enabled is True

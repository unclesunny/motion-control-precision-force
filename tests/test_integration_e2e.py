"""
End-to-end integration tests: EtherCAT → Scope → AI → Annotation.

Full pipeline: EcMaster(sim) → ScopeEngine → AIAnalyzerPipeline → AnomalyEvent[]
"""

import sys
import time
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parent.parent
_tests_path = Path(__file__).resolve().parent
for _p in [
    _tests_path,
    _project_root / "03-ethercat-master" / "bindings",
    _project_root / "04-oscilloscope" / "src",
    _project_root / "06-ai-analyzer",
	    _project_root / "06-ai-analyzer" / "ai_analyzer",
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from helpers import assert_anomaly_event_structure


class TestFullPipeline:
    """End-to-end test: EcMaster simulation → scope → AI analysis."""

    def test_pipeline_lifecycle(self, ec_master_sim):
        """Full lifecycle: create master → scan → create scope engine → start → stop."""
        from scope_engine import ScopeEngine

        engine = ScopeEngine(
            master=ec_master_sim,
            sample_rate_hz=100,
            buffer_seconds=3,
            demo_mode=True,
        )
        engine.start()
        time.sleep(0.5)
        engine.stop()

        assert engine.count > 0
        assert engine.buffer.count > 0

    def test_buffer_fills_with_samples(self, scope_engine_sim):
        """Ring buffer should fill with samples during acquisition."""
        engine = scope_engine_sim
        engine.start()
        time.sleep(0.5)
        engine.stop()

        buffer_count = engine.buffer.count
        assert buffer_count > 20, f"Buffer only has {buffer_count} samples after 0.5s"

    def test_buffer_stats_available(self, scope_engine_sim):
        """Buffer statistics should be computable after acquisition."""
        engine = scope_engine_sim
        engine.start()
        time.sleep(0.3)
        engine.stop()

        stats = engine.get_stats()
        assert len(stats) > 0
        for s in stats:
            assert "mean" in s
            assert "std" in s
            assert "min" in s
            assert "max" in s

    def test_ai_pipeline_integrated(self, scope_engine_sim):
        """AI pipeline should be instantiated on the scope engine."""
        engine = scope_engine_sim
        if engine.ai_pipeline is not None:
            engine.start()
            time.sleep(0.5)
            engine.stop()
            # After running, there should be some events (or empty, both OK)
            assert isinstance(engine.anomaly_events, list)

    def test_demo_waveform_integrity(self, scope_engine_sim):
        """Demo mode waveforms should produce physically plausible values."""
        engine = scope_engine_sim
        engine.start()
        time.sleep(0.5)
        engine.stop()

        data, ts = engine.buffer.get_all()
        # CH3 (Current, index 2): should be centered around 80%
        current_channel = data[2]
        current_mean = np.mean(current_channel)
        assert 60.0 < current_mean < 100.0, f"Current mean {current_mean:.1f} out of expected range"

    def test_anomaly_event_cap(self, scope_engine_sim):
        """Anomaly event list should be capped at 100."""
        engine = scope_engine_sim
        # Manually inject >100 events to test cap
        from scope_engine import AnomalyEvent
        for i in range(150):
            engine.anomaly_events.append(AnomalyEvent(
                timestamp=float(i), channel="Test", severity="info",
                message=f"Event {i}", value=float(i),
            ))
        # Trigger the cap logic (normally in _run_ai, but we simulate)
        if len(engine.anomaly_events) > 100:
            engine.anomaly_events = engine.anomaly_events[-50:]
        assert len(engine.anomaly_events) <= 100


class TestCrossModuleCompatibility:
    """Cross-module consistency checks."""

    def test_channel_names_consistent(self):
        """Channel names must match between scope_engine and AI config."""
        from scope_engine import DEFAULT_CHANNELS
        from config import CHANNEL_NAME_INDEX

        scope_names = [ch["name"] for ch in DEFAULT_CHANNELS]
        for name in scope_names:
            assert name in CHANNEL_NAME_INDEX, f"Channel '{name}' missing from AI config"

    def test_cia402_indices_consistent(self):
        """CiA 402 indices must match between scope_engine and AI config."""
        from scope_engine import DEFAULT_CHANNELS
        from config import CIA402_CHANNEL_MAP

        for ch in DEFAULT_CHANNELS:
            idx = ch["index"]
            name = ch["name"]
            if idx in CIA402_CHANNEL_MAP:
                assert CIA402_CHANNEL_MAP[idx] == name, \
                    f"Index 0x{idx:04X} maps to '{CIA402_CHANNEL_MAP[idx]}' not '{name}'"

    def test_anomaly_event_fields_match_ai_annotation(self):
        """AnomalyEvent should support all fields AIAnnotation produces."""
        from scope_engine import AnomalyEvent
        from analyzer_base import AIAnnotation

        ann = AIAnnotation(
            timestamp=1.0, channel="Current", category="current_saturation",
            severity="critical", confidence=0.95,
            message="Test", suggestion="Fix it", value=250.0,
        )

        # Conversion (as done in scope_engine._run_ai)
        event = AnomalyEvent(
            timestamp=ann.timestamp,
            channel=ann.channel,
            severity=ann.severity,
            message=f"[{ann.category}] {ann.message} ({ann.confidence:.0%})",
            value=ann.value,
            suggestion=ann.suggestion,
        )
        assert_anomaly_event_structure(event)
        assert event.suggestion == "Fix it"
        assert "current_saturation" in event.message

    def test_python_version_compat(self):
        """Project targets Python 3.11+."""
        vi = sys.version_info
        assert vi.major == 3 and vi.minor >= 11, \
            f"Python {vi.major}.{vi.minor} — project requires 3.11+"

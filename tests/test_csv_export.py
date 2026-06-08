"""
Tests for CSV Waveform Export module (csv_export.py).

Covers: single-axis export, multi-axis export, annotations export,
session bundle, metadata headers, edge cases, TSV delimiter.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Ensure csv_export is importable
_csv_src = Path(__file__).resolve().parent.parent / "04-oscilloscope" / "src"
sys.path.insert(0, str(_csv_src))

from csv_export import (  # noqa: E402
    DEFAULT_CHANNELS,
    export_annotations_csv,
    export_from_scope_engine,
    export_multi_axis_csv,
    export_session_bundle,
    export_waveform_csv,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def sample_data():
    """1000 samples, 8 channels, 1 kHz."""
    np.random.seed(42)
    n_ch, n_samples = 8, 1000
    data = np.random.randn(n_ch, n_samples).astype(np.float32) * 100
    ts = np.arange(n_samples, dtype=np.float64) / 1000.0
    return data, ts


@pytest.fixture
def channel_config():
    return [
        {"name": "Position Actual",  "unit": "pulses"},
        {"name": "Velocity Actual",  "unit": "rpm"},
        {"name": "Current Actual",   "unit": "%"},
        {"name": "Torque Actual",    "unit": "%"},
        {"name": "Following Error",  "unit": "pulses"},
        {"name": "Digital Inputs",   "unit": "bits"},
        {"name": "Statusword",       "unit": "hex"},
        {"name": "Op Mode Display",  "unit": "code"},
    ]


@pytest.fixture
def metadata():
    return {
        "sample_rate_hz": 1000,
        "axis_id": "X",
        "brand": "Delta A3",
        "slave_position": 0,
    }


@pytest.fixture
def sample_annotations():
    """Fake AI annotations for testing export."""

    class FakeAnnotation:
        def __init__(self, ts, ch, sev, cat, val, conf, msg, sug):
            self.timestamp = ts
            self.channel = ch
            self.severity = sev
            self.category = cat
            self.value = val
            self.confidence = conf
            self.message = msg
            self.suggestion = sug

    return [
        FakeAnnotation(1.5, "Current", "warning", "current_saturation",
                       210.0, 0.85, "Current saturation at 210%", "Reduce accel 0x6083"),
        FakeAnnotation(2.3, "Velocity", "critical", "velocity_spike",
                       580.0, 0.92, "Velocity spike 580 rpm", "Check mechanical load"),
        FakeAnnotation(3.1, "Foll.Err", "info", "tracking_drift",
                       12.0, 0.55, "Minor tracking drift", "Monitor trend"),
    ]


# ── Single-Axis Export Tests ─────────────────────────────────

class TestExportWaveformCSV:
    """Tests for export_waveform_csv()."""

    def test_basic_export(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "test.csv")
            n = export_waveform_csv(fpath, data, ts, channel_config, metadata)
            assert n == 1000
            assert os.path.exists(fpath)

            # Verify file content
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1010  # 9 metadata + 1 header + 1000 data
            # Metadata header
            assert lines[0].startswith("# Generated:")
            assert "1000 Hz" in lines[1]
            assert "X" in lines[2]
            assert "Delta A3" in lines[3]
            # Column headers (after 9 metadata lines)
            header = lines[9]
            assert "Timestamp (s)" in header
            assert "Position Actual (pulses)" in header
            assert "Velocity Actual (rpm)" in header
            # Data row
            data_line = lines[10]
            parts = data_line.strip().split(",")
            assert len(parts) == 9  # timestamp + 8 channels
            assert float(parts[0]) >= 0  # timestamp is non-negative

    def test_n_samples_limit(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "test_n.csv")
            n = export_waveform_csv(fpath, data, ts, channel_config, metadata,
                                    n_samples=100)
            assert n == 100
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 110  # 9 metadata + 1 header + 100 data

    def test_empty_data(self, channel_config, metadata):
        data = np.zeros((8, 0), dtype=np.float32)
        ts = np.zeros(0, dtype=np.float64)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "empty.csv")
            n = export_waveform_csv(fpath, data, ts, channel_config, metadata)
            assert n == 0

    def test_single_sample(self, channel_config, metadata):
        data = np.array([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0], [7.0], [8.0]],
                        dtype=np.float32)
        ts = np.array([0.001], dtype=np.float64)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "single.csv")
            n = export_waveform_csv(fpath, data, ts, channel_config, metadata)
            assert n == 1
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 11  # 9 metadata + 1 header + 1 data

    def test_tsv_delimiter(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "test.tsv")
            n = export_waveform_csv(fpath, data[:, :50], ts[:50],
                                    channel_config, metadata, delimiter="\t")
            assert n == 50
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            assert "\t" in content
            assert "," not in content.splitlines()[-1]  # data rows use tabs

    def test_default_channel_config(self, sample_data, metadata):
        """Should work without channel_config using defaults."""
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "default.csv")
            n = export_waveform_csv(fpath, data, ts, metadata=metadata)
            assert n == 1000

    def test_mismatched_timestamps_raises(self, sample_data, channel_config, metadata):
        data, _ = sample_data
        ts = np.arange(500, dtype=np.float64) / 1000.0
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "bad.csv")
            with pytest.raises(ValueError, match="Timestamp count"):
                export_waveform_csv(fpath, data, ts, channel_config, metadata)

    def test_list_input(self, channel_config, metadata):
        """Should accept Python lists, not just numpy arrays."""
        data = [[1.0, 2.0, 3.0]] * 8  # 8 ch x 3 samples
        ts = [0.0, 0.001, 0.002]
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "list.csv")
            n = export_waveform_csv(fpath, data, ts, channel_config, metadata)
            assert n == 3

    def test_nested_directory_creation(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "a", "b", "test.csv")
            n = export_waveform_csv(fpath, data[:, :10], ts[:10],
                                    channel_config, metadata)
            assert n == 10
            assert os.path.exists(fpath)

    def test_csv_is_valid(self, sample_data, channel_config, metadata):
        """Exported CSV should be parseable by Python csv module."""
        import csv
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "valid.csv")
            export_waveform_csv(fpath, data, ts, channel_config, metadata)
            with open(fpath, "r", encoding="utf-8") as f:
                # Skip metadata comment lines
                reader = csv.reader(f)
                rows = [row for row in reader if not (row and row[0].startswith("#"))]
            assert len(rows) == 1001  # header + 1000 data rows
            assert len(rows[0]) == 9  # timestamp + 8 channels


# ── Multi-Axis Export Tests ──────────────────────────────────

class TestExportMultiAxisCSV:
    """Tests for export_multi_axis_csv()."""

    def test_multi_axis_export(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        axes_data = {
            "X": (data, ts),
            "Y": (data * 0.8, ts + 0.001),
            "Z": (data * 1.2, ts + 0.002),
        }
        with tempfile.TemporaryDirectory() as tmp:
            results = export_multi_axis_csv(tmp, axes_data, channel_config, metadata)
            assert results == {"X": 1000, "Y": 1000, "Z": 1000}

            # Verify per-axis files
            for aid in ("X", "Y", "Z"):
                fpath = os.path.join(tmp, f"waveform_{aid}.csv")
                assert os.path.exists(fpath)

            # Verify manifest
            manifest_path = os.path.join(tmp, "_session.json")
            assert os.path.exists(manifest_path)
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            assert manifest["total_axes"] == 3
            assert manifest["total_samples"] == 3000
            assert len(manifest["axes"]) == 3

    def test_single_axis_in_multi(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        axes_data = {"Spindle": (data, ts)}
        with tempfile.TemporaryDirectory() as tmp:
            results = export_multi_axis_csv(tmp, axes_data, channel_config, metadata)
            assert results == {"Spindle": 1000}
            assert os.path.exists(os.path.join(tmp, "waveform_Spindle.csv"))


# ── Annotations Export Tests ─────────────────────────────────

class TestExportAnnotationsCSV:
    """Tests for export_annotations_csv()."""

    def test_annotations_export(self, sample_annotations):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "annotations.csv")
            count = export_annotations_csv(fpath, sample_annotations)
            assert count == 3

            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # 3 metadata + 1 header + 3 data = 7
            assert len(lines) == 7
            assert "Current" in lines[4]
            assert "warning" in lines[4]
            assert "current_saturation" in lines[4]

    def test_empty_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "empty_ann.csv")
            count = export_annotations_csv(fpath, [])
            assert count == 0

    def test_dict_annotations(self):
        """Should accept dicts, not just objects."""
        anns = [
            {"timestamp": 1.0, "channel": "Vel", "severity": "info",
             "category": "test", "value": 10.0, "confidence": 0.5,
             "message": "test msg", "suggestion": "fix"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "dict.csv")
            count = export_annotations_csv(fpath, anns)
            assert count == 1


# ── Session Bundle Tests ─────────────────────────────────────

class TestExportSessionBundle:
    """Tests for export_session_bundle()."""

    def test_full_session_bundle(self, sample_data, channel_config, metadata,
                                  sample_annotations):
        data, ts = sample_data
        axes_data = {
            "X": (data[:, :500], ts[:500]),
            "Y": (data[:, :500] * 0.8, ts[:500] + 0.001),
        }
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = os.path.join(tmp, "session")
            manifest = export_session_bundle(
                session_dir, axes_data,
                annotations=sample_annotations,
                channel_config=channel_config,
                metadata=metadata,
            )
            assert manifest["total_axes"] == 2
            assert manifest["total_waveform_samples"] == 1000
            assert manifest["total_annotations"] == 3
            assert os.path.exists(os.path.join(session_dir, "waveform_X.csv"))
            assert os.path.exists(os.path.join(session_dir, "waveform_Y.csv"))
            assert os.path.exists(os.path.join(session_dir, "annotations.csv"))
            assert os.path.exists(os.path.join(session_dir, "_session.json"))

    def test_session_bundle_no_annotations(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        axes_data = {"Axis0": (data, ts)}
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = os.path.join(tmp, "session_no_ann")
            manifest = export_session_bundle(
                session_dir, axes_data, channel_config=channel_config, metadata=metadata,
            )
            assert manifest["total_annotations"] == 0
            assert manifest["files"]["annotations"] is None


# ── Convenience Function Tests ───────────────────────────────

class TestExportFromScopeEngine:
    """Tests for export_from_scope_engine()."""

    def test_convenience_export(self):
        """Smoke test: the convenience wrapper should not crash."""
        # Create a minimal mock engine
        class MockEngine:
            sample_rate_hz = 1000
            _axis_ids = ["Axis0"]

            def get_waveform(self, n_samples=60000, axis_id=None):
                data = np.random.randn(8, 100).astype(np.float32) * 50
                ts = np.arange(100, dtype=np.float64) / 1000.0
                return data, ts

            anomaly_events = []

        engine = MockEngine()
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "engine_export.csv")
            n = export_from_scope_engine(engine, fpath, n_samples=50)
            assert n == 50
            assert os.path.exists(fpath)


# ── Metadata & Header Tests ──────────────────────────────────

class TestMetadataAndHeaders:
    """Tests for metadata block formatting."""

    def test_metadata_all_fields(self, sample_data, channel_config):
        data, ts = sample_data
        full_meta = {
            "sample_rate_hz": 2000,
            "axis_id": "Z",
            "brand": "Yaskawa Sigma-7",
            "slave_position": 2,
            "notes": "Test run with demo data",
        }
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "meta.csv")
            export_waveform_csv(fpath, data[:, :10], ts[:10],
                                channel_config, full_meta)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            assert "2000 Hz" in content
            assert "Z" in content
            assert "Yaskawa Sigma-7" in content
            assert "Slave Position: 2" in content
            assert "Test run" in content

    def test_duration_in_metadata(self, sample_data, channel_config, metadata):
        data, ts = sample_data
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "dur.csv")
            export_waveform_csv(fpath, data, ts, channel_config, metadata)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            # Duration should be about 0.999 seconds (1000 samples @ 1kHz)
            assert "Duration:" in content

    def test_custom_units_in_headers(self, sample_data):
        data, ts = sample_data
        ch_cfg = [
            {"name": "Force", "unit": "N"},
            {"name": "Pressure", "unit": "Pa"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "units.csv")
            export_waveform_csv(fpath, data[:2, :10], ts[:10], ch_cfg)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            assert "Force (N)" in content
            assert "Pressure (Pa)" in content

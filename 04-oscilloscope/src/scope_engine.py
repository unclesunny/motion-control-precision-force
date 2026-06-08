"""
Oscilloscope Data Acquisition Engine — bridges EcMaster to ring buffer.

Background thread: PDO exchange → channel extraction → ring buffer → AI analysis.
"""

import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ring_buffer import RingBuffer

# ── AI Analyzer integration (optional, graceful degradation) ──
_AI_ANALYZER_AVAILABLE = False
_AIAnalyzerPipeline = None
try:
    _ai_src = Path(__file__).resolve().parent.parent.parent / "06-ai-analyzer"
    if str(_ai_src) not in sys.path:
        sys.path.insert(0, str(_ai_src))
    from ai_analyzer import AIAnalyzerPipeline as _AIAnalyzerPipeline
    _AI_ANALYZER_AVAILABLE = True
except ImportError:
    pass

DEFAULT_CHANNELS = [
    {"index": 0x6064, "name": "Position", "unit": "pulses", "color": "#00FF88", "enabled": True, "label": "Position Actual"},
    {"index": 0x606C, "name": "Velocity", "unit": "rpm", "color": "#FF8800", "enabled": True, "label": "Velocity Actual"},
    {"index": 0x6078, "name": "Current", "unit": "%", "color": "#FF4444", "enabled": True, "label": "Current Actual"},
    {"index": 0x6077, "name": "Torque", "unit": "%", "color": "#44AAFF", "enabled": True, "label": "Torque Actual"},
    {"index": 0x60F4, "name": "Foll.Err", "unit": "pulses", "color": "#E066CC", "enabled": True, "label": "Following Error"},
    {"index": 0x60FD, "name": "DIO", "unit": "bits", "color": "#FFCC00", "enabled": True, "label": "Digital Inputs"},
    {"index": 0x6041, "name": "Status", "unit": "hex", "color": "#22DD88", "enabled": True, "label": "Statusword"},
    {"index": 0x6061, "name": "OpMode", "unit": "code", "color": "#CCCCCC", "enabled": True, "label": "Op Mode Display"},
]

# ── Legacy anomaly rules (kept for reference; replaced by AI pipeline) ──
_LEGACY_ANOMALY_RULES = [
    {"channel": "Current", "threshold": 200, "severity": "warning", "msg": "Current saturation"},
    {"channel": "Velocity", "threshold": 500, "severity": "warning", "msg": "Velocity spike"},
    {"channel": "Foll.Err", "threshold": 100, "severity": "critical", "msg": "Tracking error limit"},
    {"channel": "Current", "threshold": 105, "severity": "warning", "msg": "Current above rated (demo)"},
]


@dataclass
class AnomalyEvent:
    timestamp: float
    channel: str
    severity: str
    message: str
    value: float
    suggestion: str = ""  # actionable recommendation (populated by AI pipeline)


class ScopeEngine:
    """Real-time data acquisition engine for the oscilloscope.

    Multi-axis support: pass `axes` config to create per-axis ring buffers,
    AI pipelines, and a cross-axis analyzer.

    Single-axis (backwards compatible):
        engine = ScopeEngine(master)

    Multi-axis:
        engine = ScopeEngine(master, axes=[
            {"axis_id": "X", "slave_position": 0, "name": "X Axis"},
            {"axis_id": "Y", "slave_position": 1, "name": "Y Axis"},
            {"axis_id": "Z", "slave_position": 2, "name": "Z Axis"},
        ])
    """

    def __init__(self, master, sample_rate_hz: int = 1000, buffer_seconds: int = 60,
                 demo_mode: bool = False, passive: bool = False,
                 axes: Optional[List[dict]] = None,
                 on_disconnect: Optional[callable] = None):
        self.master = master
        self.sample_rate_hz = sample_rate_hz
        self.period_ms = 1000.0 / sample_rate_hz
        self.demo_mode = demo_mode or getattr(master, 'is_simulation', False)
        self._passive = passive  # True: skip exchange(), only read from buffer
        self._on_disconnect = on_disconnect  # callback(dict) on connection loss

        self.channels = DEFAULT_CHANNELS.copy()
        self._active_indices: List[int] = []
        self._active_names: List[str] = []

        # ── Multi-axis config ──
        if axes is None:
            # Backwards compatible: single axis from bus position 0
            axes = [{"axis_id": "Axis0", "slave_position": 0, "name": "Axis 0"}]
        self._axes_config = axes
        self._axis_ids = [a["axis_id"] for a in axes]

        # ── Per-axis ring buffers + pipelines ──
        buffer_size = sample_rate_hz * buffer_seconds
        self._buffers: Dict[str, RingBuffer] = {}
        self._pipelines: Dict[str, Any] = {}  # AIAnalyzerPipeline per axis
        self._cross_axis = None  # CrossAxisAnalyzer

        for axis in axes:
            aid = axis["axis_id"]
            buf = RingBuffer(n_channels=8, buffer_size=buffer_size)
            buf.channel_names = self._active_names + [f"CH{i}" for i in range(len(self._active_names), 8)]
            self._buffers[aid] = buf

            if _AI_ANALYZER_AVAILABLE:
                try:
                    self._pipelines[aid] = _AIAnalyzerPipeline(
                        sample_rate_hz=float(sample_rate_hz),
                        axis_id=aid,
                        slave_position=axis.get("slave_position", -1),
                    )
                except Exception:
                    pass

        # ── Cross-axis analyzer (4th detector) ──
        if _AI_ANALYZER_AVAILABLE and len(self._pipelines) >= 2:
            try:
                from ai_analyzer import CrossAxisAnalyzer
                self._cross_axis = CrossAxisAnalyzer()
            except Exception:
                pass

        # ── Backwards compat: single-axis aliases ──
        self.buffer = self._buffers[self._axis_ids[0]]
        self.ai_pipeline = self._pipelines.get(self._axis_ids[0])

        self._update_active()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time = 0.0
        self._sample_count = 0

        self.trigger_enabled = False
        self.trigger_channel = 0
        self.trigger_level = 0.0
        self.trigger_edge = "rising"
        self._prev_trigger_val = 0.0
        self._triggered = False
        self._post_count = 3000
        self._post_remain = 0

        self.anomaly_events: List[AnomalyEvent] = []
        self._prev_values = [0.0] * 8

        self._load_config()

    @property
    def axis_count(self) -> int:
        return len(self._axes_config)

    @property
    def axis_ids(self) -> List[str]:
        return list(self._axis_ids)

    @property
    def cross_axis_analyzer(self):
        """Cross-axis analyzer instance (4th detector). None if < 2 axes."""
        return self._cross_axis

    def get_pipeline(self, axis_id: str):
        return self._pipelines.get(axis_id)

    def get_buffer(self, axis_id: str):
        return self._buffers.get(axis_id)

    def _load_config(self):
        cfg = Path(__file__).resolve().parent.parent.parent / "05-servo-params" / "delta-a3" / "delta-a3-scope-config.json"
        try:
            with open(cfg, encoding="utf-8") as f:
                config = json.load(f)
        except (FileNotFoundError, UnicodeDecodeError):
            pass

    def _update_active(self):
        self._active_indices = []
        self._active_names = []
        for ch in self.channels:
            if ch.get("enabled", True):
                self._active_indices.append(ch["index"])
                self._active_names.append(ch["name"])
        for buf in self._buffers.values():
            buf.channel_names = self._active_names + [f"CH{i}" for i in range(len(self._active_names), 8)]

    def start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.perf_counter()
        self._sample_count = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self):
        consecutive_errors = 0
        while self._running:
            t0 = time.perf_counter()
            try:
                if not self._passive:
                    wkc = self.master.exchange()
                    # Disconnect detection: WKC=0 means bus dead
                    if not self.demo_mode and wkc <= 0:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0
                else:
                    # Passive mode: don't call exchange(), just read existing buffer
                    consecutive_errors = 0
            except Exception:
                consecutive_errors += 1

            # ── Disconnect detection thresholds ──
            # WKC errors: 100 consecutive failures (100ms @ 1kHz) = bus gone
            # Exception errors: 10 consecutive = hardware disappeared
            wkc_threshold = 100
            exc_threshold = 10
            if consecutive_errors >= wkc_threshold or consecutive_errors >= exc_threshold:
                self._signal_disconnect(consecutive_errors)
                break

            elapsed = time.perf_counter() - self._start_time
            per_axis_values: Dict[str, List[float]] = {}

            for axis in self._axes_config:
                aid = axis["axis_id"]
                slave = axis.get("slave_position", 0)

                if self.demo_mode:
                    values = self._generate_demo_values(aid, self._sample_count)
                else:
                    values = []
                    for idx in self._active_indices:
                        val = self.master.read_pdo(idx, 0, slave=slave)
                        values.append(float(val) if val is not None else 0.0)
                    while len(values) < 8:
                        values.append(0.0)

                per_axis_values[aid] = values
                buf = self._buffers[aid]
                buf.append(values, elapsed)

            self._sample_count += 1

            if self._sample_count % 10 == 0:
                self._run_ai(per_axis_values)

            if self.trigger_enabled and self._axis_ids:
                # Trigger on primary axis
                primary_vals = per_axis_values.get(self._axis_ids[0], [])
                self._check_trigger(primary_vals)

            if self._post_remain > 0:
                self._post_remain -= 1
                if self._post_remain == 0:
                    self.trigger_enabled = False

            if self._passive:
                time.sleep(self.period_ms / 1000.0)
            else:
                dt = (time.perf_counter() - t0) * 1000
                if dt < self.period_ms:
                    time.sleep((self.period_ms - dt) / 1000.0)

    def _signal_disconnect(self, error_count: int):
        """Notify that the EtherCAT connection has been lost."""
        self._running = False
        info = {
            "message": "EtherCAT connection lost. Switching to SIM mode.",
            "last_sample": self._sample_count,
            "consecutive_errors": error_count,
            "timestamp": time.time(),
        }
        if self._on_disconnect:
            try:
                self._on_disconnect(info)
            except Exception:
                pass

    @staticmethod
    def _generate_demo_values(axis_id: str, sample_count: int) -> List[float]:
        """Generate per-axis synthetic waveforms with unique phase offsets.

        Each axis has slightly different frequency/phase so multi-axis
        correlation detectors have realistic data to analyze.
        """
        phase_offsets = {
            "X": 0.0, "Y": 1.2, "Z": 2.4,
            "Axis0": 0.0, "Axis1": 1.2, "Axis2": 2.4,
        }
        offset = phase_offsets.get(axis_id, hash(axis_id) % 100 * 0.1)
        t = sample_count / 1000.0  # assumes 1kHz
        return [
            1000.0 * np.sin(2 * np.pi * 2.0 * t + offset),
            500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5 + offset),
            80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t + offset),
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2 + offset),
            15.0 * np.sin(2 * np.pi * 7.0 * t + offset),
            float(sample_count % 100 > 50),
            0x0237 if sample_count % 200 < 100 else 0x0007,
            (sample_count // 50) % 8,
        ]

    def _check_trigger(self, values):
        if self.trigger_channel >= len(values):
            return
        v = values[self.trigger_channel]
        p = self._prev_trigger_val
        hit = (self.trigger_edge in ("rising", "both") and p < self.trigger_level <= v) or \
              (self.trigger_edge in ("falling", "both") and p > self.trigger_level >= v)
        if hit and self._post_remain == 0:
            self.buffer.mark_trigger()
            self._post_remain = self._post_count
            self._triggered = True
        self._prev_trigger_val = v

    def _run_ai(self, per_axis_values: Dict[str, List[float]]):
        """Run AI analysis on current sample frame across all axes.

        Phase 1: Per-axis single-axis detectors (independent, per pipeline).
        Phase 2: Cross-axis detector (sees all axes simultaneously).
        Falls back to legacy hardcoded rules if 06-ai-analyzer is not installed.
        """
        elapsed = time.perf_counter() - self._start_time

        # ── Phase 1: Per-axis ML-based analysis ──
        for axis in self._axes_config:
            aid = axis["axis_id"]
            values = per_axis_values.get(aid)
            if values is None:
                continue

            pipeline = self._pipelines.get(aid)
            if pipeline is not None:
                buffer_stats = {}
                buf = self._buffers[aid]
                for i, name in enumerate(self._active_names):
                    if i < 8:
                        try:
                            buffer_stats[name] = buf.channel_stats(i)
                        except Exception:
                            buffer_stats[name] = {
                                "min": 0.0, "max": 0.0, "mean": 0.0,
                                "std": 0.0, "rms": 0.0, "peak_to_peak": 0.0,
                            }

                annotations = pipeline.analyze(
                    values, self._active_names, buffer_stats
                )

                for ann in annotations:
                    axis_tag = f"[{aid}] " if aid else ""
                    self.anomaly_events.append(AnomalyEvent(
                        timestamp=elapsed,
                        channel=ann.channel,
                        severity=ann.severity,
                        message=f"{axis_tag}[{ann.category}] {ann.message} ({ann.confidence:.0%})",
                        value=ann.value,
                        suggestion=ann.suggestion,
                    ))

            else:
                # ── Legacy fallback: hardcoded threshold rules ──
                for rule in _LEGACY_ANOMALY_RULES:
                    try:
                        ci = self._active_names.index(rule["channel"])
                    except ValueError:
                        continue
                    v = values[ci] if ci < len(values) else 0.0
                    if abs(v) > rule["threshold"]:
                        axis_tag = f"[{aid}] " if aid else ""
                        self.anomaly_events.append(AnomalyEvent(
                            timestamp=elapsed,
                            channel=rule["channel"], severity=rule["severity"],
                            message=f"{axis_tag}{rule['msg']}", value=v,
                        ))

        # ── Phase 2: Cross-axis analysis ──
        if self._cross_axis is not None:
            try:
                from ai_analyzer import AxisSnapshot

                snapshots = {}
                for axis in self._axes_config:
                    aid = axis["axis_id"]
                    values = per_axis_values.get(aid)
                    if values is None:
                        continue
                    buf = self._buffers[aid]
                    buf_stats = {}
                    for i, name in enumerate(self._active_names):
                        if i < 8:
                            try:
                                buf_stats[name] = buf.channel_stats(i)
                            except Exception:
                                pass

                    snapshots[aid] = AxisSnapshot(
                        axis_id=aid,
                        slave_position=axis.get("slave_position", -1),
                        values=values,
                        channel_names=self._active_names,
                        buffer_stats=buf_stats,
                        timestamp=elapsed,
                    )

                cross_annotations = self._cross_axis.analyze(snapshots)
                for ann in cross_annotations:
                    self.anomaly_events.append(AnomalyEvent(
                        timestamp=elapsed,
                        channel=ann.channel,  # "X+Y+Z" for cross-axis
                        severity=ann.severity,
                        message=f"[{ann.category}] {ann.message} ({ann.confidence:.0%})",
                        value=ann.value,
                        suggestion=ann.suggestion,
                    ))
            except Exception:
                pass

        # Cap event list at 200, trim to 100 on overflow
        if len(self.anomaly_events) > 200:
            self.anomaly_events = self.anomaly_events[-100:]

    def get_waveform(self, n_samples: int = 6000, axis_id: str = None):
        """Get waveform data for one axis (or primary if axis_id=None)."""
        aid = axis_id or self._axis_ids[0]
        buf = self._buffers.get(aid, self.buffer)
        return buf.get_recent(n_samples)

    def get_waveform_all_axes(self, n_samples: int = 6000) -> Dict[str, tuple]:
        """Get waveform data for all axes. Returns {axis_id: (data, timestamps)}."""
        return {aid: self._buffers[aid].get_recent(n_samples) for aid in self._axis_ids}

    def get_triggered_waveform(self, axis_id: str = None):
        aid = axis_id or self._axis_ids[0]
        buf = self._buffers.get(aid, self.buffer)
        return buf.get_trigger_region()

    def get_latest(self, axis_id: str = None) -> List[float]:
        aid = axis_id or self._axis_ids[0]
        buf = self._buffers.get(aid, self.buffer)
        return buf.head_data.tolist()

    def get_stats(self, axis_id: str = None) -> List[dict]:
        aid = axis_id or self._axis_ids[0]
        buf = self._buffers.get(aid, self.buffer)
        return [buf.channel_stats(i) for i in range(len(self._active_names))]

    @property
    def count(self) -> int:
        return self._sample_count

    def export_csv(self, filepath: str, n_samples: int = 0, axis_id: str = None) -> int:
        """Export waveform data to CSV. Returns number of samples written."""
        aid = axis_id or self._axis_ids[0]
        buf = self._buffers.get(aid, self.buffer)
        return buf.to_csv(filepath, n_samples)

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start_time if self._running else 0.0

    @property
    def active(self) -> bool:
        return self._running

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
    """Real-time data acquisition engine for the oscilloscope."""

    def __init__(self, master, sample_rate_hz: int = 1000, buffer_seconds: int = 60,
                 demo_mode: bool = False):
        self.master = master
        self.sample_rate_hz = sample_rate_hz
        self.period_ms = 1000.0 / sample_rate_hz
        self.demo_mode = demo_mode or getattr(master, 'is_simulation', False)

        self.channels = DEFAULT_CHANNELS.copy()
        self._active_indices: List[int] = []
        self._active_names: List[str] = []

        buffer_size = sample_rate_hz * buffer_seconds
        self.buffer = RingBuffer(n_channels=8, buffer_size=buffer_size)
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

        # ── AI pipeline (replaces legacy hardcoded rules) ──
        self.ai_pipeline = None
        if _AI_ANALYZER_AVAILABLE:
            try:
                self.ai_pipeline = _AIAnalyzerPipeline(sample_rate_hz=float(sample_rate_hz))
            except Exception:
                pass

        self._load_config()

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
        self.buffer.channel_names = self._active_names + [f"CH{i}" for i in range(len(self._active_names), 8)]

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
        while self._running:
            t0 = time.perf_counter()
            try:
                self.master.exchange()
            except Exception:
                pass

            if self.demo_mode:
                # Generate synthetic waveforms for visual demo
                t = self._sample_count / self.sample_rate_hz
                values = [
                    1000.0 * np.sin(2 * np.pi * 2.0 * t),           # CH1: Position 2Hz sine
                    500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5),      # CH2: Velocity 3.5Hz
                    80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t),      # CH3: Current 5Hz
                    60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),       # CH4: Torque
                    15.0 * np.sin(2 * np.pi * 7.0 * t),             # CH5: Following Error
                    float(self._sample_count % 100 > 50),            # CH6: Digital IO toggle
                    0x0237 if self._sample_count % 200 < 100 else 0x0007,  # CH7: Status word
                    (self._sample_count // 50) % 8,                  # CH8: Op mode
                ]
            else:
                values = []
                for idx in self._active_indices:
                    val = self.master.read_pdo(idx, 0)
                    values.append(float(val) if val is not None else 0.0)
                while len(values) < 8:
                    values.append(0.0)

            elapsed = time.perf_counter() - self._start_time
            self.buffer.append(values, elapsed)
            self._sample_count += 1

            if self._sample_count % 10 == 0:
                self._run_ai(values)

            if self.trigger_enabled:
                self._check_trigger(values)

            if self._post_remain > 0:
                self._post_remain -= 1
                if self._post_remain == 0:
                    self.trigger_enabled = False

            dt = (time.perf_counter() - t0) * 1000
            if dt < self.period_ms:
                time.sleep((self.period_ms - dt) / 1000.0)

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

    def _run_ai(self, values):
        """Run AI analysis on current sample frame.

        Uses AIAnalyzerPipeline if available (ML-based), falls back to
        legacy hardcoded threshold rules if 06-ai-analyzer is not installed.
        """
        elapsed = time.perf_counter() - self._start_time

        if self.ai_pipeline is not None:
            # ── ML-based analysis ──
            buffer_stats = {}
            for i, name in enumerate(self._active_names):
                if i < 8:
                    try:
                        buffer_stats[name] = self.buffer.channel_stats(i)
                    except Exception:
                        buffer_stats[name] = {
                            "min": 0.0, "max": 0.0, "mean": 0.0,
                            "std": 0.0, "rms": 0.0, "peak_to_peak": 0.0,
                        }

            annotations = self.ai_pipeline.analyze(
                values, self._active_names, buffer_stats
            )

            for ann in annotations:
                self.anomaly_events.append(AnomalyEvent(
                    timestamp=elapsed,
                    channel=ann.channel,
                    severity=ann.severity,
                    message=f"[{ann.category}] {ann.message} ({ann.confidence:.0%})",
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
                    self.anomaly_events.append(AnomalyEvent(
                        timestamp=elapsed,
                        channel=rule["channel"], severity=rule["severity"],
                        message=rule["msg"], value=v,
                    ))

        # Cap event list at 100, trim to 50 on overflow
        if len(self.anomaly_events) > 100:
            self.anomaly_events = self.anomaly_events[-50:]

        self._prev_values = values[:]

    def get_waveform(self, n_samples: int = 6000):
        return self.buffer.get_recent(n_samples)

    def get_triggered_waveform(self):
        return self.buffer.get_trigger_region()

    def get_latest(self) -> List[float]:
        return self.buffer.head_data.tolist()

    def get_stats(self) -> List[dict]:
        return [self.buffer.channel_stats(i) for i in range(len(self._active_names))]

    @property
    def count(self) -> int:
        return self._sample_count

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start_time if self._running else 0.0

    @property
    def active(self) -> bool:
        return self._running

"""
Delta A3 Oscilloscope — 8-Channel Real-Time Waveform Display.

Single-threaded QTimer architecture. Zero threading, zero locks, zero hangs.
Demo mode generates synthetic servo waveforms.

Usage:
    python scope_app.py              # Demo mode with sine waves
"""

import sys
import time
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

# ── AI pipeline (optional) ──────────────────────────────────
_AI_AVAILABLE = False
_AIAnalyzerPipeline = None
try:
    _ai_path = Path(__file__).resolve().parent.parent.parent / "06-ai-analyzer"
    if str(_ai_path) not in sys.path:
        sys.path.insert(0, str(_ai_path))
    from ai_analyzer import AIAnalyzerPipeline as _AIAnalyzerPipeline
    _AI_AVAILABLE = True
except ImportError:
    pass

# ── Constants ────────────────────────────────────────────
CH_COLORS  = ["#00FF88","#FF8800","#FF4444","#44AAFF","#FF44FF","#FFFF44","#44FFAA","#AAAAAA"]
CH_NAMES   = ["Position","Velocity","Current","Torque","Foll.Err","DIO","Status","OpMode"]
CH_UNITS   = ["pulses","rpm","%","%","pulses","bits","hex","code"]
CH_DEFAULT = [True, True, True, True, False, False, False, False]
BG_COLOR   = "#1A1A2E"
TEXT_COLOR = "#CCCCCC"

# ── Ring Buffer (simple, single-threaded) ────────────────

class RingBuf:
    """Single-threaded ring buffer. No locks needed."""
    def __init__(self, ch=8, size=60000):
        self.data = np.zeros((ch, size), dtype=np.float32)
        self.ts   = np.zeros(size, dtype=np.float64)
        self.head = 0
        self.full = False
        self.nch  = ch
        self.size = size

    def push(self, vals, t):
        self.data[:, self.head] = vals[:self.nch]
        self.ts[self.head] = t
        self.head = (self.head + 1) % self.size
        if self.head == 0: self.full = True

    def recent(self, n):
        n = min(n, self.size if self.full else self.head)
        if not self.full and self.head >= n:
            s = self.head - n
            return self.data[:, s:self.head].copy(), self.ts[s:self.head].copy()
        # wrapped
        out = np.zeros((self.nch, n), dtype=np.float32)
        ot  = np.zeros(n, dtype=np.float64)
        seg1 = self.size - self.head
        if seg1 >= n:
            s = self.head - n
            return self.data[:, s:self.head].copy(), self.ts[s:self.head].copy()
        if seg1 > 0:
            out[:, -seg1:] = self.data[:, -seg1:]
            ot[-seg1:] = self.ts[-seg1:]
        seg2 = n - seg1
        if seg2 > 0:
            s = self.head - seg2
            if s < 0: s += self.size
            out[:, :seg2] = self.data[:, s:s+seg2]
            ot[:seg2] = self.ts[s:s+seg2]
        return out, ot

    @property
    def count(self):
        return self.size if self.full else self.head

# ── Waveform Plot ────────────────────────────────────────

class WaveformPlot(pg.PlotWidget):
    def __init__(self):
        super().__init__()
        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.getAxis("bottom").setPen(TEXT_COLOR)
        self.getAxis("left").setPen(TEXT_COLOR)
        self.setLabel("bottom", "Time", "s")
        self.curves = []
        self.visible = CH_DEFAULT.copy()
        for i, c in enumerate(CH_COLORS):
            crv = self.plot(pen=pg.mkPen(color=QColor(c), width=1.2), name=CH_NAMES[i])
            self.curves.append(crv)
        self.addLegend(offset=(-10, 10))
        # Cursors
        self.ca = pg.InfiniteLine(pos=-0.05, angle=90, pen=pg.mkPen("#FFFF00", style=Qt.DashLine), movable=True)
        self.cb = pg.InfiniteLine(pos=-0.02, angle=90, pen=pg.mkPen("#FF8800", style=Qt.DashLine), movable=True)
        self.addItem(self.ca); self.addItem(self.cb)

    def update_data(self, data, ts):
        if data.size == 0: return
        for i, crv in enumerate(self.curves):
            if i < data.shape[0] and self.visible[i]:
                crv.setData(ts, data[i])
            else:
                crv.clear()

    def toggle_ch(self, i, v):
        self.visible[i] = v
        if not v: self.curves[i].clear()

# ── Control Panel ────────────────────────────────────────

class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMaximumWidth(300)
        lay = QVBoxLayout(self)

        # Timebase
        g = QGroupBox("Timebase"); gl = QHBoxLayout(g)
        self.tb = QComboBox()
        self.tb.addItems(["1s","2s","5s","10s","30s"])
        self.tb.setCurrentText("5s")
        gl.addWidget(QLabel("Window:")); gl.addWidget(self.tb)
        lay.addWidget(g)

        # Channels
        g = QGroupBox("Channels"); gl = QVBoxLayout(g)
        self.chk = []
        for i, nm in enumerate(CH_NAMES):
            cb = QCheckBox(f"{nm}")
            cb.setChecked(CH_DEFAULT[i])
            cb.setStyleSheet(f"color:{CH_COLORS[i]};font-weight:bold")
            self.chk.append(cb)
            gl.addWidget(cb)
        lay.addWidget(g)

        # Trigger
        g = QGroupBox("Trigger"); gl = QVBoxLayout(g)
        self.tch = QComboBox(); [self.tch.addItem(n) for n in CH_NAMES[:4]]
        self.tedge = QComboBox(); self.tedge.addItems(["rising","falling","both"])
        self.tlvl = QDoubleSpinBox(); self.tlvl.setRange(-10000,10000); self.tlvl.setValue(0)
        self.tbtn = QPushButton("Arm (Single)")
        gl.addWidget(QLabel("Source:")); gl.addWidget(self.tch)
        gl.addWidget(QLabel("Edge:")); gl.addWidget(self.tedge)
        gl.addWidget(QLabel("Level:")); gl.addWidget(self.tlvl)
        gl.addWidget(self.tbtn)
        lay.addWidget(g)

        # Stats
        g = QGroupBox("Stats"); gl = QVBoxLayout(g)
        self.stats_lbl = QLabel("Waiting...")
        self.stats_lbl.setStyleSheet(f"color:{TEXT_COLOR};font-family:monospace;font-size:10px")
        gl.addWidget(self.stats_lbl)
        lay.addWidget(g)

        # AI
        g = QGroupBox("AI"); gl = QVBoxLayout(g)
        self.ai_lbl = QLabel("No anomalies")
        self.ai_lbl.setStyleSheet("color:#44FF44;font-size:11px")
        self.ai_lbl.setWordWrap(True)
        gl.addWidget(self.ai_lbl)
        lay.addWidget(g)
        lay.addStretch()

# ── Main Window ──────────────────────────────────────────

class ScopeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Delta A3 Oscilloscope — EtherCAT Servo Debugger")
        self.resize(1400, 800)

        # Buffer
        self.buf = RingBuf(ch=8, size=60000)
        self.t0 = time.perf_counter()
        self.sample_n = 0
        self.tw = 5.0  # time window seconds

        # Plot
        self.plot = WaveformPlot()

        # Controls
        self.ctrl = ControlPanel()
        self.ctrl.tb.currentTextChanged.connect(self._set_tw)
        for i, cb in enumerate(self.ctrl.chk):
            cb.toggled.connect(lambda v, idx=i: self.plot.toggle_ch(idx, v))
        self.ctrl.tbtn.clicked.connect(self._arm_trig)

        # Layout
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self.plot); sp.addWidget(self.ctrl)
        sp.setStretchFactor(0, 3); sp.setStretchFactor(1, 1)
        self.setCentralWidget(sp)

        # Status bar
        self.st = QStatusBar(); self.setStatusBar(self.st)
        self.fps_lbl = QLabel("FPS: --"); self.n_lbl = QLabel("Samples: 0")
        self.cur_lbl = QLabel("dt=-- dy=--")
        self.st.addWidget(self.fps_lbl); self.st.addWidget(self.n_lbl); self.st.addWidget(self.cur_lbl)

        # Timers
        self.acq_timer = QTimer()
        self.acq_timer.timeout.connect(self._acq_tick)
        self.acq_timer.start(1)  # ~1ms → ~1000 Hz

        self.draw_timer = QTimer()
        self.draw_timer.timeout.connect(self._draw_tick)
        self.draw_timer.start(33)  # ~30 FPS

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._stats_tick)
        self.stats_timer.start(2000)

        # FPS tracking
        self._frames = 0; self._last_fps = time.perf_counter()

        # Trigger
        self.trig_on = False; self.trig_ch = 0; self.trig_lvl = 0.0
        self.trig_edge = "rising"; self._prev_v = 0.0; self._post_n = 0

        # AI pipeline
        self.ai_pipeline = None
        if _AI_AVAILABLE:
            try:
                self.ai_pipeline = _AIAnalyzerPipeline(sample_rate_hz=1000.0)
            except Exception:
                pass

        # Shortcuts
        QShortcut(QKeySequence("Space"), self, self._toggle)
        QShortcut(QKeySequence("R"), self, self._reset)

    # ── Acquisition (1ms tick) ──────────────────────────
    def _acq_tick(self):
        t = time.perf_counter() - self.t0
        self.sample_n += 1

        # Demo: synthetic servo waveforms
        s = self.sample_n / 1000.0
        vals = [
            1000.0 * math.sin(2*math.pi*2.0*s),            # Position
            500.0  * math.sin(2*math.pi*3.5*s + 0.5),      # Velocity
            80.0   + 30.0 * math.sin(2*math.pi*5.0*s),     # Current
            60.0   * math.sin(2*math.pi*2.0*s + 1.2),      # Torque
            15.0   * math.sin(2*math.pi*7.0*s),            # Foll.Err
            float(self.sample_n % 100 > 50),                # DIO
            0x0237 if self.sample_n % 200 < 100 else 0x0007, # Status
            (self.sample_n // 50) % 8,                      # OpMode
        ]
        self.buf.push(vals, t)

        # Trigger check
        if self.trig_on and self._post_n == 0:
            v = vals[self.trig_ch]
            hit = (self.trig_edge in ("rising","both") and self._prev_v < self.trig_lvl <= v) or \
                  (self.trig_edge in ("falling","both") and self._prev_v > self.trig_lvl >= v)
            if hit:
                self._post_n = 3000
            self._prev_v = v
        if self._post_n > 0:
            self._post_n -= 1
            if self._post_n == 0:
                self.trig_on = False

    # ── Draw (30 FPS tick) ──────────────────────────────
    def _draw_tick(self):
        n = int(self.tw * 1000)
        data, ts = self.buf.recent(n)
        if data.size == 0: return
        ts = ts - ts[-1]  # latest = 0
        self.plot.update_data(data, ts)

        # Cursor readout
        dt = abs(self.plot.ca.value() - self.plot.cb.value()) * 1000
        self.cur_lbl.setText(f"dt={dt:.1f}ms")

        # FPS
        self._frames += 1
        now = time.perf_counter()
        if now - self._last_fps >= 1.0:
            self.fps_lbl.setText(f"FPS: {self._frames/(now-self._last_fps):.0f}")
            self.n_lbl.setText(f"Samples: {self.sample_n}")
            self._frames = 0; self._last_fps = now

    # ── Stats + AI (2s tick) ────────────────────────────
    def _stats_tick(self):
        if self.buf.count < 100: return
        d, _ = self.buf.recent(self.buf.count)
        lines = []
        anomalies = []

        # Build buffer stats for AI pipeline
        buffer_stats = {}
        for i in range(min(8, d.shape[0])):
            ch = d[i]
            mn, mx, sd = float(np.mean(ch)), float(np.max(ch)), float(np.std(ch))
            rms = float(np.sqrt(np.mean(ch ** 2)))
            lines.append(f"{CH_NAMES[i]:<8s} μ={mn:>8.1f} σ={sd:>8.1f} pk={mx:>8.1f}")
            buffer_stats[CH_NAMES[i]] = {
                "mean": mn, "std": sd, "min": float(np.min(ch)), "max": mx,
                "rms": rms, "peak_to_peak": mx - float(np.min(ch)),
            }

        # ── AI analysis ──
        if self.ai_pipeline is not None and d.shape[0] >= 8:
            try:
                latest_vals = d[:, -1].tolist() if d.shape[1] > 0 else [0.0] * 8
                anns = self.ai_pipeline.analyze(latest_vals, CH_NAMES[:8], buffer_stats)
                for ann in anns:
                    icon = {"info": "i", "warning": "⚠", "critical": "🔴"}.get(ann.severity, "?")
                    anomalies.append(f"{icon} {ann.channel}: {ann.message[:80]}")
            except Exception:
                pass

        # Fallback: legacy threshold check if AI not available
        if not self.ai_pipeline:
            for i in range(min(8, d.shape[0])):
                ch = d[i]
                mx = float(np.max(ch))
                if i == 2 and mx > 105:
                    anomalies.append(f"⚠ Current peak {mx:.0f}% — check load")
                if i == 4 and mx > 12:
                    anomalies.append(f"🔴 Tracking error {mx:.0f} — check mechanics")

        self.ctrl.stats_lbl.setText("\n".join(lines))
        self.ctrl.ai_lbl.setText("\n".join(anomalies) if anomalies else "✓ Normal")
        self.ctrl.ai_lbl.setStyleSheet(f"color:{'#FF8844' if anomalies else '#44FF44'};font-size:11px")

    # ── Slots ────────────────────────────────────────────
    def _set_tw(self, txt):
        self.tw = {"1s":1,"2s":2,"5s":5,"10s":10,"30s":30}.get(txt, 5)

    def _arm_trig(self):
        self.trig_ch = self.ctrl.tch.currentIndex()
        self.trig_lvl = self.ctrl.tlvl.value()
        self.trig_edge = self.ctrl.tedge.currentText()
        self.trig_on = True
        self.st.showMessage(f"Trigger armed: {CH_NAMES[self.trig_ch]} {self.trig_edge} @ {self.trig_lvl:.0f}", 3000)

    def _toggle(self):
        if self.acq_timer.isActive():
            self.acq_timer.stop(); self.draw_timer.stop()
            self.st.showMessage("PAUSED")
        else:
            self.acq_timer.start(1); self.draw_timer.start(33)
            self.st.showMessage("RUNNING")

    def _reset(self):
        self.buf = RingBuf(ch=8, size=60000)
        self.sample_n = 0; self.t0 = time.perf_counter()
        self.st.showMessage("Buffer cleared")

# ── Main ─────────────────────────────────────────────────

def main():
    pg.setConfigOptions(antialias=True, background=BG_COLOR, foreground=TEXT_COLOR, useOpenGL=False)
    app = QApplication(sys.argv)
    app.setApplicationName("Delta A3 Oscilloscope")
    win = ScopeWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

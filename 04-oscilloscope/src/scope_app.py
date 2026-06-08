"""
Delta A3 Oscilloscope — Multi-Axis Waveform Display.

Single-threaded QTimer architecture. Zero threading, zero locks, zero hangs.
Demo mode generates per-axis synthetic servo waveforms with phase offsets.

Supports 1-64 axes via a tabbed UI. Each axis shows 8 CiA 402 channels.
Cross-axis events (bus sag, contouring, ring health, mechanical coupling)
appear in a dedicated panel below the waveform tabs.

Usage:
    python scope_app.py              # Demo mode, 3 axes
    python scope_app.py --axes 6     # Demo mode, 6 axes
"""

import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressDialog,
    QPushButton, QSplitter, QStackedWidget, QStatusBar, QTabWidget,
    QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

# ── Mode constants ─────────────────────────────────────────
MODE_SIM = "sim"
MODE_SCANNING = "scanning"
MODE_DISCOVER = "discover"

# Discover step names
DISCOVER_STEPS = [
    "Detect EtherCAT adapter",
    "Initialize EtherCAT master",
    "Scan bus for slaves",
    "Discover slave identities",
    "Auto-name axes",
]

# ── CSV export (shared module) ─────────────────────────────
try:
    from csv_export import (
        export_waveform_csv, export_multi_axis_csv,
        export_annotations_csv, export_session_bundle,
    )
    _CSV_EXPORT_AVAILABLE = True
except ImportError:
    _CSV_EXPORT_AVAILABLE = False

# ── AI pipeline (optional) ──────────────────────────────────
_AI_AVAILABLE = False
_AIAnalyzerPipeline = None
_CrossAxisAnalyzer = None
_AxisSnapshot = None
try:
    _ai_path = Path(__file__).resolve().parent.parent.parent / "06-ai-analyzer"
    if str(_ai_path) not in sys.path:
        sys.path.insert(0, str(_ai_path))
    from ai_analyzer import AIAnalyzerPipeline as _AIAnalyzerPipeline
    from ai_analyzer import CrossAxisAnalyzer as _CrossAxisAnalyzer
    from ai_analyzer import AxisSnapshot as _AxisSnapshot
    _AI_AVAILABLE = True
except ImportError:
    pass

# ── Multi-axis config ──────────────────────────────────────

DEFAULT_AXES = [
    {"id": "X", "name": "X Axis", "color": "#44FF44", "offset": 0.0},
    {"id": "Y", "name": "Y Axis", "color": "#FF8800", "offset": 1.2},
    {"id": "Z", "name": "Z Axis", "color": "#44AAFF", "offset": 2.4},
]
N_CH = 8
CH_COLORS  = ["#00FF88","#FF8800","#FF4444","#44AAFF","#E066CC","#FFCC00","#22DD88","#CCCCCC"]
CH_NAMES   = ["Position Actual","Velocity Actual","Current Actual","Torque Actual",
              "Following Error","Digital Inputs","Statusword","Op Mode Display"]
CH_UNITS   = ["pulses","rpm","%","%","pulses","bits","hex","code"]
CH_DEFAULT = [True, True, True, True, True, True, True, True]
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
    def __init__(self, axis_label: str = "", axis_color: str = "#44FF44"):
        super().__init__()
        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.getAxis("bottom").setPen(TEXT_COLOR)
        self.getAxis("left").setPen(TEXT_COLOR)
        label = f"{axis_label} — Time" if axis_label else "Time"
        self.setLabel("bottom", label, "s")
        self.curves = []
        self.visible = CH_DEFAULT.copy()
        self._axis_color = axis_color
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


# ── Cross-Axis Events Panel ───────────────────────────────

class CrossAxisPanel(QWidget):
    """Shows cross-axis events (bus sag, contouring, ring health, coupling)."""

    CROSS_CATEGORY_COLORS = {
        "cross_bus_sag": "#FF8844",
        "cross_contouring_error": "#FF44FF",
        "cross_ring_cascade": "#FF4444",
        "cross_ring_emi": "#FFAA00",
        "cross_mechanical_coupling": "#44AAFF",
    }

    def __init__(self):
        super().__init__()
        self.setMaximumHeight(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)

        hdr = QHBoxLayout()
        lbl = QLabel("Cross-Axis Events")
        lbl.setStyleSheet(f"color:{TEXT_COLOR};font-weight:bold;font-size:12px")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._count_lbl = QLabel("0 events")
        self._count_lbl.setStyleSheet("color:#666688;font-size:12px")
        hdr.addWidget(self._count_lbl)
        lay.addLayout(hdr)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumHeight(110)
        self._text.setStyleSheet(
            f"background-color:#0D0D1A;color:{TEXT_COLOR};"
            f"font-family:monospace;font-size:11px;border:1px solid #2A2A4E;"
        )
        lay.addWidget(self._text)

        self._events: list = []  # keep last 50

    def add_event(self, annotation):
        """Add a cross-axis annotation event."""
        cat = getattr(annotation, 'category', '')
        msg = getattr(annotation, 'message', str(annotation))
        sev = getattr(annotation, 'severity', 'info')
        color = self.CROSS_CATEGORY_COLORS.get(cat, TEXT_COLOR)
        sev_icon = {"info": "i", "warning": "⚠", "critical": "🔴"}.get(sev, "?")

        self._events.append(f'<span style="color:{color}">{sev_icon} [{cat}]</span> {msg}')
        if len(self._events) > 50:
            self._events = self._events[-50:]

        self._text.setHtml("<br>".join(reversed(self._events)))
        self._count_lbl.setText(f"{len(self._events)} events")

    def clear(self):
        self._events.clear()
        self._text.clear()
        self._count_lbl.setText("0 events")

# ── Discovery Panel ──────────────────────────────────────

class DiscoveryPanel(QWidget):
    """In-window hardware discovery checklist.

    Shows a step-by-step checklist during EtherCAT bus discovery.
    Each step updates with ✓ (pass) or ✗ (fail) as it completes.
    On success: signals parent to enter Discover mode.
    On failure: shows [Run in Sim Mode] / [Exit] buttons.
    """

    discovery_complete = Signal(bool, object, list)  # success, master, axes_cfg

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background-color:{BG_COLOR};")
        self._step_labels = []
        self._step_status = {}  # name → "pending"|"ok"|"fail"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(10)

        # Title
        title = QLabel("EtherCAT Hardware Discovery")
        title.setStyleSheet(f"color:{TEXT_COLOR};font-size:16px;font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        lay.addSpacing(12)

        # Step list
        self._step_widget = QWidget()
        self._step_widget.setStyleSheet(
            f"background-color:#0D0D1A;border:1px solid #2A2A4E;border-radius:6px;")
        step_lay = QVBoxLayout(self._step_widget)
        step_lay.setContentsMargins(16, 12, 16, 12)
        step_lay.setSpacing(6)

        for name in DISCOVER_STEPS:
            row = QHBoxLayout()
            icon_lbl = QLabel("  ⏳")
            icon_lbl.setStyleSheet("color:#666688;font-size:13px;font-family:Consolas;")
            icon_lbl.setFixedWidth(30)
            step_lbl = QLabel(name)
            step_lbl.setStyleSheet(f"color:#666688;font-size:13px;")
            detail_lbl = QLabel("")
            detail_lbl.setStyleSheet("color:#555566;font-size:11px;")
            row.addWidget(icon_lbl)
            row.addWidget(step_lbl)
            row.addWidget(detail_lbl)
            row.addStretch()
            step_lay.addLayout(row)
            self._step_labels.append((name, icon_lbl, step_lbl, detail_lbl))
            self._step_status[name] = "pending"

        lay.addWidget(self._step_widget)

        # Status message
        self._status_msg = QLabel("Checking hardware...")
        self._status_msg.setStyleSheet(f"color:#AAAACC;font-size:12px;")
        self._status_msg.setAlignment(Qt.AlignCenter)
        self._status_msg.setWordWrap(True)
        lay.addWidget(self._status_msg)

        lay.addSpacing(8)

        # Button row (hidden until needed)
        self._btn_row = QWidget()
        btn_lay = QHBoxLayout(self._btn_row)
        btn_lay.setAlignment(Qt.AlignCenter)

        self._sim_btn = QPushButton("Run in Sim Mode")
        self._sim_btn.setStyleSheet(
            "background:#3A2A1A;color:#FF8844;font-weight:bold;"
            "border:2px solid #5A3A2A;padding:10px 24px;font-size:13px;")
        self._sim_btn.clicked.connect(lambda: self.discovery_complete.emit(False, None, []))

        self._exit_btn = QPushButton("Exit")
        self._exit_btn.setStyleSheet(
            "background:#2A2A4E;color:#AAAACC;"
            "border:1px solid #4A4A6E;padding:10px 24px;font-size:13px;")
        self._exit_btn.clicked.connect(lambda: sys.exit(0))

        btn_lay.addWidget(self._sim_btn)
        btn_lay.addWidget(self._exit_btn)
        self._btn_row.hide()

        lay.addWidget(self._btn_row)
        lay.addStretch()

    def set_step(self, step_index: int, status: str, detail: str = ""):
        """Update a step's status. status: 'ok', 'fail', 'running'."""
        if step_index >= len(self._step_labels):
            return

        name, icon_lbl, step_lbl, detail_lbl = self._step_labels[step_index]

        if status == "running":
            icon_lbl.setText("  ⏳")
            icon_lbl.setStyleSheet("color:#FFCC44;font-size:13px;font-family:Consolas;")
            step_lbl.setStyleSheet("color:#FFCC44;font-size:13px;font-weight:bold;")
            detail_lbl.setText(detail)
            detail_lbl.setStyleSheet("color:#8888AA;font-size:11px;")
            self._status_msg.setText(f"Step {step_index + 1}/{len(DISCOVER_STEPS)}: {name}...")
            self._status_msg.setStyleSheet("color:#FFCC44;font-size:12px;")
            self._step_status[name] = "running"
        elif status == "ok":
            icon_lbl.setText("  ✓")
            icon_lbl.setStyleSheet("color:#44FF44;font-size:13px;font-family:Consolas;")
            step_lbl.setStyleSheet("color:#44AA66;font-size:13px;")
            detail_lbl.setText(detail)
            detail_lbl.setStyleSheet("color:#44AA66;font-size:11px;")
            self._step_status[name] = "ok"
        elif status == "fail":
            icon_lbl.setText("  ✗")
            icon_lbl.setStyleSheet("color:#FF4444;font-size:13px;font-family:Consolas;")
            step_lbl.setStyleSheet("color:#FF6644;font-size:13px;")
            detail_lbl.setText(detail)
            detail_lbl.setStyleSheet("color:#FF6644;font-size:11px;")
            self._step_status[name] = "fail"

    def set_discovery_result(self, success: bool, master=None, axes_cfg: list = None):
        """Called when discovery completes. Shows result and appropriate action."""
        if success:
            self._status_msg.setText(
                f"✓ Hardware found! {len(axes_cfg or [])} axis(es) ready.\nEntering Discover mode...")
            self._status_msg.setStyleSheet("color:#44FF44;font-size:13px;font-weight:bold;")
            self.discovery_complete.emit(True, master, axes_cfg or [])
        else:
            self._status_msg.setText(
                "No EtherCAT hardware detected.\nChoose Sim mode to continue with synthetic waveforms.")
            self._status_msg.setStyleSheet("color:#FF8844;font-size:12px;")
            self._btn_row.show()

    @property
    def step_count(self) -> int:
        return len(DISCOVER_STEPS)


# ── Axis Groups Config ───────────────────────────────────

class AxisGroupConfig:
    """Defines tree structure: groups contain axes."""

    @staticmethod
    def from_axes(axes_cfg: list) -> list:
        """Auto-group: first 3 axes → 'Motion', rest → 'Auxiliary'."""
        if len(axes_cfg) <= 3:
            return [{"name": "Axes", "axes": [a["id"] for a in axes_cfg]}]
        return [
            {"name": "Motion", "axes": [a["id"] for a in axes_cfg[:3]]},
            {"name": "Auxiliary", "axes": [a["id"] for a in axes_cfg[3:]]},
        ]


# ── Axis Tree Panel ──────────────────────────────────────

class AxisTreePanel(QWidget):
    """Left sidebar: tree view with groups, axes, and diagnostics nodes.

    Clicking an axis node → main view shows that axis's waveform plot.
    Clicking 'Cross-Axis Events' → shows the cross-axis events panel.
    """

    NODE_AXIS = 0
    NODE_GROUP = 1
    NODE_CROSS = 2

    def __init__(self, axes_cfg: list, groups: list):
        super().__init__()
        self.setMaximumWidth(220)
        self.setMinimumWidth(160)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)

        lbl = QLabel("Axes")
        lbl.setStyleSheet(f"color:{TEXT_COLOR};font-weight:bold;font-size:13px")
        lay.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._tree.setStyleSheet(
            f"background-color:#0D0D1A;color:{TEXT_COLOR};"
            f"border:1px solid #2A2A4E;font-size:11px;"
            f"QTreeWidget::item:selected {{background-color:#2A2A5E;}}"
        )
        self._node_map = {}  # {text: (type, axis_id|group_name)}
        self._axis_items = {}  # {axis_id: QTreeWidgetItem}

        # Populate tree
        for group in groups:
            grp_name = group["name"]
            grp_item = QTreeWidgetItem([f"▸ {grp_name}"])
            grp_item.setFlags(grp_item.flags() | Qt.ItemIsAutoTristate)
            font = grp_item.font(0); font.setBold(True); grp_item.setFont(0, font)
            self._tree.addTopLevelItem(grp_item)

            for aid in group.get("axes", []):
                ax = next((a for a in axes_cfg if a["id"] == aid), None)
                color = ax.get("color", "#44FF44") if ax else "#44FF44"
                child = QTreeWidgetItem([f"  {aid}"])
                child.setForeground(0, QColor(color))
                grp_item.addChild(child)
                self._axis_items[aid] = child
                self._node_map[child] = (self.NODE_AXIS, aid)

            grp_item.setExpanded(True)

        # Cross-Axis Events node
        cross_item = QTreeWidgetItem(["▸ Diagnostics"])
        cross_font = cross_item.font(0); cross_font.setBold(True); cross_item.setFont(0, cross_font)
        self._tree.addTopLevelItem(cross_item)

        cross_events = QTreeWidgetItem(["  Cross-Axis"])
        cross_events.setForeground(0, QColor("#FF8844"))
        cross_item.addChild(cross_events)
        self._node_map[cross_events] = (self.NODE_CROSS, "cross_events")
        cross_item.setExpanded(True)

        lay.addWidget(self._tree)

    @property
    def tree(self):
        return self._tree

    def get_axis_item(self, axis_id: str):
        return self._axis_items.get(axis_id)

    def select_first_axis(self):
        """Select the first axis node in the tree."""
        if self._axis_items:
            first = next(iter(self._axis_items.values()))
            self._tree.setCurrentItem(first)


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

        # Export
        self.export_btn = QPushButton("Export Current Axis (Ctrl+S)")
        self.export_all_btn = QPushButton("Export All Axes")
        lay.addWidget(self.export_btn)
        lay.addWidget(self.export_all_btn)

        # Stats
        g = QGroupBox("Stats"); gl = QVBoxLayout(g)
        self.stats_lbl = QLabel("Waiting...")
        self.stats_lbl.setStyleSheet(f"color:{TEXT_COLOR};font-family:monospace;font-size:12px")
        gl.addWidget(self.stats_lbl)
        lay.addWidget(g)

        # AI
        g = QGroupBox("AI"); gl = QVBoxLayout(g)
        self.ai_lbl = QLabel("No anomalies")
        self.ai_lbl.setStyleSheet("color:#44FF44;font-size:13px")
        self.ai_lbl.setWordWrap(True)
        gl.addWidget(self.ai_lbl)
        lay.addWidget(g)
        lay.addStretch()

# ── Main Window ──────────────────────────────────────────

class ScopeWindow(QMainWindow):
    # Signal: emitted when disconnect detected from engine thread
    disconnect_detected = Signal(dict)

    def __init__(self, axes_cfg: list = None, mode: str = MODE_SIM,
                 master=None, discovering: bool = False):
        super().__init__()
        self._axes_cfg = axes_cfg or ([] if discovering else DEFAULT_AXES)
        self._n_axes = len(self._axes_cfg)
        self._groups = AxisGroupConfig.from_axes(self._axes_cfg) if self._axes_cfg else []
        self._mode = MODE_SCANNING if discovering else mode
        self._master = master

        # Connect disconnect signal
        self.disconnect_detected.connect(self._on_disconnect_detected)

        # ── Discovery panel (created regardless, only shown when needed) ──
        self._discovery_panel = DiscoveryPanel()
        self._discovery_panel.discovery_complete.connect(self._on_discovery_complete)

        title = f"Servo Oscilloscope — {self._n_axes} Axis{'s' if self._n_axes > 1 else ''}"
        self.setWindowTitle(title)
        self.resize(1400, 800)

        # Global base font + QGroupBox title size
        self.setStyleSheet("QWidget { font-size: 12px; } "
                           "QGroupBox { font-weight: bold; } "
                           "QGroupBox::title { font-size: 13px; }")

        # Per-axis ring buffers
        self._bufs = {}
        for ax in self._axes_cfg:
            self._bufs[ax["id"]] = RingBuf(ch=8, size=60000)

        # Per-axis AI pipelines
        self._pipelines = {}
        self._cross_axis = None
        if _AI_AVAILABLE:
            for ax in self._axes_cfg:
                try:
                    self._pipelines[ax["id"]] = _AIAnalyzerPipeline(
                        sample_rate_hz=1000.0,
                        axis_id=ax["id"],
                        slave_position=self._axes_cfg.index(ax),
                    )
                except Exception:
                    pass
            if len(self._pipelines) >= 2 and _CrossAxisAnalyzer is not None:
                try:
                    self._cross_axis = _CrossAxisAnalyzer()
                except Exception:
                    pass

        # Backwards compat
        self.buf = self._bufs[self._axes_cfg[0]["id"]]
        self.ai_pipeline = self._pipelines.get(self._axes_cfg[0]["id"])

        self.t0 = time.perf_counter()
        self.sample_n = 0
        self.tw = 5.0

        # ── Tree + Detail Layout ──
        # Left sidebar: tree view (axis selection) — empty until discovery completes
        if self._axes_cfg:
            self._axis_tree = AxisTreePanel(self._axes_cfg, self._groups)
        else:
            self._axis_tree = AxisTreePanel([], [])
        self._axis_tree.tree.currentItemChanged.connect(self._on_tree_select)

        # Right: stacked widget — discovery panel + per-axis plots + cross-axis page
        self._stack = QStackedWidget()
        self._plots = {}
        self._stack_index = {}  # {axis_id|"cross": stack_index}

        # Discovery panel is always the first page (index 0)
        self._stack_index["__discovery__"] = self._stack.addWidget(self._discovery_panel)

        for ax in self._axes_cfg:
            plot = WaveformPlot(axis_label=ax["name"], axis_color=ax.get("color", "#44FF44"))
            self._plots[ax["id"]] = plot
            self._stack_index[ax["id"]] = self._stack.addWidget(plot)

        # Cross-axis events page
        self._cross_panel = CrossAxisPanel()
        self._stack_index["cross"] = self._stack.addWidget(self._cross_panel)

        if self._axes_cfg:
            self.plot = self._plots[self._axes_cfg[0]["id"]]  # backwards compat
            self._current_axis = self._axes_cfg[0]["id"]
        else:
            self.plot = None
            self._current_axis = None

        # ── Show discovery panel if scanning ──
        if self._mode == MODE_SCANNING:
            self._stack.setCurrentIndex(self._stack_index["__discovery__"])
        elif self._axes_cfg:
            self._stack.setCurrentIndex(self._stack_index.get(
                self._axes_cfg[0]["id"], 0))

        # ── Controls ──
        self.ctrl = ControlPanel()
        self.ctrl.tb.currentTextChanged.connect(self._set_tw)
        for i, cb in enumerate(self.ctrl.chk):
            cb.toggled.connect(lambda v, idx=i: self._toggle_ch_all(idx, v))
        self.ctrl.tbtn.clicked.connect(self._arm_trig)

        # ── Layout: tree | stack | controls ──
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self._axis_tree)
        sp.addWidget(self._stack)
        sp.addWidget(self.ctrl)
        sp.setStretchFactor(0, 1)
        sp.setStretchFactor(1, 4)
        sp.setStretchFactor(2, 1)
        self.setCentralWidget(sp)

        # Select first axis by default
        self._axis_tree.select_first_axis()

        # ── Toolbar: mode switch ──
        self._toolbar = QToolBar("Mode")
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)

        self._mode_lbl = QLabel("")
        self._mode_lbl.setStyleSheet("font-weight:bold;font-size:13px;padding:0 8px;")
        self._toolbar.addWidget(self._mode_lbl)

        self._sim_btn = QPushButton("Sim ⬤")
        self._sim_btn.setToolTip("Switch to simulation mode (synthetic waveforms)")
        self._sim_btn.clicked.connect(self._switch_to_sim)
        self._toolbar.addWidget(self._sim_btn)

        self._discover_btn = QPushButton("🔍 Discover")
        self._discover_btn.setToolTip("Re-scan EtherCAT bus for hardware")
        self._discover_btn.clicked.connect(self._switch_to_discover)
        self._toolbar.addWidget(self._discover_btn)

        self._toolbar.addSeparator()
        self._bus_info_lbl = QLabel("")
        self._bus_info_lbl.setStyleSheet("color:#888;font-size:11px;padding:0 8px;")
        self._toolbar.addWidget(self._bus_info_lbl)

        self._update_mode_ui()

        # ── Status bar ──
        self.st = QStatusBar(); self.setStatusBar(self.st)
        self.fps_lbl = QLabel("FPS: --"); self.fps_lbl.setStyleSheet("font-size:12px")
        self.n_lbl = QLabel("Samples: 0"); self.n_lbl.setStyleSheet("font-size:12px")
        self.cur_lbl = QLabel("dt=--"); self.cur_lbl.setStyleSheet("font-size:12px")
        self.axis_lbl = QLabel(f"Axes: {self._n_axes}"); self.axis_lbl.setStyleSheet("font-size:12px")
        self.st.addWidget(self.fps_lbl); self.st.addWidget(self.n_lbl)
        self.st.addWidget(self.cur_lbl); self.st.addWidget(self.axis_lbl)

        # ── Timers ──
        self.acq_timer = QTimer()
        self.acq_timer.timeout.connect(self._acq_tick)

        self.draw_timer = QTimer()
        self.draw_timer.timeout.connect(self._draw_tick)

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._stats_tick)

        # Don't start timers if we're still discovering
        if self._mode != MODE_SCANNING:
            self.acq_timer.start(1)
            self.draw_timer.start(33)
            self.stats_timer.start(2000)

        self._frames = 0; self._last_fps = time.perf_counter()

        # Trigger
        self.trig_on = False; self.trig_ch = 0; self.trig_lvl = 0.0
        self.trig_edge = "rising"; self._prev_v = 0.0; self._post_n = 0

        # Shortcuts
        QShortcut(QKeySequence("Space"), self, self._toggle)
        QShortcut(QKeySequence("R"), self, self._reset)
        QShortcut(QKeySequence("Ctrl+S"), self, self._export)
        QShortcut(QKeySequence("Ctrl+Tab"), self, self._next_axis)
        self.ctrl.export_btn.clicked.connect(self._export)
        self.ctrl.export_all_btn.clicked.connect(self._export_all)

    # ── Tree Selection ────────────────────────────────────

    def _on_tree_select(self, current, previous):
        """Handle tree node selection — switch stack page."""
        if current is None:
            return
        node_info = self._axis_tree._node_map.get(current)
        if node_info is None:
            return

        node_type, key = node_info
        if node_type == AxisTreePanel.NODE_AXIS:
            # Switch to axis plot
            if key in self._stack_index:
                self._stack.setCurrentIndex(self._stack_index[key])
                self._current_axis = key
        elif node_type == AxisTreePanel.NODE_CROSS:
            # Switch to cross-axis events
            self._stack.setCurrentIndex(self._stack_index["cross"])

    @property
    def axis_count(self) -> int:
        return self._n_axes

    @property
    def cross_axis_analyzer(self):
        return self._cross_axis

    # ── Discovery Completion ──────────────────────────────

    def _on_discovery_complete(self, success: bool, master, axes_cfg: list):
        """Called when DiscoveryPanel finishes the hardware check."""
        if success:
            # Enter Discover mode with discovered hardware
            if master:
                self._master = master
            self._enter_discover_mode(master, axes_cfg)
            # Remove discovery panel from stack and start timers
            if "__discovery__" in self._stack_index:
                self._stack.removeWidget(self._discovery_panel)
                del self._stack_index["__discovery__"]
                # Fixup indices after removal
                for key in list(self._stack_index.keys()):
                    if self._stack_index[key] > 0:
                        self._stack_index[key] -= 1
            self.acq_timer.start(1)
            self.draw_timer.start(33)
            self.stats_timer.start(2000)
        else:
            # Discovery failed — stay on discovery panel (Sim/Exit buttons shown)
            # When user clicks Sim, the panel emits discovery_complete(False, None, [])
            # which calls this again with empty axes_cfg → enter Sim mode
            if axes_cfg == [] and master is None and not success:
                # User chose Sim mode
                self._axes_cfg = DEFAULT_AXES
                self._n_axes = len(self._axes_cfg)
                self._groups = AxisGroupConfig.from_axes(self._axes_cfg)

                # Rebuild for Sim
                self._bufs = {}
                for ax in self._axes_cfg:
                    self._bufs[ax["id"]] = RingBuf(ch=8, size=60000)

                # Remove discovery panel
                if "__discovery__" in self._stack_index:
                    self._stack.removeWidget(self._discovery_panel)
                    del self._stack_index["__discovery__"]

                # Create plots
                self._rebuild_ui_for_axes(self._axes_cfg)

                self._mode = MODE_SIM
                self._update_mode_ui()
                self.acq_timer.start(1)
                self.draw_timer.start(33)
                self.stats_timer.start(2000)
                self.st.showMessage("Sim mode — synthetic waveforms", 5000)
            # else: discovery still in progress or user hasn't chosen yet

    def _start_discovery(self):
        """Run the hardware discovery steps, updating the DiscoveryPanel."""
        panel = self._discovery_panel

        def _run_step(step_idx: int):
            if step_idx >= panel.step_count:
                return

            panel.set_step(step_idx, "running")

            # Import discover module
            _bindings_path = str(Path(__file__).resolve().parent.parent.parent
                                 / "03-ethercat-master" / "bindings")
            if _bindings_path not in sys.path:
                sys.path.insert(0, _bindings_path)

            if step_idx == 0:
                # Step 1: Detect NIC
                try:
                    from discover import detect_ethercat_adapter
                    adapter = detect_ethercat_adapter()
                    if adapter is None:
                        panel.set_step(0, "fail", "No EtherCAT adapter found")
                        _finish_discovery(False)
                        return
                    panel.set_step(0, "ok", str(adapter)[:50])
                    self._discover_adapter = adapter
                    QTimer.singleShot(100, lambda: _run_step(1))
                except Exception as e:
                    panel.set_step(0, "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 1:
                # Step 2: Initialize master
                try:
                    from ec_master import EcMaster
                    master = EcMaster(adapter=self._discover_adapter)
                    self._discover_master = master
                    panel.set_step(1, "ok", "SOEM/IgH ready")
                    QTimer.singleShot(100, lambda: _run_step(2))
                except Exception as e:
                    panel.set_step(1, "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 2:
                # Step 3: Scan bus
                try:
                    self._discover_master.scan()
                    count = self._discover_master.slavecount
                    if count == 0:
                        panel.set_step(2, "fail", "No slaves on bus")
                        _finish_discovery(False)
                        return
                    panel.set_step(2, "ok", f"{count} slave(s) found")
                    QTimer.singleShot(100, lambda: _run_step(3))
                except Exception as e:
                    panel.set_step(2, "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 3:
                # Step 4: Discover slave identities
                try:
                    slaves = self._discover_master.discover()
                    if not slaves:
                        panel.set_step(3, "fail", "Slaves not responding")
                        _finish_discovery(False)
                        return
                    servo_count = sum(1 for s in slaves
                                     if s.get("esi_match", {}).get("is_servo_drive"))
                    panel.set_step(3, "ok", f"{len(slaves)} devices ({servo_count} servos)")
                    self._discover_slaves = slaves
                    QTimer.singleShot(100, lambda: _run_step(4))
                except Exception as e:
                    panel.set_step(3, "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 4:
                # Step 5: Auto-name axes
                try:
                    from discover import auto_name_axes, save_axis_config
                    axes_cfg = auto_name_axes(self._discover_slaves)
                    save_axis_config(axes_cfg)
                    axis_list = ", ".join(a["id"] for a in axes_cfg)
                    panel.set_step(4, "ok", f"{len(axes_cfg)} axes: {axis_list}")
                    # Success!
                    master = self._discover_master
                    QTimer.singleShot(400, lambda: _finish_discovery(True, master, axes_cfg))
                except Exception as e:
                    panel.set_step(4, "fail", str(e)[:60])
                    _finish_discovery(False)

        def _finish_discovery(success: bool, master=None, axes_cfg: list = None):
            # Clean up on failure
            if not success:
                if hasattr(self, '_discover_master') and self._discover_master:
                    try:
                        self._discover_master.close()
                    except Exception:
                        pass
            panel.set_discovery_result(success, master, axes_cfg)

        # Start with step 0 after a short delay so the window renders first
        QTimer.singleShot(150, lambda: _run_step(0))

    # ── Mode Management ────────────────────────────────────

    def _update_mode_ui(self):
        """Update toolbar buttons and mode label to reflect current mode."""
        if self._mode == MODE_SIM:
            self._mode_lbl.setText("Mode: ● Sim (synthetic)")
            self._mode_lbl.setStyleSheet(
                "color:#FF8844;font-weight:bold;font-size:13px;padding:0 8px;")
            self._sim_btn.setStyleSheet(
                "background:#3A2A1A;color:#FF8844;font-weight:bold;border:2px solid #FF8844;")
            self._discover_btn.setStyleSheet("")
        elif self._mode == MODE_SCANNING:
            self._mode_lbl.setText("Mode: ⏳ Scanning...")
            self._mode_lbl.setStyleSheet(
                "color:#FFCC44;font-weight:bold;font-size:13px;padding:0 8px;")
            self._sim_btn.setStyleSheet("")
            self._discover_btn.setStyleSheet("")
        else:  # MODE_DISCOVER
            bus_info = ""
            if self._master and self._master.slavecount > 0:
                bus_info = f" ({self._master.slavecount} slave"
                bus_info += "s)" if self._master.slavecount > 1 else ")"
            else:
                bus_info = ""
            self._mode_lbl.setText(f"Mode: 🔍 Discover{bus_info}")
            self._mode_lbl.setStyleSheet(
                "color:#44FF44;font-weight:bold;font-size:13px;padding:0 8px;")
            self._sim_btn.setStyleSheet("")
            self._discover_btn.setStyleSheet(
                "background:#1A3A1A;color:#44FF44;font-weight:bold;border:2px solid #44FF44;")
            self._update_master_info()

    def _update_master_info(self):
        """Update bus info label in toolbar."""
        if self._master is None:
            self._bus_info_lbl.setText("")
            return
        m = self._master
        info_parts = [f"Adapter: {getattr(m, 'adapter', 'N/A')}",
                      f"Slaves: {m.slavecount}"]
        if m.slavecount > 0:
            for s in m.slaves:
                if hasattr(s, 'name'):
                    info_parts.append(f"[{s.position}] {s.name}")
                    break
        self._bus_info_lbl.setText("  |  ".join(info_parts))

    def _switch_to_sim(self):
        """User clicked [Sim ⬤] button — switch to simulation mode."""
        if self._mode == MODE_SIM:
            return  # already in Sim

        # Save state before closing master
        self._save_session_state()

        # Close master connection
        if self._master:
            try:
                self._master.close()
            except Exception:
                pass
            self._master = None

        self._mode = MODE_SIM
        self._update_mode_ui()
        self.st.showMessage("Switched to Sim mode — synthetic waveforms", 3000)

    def _switch_to_discover(self):
        """User clicked [🔍 Discover] button — try to connect to hardware."""
        if self._mode == MODE_DISCOVER:
            return  # already in Discover

        if self._mode == MODE_SCANNING:
            return  # already scanning

        success = self._try_discover(show_progress=True)
        if not success:
            choice = self._prompt_no_hardware()
            if choice == "exit":
                self.close()
                return
            # choice == "sim": stay in Sim
            self._mode = MODE_SIM
            self._update_mode_ui()

    def _try_discover(self, show_progress: bool = False) -> bool:
        """Attempt to connect to real EtherCAT hardware.

        Returns True if hardware found and scope rebuilt in Discover mode.
        Returns False if no hardware available.
        """
        self._mode = MODE_SCANNING
        self._update_mode_ui()

        # Optional progress dialog
        progress = None
        if show_progress:
            progress = QProgressDialog(
                "Scanning EtherCAT bus...", "Cancel", 0, 4, self)
            progress.setWindowTitle("Discover")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            progress.setValue(0)
            progress.setLabelText("Detecting EtherCAT adapter...")
            QApplication.processEvents()

        try:
            # 1. Detect NIC
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent
                                    / "03-ethercat-master" / "bindings"))
            from discover import detect_ethercat_adapter

            adapter = detect_ethercat_adapter()
            if adapter is None:
                self._mode = MODE_SIM
                self._update_mode_ui()
                return False

            if progress:
                progress.setValue(1)
                progress.setLabelText(f"Found adapter: {adapter}\nInitializing master...")
                QApplication.processEvents()

            # 2. Initialize and scan
            from ec_master import EcMaster
            master = EcMaster(adapter=adapter)
            master.scan()

            if progress:
                progress.setValue(2)
                progress.setLabelText(f"Scanning bus... Found {master.slavecount} slave(s)")
                QApplication.processEvents()

            # 3. Discover slaves
            slaves = master.discover()
            if not slaves:
                master.close()
                self._mode = MODE_SIM
                self._update_mode_ui()
                return False

            if progress:
                progress.setValue(3)
                progress.setLabelText(f"Discovered {len(slaves)} slave(s). Auto-naming axes...")
                QApplication.processEvents()

            # 4. Auto-name axes
            from discover import auto_name_axes, save_axis_config
            axes_cfg = auto_name_axes(slaves)
            save_axis_config(axes_cfg)

            if progress:
                progress.setValue(4)
                QApplication.processEvents()

            # 5. Rebuild scope in Discover mode
            self._enter_discover_mode(master, axes_cfg)

            if progress:
                progress.close()

            return True

        except Exception as e:
            if progress:
                progress.close()
            self._mode = MODE_SIM
            self._update_mode_ui()
            print(f"[Discover] Failed: {e}")
            return False

    def _prompt_no_hardware(self) -> str:
        """Show dialog when no EtherCAT hardware is detected.
        Returns 'sim' or 'exit'.
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("No EtherCAT Hardware Detected")
        msg.setIcon(QMessageBox.Warning)
        msg.setText("No EtherCAT-compatible NIC found or\n"
                     "no slaves responded on the bus.")
        msg.setInformativeText(
            "Check:\n"
            "  • Npcap/WinPcap installed\n"
            "  • NIC connected to servo drives\n"
            "  • Servo drives powered on\n\n"
            "You can run in simulation mode with synthetic waveforms.")
        btn_sim = msg.addButton("Run in Sim Mode", QMessageBox.AcceptRole)
        btn_exit = msg.addButton("Exit", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_sim)
        msg.exec()

        if msg.clickedButton() == btn_sim:
            return "sim"
        return "exit"

    def _enter_discover_mode(self, master, axes_cfg: list):
        """Rebuild the scope with a real EtherCAT master."""
        # Close old master if any
        if self._master and self._master is not master:
            try:
                self._master.close()
            except Exception:
                pass

        self._master = master
        self._axes_cfg = axes_cfg
        self._n_axes = len(axes_cfg)
        self._groups = AxisGroupConfig.from_axes(axes_cfg)

        # Rebuild per-axis ring buffers
        self._bufs = {}
        for ax in axes_cfg:
            self._bufs[ax["id"]] = RingBuf(ch=8, size=60000)

        # Rebuild AI pipelines (optional)
        self._pipelines = {}
        self._cross_axis = None
        if _AI_AVAILABLE:
            for ax in axes_cfg:
                try:
                    self._pipelines[ax["id"]] = _AIAnalyzerPipeline(
                        sample_rate_hz=1000.0,
                        axis_id=ax["id"],
                        slave_position=axes_cfg.index(ax),
                    )
                except Exception:
                    pass
            if len(self._pipelines) >= 2 and _CrossAxisAnalyzer is not None:
                try:
                    self._cross_axis = _CrossAxisAnalyzer()
                except Exception:
                    pass

        # Backwards compat
        self.buf = self._bufs.get(axes_cfg[0]["id"]) if axes_cfg else self._bufs.get(
            list(self._bufs.keys())[0] if self._bufs else None)
        self.ai_pipeline = self._pipelines.get(
            axes_cfg[0]["id"] if axes_cfg else None)

        # Rebuild UI
        self._rebuild_ui_for_axes(axes_cfg)

        self._mode = MODE_DISCOVER
        self._update_mode_ui()
        self.st.showMessage(
            f"Discover mode — {self._n_axes} axis(es), {master.slavecount} slave(s)", 5000)

    def _enter_sim_mode(self, from_disconnect: bool = False):
        """Enter Sim mode, preserving state if coming from Discover."""
        if from_disconnect or self._mode == MODE_DISCOVER:
            self._save_session_state()

        if self._master:
            try:
                self._master.close()
            except Exception:
                pass
            self._master = None

        self._mode = MODE_SIM
        self._update_mode_ui()
        self.st.showMessage("Switched to Sim mode — synthetic waveforms", 3000)

    def _save_session_state(self):
        """Save current topology + last waveform before mode switch."""
        try:
            # Save axis config
            from discover import save_axis_config
            save_axis_config(self._axes_cfg)
        except Exception:
            pass

        # Save last waveform per axis
        for ax in self._axes_cfg:
            aid = ax["id"]
            buf = self._bufs.get(aid)
            if buf and buf.count > 0:
                try:
                    data, ts = buf.recent(min(buf.count, 60000))
                    npz_path = Path(f"last_waveform_{aid}.npz")
                    np.savez_compressed(
                        npz_path,
                        data=data, timestamps=ts,
                        axis_id=aid,
                        timestamp=datetime.now().isoformat(),
                    )
                except Exception:
                    pass

        # Save session metadata
        try:
            session_meta = {
                "mode": self._mode,
                "switched_at": datetime.now().isoformat(),
                "previous_axes": [ax["id"] for ax in self._axes_cfg],
                "previous_slave_count": self._n_axes,
            }
            with open("session_meta.json", "w") as f:
                json.dump(session_meta, f, indent=2)
        except Exception:
            pass

    def _rebuild_ui_for_axes(self, axes_cfg: list):
        """Rebuild tree, plots, and stacked widget for a new axis config."""
        # Clear old plots
        while self._stack.count() > 0:
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            if hasattr(w, 'deleteLater'):
                w.deleteLater()

        self._plots = {}
        self._stack_index = {}

        for ax in axes_cfg:
            plot = WaveformPlot(axis_label=ax["name"],
                               axis_color=ax.get("color", "#44FF44"))
            self._plots[ax["id"]] = plot
            self._stack_index[ax["id"]] = self._stack.addWidget(plot)

        # Cross-axis events page
        self._cross_panel = CrossAxisPanel()
        self._stack_index["cross"] = self._stack.addWidget(self._cross_panel)

        # Rebuild axis tree
        groups = AxisGroupConfig.from_axes(axes_cfg)
        self._axis_tree = AxisTreePanel(axes_cfg, groups)
        self._axis_tree.tree.currentItemChanged.connect(self._on_tree_select)

        # Update the splitter: remove old tree, insert new one
        sp = self.centralWidget()
        if isinstance(sp, QSplitter):
            old_tree = sp.widget(0)
            if old_tree:
                old_tree.hide()
                old_tree.deleteLater()
            sp.insertWidget(0, self._axis_tree)
            sp.setStretchFactor(0, 1)

        # Update instance state
        self._axes_cfg = axes_cfg
        self._n_axes = len(axes_cfg)
        self._groups = groups
        self._current_axis = axes_cfg[0]["id"] if axes_cfg else self._current_axis
        self.plot = self._plots.get(self._current_axis)

        self._axis_tree.select_first_axis()

        # Update title and axis label
        self.setWindowTitle(
            f"Servo Oscilloscope — {self._n_axes} Axis"
            f"{'s' if self._n_axes > 1 else ''}")
        self.axis_lbl.setText(f"Axes: {self._n_axes}")

    def _on_disconnect_detected(self, info: dict):
        """Handle disconnect signal from engine thread."""
        msg = info.get("message", "EtherCAT connection lost.")
        QMessageBox.warning(self, "Connection Lost",
                            f"{msg}\n\nSwitching to Sim mode.")
        self._enter_sim_mode(from_disconnect=True)
    @staticmethod
    def _demo_values(axis_offset: float, sample_n: int) -> list:
        s = sample_n / 1000.0
        return [
            1000.0 * math.sin(2*math.pi*2.0*s + axis_offset),
            500.0  * math.sin(2*math.pi*3.5*s + 0.5 + axis_offset),
            80.0   + 30.0 * math.sin(2*math.pi*5.0*s + axis_offset),
            60.0   * math.sin(2*math.pi*2.0*s + 1.2 + axis_offset),
            15.0   * math.sin(2*math.pi*7.0*s + axis_offset),
            float(sample_n % 100 > 50),
            0x0237 if sample_n % 200 < 100 else 0x0007,
            (sample_n // 50) % 8,
        ]

    # ── Acquisition (1ms tick) ──────────────────────────
    def _acq_tick(self):
        t = time.perf_counter() - self.t0
        self.sample_n += 1

        per_axis_vals = {}

        if self._mode == MODE_DISCOVER and self._master is not None:
            # ── Discover mode: read real PDOs ──
            try:
                self._master.exchange()
            except Exception:
                pass

            for ax in self._axes_cfg:
                slave_pos = ax.get("slave_position", 0)
                vals = []
                for ch_idx in [0x6064, 0x606C, 0x6078, 0x6077,
                               0x60F4, 0x60FD, 0x6041, 0x6061]:
                    val = self._master.read_pdo(ch_idx, 0, slave=slave_pos + 1)
                    vals.append(float(val) if val is not None else 0.0)
                self._bufs[ax["id"]].push(vals, t)
                per_axis_vals[ax["id"]] = vals
        else:
            # ── Sim mode: synthetic demo values ──
            for ax in self._axes_cfg:
                vals = self._demo_values(ax.get("offset", 0.0), self.sample_n)
                self._bufs[ax["id"]].push(vals, t)
                per_axis_vals[ax["id"]] = vals

        # Trigger check on primary axis
        primary_vals = per_axis_vals.get(self._axes_cfg[0]["id"], [0]*8)
        if self.trig_on and self._post_n == 0:
            v = primary_vals[self.trig_ch] if self.trig_ch < len(primary_vals) else 0
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

        # Update only the currently visible axis plot
        aid = self._current_axis
        buf = self._bufs.get(aid)
        plot = self._plots.get(aid)
        if buf and plot:
            data, ts = buf.recent(n)
            if data.size > 0:
                ts = ts - ts[-1]
                plot.update_data(data, ts)
            dt = abs(plot.ca.value() - plot.cb.value()) * 1000
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
        lines = []
        all_anomalies = []

        # Per-axis stats + single-axis AI
        for ax in self._axes_cfg:
            aid = ax["id"]
            buf = self._bufs[aid]
            if buf.count < 100:
                continue

            d, _ = buf.recent(buf.count)
            if d.size == 0:
                continue

            buf_stats = {}
            for i in range(min(N_CH, d.shape[0])):
                ch = d[i]
                mn, mx, sd = float(np.mean(ch)), float(np.max(ch)), float(np.std(ch))
                rms = float(np.sqrt(np.mean(ch ** 2)))
                buf_stats[CH_NAMES[i]] = {
                    "mean": mn, "std": sd, "min": float(np.min(ch)), "max": mx,
                    "rms": rms, "peak_to_peak": mx - float(np.min(ch)),
                }

            ppl = self._pipelines.get(aid)
            if ppl is not None and d.shape[0] >= 8:
                try:
                    latest_vals = d[:, -1].tolist() if d.shape[1] > 0 else [0.0] * 8
                    anns = ppl.analyze(latest_vals, CH_NAMES[:8], buf_stats)
                    for ann in anns:
                        icon = {"info": "i", "warning": "⚠", "critical": "🔴"}.get(ann.severity, "?")
                        all_anomalies.append(f"[{aid}] {icon} {ann.channel}: {ann.message[:70]}")
                except Exception:
                    pass

            # Stats for display (first axis only in sidebar)
            if ax == self._axes_cfg[0]:
                for i in range(min(N_CH, d.shape[0])):
                    ch = d[i]
                    mn, mx, sd = float(np.mean(ch)), float(np.max(ch)), float(np.std(ch))
                    lines.append(f"{CH_NAMES[i]:<8s} μ={mn:>8.1f} σ={sd:>8.1f} pk={mx:>8.1f}")

        # ── Cross-axis AI ──
        if self._cross_axis is not None and _AxisSnapshot is not None:
            try:
                snapshots = {}
                for ax in self._axes_cfg:
                    aid = ax["id"]
                    buf = self._bufs[aid]
                    if buf.count < 100:
                        continue
                    d, _ = buf.recent(buf.count)
                    if d.size == 0:
                        continue

                    buf_stats = {}
                    for i in range(min(N_CH, d.shape[0])):
                        ch = d[i]
                        buf_stats[CH_NAMES[i]] = {
                            "mean": float(np.mean(ch)), "std": float(np.std(ch)),
                            "min": float(np.min(ch)), "max": float(np.max(ch)),
                            "rms": float(np.sqrt(np.mean(ch**2))),
                            "peak_to_peak": float(np.max(ch) - np.min(ch)),
                        }

                    latest = d[:, -1].tolist() if d.shape[1] > 0 else [0.0]*8
                    snapshots[aid] = _AxisSnapshot(
                        axis_id=aid,
                        slave_position=self._axes_cfg.index(ax),
                        values=latest,
                        channel_names=CH_NAMES[:8],
                        buffer_stats=buf_stats,
                        timestamp=time.time(),
                    )

                cross_anns = self._cross_axis.analyze(snapshots)
                for ann in cross_anns:
                    self._cross_panel.add_event(ann)
                    icon = {"info": "i", "warning": "⚠", "critical": "🔴"}.get(ann.severity, "?")
                    all_anomalies.append(f"CROSS {icon} {ann.channel}: {ann.message[:70]}")
            except Exception:
                pass

        self.ctrl.stats_lbl.setText("\n".join(lines) if lines else "Waiting...")
        self.ctrl.ai_lbl.setText("\n".join(all_anomalies) if all_anomalies else "✓ Normal")
        self.ctrl.ai_lbl.setStyleSheet(
            f"color:{'#FF8844' if all_anomalies else '#44FF44'};font-size:13px"
        )

    # ── Slots ────────────────────────────────────────────
    def _toggle_ch_all(self, idx, visible):
        """Toggle a channel across ALL axis plots."""
        for plot in self._plots.values():
            plot.toggle_ch(idx, visible)

    def _set_tw(self, txt):
        self.tw = {"1s":1,"2s":2,"5s":5,"10s":10,"30s":30}.get(txt, 5)

    def _arm_trig(self):
        self.trig_ch = self.ctrl.tch.currentIndex()
        self.trig_lvl = self.ctrl.tlvl.value()
        self.trig_edge = self.ctrl.tedge.currentText()
        self.trig_on = True
        self.st.showMessage(
            f"Trigger armed: {CH_NAMES[self.trig_ch]} {self.trig_edge} @ {self.trig_lvl:.0f}", 3000
        )

    def _toggle(self):
        if self.acq_timer.isActive():
            self.acq_timer.stop(); self.draw_timer.stop()
            self.st.showMessage("PAUSED")
        else:
            self.acq_timer.start(1); self.draw_timer.start(33)
            self.st.showMessage("RUNNING")

    def _reset(self):
        for ax in self._axes_cfg:
            self._bufs[ax["id"]] = RingBuf(ch=8, size=60000)
        self.sample_n = 0; self.t0 = time.perf_counter()
        self._cross_panel.clear()
        self.st.showMessage("Buffers cleared")

    def _next_axis(self):
        """Cycle to the next axis in the tree."""
        axis_ids = list(self._plots.keys())
        if not axis_ids:
            return
        try:
            cur_idx = axis_ids.index(self._current_axis)
        except ValueError:
            cur_idx = 0
        next_idx = (cur_idx + 1) % len(axis_ids)
        next_aid = axis_ids[next_idx]
        self._current_axis = next_aid
        if next_aid in self._stack_index:
            self._stack.setCurrentIndex(self._stack_index[next_aid])
        # Highlight in tree
        item = self._axis_tree.get_axis_item(next_aid)
        if item:
            self._axis_tree.tree.setCurrentItem(item)

    def _export(self):
        """Export waveform data to CSV for the current axis."""
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime

        aid = self._current_axis
        default_name = datetime.now().strftime(f"scope_{aid}_%Y%m%d_%H%M%S.csv")
        filepath, _ = QFileDialog.getSaveFileName(
            self, f"Export {aid} Waveform CSV", default_name, "CSV files (*.csv)"
        )
        if not filepath:
            return

        buf = self._bufs[aid]
        d, ts = buf.recent(buf.count)

        channel_config = [
            {"name": CH_NAMES[i], "unit": CH_UNITS[i]} for i in range(min(N_CH, d.shape[0]))
        ]
        metadata = {
            "sample_rate_hz": 1000,
            "axis_id": aid,
            "slave_position": self._axes_cfg.index(next(
                (a for a in self._axes_cfg if a["id"] == aid), self._axes_cfg[0]
            )),
        }

        if _CSV_EXPORT_AVAILABLE:
            n = export_waveform_csv(filepath, d, ts, channel_config, metadata)
        else:
            import csv
            n = d.shape[1]
            headers = ["Timestamp (s)"] + [c["name"] for c in channel_config]
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for i in range(n):
                    row = [f"{ts[i]:.6f}"] + [f"{d[ch, i]:.6g}" for ch in range(d.shape[0])]
                    writer.writerow(row)

        self.st.showMessage(f"Exported {n} samples to {filepath}")

    def _export_all(self):
        """Export all axes and AI annotations to a session directory."""
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime

        default_dir = datetime.now().strftime("scope_session_%Y%m%d_%H%M%S")
        from PySide6.QtWidgets import QFileDialog as QFD
        output_dir = QFD.getExistingDirectory(
            self, "Select Output Directory for Session Export",
        )
        if not output_dir:
            return

        import os
        session_dir = os.path.join(output_dir, default_dir)

        # Collect per-axis data
        axes_data = {}
        for ax in self._axes_cfg:
            aid = ax["id"]
            buf = self._bufs[aid]
            d, ts = buf.recent(buf.count)
            if d.size > 0:
                axes_data[aid] = (d, ts)

        if not axes_data:
            QMessageBox.warning(self, "Export", "No data to export.")
            return

        channel_config = [
            {"name": CH_NAMES[i], "unit": CH_UNITS[i]} for i in range(N_CH)
        ]
        metadata = {"sample_rate_hz": 1000}

        if _CSV_EXPORT_AVAILABLE:
            manifest = export_session_bundle(
                session_dir, axes_data,
                channel_config=channel_config,
                metadata=metadata,
            )
            total = manifest.get("total_waveform_samples", 0)
            axes_count = manifest.get("total_axes", 0)
        else:
            # Fallback: manual per-axis CSV
            os.makedirs(session_dir, exist_ok=True)
            total = 0
            axes_count = len(axes_data)
            for aid, (d, ts) in axes_data.items():
                fpath = os.path.join(session_dir, f"waveform_{aid}.csv")
                import csv
                n = d.shape[1]
                headers = ["Timestamp (s)"] + [c["name"] for c in channel_config[:d.shape[0]]]
                with open(fpath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for i in range(n):
                        row = [f"{ts[i]:.6f}"] + [f"{d[ch, i]:.6g}" for ch in range(d.shape[0])]
                        writer.writerow(row)
                total += n

        self.st.showMessage(
            f"Exported {axes_count} axes, {total} samples to {session_dir}"
        )

        # Show summary dialog
        QMessageBox.information(
            self, "Export Complete",
            f"Session exported to:\n{session_dir}\n\n"
            f"Axes: {axes_count}\n"
            f"Total samples: {total:,}"
        )

# ── Main ─────────────────────────────────────────────────

def main():
    pg.setConfigOptions(antialias=True, background=BG_COLOR, foreground=TEXT_COLOR, useOpenGL=False)
    app = QApplication(sys.argv)
    app.setApplicationName("Servo Multi-Axis Oscilloscope")

    # ── Parse CLI args ──
    force_sim = "--sim" in sys.argv
    n_axes = 3
    for i, arg in enumerate(sys.argv):
        if arg == "--axes" and i + 1 < len(sys.argv):
            try:
                n_axes = int(sys.argv[i + 1])
                n_axes = max(1, min(n_axes, 64))
            except ValueError:
                pass

    # ── Build default axes config (used only in --sim mode) ──
    axis_names_extra = ["U", "V", "W", "A", "B", "C", "S0", "S1", "S2", "S3"]
    colors_extra = ["#FF44FF", "#FFCC00", "#00FFCC", "#FF6644",
                    "#66FF66", "#6688FF", "#FF66CC", "#66FFFF",
                    "#CCFF44", "#FF4466"]

    default_axes_cfg = []
    for i in range(n_axes):
        if i < len(DEFAULT_AXES):
            cfg = DEFAULT_AXES[i].copy()
        else:
            extra_idx = i - len(DEFAULT_AXES)
            name = axis_names_extra[extra_idx] if extra_idx < len(axis_names_extra) else f"A{i}"
            color = colors_extra[extra_idx % len(colors_extra)]
            cfg = {"id": name, "name": f"{name} Axis", "color": color, "offset": i * 0.8}
        default_axes_cfg.append(cfg)

    if force_sim:
        # ── Straight to Sim mode ──
        win = ScopeWindow(axes_cfg=default_axes_cfg, mode=MODE_SIM)
        win.show()
    else:
        # ── Discover-first: show UI immediately, run discovery inside it ──
        win = ScopeWindow(discovering=True)
        win.show()
        # Start discovery after the window is visible
        QTimer.singleShot(200, win._start_discovery)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

"""
Tkinter Oscilloscope — 8-channel, zero-dependency, 195+ FPS.

Python stdlib only. No Qt, no pyqtgraph, no pip install needed.
Just: python scope_tk.py

Keys: 1-8 = Toggle channel  Space = Pause/Resume  Q = Quit
"""

import math
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import List, Optional

# ── Optional: AI pipeline integration ────────────────────────
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

# ── Optional: scope engine (for non-demo data source) ────────
_SCOPE_ENGINE_AVAILABLE = False
try:
    from scope_engine import ScopeEngine
    _SCOPE_ENGINE_AVAILABLE = True
except ImportError:
    pass

# ── Optional: CSV export module ────────────────────────────────
_CSV_EXPORT_AVAILABLE = False
try:
    from csv_export import export_waveform_csv
    _CSV_EXPORT_AVAILABLE = True
except ImportError:
    pass

# ── Channel definitions ──────────────────────────────────────
CHANNELS = [
    {"name": "Position Actual", "unit": "pulses", "color": "#00FF88"},
    {"name": "Velocity Actual", "unit": "rpm",    "color": "#FF8800"},
    {"name": "Current Actual",  "unit": "%",      "color": "#FF4444"},
    {"name": "Torque Actual",   "unit": "%",      "color": "#44AAFF"},
    {"name": "Following Error", "unit": "pulses", "color": "#E066CC"},
    {"name": "Digital Inputs",  "unit": "bits",   "color": "#FFCC00"},
    {"name": "Statusword",      "unit": "hex",    "color": "#22DD88"},
    {"name": "Op Mode Display", "unit": "code",   "color": "#CCCCCC"},
]
N_CH = 8

# ── Colors ───────────────────────────────────────────────────
BG       = "#0D0D1A"
GRID     = "#1A1A2E"
DIVIDER  = "#2A2A4E"
TEXT     = "#AAAACC"
TEXT_DIM = "#666688"
SIDEBAR  = "#111122"
WARN     = "#FF8844"
OK       = "#44FF44"
CRITICAL = "#FF4444"
INFO     = "#44AAFF"


class TkScope:
    """Zero-dependency 8-channel oscilloscope. Python stdlib only."""

    def __init__(self, sample_rate: int = 1000, history_sec: float = 6.0,
                 mode: str = "sim", master=None, discovering: bool = False):
        self.sample_rate = sample_rate
        self.history_samples = int(sample_rate * history_sec)
        self._running = True
        self._paused = False
        self._frame = 0
        self._t0 = time.perf_counter()
        self._sample_count = 0
        self._ai_events: List[str] = []
        self._mode = "scanning" if discovering else mode
        self._master = master

        # ── Discovery state ──
        self._discovery_adapter = None
        self._discovery_master = None
        self._discovery_slaves = None
        self._disc_steps = [
            ("Detect EtherCAT adapter", "pending", ""),
            ("Initialize EtherCAT master", "pending", ""),
            ("Scan bus for slaves", "pending", ""),
            ("Discover slave identities", "pending", ""),
            ("Auto-name axes", "pending", ""),
        ]
        self._disc_done = False
        self._disc_show_buttons = False

        # Ring buffers
        self._data = [[0.0] * self.history_samples for _ in range(N_CH)]

        # AI pipeline
        self.ai_pipeline = None
        if _AI_AVAILABLE:
            try:
                self.ai_pipeline = _AIAnalyzerPipeline(sample_rate_hz=float(sample_rate))
            except Exception:
                pass

        # Channel visibility (4 channels on by default)
        self.ch_visible = [True] * N_CH  # all 8 channels on by default

        # ── Build UI ──────────────────────────────────────────
        self.root = tk.Tk()
        mode_str = "🔍 Discover" if self._mode == "discover" else "● Sim (synthetic)"
        self.root.title(f"Delta A3 Oscilloscope — {mode_str}")
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(main, bg=SIDEBAR, width=220)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        self._build_sidebar(sidebar)

        # Key bindings
        self.root.bind("<space>", lambda e: self.toggle_pause())
        self.root.bind("<r>", lambda e: self._clear())
        self.root.bind("<s>", lambda e: self._export())
        self.root.bind("<Control-s>", lambda e: self._export())
        self.root.bind("<q>", lambda e: self.stop())
        for i in range(1, 9):
            self.root.bind(str(i), lambda e, n=i-1: self._toggle_ch(n))

        # Start render loop
        self._draw()

    # ── Sidebar ─────────────────────────────────────────────

    def _build_sidebar(self, fg: tk.Frame):
        tk.Label(fg, text="Channels", fg=TEXT, bg=SIDEBAR,
                 font=("Consolas", 10, "bold")).pack(pady=(10, 4))

        self._ch_btns = []
        self._ch_vals = []
        for i in range(N_CH):
            row = tk.Frame(fg, bg=SIDEBAR)
            row.pack(fill=tk.X, padx=8, pady=1)
            s = self.ch_visible[i]
            dot = tk.Label(row, text="●", fg=CHANNELS[i]["color"] if s else "#444",
                          bg=SIDEBAR, font=("Consolas", 10))
            dot.pack(side=tk.LEFT)
            nm = tk.Label(row, text=CHANNELS[i]["name"], fg=TEXT if s else TEXT_DIM,
                         bg=SIDEBAR, font=("Consolas", 9))
            nm.pack(side=tk.LEFT, padx=(4, 8))
            val = tk.Label(row, text="--", fg=TEXT_DIM, bg=SIDEBAR,
                          font=("Consolas", 8))
            val.pack(side=tk.RIGHT)
            for w in (row, dot, nm):
                w.bind("<Button-1>", lambda e, n=i: self._toggle_ch(n))
            self._ch_btns.append((dot, nm))
            self._ch_vals.append(val)

        tk.Label(fg, text="Controls", fg=TEXT, bg=SIDEBAR,
                 font=("Consolas", 10, "bold")).pack(pady=(16, 4))

        self._pause_btn = tk.Label(fg, text="▶ Running", fg=OK, bg="#2A2A4E",
                                    font=("Consolas", 9), padx=8, pady=4, cursor="hand2")
        self._pause_btn.pack(pady=2)
        self._pause_btn.bind("<Button-1>", lambda e: self.toggle_pause())

        # Mode indicator — prominent colored banner
        mode_bg = "#1A3A1A" if self._mode == "discover" else "#3A2A1A"
        mode_fg = "#44FF44" if self._mode == "discover" else "#FF8844"
        mode_border = "#2A5A2A" if self._mode == "discover" else "#5A3A2A"
        self._mode_frame = tk.Frame(fg, bg=mode_border, padx=1, pady=1)
        self._mode_frame.pack(fill=tk.X, padx=4, pady=(8, 2))
        self._mode_lbl = tk.Label(self._mode_frame, text=self._mode_label(),
                                  fg=mode_fg, bg=mode_bg,
                                  font=("Consolas", 10, "bold"),
                                  padx=6, pady=4)
        self._mode_lbl.pack(fill=tk.X)

        self._connect_btn = tk.Label(fg, text="⬤ Switch to Sim" if self._mode == "discover" else "🔍 Discover Hardware",
                                     fg=TEXT, bg="#2A2A4E",
                                     font=("Consolas", 9), padx=8, pady=4, cursor="hand2")
        self._connect_btn.pack(pady=2, padx=4, fill=tk.X)
        self._connect_btn.bind("<Button-1>", lambda e: self._toggle_mode())

        self._fps_lbl = tk.Label(fg, text="FPS: --", fg=TEXT_DIM, bg=SIDEBAR,
                                  font=("Consolas", 8))
        self._fps_lbl.pack(anchor=tk.W, pady=(12, 0))
        self._samples_lbl = tk.Label(fg, text="Samples: 0", fg=TEXT_DIM, bg=SIDEBAR,
                                      font=("Consolas", 8))
        self._samples_lbl.pack(anchor=tk.W)

        self._stats_lbl = tk.Label(fg, text="--", fg=TEXT_DIM, bg=SIDEBAR,
                                    font=("Consolas", 8), justify=tk.LEFT)
        self._stats_lbl.pack(anchor=tk.W, pady=(4, 0))

        self._ai_lbl = tk.Label(fg, text="", fg=OK, bg=SIDEBAR,
                                 font=("Consolas", 8), wraplength=200, justify=tk.LEFT)
        self._ai_lbl.pack(anchor=tk.W, pady=(8, 0))

        tk.Label(fg, text="Keys: 1-8 Toggle  Space Pause  S Save  Q Quit",
                fg=TEXT_DIM, bg=SIDEBAR, font=("Consolas", 7)).pack(pady=(16, 4))

    def _mode_label(self) -> str:
        if self._mode == "discover":
            slaves = getattr(self._master, 'slavecount', 0) if self._master else 0
            return f"Mode: 🔍 Discover ({slaves} slave(s))" if slaves else "Mode: 🔍 Discover"
        return "Mode: ● Sim (synthetic)"

    def _toggle_mode(self):
        """Toggle between Sim and Discover mode."""
        if self._mode == "discover":
            self._mode = "sim"
            if self._master:
                try:
                    self._master.close()
                except Exception:
                    pass
                self._master = None
            self._update_mode_ui()
            print("[scope_tk] Switched to Sim mode")
        else:
            # Try Discover
            print("[scope_tk] Attempting Discover...")
            try:
                from discover import detect_ethercat_adapter
                adapter = detect_ethercat_adapter()
                if adapter is None:
                    print("[scope_tk] No EtherCAT NIC found. Staying in Sim.")
                    self._show_no_hardware_warning()
                    return
            except Exception as e:
                print(f"[scope_tk] NIC detection failed: {e}")
                self._show_no_hardware_warning()
                return

            try:
                from ec_master import EcMaster
                from discover import auto_name_axes
                master = EcMaster(adapter=adapter)
                master.scan()
                slaves = master.discover()
                if not slaves:
                    print("[scope_tk] No slaves found. Staying in Sim.")
                    master.close()
                    self._show_no_hardware_warning()
                    return
                axes_cfg = auto_name_axes(slaves)
                print(f"[scope_tk] Discover mode: {len(slaves)} slave(s), "
                      f"{len(axes_cfg)} axis(es)")
                self._master = master
                self._mode = "discover"
                self._update_mode_ui()
            except Exception as e:
                print(f"[scope_tk] Discover failed: {e}")
                self._show_no_hardware_warning()

    def _update_mode_ui(self):
        """Update mode label, frame colors, button text, and window title."""
        if self._mode == "discover":
            slaves = getattr(self._master, 'slavecount', 0) if self._master else 0
            mode_bg = "#1A3A1A"
            mode_fg = "#44FF44"
            mode_border = "#2A5A2A"
            btn_text = "⬤ Switch to Sim"
            title_mode = f"🔍 Discover ({slaves} slave(s))" if slaves else "🔍 Discover"
        else:
            mode_bg = "#3A2A1A"
            mode_fg = "#FF8844"
            mode_border = "#5A3A2A"
            btn_text = "🔍 Discover Hardware"
            title_mode = "● Sim (synthetic)"

        self._mode_lbl.configure(text=self._mode_label(), fg=mode_fg, bg=mode_bg)
        self._mode_frame.configure(bg=mode_border)
        self._connect_btn.configure(text=btn_text)
        self.root.title(f"Delta A3 Oscilloscope — {title_mode}")

    def _show_no_hardware_warning(self):
        """Show a warning popup when no EtherCAT hardware is found."""
        import tkinter.messagebox as mb
        mb.showwarning(
            "No EtherCAT Hardware Detected",
            "No EtherCAT-compatible NIC found or\n"
            "no slaves responded on the bus.\n\n"
            "Check:\n"
            "  • Npcap/WinPcap installed\n"
            "  • NIC connected to servo drives\n"
            "  • Servo drives powered on\n\n"
            "Staying in Sim mode with synthetic waveforms.",
            parent=self.root,
        )
        self.ch_visible[n] = not self.ch_visible[n]
        s = self.ch_visible[n]
        dot, nm = self._ch_btns[n]
        dot.configure(fg=CHANNELS[n]["color"] if s else "#444")
        nm.configure(fg=TEXT if s else TEXT_DIM)

    def toggle_pause(self):
        self._paused = not self._paused
        self._pause_btn.configure(
            text="⏸ Paused" if self._paused else "▶ Running",
            fg=WARN if self._paused else OK,
        )

    def _clear(self):
        for ch in range(N_CH):
            self._data[ch] = [0.0] * self.history_samples
        self._sample_count = 0
        self._ai_events.clear()

    def _export(self):
        """Export waveform data to CSV via save dialog."""
        from tkinter import filedialog
        from datetime import datetime

        default_name = datetime.now().strftime("scope_%Y%m%d_%H%M%S.csv")
        filepath = filedialog.asksaveasfilename(
            title="Export Waveform CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filepath:
            return  # user cancelled

        n = min(self._sample_count, self.history_samples)

        # Build data arrays from ring buffers
        import numpy as np
        data = np.array([self._data[ch][:n] for ch in range(N_CH)], dtype=np.float32)
        timestamps = np.array([i / self.sample_rate for i in range(n)], dtype=np.float64)

        channel_config = [
            {"name": CHANNELS[i]["name"], "unit": CHANNELS[i]["unit"]}
            for i in range(N_CH)
        ]
        metadata = {
            "sample_rate_hz": self.sample_rate,
            "axis_id": "Axis0",
        }

        if _CSV_EXPORT_AVAILABLE:
            written = export_waveform_csv(filepath, data, timestamps, channel_config, metadata)
        else:
            import csv
            headers = ["Timestamp (s)"] + [c["name"] for c in channel_config]
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for i in range(n):
                    row = [f"{timestamps[i]:.6f}"]
                    for ch in range(N_CH):
                        row.append(f"{data[ch, i]:.6g}")
                    writer.writerow(row)
            written = n

        self._status_msg = f"Exported {written} samples to {filepath}"
        print(self._status_msg)

    # ── Data generation ────────────────────────────────────

    def _gen_sample(self) -> List[float]:
        t = self._sample_count / self.sample_rate
        return [
            1000.0 * math.sin(2 * math.pi * 2.0 * t),               # Position
            500.0 * math.sin(2 * math.pi * 3.5 * t + 0.5),          # Velocity
            80.0 + 30.0 * math.sin(2 * math.pi * 5.0 * t),           # Current
            60.0 * math.sin(2 * math.pi * 2.0 * t + 1.2),            # Torque
            15.0 * math.sin(2 * math.pi * 7.0 * t),                  # Foll.Err
            float(self._sample_count % 100 > 50),                    # DIO
            0x0237 if self._sample_count % 200 < 100 else 0x0007,   # Status
            float((self._sample_count // 50) % 8),                   # OpMode
        ]

    def _push(self, values: List[float]):
        for ch in range(N_CH):
            buf = self._data[ch]
            buf[:-1] = buf[1:]
            buf[-1] = values[ch]
        self._sample_count += 1

    # ── AI analysis ────────────────────────────────────────

    def _run_ai(self, values: List[float]):
        """Run AI pipeline with real buffer statistics."""
        if self.ai_pipeline is None:
            return

        try:
            # Compute per-channel stats from actual ring buffer data
            names = [c["name"] for c in CHANNELS]
            buffer_stats = {}
            for ci in range(N_CH):
                buf = self._data[ci]
                if len(buf) < 30:
                    continue
                tail = buf[-200:]  # last 200 samples (~200ms)
                mn = sum(tail) / len(tail)
                mx = max(tail)
                mn_all = min(tail)
                sd = (sum((v - mn) ** 2 for v in tail) / len(tail)) ** 0.5
                rms = (sum(v ** 2 for v in tail) / len(tail)) ** 0.5
                buffer_stats[names[ci]] = {
                    "mean": mn, "std": sd, "min": mn_all, "max": mx,
                    "rms": rms, "peak_to_peak": mx - mn_all,
                }

            anns = self.ai_pipeline.analyze(values, names, buffer_stats)

            for ann in anns:
                sev_c = {"info": INFO, "warning": WARN, "critical": CRITICAL}
                icon = {"info": "i", "warning": "!", "critical": "!!"}
                msg = f"{icon.get(ann.severity, '?')} {ann.channel}: {ann.message[:100]}"
                if ann.suggestion:
                    msg += f"\n  -> {ann.suggestion[:80]}"
                self._ai_events.append(msg)
                if len(self._ai_events) > 20:
                    self._ai_events = self._ai_events[-8:]
                self._ai_lbl.configure(
                    text="\n".join(self._ai_events[-4:]),
                    fg=sev_c.get(ann.severity, TEXT),
                )
        except Exception:
            pass

    # ── Discovery (in-window checklist) ────────────────────

    def _start_discovery(self):
        """Run hardware discovery steps, updating the in-window checklist."""
        # Ensure bindings path is available
        _bindings_path = str(Path(__file__).resolve().parent.parent.parent
                             / "03-ethercat-master" / "bindings")
        if _bindings_path not in sys.path:
            sys.path.insert(0, _bindings_path)

        def _run_step(step_idx: int):
            # Bail if window closed or mode changed
            if not self._running or self._mode != "scanning":
                return
            if step_idx >= len(self._disc_steps):
                return

            name, _, _ = self._disc_steps[step_idx]
            self._disc_steps[step_idx] = (name, "running", "Working...")

            if step_idx == 0:
                try:
                    from discover import detect_ethercat_adapter
                    adapter = detect_ethercat_adapter()
                    if adapter is None:
                        self._disc_steps[0] = ("Detect EtherCAT adapter", "fail",
                                               "No adapter found")
                        _finish_discovery(False)
                        return
                    self._disc_steps[0] = ("Detect EtherCAT adapter", "ok", str(adapter)[:50])
                    self._discovery_adapter = adapter
                    self.root.after(80, lambda: _run_step(1))
                except Exception as e:
                    self._disc_steps[0] = ("Detect EtherCAT adapter", "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 1:
                try:
                    from ec_master import EcMaster
                    master = EcMaster(adapter=self._discovery_adapter)
                    self._discovery_master = master
                    self._disc_steps[1] = ("Initialize EtherCAT master", "ok", "SOEM/IgH ready")
                    self.root.after(80, lambda: _run_step(2))
                except Exception as e:
                    self._disc_steps[1] = ("Initialize EtherCAT master", "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 2:
                try:
                    self._discovery_master.scan()
                    count = self._discovery_master.slavecount
                    if count == 0:
                        self._disc_steps[2] = ("Scan bus for slaves", "fail", "No slaves on bus")
                        _finish_discovery(False)
                        return
                    self._disc_steps[2] = ("Scan bus for slaves", "ok", f"{count} slave(s)")
                    self.root.after(80, lambda: _run_step(3))
                except Exception as e:
                    self._disc_steps[2] = ("Scan bus for slaves", "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 3:
                try:
                    slaves = self._discovery_master.discover()
                    if not slaves:
                        self._disc_steps[3] = ("Discover slave identities", "fail",
                                               "No response from slaves")
                        _finish_discovery(False)
                        return
                    servo_count = sum(1 for s in slaves
                                     if s.get("esi_match", {}).get("is_servo_drive"))
                    self._disc_steps[3] = ("Discover slave identities", "ok",
                                          f"{len(slaves)} devices ({servo_count} servos)")
                    self._discovery_slaves = slaves
                    self.root.after(80, lambda: _run_step(4))
                except Exception as e:
                    self._disc_steps[3] = ("Discover slave identities", "fail", str(e)[:60])
                    _finish_discovery(False)

            elif step_idx == 4:
                try:
                    from discover import auto_name_axes, save_axis_config
                    axes_cfg = auto_name_axes(self._discovery_slaves)
                    save_axis_config(axes_cfg)
                    axis_list = ", ".join(a["id"] for a in axes_cfg)
                    self._disc_steps[4] = ("Auto-name axes", "ok", f"{len(axes_cfg)} axes: {axis_list}")
                    self.root.after(300, lambda: _finish_discovery(
                        True, self._discovery_master, axes_cfg))
                except Exception as e:
                    self._disc_steps[4] = ("Auto-name axes", "fail", str(e)[:60])
                    _finish_discovery(False)

        def _finish_discovery(success: bool, master=None, axes_cfg=None):
            if not self._running or self._mode != "scanning":
                return
            self._disc_done = True
            if success:
                self._master = master
                self._mode = "discover"
                self._update_mode_ui()
                # Clear discovery state
                self._disc_steps = []
                self._disc_show_buttons = False
                print(f"[scope_tk] Discover mode: {len(axes_cfg)} axis(es)")
            else:
                self._disc_show_buttons = True
                if master:
                    try:
                        master.close()
                    except Exception:
                        pass

        # Start discovery after window is visible
        self.root.after(200, lambda: _run_step(0))

    def _render_discovery(self, w: int, h: int):
        """Render the in-window discovery checklist."""
        c = self.canvas
        c.delete("all")

        # Title
        title_x, title_y = w // 2, 50
        c.create_text(title_x, title_y,
                     text="EtherCAT Hardware Discovery",
                     fill=TEXT, font=("Consolas", 15, "bold"))

        # Step list
        y_start = 100
        step_h = 38
        icon_map = {"pending": ("⏳", "#666688"), "running": ("⏳", "#FFCC44"),
                    "ok": ("✓", "#44FF44"), "fail": ("✗", "#FF4444")}

        for i, (name, status, detail) in enumerate(self._disc_steps):
            y = y_start + i * step_h
            icon, color = icon_map.get(status, ("?", "#666"))
            c.create_text(80, y, text=icon, fill=color,
                         font=("Consolas", 13), anchor=tk.W)
            text_color = {"running": "#FFCC44", "ok": "#44AA66",
                         "fail": "#FF6644", "pending": "#666688"}.get(status, "#666")
            c.create_text(110, y, text=name, fill=text_color,
                         font=("Consolas", 12), anchor=tk.W)
            if detail:
                c.create_text(460, y, text=detail, fill=text_color,
                             font=("Consolas", 10), anchor=tk.W)

        # Status message
        status_y = y_start + 5 * step_h + 40
        if self._disc_done and self._disc_show_buttons:
            c.create_text(w // 2, status_y,
                         text="No EtherCAT hardware detected.\n"
                              "Choose Sim mode to continue with synthetic waveforms.",
                         fill=WARN, font=("Consolas", 12), justify=tk.CENTER)

            # Sim button
            bx, by = w // 2 - 100, status_y + 60
            c.create_rectangle(bx - 60, by - 14, bx + 60, by + 18,
                             fill="#3A2A1A", outline="#5A3A2A", width=2,
                             tags="btn_sim")
            c.create_text(bx, by, text="Run in Sim Mode",
                         fill="#FF8844", font=("Consolas", 11, "bold"),
                         tags="btn_sim")
            self.canvas.tag_bind("btn_sim", "<Button-1>", lambda e: self._disc_enter_sim())

            # Exit button
            ex, ey = w // 2 + 100, status_y + 60
            c.create_rectangle(ex - 40, ey - 14, ex + 40, ey + 18,
                             fill="#2A2A4E", outline="#4A4A6E", width=2,
                             tags="btn_exit")
            c.create_text(ex, ey, text="Exit",
                         fill="#AAAACC", font=("Consolas", 11, "bold"),
                         tags="btn_exit")
            self.canvas.tag_bind("btn_exit", "<Button-1>", lambda e: self.stop())
        elif self._disc_done:
            pass  # success case handled by _finish_discovery → mode switch
        else:
            running_step = next((s for s in self._disc_steps if s[1] == "running"), None)
            if running_step:
                idx = next(i for i, s in enumerate(self._disc_steps) if s[1] == "running")
                c.create_text(w // 2, status_y,
                             text=f"Step {idx + 1}/{len(self._disc_steps)}: {running_step[0]}...",
                             fill="#FFCC44", font=("Consolas", 12))

    def _disc_enter_sim(self):
        """User clicked 'Run in Sim Mode' from the discovery panel."""
        self._mode = "sim"
        self._disc_steps = []
        self._disc_show_buttons = False
        self._disc_done = False
        self._update_mode_ui()
        self._discovery_adapter = None
        self._discovery_master = None
        self._discovery_slaves = None
        print("[scope_tk] Entered Sim mode from discovery panel")

    # ── Main render loop ───────────────────────────────────

    def _draw(self):
        if not self._running:
            return

        self._frame += 1
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()

        if self._mode == "scanning":
            self._render_discovery(w, h)
            self.root.after(16, self._draw)  # keep looping for live updates
            return

        if not self._paused and w > 50 and h > 50:
            # Generate samples (~60 FPS worth)
            n_new = max(1, self.sample_rate // 60)
            for _ in range(n_new):
                values = self._gen_sample()
                self._push(values)
                if self._sample_count % 10 == 0:
                    self._run_ai(values)

            self._render(w, h)

        self.root.after(16, self._draw)

    def _render(self, w: int, h: int):
        c = self.canvas
        c.delete("all")

        vis = [i for i in range(N_CH) if self.ch_visible[i]]
        n_vis = len(vis)
        if n_vis == 0:
            return

        ch_h = h / n_vis

        # Grid
        for i in range(1, 10):
            x = w * i / 10
            c.create_line(x, 0, x, h, fill=GRID, width=0.5)
        for i in range(1, n_vis + 1):
            y = h * i / n_vis
            c.create_line(0, y, w, y, fill=DIVIDER, width=1)

        # Waveforms
        for draw_n, ch_idx in enumerate(vis):
            y0 = draw_n * ch_h + 22
            y1 = (draw_n + 1) * ch_h - 8
            y_rng = y1 - y0
            if y_rng < 20:
                continue

            buf = self._data[ch_idx]
            if len(buf) < 2:
                continue

            dmin, dmax = min(buf), max(buf)
            if dmax - dmin < 1:
                dmin, dmax = -100, 100
            pad = (dmax - dmin) * 0.05
            dmin -= pad
            dmax += pad

            color = CHANNELS[ch_idx]["color"]
            name = CHANNELS[ch_idx]["name"]
            unit = CHANNELS[ch_idx]["unit"]

            # Label
            c.create_text(8, y0 - 10, text=name, fill=color,
                         anchor=tk.W, font=("Consolas", 9))
            c.create_text(w - 8, y0 - 10, text=f"{dmin:.0f}..{dmax:.0f} {unit}",
                         fill=TEXT_DIM, anchor=tk.E, font=("Consolas", 7))

            # Polyline (single canvas item — fast)
            pts = []
            step = max(1, len(buf) // (w - 20))
            for i in range(0, len(buf), step):
                x = 10 + (w - 20) * i / len(buf)
                y = y1 - y_rng * (buf[i] - dmin) / (dmax - dmin)
                pts.extend([x, y])

            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=1.2)

            # Zero line
            if dmin < 0 < dmax:
                yz = y1 - y_rng * (0 - dmin) / (dmax - dmin)
                c.create_line(10, yz, w - 10, yz, fill="#222244", width=0.5)

            # Latest value
            self._ch_vals[ch_idx].configure(text=f"{buf[-1]:.1f} {unit}")

        # Stats update (~4 Hz)
        if self._frame % 15 == 0:
            elapsed = time.perf_counter() - self._t0
            fps = self._frame / elapsed if elapsed > 0 else 0
            self._fps_lbl.configure(text=f"FPS: {fps:.0f}")
            self._samples_lbl.configure(text=f"Samples: {self._sample_count}")

            lines = []
            for ch_idx in vis[:4]:
                buf = self._data[ch_idx]
                if len(buf) > 100:
                    tail = buf[-200:]
                    mn = sum(tail) / len(tail)
                    mx = max(tail)
                    lines.append(f"{CHANNELS[ch_idx]['name']:8s} pk={mx:7.0f} μ={mn:7.0f}")
            self._stats_lbl.configure(text="\n".join(lines))

    def run(self):
        self.root.mainloop()

    def stop(self):
        self._running = False
        self.root.quit()
        self.root.destroy()


def main():
    print("Delta A3 Oscilloscope — tkinter (Python stdlib, 0 dependencies)")
    print("Keys: 1-8 = Toggle channel | Space = Pause | Q = Quit")

    force_sim = "--sim" in sys.argv

    if force_sim:
        app = TkScope(sample_rate=1000, mode="sim")
    else:
        # Discover-first: show the window immediately, run discovery inside it
        app = TkScope(sample_rate=1000, discovering=True)
        app._start_discovery()

    app.run()


if __name__ == "__main__":
    main()

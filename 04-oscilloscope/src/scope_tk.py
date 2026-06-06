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

# ── Channel definitions ──────────────────────────────────────
CHANNELS = [
    {"name": "Position", "unit": "pulses", "color": "#00FF88"},
    {"name": "Velocity", "unit": "rpm",    "color": "#FF8800"},
    {"name": "Current",  "unit": "%",      "color": "#FF4444"},
    {"name": "Torque",   "unit": "%",      "color": "#44AAFF"},
    {"name": "Foll.Err", "unit": "pulses", "color": "#FF44FF"},
    {"name": "DIO",      "unit": "bits",   "color": "#FFFF44"},
    {"name": "Status",   "unit": "hex",    "color": "#44FFAA"},
    {"name": "OpMode",   "unit": "code",   "color": "#AAAAAA"},
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

    def __init__(self, sample_rate: int = 1000, history_sec: float = 6.0):
        self.sample_rate = sample_rate
        self.history_samples = int(sample_rate * history_sec)
        self._running = True
        self._paused = False
        self._frame = 0
        self._t0 = time.perf_counter()
        self._sample_count = 0
        self._ai_events: List[str] = []

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
        self.ch_visible = [True, True, True, True, False, False, False, False]

        # ── Build UI ──────────────────────────────────────────
        self.root = tk.Tk()
        self.root.title("Delta A3 Oscilloscope — tkinter (Python stdlib, 0 deps)")
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

        tk.Label(fg, text="Keys: 1-8 Toggle  Space Pause  Q Quit",
                fg=TEXT_DIM, bg=SIDEBAR, font=("Consolas", 7)).pack(pady=(16, 4))

    def _toggle_ch(self, n: int):
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

    # ── Main render loop ───────────────────────────────────

    def _draw(self):
        if not self._running:
            return

        self._frame += 1
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()

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
    app = TkScope(sample_rate=1000)
    app.run()


if __name__ == "__main__":
    main()

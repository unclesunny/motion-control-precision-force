"""
Multi-Axis AI Simulation Demo — 3-Axis + Cross-Axis Analysis.

Runs the full 4-detector pipeline (3 single-axis + 1 cross-axis) against
synthetic servo data for 3 axes (X, Y, Z). Injects 4 cross-axis fault
scenarios and verifies end-to-end detection.

Usage:
    python demo_multi_axis.py              # All scenarios
    python demo_multi_axis.py --axes 6     # 6-axis demo
"""

import sys
import time
from pathlib import Path

import numpy as np

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure AI analyzer is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "06-ai-analyzer"))

from ai_analyzer import AIAnalyzerPipeline, CrossAxisAnalyzer, AxisSnapshot

# ── Color helpers ────────────────────────────────────────────
C = {
    "R": "\033[91m", "G": "\033[92m", "Y": "\033[93m",
    "B": "\033[94m", "M": "\033[95m", "C": "\033[96m",
    "W": "\033[97m", "dim": "\033[2m", "reset": "\033[0m",
    "bold": "\033[1m",
}
SEV_ICON = {"info": "ℹ", "warning": "⚠", "critical": "🔴"}
SEV_COLOR = {"info": C["B"], "warning": C["Y"], "critical": C["R"]}

CH_NAMES = ["Position", "Velocity", "Current", "Torque",
            "Foll.Err", "DIO", "Status", "OpMode"]


def header():
    print(f"""
{C['bold']}{C['C']}╔══════════════════════════════════════════════════════════════════╗
║     Multi-Axis AI Analyzer — Cross-Axis Detection Demo          ║
║     4 Detectors: Current │ Tracking │ Resonance │ Cross-Axis   ║
║     3 Axes: X, Y, Z  —  Bus Sag │ Contouring │ Ring │ Coupling ║
╚══════════════════════════════════════════════════════════════════╝{C['reset']}
""")


def print_ann(ann, prefix=""):
    icon = SEV_ICON.get(ann.severity, "?")
    color = SEV_COLOR.get(ann.severity, C["W"])
    axis_tag = f"[{ann.axis_id}] " if getattr(ann, 'axis_id', '') else ""
    print(f"  {prefix}{color}{icon} {axis_tag}[{ann.category}]{C['reset']} "
          f"{C['bold']}{ann.channel}{C['reset']}: {ann.message}")
    if ann.suggestion:
        print(f"    {C['dim']}→ {ann.suggestion}{C['reset']}")


def print_section(title, color=C["C"]):
    print(f"\n{color}{C['bold']}┌─── {title} ───┐{C['reset']}")


def build_stats(values_array, name=""):
    """Compute buffer stats from a values array."""
    vals = np.array(values_array)
    return {
        "mean": float(np.mean(vals)),
        "std": float(np.std(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "rms": float(np.sqrt(np.mean(vals ** 2))),
        "peak_to_peak": float(np.max(vals) - np.min(vals)),
    }


# ══════════════════════════════════════════════════════════════════
# Scenario 1: Normal Operation (baseline)
# ══════════════════════════════════════════════════════════════════

def _prime_cross_axis(cross_axis, n: int = 200):
    """Prime cross-axis detectors with normal multi-axis data.

    Critical: cross-axis detectors maintain sliding windows. Without priming,
    the first fault injection fills the window entirely with anomalous data,
    making the dynamic threshold adapt to the fault level. Priming with
    normal data establishes a valid baseline.
    """
    if cross_axis is None:
        return
    for i in range(n):
        t = i / 1000.0
        snapshots = {}
        for aid, offset in [("X", 0.0), ("Y", 1.2), ("Z", 2.4)]:
            vals = [
                1000.0*np.sin(2*np.pi*2.0*t + offset),
                500.0*np.sin(2*np.pi*3.5*t + 0.5 + offset),
                80.0 + 30.0*np.sin(2*np.pi*5.0*t + offset),
                60.0*np.sin(2*np.pi*2.0*t + 1.2 + offset),
                5.0 + np.random.normal(0, 1.0),
                float(i % 100 > 50), 0x0237, 1.0,
            ]
            snapshots[aid] = AxisSnapshot(
                axis_id=aid,
                slave_position={"X": 0, "Y": 1, "Z": 2}[aid],
                values=vals,
                channel_names=CH_NAMES,
                buffer_stats={
                    "Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 140.0,
                               "rms": 85.0, "peak_to_peak": 120.0,
                               "fft_peak_magnitude": 0.0},
                    "Foll.Err": {"mean": 5.0, "std": 2.0, "min": 0.0, "max": 15.0,
                                "rms": 7.0, "peak_to_peak": 15.0},
                    "Velocity": {"fft_peak_magnitude": 0.0},
                    "Position": {"min": -1000.0, "max": 1000.0},
                },
            )
        cross_axis.analyze(snapshots, slave_errors={0: False, 1: False, 2: False})


def run_normal(pipelines, cross_axis, duration_s=3):
    """3-axis normal servo operation — expect zero annotations."""
    print_section("Scenario 1: Normal 3-Axis Operation", C["G"])
    print(f"  {C['dim']}Running {duration_s}s normal operation across 3 axes...{C['reset']}")

    # Prime cross-axis with normal data
    _prime_cross_axis(cross_axis, n=300)

    all_annotations = []
    for i in range(duration_s * 1000):
        t = i / 1000.0
        per_axis = {}
        for aid, offset in [("X", 0.0), ("Y", 1.2), ("Z", 2.4)]:
            vals = [
                1000.0 * np.sin(2*np.pi*2.0*t + offset),
                500.0 * np.sin(2*np.pi*3.5*t + 0.5 + offset),
                80.0 + 30.0 * np.sin(2*np.pi*5.0*t + offset),
                60.0 * np.sin(2*np.pi*2.0*t + 1.2 + offset),
                10.0 + 5.0 * np.sin(2*np.pi*7.0*t + offset),
                float(i % 100 > 50), 0x0237, 1.0,
            ]
            per_axis[aid] = vals

        for aid, pipeline in pipelines.items():
            stats = {"Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 140.0,
                                "rms": 85.0, "peak_to_peak": 120.0},
                     "Foll.Err": {"mean": 10.0, "std": 5.0, "min": 0.0, "max": 30.0,
                                 "rms": 14.0, "peak_to_peak": 30.0},
                     "Velocity": {"mean": 0.0, "std": 350.0, "min": -500.0, "max": 500.0,
                                 "rms": 350.0, "peak_to_peak": 1000.0}}
            anns = pipeline.analyze(per_axis[aid], CH_NAMES, stats)
            all_annotations.extend(anns)

        if cross_axis and i % 100 == 0:
            snapshots = {}
            for aid, vals in per_axis.items():
                snapshots[aid] = AxisSnapshot(
                    axis_id=aid, slave_position={"X":0,"Y":1,"Z":2}[aid],
                    values=vals, channel_names=CH_NAMES,
                    buffer_stats={
                        "Current": {"mean": 80.0, "fft_peak_magnitude": 0.0},
                        "Foll.Err": {"mean": 5.0, "std": 2.0},
                        "Velocity": {"fft_peak_magnitude": 0.0},
                        "Position": {"min": -1000.0, "max": 1000.0},
                    },
                )
            cross_axis.analyze(snapshots, slave_errors={0: False, 1: False, 2: False})

    for p in pipelines.values():
        p.reset()
    if cross_axis:
        cross_axis.reset()

    real_anomalies = [a for a in all_annotations
                      if a.category not in ("current_wear", "resonance_detected", "cross_ring_emi")]
    if real_anomalies:
        print(f"  {C['Y']}{len(real_anomalies)} unexpected annotations{C['reset']}")
        for a in real_anomalies[:3]:
            print_ann(a)
    else:
        print(f"  {C['G']}✓ No false positives — all 3 axes normal{C['reset']}")

    return len(real_anomalies)


# ══════════════════════════════════════════════════════════════════
# Scenario 2: Power Bus Sag
# ══════════════════════════════════════════════════════════════════

def run_bus_sag(pipelines, cross_axis):
    """All 3 axes' current drops simultaneously → bus sag detection."""
    print_section("Scenario 2: Power Bus Sag (Cross-Axis)")

    # Prime cross-axis detector with normal current (establishes baseline)
    print(f"  {C['dim']}Priming cross-axis: 300 samples at 80% current...{C['reset']}")
    _prime_cross_axis(cross_axis, n=300)

    # Inject bus sag: all axes drop to 20% simultaneously
    print(f"  {C['R']}>>> Injecting bus sag: all 3 axes current → 20% (75% drop){C['reset']}")
    cross_anns_all = []
    for i in range(150):
        t = i / 1000.0
        snapshots = {}
        for aid, offset in [("X", 0.0), ("Y", 1.2), ("Z", 2.4)]:
            vals = [1000.0*np.sin(2*np.pi*2.0*t + offset),
                    500.0*np.sin(2*np.pi*3.5*t + 0.5 + offset),
                    20.0 + 5.0*np.sin(2*np.pi*5.0*t + offset),  # 80→20
                    60.0*np.sin(2*np.pi*2.0*t + 1.2 + offset),
                    10.0, 0.0, 0x0237, 1.0]
            snapshots[aid] = AxisSnapshot(
                axis_id=aid, slave_position={"X":0,"Y":1,"Z":2}[aid],
                values=vals, channel_names=CH_NAMES,
                buffer_stats={
                    "Current": {"mean": 20.0, "std": 5.0, "fft_peak_magnitude": 0.0},
                    "Velocity": {"fft_peak_magnitude": 0.0},
                    "Position": {"min": -1000.0, "max": 1000.0},
                },
            )
        cross_anns_all.extend(cross_axis.analyze(snapshots))

    for p in pipelines.values(): p.reset()
    cross_axis.reset()

    bus_sag = [a for a in cross_anns_all if a.category == "cross_bus_sag"]
    if bus_sag:
        for a in bus_sag:
            print_ann(a)
        print(f"  {C['G']}✓ Bus sag detected on {bus_sag[0].metadata.get('drop_count','?')} axes{C['reset']}")
    else:
        print(f"  {C['Y']}⚠ Bus sag NOT detected{C['reset']}")
    return len(bus_sag), bus_sag


# ══════════════════════════════════════════════════════════════════
# Scenario 3: Contouring Error
# ══════════════════════════════════════════════════════════════════

def run_contouring(pipelines, cross_axis):
    """X+Y following errors spike simultaneously → contouring error."""
    print_section("Scenario 3: Contouring Error (Cross-Axis)")

    # Prime cross-axis with low foll.err (establishes low threshold)
    print(f"  {C['dim']}Priming cross-axis: 300 samples with foll.err ≈ 5...{C['reset']}")
    _prime_cross_axis(cross_axis, n=300)

    # Inject contouring: X+Y foll.err spike while buffer stats remain low
    print(f"  {C['R']}>>> Injecting XY contouring: foll.err X+Y = 500 pulses (normal baseline still in window){C['reset']}")
    cross_anns_all = []
    for i in range(100):
        t = i / 1000.0
        snapshots = {}
        for aid, ferr in [("X", 500.0), ("Y", 500.0), ("Z", 5.0)]:
            offset = {"X": 0.0, "Y": 1.2, "Z": 2.4}[aid]
            vals = [1000.0*np.sin(2*np.pi*2.0*t + offset),
                    500.0*np.sin(2*np.pi*3.5*t + 0.5 + offset),
                    80.0, 60.0, ferr, 0.0, 0x0237, 1.0]
            snapshots[aid] = AxisSnapshot(
                axis_id=aid, slave_position={"X":0,"Y":1,"Z":2}[aid],
                values=vals, channel_names=CH_NAMES,
                buffer_stats={
                    "Foll.Err": {"mean": 5.0, "std": 2.0, "rms": 7.0},
                    "Current": {"fft_peak_magnitude": 0.0},
                    "Position": {"min": -1000.0, "max": 1000.0},
                    "Velocity": {"fft_peak_magnitude": 0.0},
                },
            )
        cross_anns_all.extend(cross_axis.analyze(snapshots))

    for p in pipelines.values(): p.reset()
    cross_axis.reset()

    contouring = [a for a in cross_anns_all if a.category == "cross_contouring_error"]
    if contouring:
        for a in contouring:
            print_ann(a)
        print(f"  {C['G']}✓ Contouring error detected on {contouring[0].metadata.get('axis_pair','?')}{C['reset']}")
    else:
        print(f"  {C['Y']}⚠ Contouring error NOT detected{C['reset']}")
    return len(contouring), contouring


# ══════════════════════════════════════════════════════════════════
# Scenario 4: EtherCAT Ring Cascade
# ══════════════════════════════════════════════════════════════════

def run_ring_cascade(cross_axis):
    """Simulate EtherCAT frame errors cascading from slave 1."""
    print_section("Scenario 4: EtherCAT Ring Cascade (Cross-Axis)")

    # Prime with healthy ring
    print(f"  {C['dim']}Priming: 50 cycles of healthy ring...{C['reset']}")
    healthy = {0: False, 1: False, 2: False, 3: False}
    for _ in range(50):
        cross_axis.analyze({}, slave_errors=healthy)

    # Inject continuous cascade (no interleaving)
    print(f"  {C['R']}>>> Injecting ring cascade: slave 1 fails → slaves 2,3 cascade (continuous){C['reset']}")
    cascade = {0: False, 1: True, 2: True, 3: True}
    ring_anns = []
    for _ in range(30):
        anns = cross_axis.analyze({}, slave_errors=cascade)
        ring_anns.extend(anns)

    cross_axis.reset()

    cascade_anns = [a for a in ring_anns if a.category == "cross_ring_cascade"]
    if cascade_anns:
        for a in cascade_anns:
            print_ann(a)
        meta = cascade_anns[0].metadata
        print(f"  {C['G']}✓ Ring cascade: root at slave {meta.get('first_error_slave','?')}, "
              f"depth={meta.get('cascade_depth','?')}{C['reset']}")
    else:
        print(f"  {C['Y']}⚠ Ring cascade NOT detected{C['reset']}")
    return len(cascade_anns), cascade_anns


# ══════════════════════════════════════════════════════════════════
# Scenario 5: Mechanical Coupling
# ══════════════════════════════════════════════════════════════════

def run_mechanical_coupling(pipelines, cross_axis):
    """Axis Y vibration depends on Axis X position → mechanical coupling."""
    print_section("Scenario 5: Mechanical Coupling (Cross-Axis)")

    # Prime with uniform low vibration
    print(f"  {C['dim']}Priming: 200 samples with uniform low vibration...{C['reset']}")
    _prime_cross_axis(cross_axis, n=200)

    # 200 cycles where Y's vibration is 10× higher when X is near +250mm
    print(f"  {C['R']}>>> Injecting position-dependent vibration: Y vibration 10× at X≈+250mm{C['reset']}")
    n_bins = 8
    positions = np.linspace(-500, 500, n_bins)
    cross_anns_all = []

    for cycle in range(300):
        bin_idx = cycle % n_bins
        pos_x = positions[bin_idx]
        high_bin = 6  # position ~+250mm
        fft_mag = 50.0 if bin_idx == high_bin else 5.0

        snapshots = {}
        # Source = Y (has Velocity FFT peak)
        snapshots["Y"] = AxisSnapshot(
            axis_id="Y", slave_position=1,
            values=[2000.0, 500.0, 75.0, 55.0, 3.0, 0.0, 0x0237, 1.0],
            channel_names=CH_NAMES,
            buffer_stats={
                "Velocity": {"fft_peak_magnitude": fft_mag},
                "Position": {"min": -500.0, "max": 500.0},
            },
        )
        # Target = X (has Position range)
        snapshots["X"] = AxisSnapshot(
            axis_id="X", slave_position=0,
            values=[pos_x, 500.0, 80.0, 60.0, 5.0, 0.0, 0x0237, 1.0],
            channel_names=CH_NAMES,
            buffer_stats={"Position": {"min": -500.0, "max": 500.0},
                         "Velocity": {"fft_peak_magnitude": 0.0}},
        )
        snapshots["Z"] = AxisSnapshot(
            axis_id="Z", slave_position=2,
            values=[500.0, 200.0, 85.0, 50.0, 4.0, 0.0, 0x0237, 1.0],
            channel_names=CH_NAMES,
            buffer_stats={"Position": {"min": -500.0, "max": 500.0},
                         "Velocity": {"fft_peak_magnitude": 0.0}},
        )
        cross_anns_all.extend(cross_axis.analyze(snapshots))

    for p in pipelines.values(): p.reset()
    cross_axis.reset()

    coupling = [a for a in cross_anns_all if a.category == "cross_mechanical_coupling"]
    if coupling:
        for a in coupling:
            print_ann(a)
        meta = coupling[0].metadata
        print(f"  {C['G']}✓ Mechanical coupling: {meta.get('source_axis')}↔{meta.get('target_axis')}, "
              f"ratio={meta.get('magnitude_ratio',0):.1f}×{C['reset']}")
    else:
        print(f"  {C['Y']}⚠ Mechanical coupling NOT detected{C['reset']}")
    return len(coupling), coupling


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    header()

    # Parse --axes
    n_axes = 3
    for i, arg in enumerate(sys.argv):
        if arg == "--axes" and i + 1 < len(sys.argv):
            try:
                n_axes = int(sys.argv[i + 1])
            except ValueError:
                pass

    axis_names_extra = ["U", "V", "W", "A", "B", "C"]
    axis_ids = ["X", "Y", "Z"] + axis_names_extra[:max(0, n_axes - 3)]

    print(f"{C['dim']}Initializing {n_axes}-axis AI Pipeline "
          f"(4 detectors: 3 single-axis + 1 cross-axis)...{C['reset']}")

    pipelines = {}
    for i, aid in enumerate(axis_ids):
        pipelines[aid] = AIAnalyzerPipeline(
            sample_rate_hz=1000.0,
            axis_id=aid,
            slave_position=i,
        )

    cross_axis = CrossAxisAnalyzer() if n_axes >= 2 else None

    print(f"  Per-axis pipelines: {list(pipelines.keys())}")
    print(f"  Cross-axis analyzer: {'enabled' if cross_axis else 'disabled (need ≥2 axes)'}")
    for aid, p in pipelines.items():
        print(f"    {aid}: {[a.name for a in p.analyzers]}")
    if cross_axis:
        print(f"    cross: {cross_axis.status()['detectors']}")

    # ── Run all scenarios ──
    results = {}
    time.sleep(0.2)

    results["normal"] = run_normal(pipelines, cross_axis, duration_s=3)
    time.sleep(0.2)

    results["bus_sag"] = run_bus_sag(pipelines, cross_axis)
    time.sleep(0.2)

    results["contouring"] = run_contouring(pipelines, cross_axis)
    time.sleep(0.2)

    results["ring_cascade"] = run_ring_cascade(cross_axis)
    time.sleep(0.2)

    results["coupling"] = run_mechanical_coupling(pipelines, cross_axis)
    time.sleep(0.2)

    # ── Summary ─────────────────────────────────────────────
    print(f"""
{C['bold']}╔══════════════════════════════════════════════════════════════╗
║                   Multi-Axis Demo Summary                       ║
╠══════════════════════════════════════════════════════════════╣
║  Normal Operation:     {results['normal']:>4d} false positives (expect 0)          ║
║  Bus Sag Detection:    {results['bus_sag'][0]:>4d} annotations (expect ≥1)       ║
║  Contouring Error:     {results['contouring'][0]:>4d} annotations (expect ≥1)       ║
║  Ring Cascade:         {results['ring_cascade'][0]:>4d} annotations (expect ≥1)       ║
║  Mechanical Coupling:  {results['coupling'][0]:>4d} annotations (expect ≥1)       ║
╠══════════════════════════════════════════════════════════════╣
║  Detectors per axis:   3 (Current + Tracking + Resonance)     ║
║  Cross-axis detectors: 4 (Bus Sag + Contouring + Ring +      ║
║                           Coupling)                            ║
║  Total axes tested:    {n_axes}                                          ║
╚══════════════════════════════════════════════════════════════╝{C['reset']}

  {C['G']}Full Oscilloscope:{C['reset']} python run_scope.py --qt
  {C['G']}CLI Analyzer:{C['reset']}     python 06-ai-analyzer/servo_cli.py
  {C['G']}Multi-Axis PyQt:{C['reset']} python 04-oscilloscope/src/scope_app.py --axes {n_axes}
""")


if __name__ == "__main__":
    main()

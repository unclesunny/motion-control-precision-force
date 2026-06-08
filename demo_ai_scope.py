"""
AI Oscilloscope Simulation Demo — Terminal-based.

Runs the full AI analyzer pipeline against synthetic servo data
with injected anomalies. No GUI required.
"""

import sys
import time
from pathlib import Path

# Force UTF-8 + ANSI escape code support on Windows terminals
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Enable ANSI virtual terminal processing (Windows 10+)
    import ctypes
    kernel32 = ctypes.windll.kernel32
    for handle in [ctypes.c_void_p(-11), ctypes.c_void_p(-12)]:  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING

import numpy as np

# Ensure AI analyzer is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "06-ai-analyzer"))

from ai_analyzer import AIAnalyzerPipeline

# ── Color helpers ────────────────────────────────────────────
C = {
    "R": "\033[91m", "G": "\033[92m", "Y": "\033[93m",
    "B": "\033[94m", "M": "\033[95m", "C": "\033[96m",
    "W": "\033[97m", "dim": "\033[2m", "reset": "\033[0m",
    "bold": "\033[1m",
}
SEV_ICON = {"info": "ℹ", "warning": "⚠", "critical": "🔴"}
SEV_COLOR = {"info": C["B"], "warning": C["Y"], "critical": C["R"]}


def demo_header():
    print(f"""
{C['bold']}{C['C']}╔══════════════════════════════════════════════════════════════╗
║     Delta A3 Oscilloscope — AI Analyzer Simulation Demo      ║
║     3 Detectors: Current │ Tracking Error │ Resonance        ║
╚══════════════════════════════════════════════════════════════╝{C['reset']}
""")


def print_annotation(ann):
    icon = SEV_ICON.get(ann.severity, "?")
    color = SEV_COLOR.get(ann.severity, C["W"])
    print(f"  {color}{icon} [{ann.category}]{C['reset']} {C['bold']}{ann.channel}{C['reset']}: {ann.message}")
    if ann.suggestion:
        print(f"    {C['dim']}→ {ann.suggestion}{C['reset']}")
    print(f"    confidence={ann.confidence:.0%}  severity={ann.severity}  value={ann.value:.1f}")


# ── Scenario 1: Normal Operation ─────────────────────────────

def run_normal_operation(pipeline, duration_s=5):
    """Normal servo operation — no anomalies expected."""
    print(f"\n{C['G']}┌─── Scenario 1: Normal Operation ({duration_s}s) ───┐{C['reset']}")
    ch_names = ["Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode"]

    all_annotations = []
    for i in range(duration_s * 1000):  # 1000 Hz analysis rate
        t = i / 1000.0
        values = [
            1000.0 * np.sin(2 * np.pi * 2.0 * t),             # Position
            500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5),        # Velocity
            80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t),        # Current (normal ~80%)
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),         # Torque
            10.0 + 5.0 * np.sin(2 * np.pi * 7.0 * t),         # Foll.Err (normal ~10)
            float(i % 100 > 50),                               # DIO
            0x0237 if i % 200 < 100 else 0x0007,              # Status
            (i // 50) % 8,                                     # OpMode
        ]
        buffer_stats = {
            "Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 140.0,
                        "rms": 85.0, "peak_to_peak": 120.0},
            "Foll.Err": {"mean": 10.0, "std": 5.0, "min": 0.0, "max": 30.0,
                         "rms": 14.0, "peak_to_peak": 30.0},
            "Velocity": {"mean": 0.0, "std": 350.0, "min": -500.0, "max": 500.0,
                         "rms": 350.0, "peak_to_peak": 1000.0},
        }
        annotations = pipeline.analyze(values, ch_names, buffer_stats)
        all_annotations.extend(annotations)

    # Show summary
    if all_annotations:
        print(f"  {C['Y']}Unexpected: {len(all_annotations)} annotations on normal data{C['reset']}")
        for ann in all_annotations[:3]:
            print_annotation(ann)
    else:
        print(f"  {C['G']}✓ No false positives — all channels normal{C['reset']}")

    annotations = list(all_annotations)
    pipeline.reset()
    return len(all_annotations), annotations


# ── Scenario 2: Current Saturation ───────────────────────────

def run_current_saturation(pipeline):
    """Inject a current saturation event."""
    print(f"\n{C['R']}┌─── Scenario 2: Current Saturation ───┐{C['reset']}")
    ch_names = ["Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode"]

    # Normal operation first
    for i in range(1000):
        t = i / 1000.0
        values = [
            1000.0 * np.sin(2 * np.pi * 2.0 * t),
            500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5),
            80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t),
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),
            10.0 + 5.0 * np.sin(2 * np.pi * 7.0 * t),
            float(i % 100 > 50), 0x0237, 1.0,
        ]
        buffer_stats = {
            "Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 140.0,
                        "rms": 85.0, "peak_to_peak": 120.0},
        }
        pipeline.analyze(values, ch_names, buffer_stats)

    # ── BAM! Current spike to 250% (saturation) ──
    print(f"  {C['R']}>>> Injecting current spike: 250% (saturation limit is 200%){C['reset']}")
    t = 1.0
    values = [1000.0, 500.0, 250.0, 60.0, 15.0, 0.0, 0x0237, 1.0]
    buffer_stats = {
        "Current": {"mean": 80.0, "std": 30.0, "min": 20.0, "max": 250.0,
                    "rms": 85.0, "peak_to_peak": 230.0},
    }
    annotations = pipeline.analyze(values, ch_names, buffer_stats)

    for ann in annotations:
        print_annotation(ann)

    result_anns = list(annotations)
    pipeline.reset()
    return len(annotations), result_anns


# ── Scenario 3: Tracking Error ───────────────────────────────

def run_tracking_error(pipeline):
    """Inject a following error spike."""
    print(f"\n{C['R']}┌─── Scenario 3: Tracking Error (Absolute Limit) ───┐{C['reset']}")
    ch_names = ["Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode"]

    for i in range(500):
        t = i / 1000.0
        values = [
            1000.0 * np.sin(2 * np.pi * 2.0 * t),
            500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5),
            80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t),
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),
            10.0 + np.random.normal(0, 3.0),  # normal error
            float(i % 100 > 50), 0x0237, 1.0,
        ]
        buffer_stats = {
            "Foll.Err": {"mean": 10.0, "std": 5.0, "min": 0.0, "max": 30.0,
                         "rms": 14.0, "peak_to_peak": 30.0},
        }
        pipeline.analyze(values, ch_names, buffer_stats)

    # ── Following error exceeding absolute hardware limit ──
    print(f"  {C['R']}>>> Following error: 2,000,000 pulses (limit: 1,000,000){C['reset']}")
    values = [1000.0, 500.0, 80.0, 60.0, 2000000.0, 0.0, 0x0237, 1.0]
    annotations = pipeline.analyze(values, ch_names, {})

    for ann in annotations:
        print_annotation(ann)

    result_anns = list(annotations)
    pipeline.reset()
    return len(annotations), result_anns


# ── Scenario 4: Mechanical Resonance ─────────────────────────

def run_resonance(pipeline):
    """Generate a signal with mechanical resonance harmonics."""
    print(f"\n{C['Y']}┌─── Scenario 4: Mechanical Resonance Detection ───┐{C['reset']}")
    ch_names = ["Position", "Velocity", "Current", "Torque"]

    print(f"  {C['dim']}Feeding 1024 samples of velocity with 75Hz fundamental + 3 harmonics...{C['reset']}")
    fundamental = 75.0
    all_annotations = []
    n_samples = 1024

    for i in range(n_samples):
        t = i / 1000.0
        # Velocity: rich harmonic content with low noise floor
        vel = (
            300.0 * np.sin(2 * np.pi * fundamental * t)          # fundamental 75Hz
            + 180.0 * np.sin(2 * np.pi * fundamental * 2 * t)    # 2nd harmonic 150Hz
            + 120.0 * np.sin(2 * np.pi * fundamental * 3 * t)    # 3rd harmonic 225Hz
            + np.random.normal(0, 2.0)                            # very low noise
        )
        cur = 80.0 + 10.0 * np.sin(2 * np.pi * 50.0 * t)
        values = [
            1000.0 * np.sin(2 * np.pi * 5.0 * t),
            vel,
            cur,
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),
        ]
        buffer_stats = {
            "Velocity": {"mean": 0.0, "std": 200.0, "min": -500.0, "max": 500.0,
                         "rms": 200.0, "peak_to_peak": 1000.0},
        }
        annotations = pipeline.analyze(values, ch_names, buffer_stats)
        all_annotations.extend(annotations)

    if all_annotations:
        for ann in all_annotations:
            print_annotation(ann)
    else:
        print(f"  {C['dim']}(No resonance annotation — check detector config){C['reset']}")

    result_anns = list(all_annotations)
    pipeline.reset()
    return len(all_annotations), result_anns


# ── Scenario 5: Mechanical Wear (CUSUM drift) ────────────────

def run_mechanical_wear(pipeline):
    """Simulate gradual mechanical wear via CUSUM drift detection."""
    print(f"\n{C['Y']}┌─── Scenario 5: Mechanical Wear (CUSUM Drift) ───┐{C['reset']}")
    ch_names = ["Position", "Velocity", "Current", "Torque"]

    print(f"  {C['dim']}Current drifting from 80% → 160% over 300 samples (wear pattern)...{C['reset']}")
    all_annotations = []

    for i in range(300):
        t = i / 1000.0  # 1kHz sample rate
        # Steeper drift with less noise — clearer CUSUM signal
        drift_current = 80.0 + (i / 300.0) * 80.0 + np.random.normal(0, 1.0)
        values = [
            1000.0 * np.sin(2 * np.pi * 2.0 * t),
            500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5),
            drift_current,
            60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2),
        ]
        buffer_stats = {
            "Current": {"mean": 80.0 + (i / 300.0) * 60.0, "std": 15.0,
                        "min": 50.0, "max": 180.0, "rms": 100.0, "peak_to_peak": 130.0},
        }
        annotations = pipeline.analyze(values, ch_names, buffer_stats)
        all_annotations.extend(annotations)

    if all_annotations:
        print(f"  {C['Y']}{len(all_annotations)} wear-related annotations detected{C['reset']}")
        for ann in all_annotations[:5]:
            print_annotation(ann)
    else:
        print(f"  {C['dim']}No wear annotations — drift may be below CUSUM threshold{C['reset']}")

    result_anns = list(all_annotations)
    pipeline.reset()
    return len(all_annotations), result_anns


# ── Main Demo ────────────────────────────────────────────────

def main():
    demo_header()

    print(f"{C['dim']}Initializing AI Analyzer Pipeline (3 detectors)...{C['reset']}")
    pipeline = AIAnalyzerPipeline(sample_rate_hz=1000.0)  # 1kHz for FFT Nyquist coverage
    print(f"  Detectors: {[a.name for a in pipeline.analyzers]}")
    print(f"  Bridge available: {pipeline.bridge.bridge_available}")
    time.sleep(0.5)

    # Run all scenarios — collect annotations for recommendations
    results = {}
    all_annotations = []

    results["normal"] = run_normal_operation(pipeline, duration_s=3)
    time.sleep(0.3)
    results["saturation"], anns = run_current_saturation(pipeline)
    all_annotations.extend(anns)
    time.sleep(0.3)
    results["tracking"], anns = run_tracking_error(pipeline)
    all_annotations.extend(anns)
    time.sleep(0.3)
    results["resonance"], anns = run_resonance(pipeline)
    all_annotations.extend(anns)
    time.sleep(0.3)
    results["wear"], anns = run_mechanical_wear(pipeline)
    all_annotations.extend(anns)
    print(f"\n{C['bold']}{C['C']}┌─── AI Tuning Recommendations ───┐{C['reset']}")
    params = pipeline._recommender.recommend(all_annotations)
    if params:
        for p in params[:6]:
            action_icon = {"increase": "+", "decrease": "-", "set": "→", "check": "?"}.get(p.action, "?")
            print(f"  {C['Y']}{action_icon}{C['reset']} {p.index_hex} {p.name[:45]}")
            print(f"    {C['dim']}{p.reason}{C['reset']}")
            if p.target_value:
                print(f"    Target: {p.target_value:.0f}")
            if p.safety:
                print(f"    {C['dim']}Safety: {p.safety}{C['reset']}")
    else:
        print(f"  {C['dim']}No parameter adjustments needed.{C['reset']}")

    # ── Summary ─────────────────────────────────────────────
    counts = {k: results[k][0] if isinstance(results[k], tuple) else results[k] for k in results}
    print(f"""
{C['bold']}╔══════════════════════════════════════════════════════════════╗
║                      Demo Summary                             ║
╠══════════════════════════════════════════════════════════════╣
║  Normal Operation:   {counts['normal']:>4d} annotations (expect 0)                     ║
║  Current Saturation: {counts['saturation']:>4d} annotations (expect ≥1)                ║
║  Tracking Error:     {counts['tracking']:>4d} annotations (expect ≥1)                ║
║  Resonance:          {counts['resonance']:>4d} annotations (expect ≥1)                ║
║  Mechanical Wear:    {counts['wear']:>4d} annotations (expect ≥1)                ║
╠══════════════════════════════════════════════════════════════╣
║  Total annotations:  {sum(counts.values()):>4d}                                    ║
║  Tuning params rec:  {len(params):>4d}                                    ║
╚══════════════════════════════════════════════════════════════╝{C['reset']}

  {C['G']}Web Oscilloscope:{C['reset']} http://localhost:8888 (4-channel Canvas)
  {C['G']}AI Module Docs:{C['reset']} 06-ai-analyzer/README.md
  {C['G']}Full Roadmap:{C['reset']}  ROADMAP.md
""")


if __name__ == "__main__":
    main()

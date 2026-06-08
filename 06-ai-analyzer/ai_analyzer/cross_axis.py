"""
Cross-Axis Analyzer — 4th detector for multi-axis servo systems.

Detects problems invisible to single-axis analysis:
  1. Power bus sag          — all axes' current dips simultaneously
  2. Contouring error        — XY/Z trajectory orthogonal deviation
  3. EtherCAT ring cascade   — error propagation across slave positions
  4. Mechanical coupling     — vibration amplitude vs partner axis position

Architecture:
  This analyzer is fundamentally different from single-axis detectors.
  Instead of (values, channel_names, buffer_stats) per axis, it receives
  a Dict[str, AxisSnapshot] — the aggregated state of ALL axes at one
  timestamp. It runs AFTER all single-axis detectors.

  All sub-detectors work with sliding window buffers (not ring buffers)
  because they only see aggregated data every N samples. Window size is
  configurable and independent of the scope ring buffer.

References:
  - ISO 10791-6:2014 — contouring accuracy for machining centers
  - Delta ASDA-A3 manual §8.2 — multi-axis coordinated motion
  - IgH EtherCAT Master 1.5.2 ecrt.h — WKC/domain state monitoring
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .config import (
        CROSS_AXIS_CONFIG,
        CHANNEL_NAME_INDEX,
    )
except ImportError:
    from analyzer_base import AIAnnotation, AnalyzerBase
    from config import (
        CROSS_AXIS_CONFIG,
        CHANNEL_NAME_INDEX,
    )


# ============================================================================
# AxisSnapshot — aggregated single-axis state for cross-axis analysis
# ============================================================================


@dataclass
class AxisSnapshot:
    """Single-axis data at one timestamp for cross-axis analysis.

    This is the input type for CrossAxisAnalyzer.analyze(). Each axis
    contributes one snapshot per analysis frame. The analyzer sees all
    axes' snapshots simultaneously and finds cross-axis patterns.

    Fields:
        axis_id: Human-readable axis name ("X", "Y", "Z", "Spindle", ...).
        slave_position: EtherCAT slave position (0-based).
        values: Current channel values [pos, vel, cur, torque, ferr, dio, status, opmode].
        channel_names: Channel name list ["Position", "Velocity", ...].
        buffer_stats: Per-channel statistics from the axis ring buffer.
        annotations: Single-axis detector annotations for this frame
                    (already classified by HITL gate).
        timestamp: Time in seconds (monotonic).
    """
    axis_id: str
    slave_position: int
    values: List[float]
    channel_names: List[str]
    buffer_stats: Dict[str, dict] = field(default_factory=dict)
    annotations: List = field(default_factory=list)
    timestamp: float = 0.0

    def get(self, channel_name: str) -> float:
        """Get a channel value by name."""
        try:
            idx = self.channel_names.index(channel_name)
            return self.values[idx] if idx < len(self.values) else 0.0
        except ValueError:
            return 0.0

    def get_stat(self, channel_name: str, stat: str = "mean") -> float:
        """Get a buffer statistic for a channel."""
        ch_stats = self.buffer_stats.get(channel_name, {})
        return ch_stats.get(stat, 0.0)


# ============================================================================
# Cross-Axis Annotation — extends AIAnnotation for cross-axis metadata
# ============================================================================


def cross_annotation(
    category: str,
    severity: str,
    confidence: float,
    message: str,
    involved_axes: List[str],
    suggestion: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> AIAnnotation:
    """Create an AIAnnotation for a cross-axis event.

    The 'channel' field is set to the involved axes joined by '+',
    e.g. "X+Y+Z". Metadata always includes involved_axes for
    downstream axis-scoped HITL routing.
    """
    meta = metadata or {}
    meta["involved_axes"] = involved_axes
    meta["cross_axis"] = True

    return AIAnnotation(
        timestamp=time.time(),
        channel="+".join(involved_axes),
        category=category,
        severity=severity,
        confidence=confidence,
        message=message,
        suggestion=suggestion,
        value=0.0,
        metadata=meta,
    )


# ============================================================================
# Sub-Detector 1: Power Bus Sag
# ============================================================================


class BusSagDetector:
    """Detects simultaneous current drop across all axes — PSU overload.

    When the power supply cannot deliver enough current (e.g. spindle
    accelerating while all axes are moving), all servo drives experience
    a simultaneous current sag. Single-axis detectors see "current below
    expected" but can't distinguish bus sag from load reduction.

    Algorithm:
      - Maintain sliding window of Current values per axis
      - Each analysis cycle: compute pairwise Pearson-r between all axes'
        current windows
      - If ≥ min_axes show r > correlation_threshold AND mean drop > drop_pct
        → bus sag event

    Parameters (from CROSS_AXIS_CONFIG):
      window:           sliding window size (samples)
      min_axes:         minimum axes for sag detection (≥2)
      correlation_threshold: Pearson-r above which axes are "moving together"
      drop_pct:         mean current must drop this far below baseline
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or CROSS_AXIS_CONFIG.get("bus_sag", {})
        self._window_size = cfg.get("window", 200)
        self._min_axes = cfg.get("min_axes", 2)
        self._corr_threshold = cfg.get("correlation_threshold", 0.7)
        self._drop_pct = cfg.get("drop_pct", 0.30)

        # Per-axis current windows: {axis_id: deque}
        self._current_windows: Dict[str, Deque[float]] = {}

    def feed(self, axes: Dict[str, AxisSnapshot]):
        """Feed one frame of current data."""
        for axis_id, snap in axes.items():
            if axis_id not in self._current_windows:
                self._current_windows[axis_id] = deque(maxlen=self._window_size)
            self._current_windows[axis_id].append(snap.get("Current"))

    def analyze(self, axes: Dict[str, AxisSnapshot]) -> List[AIAnnotation]:
        """Check for bus sag in the current window state."""
        self.feed(axes)

        annotations: List[AIAnnotation] = []
        active_axes = [aid for aid, w in self._current_windows.items()
                       if len(w) >= 30]

        if len(active_axes) < self._min_axes:
            return annotations

        # Two-window comparison: recent half vs early half of sliding window.
        # If the recent mean is significantly below the early baseline (which
        # represents the "normal" current level), we have a sag.
        correlations: Dict[str, float] = {}
        dropping_axes: List[str] = []
        drop_pcts: Dict[str, float] = {}

        axis_ids = sorted(active_axes)
        for i in range(len(axis_ids)):
            a1 = axis_ids[i]
            arr1 = np.array(self._current_windows[a1])
            n = len(arr1)
            split = max(n // 3, 5)
            early_baseline = np.mean(arr1[:split])      # oldest → "normal"
            recent_mean = np.mean(arr1[-split:])         # newest → "now"
            if early_baseline > 0:
                drop1 = (early_baseline - recent_mean) / early_baseline
                drop_pcts[a1] = drop1
                if drop1 > self._drop_pct:
                    dropping_axes.append(a1)

            for j in range(i + 1, len(axis_ids)):
                a2 = axis_ids[j]
                arr2 = np.array(self._current_windows[a2])
                r = self._pearson_r(arr1, arr2)
                correlations[f"{a1}-{a2}"] = r

        # Count correlated pairs (above threshold)
        correlated_pairs = sum(1 for r in correlations.values() if r > self._corr_threshold)
        total_pairs = max(len(correlations), 1)

        n_axes = len(active_axes)
        drop_count = len(dropping_axes)

        if drop_count >= self._min_axes and correlated_pairs >= max(1, total_pairs // 2):
            avg_drop_pct = sum(drop_pcts[a] for a in dropping_axes) / drop_count
            confidence = min(1.0, drop_count / n_axes + correlated_pairs / total_pairs)
            msg = (
                f"Power bus sag: {drop_count}/{n_axes} axes current dropping "
                f"(~{avg_drop_pct:.0%} avg drop). "
                f"Correlated pairs: {correlated_pairs}/{total_pairs}. "
                f"Check PSU capacity or shared DC bus."
            )
            annotations.append(cross_annotation(
                category="cross_bus_sag",
                severity="warning",
                confidence=confidence,
                message=msg,
                involved_axes=dropping_axes,
                suggestion="Verify power supply capacity. Consider staggered acceleration or PSU upgrade.",
                metadata={
                    "drop_count": drop_count,
                    "correlated_pairs": correlated_pairs,
                    "dropping_axes": dropping_axes,
                    "correlations": correlations,
                    "avg_drop_pct": avg_drop_pct,
                },
            ))

        return annotations

    @staticmethod
    def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
        n = min(len(x), len(y))
        if n < 3:
            return 0.0
        x, y = x[-n:], y[-n:]
        xm, ym = np.mean(x), np.mean(y)
        xs, ys = x - xm, y - ym
        num = np.sum(xs * ys)
        den = np.sqrt(np.sum(xs ** 2) * np.sum(ys ** 2))
        if den < 1e-10:
            return 0.0
        return float(num / den)

    def reset(self):
        self._current_windows.clear()


# ============================================================================
# Sub-Detector 2: Contouring Error
# ============================================================================


class ContouringDetector:
    """Detects trajectory contouring errors across two or more axes.

    Individual following errors can be within tolerance while the combined
    2D/3D error deviates from the commanded path. Common in CNC machining
    where circular interpolation creates orthogonal error components.

    Algorithm:
      - Collect Foll.Err from paired axes (default: X/Y for planar contouring)
      - Compute orthogonal deviation: sqrt(dx² + dy²) for linear trajectory
      - Compare against combined threshold: 1.5× max individual threshold
      - Extensible to axis pairs config: [("X","Y"), ("X","Z"), ("Y","Z")]

    Parameters (from CROSS_AXIS_CONFIG):
      axis_pairs:      list of (axis1, axis2) tuples to monitor
      threshold_mult:  combined threshold = mult × max(individual_3σ)
      min_error_pulses: minimum error before reporting (noise gate)
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or CROSS_AXIS_CONFIG.get("contouring", {})
        self._axis_pairs: List[Tuple[str, str]] = [
            tuple(p) for p in cfg.get("axis_pairs", [("X", "Y")])
        ]
        self._threshold_mult = cfg.get("threshold_multiplier", 1.5)
        self._min_error = cfg.get("min_error_pulses", 10.0)

        # Per-pair error windows
        self._pair_buffers: Dict[Tuple[str, str], Tuple[Deque[float], Deque[float]]] = {}

    def analyze(self, axes: Dict[str, AxisSnapshot]) -> List[AIAnnotation]:
        annotations: List[AIAnnotation] = []

        for pair in self._axis_pairs:
            a1, a2 = pair
            if a1 not in axes or a2 not in axes:
                continue

            err1 = axes[a1].get("Foll.Err")
            err2 = axes[a2].get("Foll.Err")

            # Feed buffers
            if pair not in self._pair_buffers:
                self._pair_buffers[pair] = (
                    deque(maxlen=200),
                    deque(maxlen=200),
                )
            buf1, buf2 = self._pair_buffers[pair]
            buf1.append(err1)
            buf2.append(err2)

            if len(buf1) < 30:
                continue

            # Combined orthogonal error
            combined = math.sqrt(err1 ** 2 + err2 ** 2)

            # Dynamic threshold based on individual statistics
            arr1 = np.array(buf1)
            arr2 = np.array(buf2)
            thresh1 = np.mean(arr1) + 3 * np.std(arr1)
            thresh2 = np.mean(arr2) + 3 * np.std(arr2)
            combined_threshold = self._threshold_mult * max(thresh1, thresh2, self._min_error)

            if combined > combined_threshold:
                confidence = min(1.0, (combined - combined_threshold) / max(combined_threshold, 1.0) + 0.3)
                msg = (
                    f"Contouring error on {a1}+{a2}: combined deviation {combined:.0f} pulses "
                    f"(threshold {combined_threshold:.0f}). "
                    f"Individual: {a1}={err1:.0f}, {a2}={err2:.0f}."
                )
                annotations.append(cross_annotation(
                    category="cross_contouring_error",
                    severity="warning",
                    confidence=confidence,
                    message=msg,
                    involved_axes=[a1, a2],
                    suggestion="Check trajectory generation (0x6086). Reduce interpolation feedrate. Verify mechanical coupling.",
                    metadata={
                        "axis_pair": list(pair),
                        "combined_error": combined,
                        "threshold": combined_threshold,
                        "err1": err1,
                        "err2": err2,
                    },
                ))

        return annotations

    def reset(self):
        self._pair_buffers.clear()


# ============================================================================
# Sub-Detector 3: EtherCAT Ring Health
# ============================================================================


class RingHealthDetector:
    """Detects EtherCAT frame error cascade across slave positions.

    In a daisy-chain topology, if slave N corrupts a frame, all downstream
    slaves (N+1, N+2, ...) also show errors. Single-axis analysis would
    incorrectly blame slave N+1. This detector traces the error cascade
    to find the true root cause.

    Algorithm:
      - Collect working counter (WKC) or error flag per slave position
      - If slave N has the FIRST error and all later slaves also error →
        root cause is slave N (bad cable, loose connector, dying PHY)
      - If errors are sporadic across random slaves → EMI/RFI, not cascade

    Parameters (from CROSS_AXIS_CONFIG):
      window:              history window (samples)
      cascade_threshold:   consecutive error count to flag cascade
      sporadic_threshold:  isolated errors > this pct → EMI warning
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or CROSS_AXIS_CONFIG.get("ring_health", {})
        self._window_size = cfg.get("window", 1000)
        self._cascade_threshold = cfg.get("cascade_threshold", 10)
        self._sporadic_threshold = cfg.get("sporadic_threshold", 0.1)

        # Per-slave error history {slave_position: deque of bool}
        self._error_history: Dict[int, Deque[bool]] = {}
        self._master_errors: Deque[bool] = deque(maxlen=self._window_size)

    def feed(self, slave_positions: Dict[int, bool],
             master_error: bool = False):
        """Feed one cycle of WKC/error state.

        Args:
            slave_positions: {slave_position: has_error} for each slave.
            master_error: True if master detected a bus-level error.
        """
        for pos, has_error in slave_positions.items():
            if pos not in self._error_history:
                self._error_history[pos] = deque(maxlen=self._window_size)
            self._error_history[pos].append(has_error)

        self._master_errors.append(master_error)

    def analyze(self, slave_positions: Dict[int, bool],
                master_error: bool = False) -> List[AIAnnotation]:
        """Check for error cascading."""
        self.feed(slave_positions, master_error)

        annotations: List[AIAnnotation] = []
        positions = sorted(self._error_history.keys())

        if len(positions) < 2:
            return annotations

        # Find first-error slave: the one whose error rate spikes
        # while upstream slaves are healthy
        first_error_slave = None
        cascade_depth = 0

        for i, pos in enumerate(positions):
            hist = self._error_history.get(pos, deque())
            if len(hist) < self._cascade_threshold:
                continue

            recent = list(hist)[-self._cascade_threshold:]
            err_rate = sum(recent) / len(recent)

            if err_rate > 0.5:
                if first_error_slave is None:
                    # Check upstream: are slaves before this one healthy?
                    upstream_healthy = True
                    for j in range(i):
                        upstream_hist = self._error_history.get(positions[j], deque())
                        if len(upstream_hist) >= self._cascade_threshold:
                            up_recent = list(upstream_hist)[-self._cascade_threshold:]
                            if sum(up_recent) / len(up_recent) > 0.3:
                                upstream_healthy = False
                                break
                    if upstream_healthy:
                        first_error_slave = pos
                        cascade_depth = 1
                else:
                    cascade_depth += 1

        if first_error_slave is not None and cascade_depth >= 2:
            cascaded_slaves = [p for p in positions if p >= first_error_slave]
            confidence = min(1.0, cascade_depth / len(positions) + 0.3)
            msg = (
                f"EtherCAT ring cascade: {cascade_depth} slaves affected. "
                f"Root cause at slave {first_error_slave} "
                f"(upstream slaves healthy). Cascaded to: {cascaded_slaves}. "
                f"Check cable {first_error_slave-1}→{first_error_slave} "
                f"and slave {first_error_slave} PHY."
            )
            annotations.append(cross_annotation(
                category="cross_ring_cascade",
                severity="critical",
                confidence=confidence,
                message=msg,
                involved_axes=[str(p) for p in cascaded_slaves],
                suggestion=f"Inspect EtherCAT cable between slave {first_error_slave-1} and slave {first_error_slave}. Check RJ45 connector, grounding, and cable shield.",
                metadata={
                    "first_error_slave": first_error_slave,
                    "cascade_depth": cascade_depth,
                    "cascaded_slaves": cascaded_slaves,
                },
            ))

        # Check for sporadic errors (EMI/RFI pattern)
        sporadic_count = 0
        total_checks = 0
        for pos in positions:
            hist = self._error_history.get(pos, deque())
            if len(hist) < self._cascade_threshold:
                continue
            recent = list(hist)[-self._cascade_threshold:]
            err_count = sum(recent)
            if 0 < err_count <= 3:  # occasional, not persistent
                sporadic_count += 1
            total_checks += 1

        if total_checks > 0 and (sporadic_count / total_checks) > self._sporadic_threshold:
            msg = (
                f"EtherCAT sporadic errors: {sporadic_count}/{total_checks} slaves "
                f"show intermittent frame errors. Possible EMI/RFI interference."
            )
            annotations.append(cross_annotation(
                category="cross_ring_emi",
                severity="warning" if sporadic_count / total_checks < 0.3 else "critical",
                confidence=0.6,
                message=msg,
                involved_axes=[str(p) for p in positions],
                suggestion="Check EtherCAT cable shielding. Verify grounding. Avoid routing near VFD/motor cables.",
                metadata={
                    "sporadic_count": sporadic_count,
                    "total_slaves": total_checks,
                    "sporadic_rate": sporadic_count / max(total_checks, 1),
                },
            ))

        return annotations

    def reset(self):
        self._error_history.clear()
        self._master_errors.clear()


# ============================================================================
# Sub-Detector 4: Mechanical Coupling
# ============================================================================


class MechanicalCouplingDetector:
    """Detects cross-axis mechanical coupling via vibration correlation.

    In gantry/portal machines, one axis's vibration can excite resonance
    in another axis when they're mechanically linked. This detector
    correlates velocity FFT peak magnitudes with partner axis position.

    Algorithm:
      - For each coupling pair (e.g. X→Y): partition Y position into bins
      - Within each bin, compute mean FFT peak magnitude of X's velocity
      - If any position bin has 3× the magnitude of the lowest bin →
        position-dependent coupling detected

    Parameters (from CROSS_AXIS_CONFIG):
      coupling_pairs: list of (source_axis, target_axis) tuples
      position_bins:  number of position range partitions
      peak_ratio:     magnitude ratio to flag coupling (3.0 = 3×)
      window:         FFT peak history window
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or CROSS_AXIS_CONFIG.get("mechanical_coupling", {})
        self._coupling_pairs: List[Tuple[str, str]] = [
            tuple(p) for p in cfg.get("coupling_pairs", [("Y", "X")])
        ]
        self._position_bins = cfg.get("position_bins", 8)
        self._peak_ratio = cfg.get("peak_ratio", 3.0)
        self._window = cfg.get("window", 500)

        # Per-pair data: {pair: {bin_idx: [peak_magnitudes]}}
        self._pair_data: Dict[Tuple[str, str], Dict[int, Deque[float]]] = {}

    def feed(self, axes: Dict[str, AxisSnapshot]):
        """Feed one frame: record FFT peak + partner position."""
        for source, target in self._coupling_pairs:
            if source not in axes or target not in axes:
                continue

            pair = (source, target)
            if pair not in self._pair_data:
                self._pair_data[pair] = {b: deque(maxlen=self._window)
                                         for b in range(self._position_bins)}

            # Get source's dominant FFT peak magnitude from Velocity channel stats
            # (MechanicalResonanceDetector writes fft_peak_magnitude into buffer_stats)
            source_snap = axes[source]
            fft_mag = source_snap.buffer_stats.get("Velocity", {}).get("fft_peak_magnitude", 0.0)

            # Get target axis position and bin it
            target_snap = axes[target]
            target_pos = target_snap.get("Position")
            pos_range = target_snap.buffer_stats.get("Position", {})
            pos_min = pos_range.get("min", -1000.0)
            pos_max = pos_range.get("max", 1000.0)
            pos_span = pos_max - pos_min

            if pos_span < 1.0:
                bin_idx = 0
            else:
                bin_idx = min(self._position_bins - 1,
                              int((target_pos - pos_min) / pos_span * self._position_bins))

            self._pair_data[pair][bin_idx].append(fft_mag)

    def analyze(self, axes: Dict[str, AxisSnapshot]) -> List[AIAnnotation]:
        """Check for position-dependent vibration coupling."""
        self.feed(axes)
        annotations: List[AIAnnotation] = []

        for pair in self._coupling_pairs:
            source, target = pair
            if pair not in self._pair_data:
                continue

            bin_means = {}
            for bin_idx, mags in self._pair_data[pair].items():
                if len(mags) >= 10:
                    bin_means[bin_idx] = np.mean(mags)

            if len(bin_means) < 3:
                continue

            # Find min and max bin magnitudes
            min_bin = min(bin_means, key=bin_means.get)
            max_bin = max(bin_means, key=bin_means.get)
            min_mag = bin_means[min_bin]
            max_mag = bin_means[max_bin]

            if min_mag < 1e-6:
                continue

            ratio = max_mag / min_mag

            if ratio > self._peak_ratio:
                target_snap = axes.get(target)
                pos_range = target_snap.buffer_stats.get("Position", {}) if target_snap else {}
                pos_min = pos_range.get("min", -1000.0)
                pos_max = pos_range.get("max", 1000.0)
                pos_span = pos_max - pos_min

                trouble_pos = pos_min + (max_bin + 0.5) / self._position_bins * pos_span
                confidence = min(1.0, (ratio - self._peak_ratio) / self._peak_ratio + 0.4)

                msg = (
                    f"Cross-axis mechanical coupling: {source} vibration {ratio:.1f}× higher "
                    f"when {target} near position {trouble_pos:.0f}. "
                    f"Check gantry/portal mechanical alignment and rigidity."
                )
                annotations.append(cross_annotation(
                    category="cross_mechanical_coupling",
                    severity="warning",
                    confidence=confidence,
                    message=msg,
                    involved_axes=[source, target],
                    suggestion=f"Inspect mechanical coupling between {source} and {target} axes. Check gantry bridge rigidity, bolt torque, and alignment.",
                    metadata={
                        "source_axis": source,
                        "target_axis": target,
                        "magnitude_ratio": ratio,
                        "peak_position": trouble_pos,
                        "bin_means": {str(k): v for k, v in bin_means.items()},
                    },
                ))

        return annotations

    def reset(self):
        self._pair_data.clear()


# ============================================================================
# CrossAxisAnalyzer — unified 4th detector
# ============================================================================


class CrossAxisAnalyzer(AnalyzerBase):
    """Analyzes patterns across ALL axes simultaneously.

    This is NOT a drop-in replacement for single-axis detectors. It runs
    AFTER all per-axis pipelines and receives the aggregated state of all
    axes. Its sub-detectors look for patterns that are invisible when
    analyzing each axis in isolation.

    Sub-detectors (enabled/disabled independently):
      - BusSagDetector:            power supply overload detection
      - ContouringDetector:        multi-axis trajectory deviation
      - RingHealthDetector:        EtherCAT error cascade tracing
      - MechanicalCouplingDetector: cross-axis vibration coupling

    Usage:
        analyzer = CrossAxisAnalyzer()
        analyzer.enable_detector("bus_sag")
        analyzer.disable_detector("ring_health")

        snapshots = {
            "X": AxisSnapshot("X", 0, [1000.0, 500.0, ...], ch_names, stats),
            "Y": AxisSnapshot("Y", 1, [2000.0, 300.0, ...], ch_names, stats),
            "Z": AxisSnapshot("Z", 2, [500.0, 200.0, ...], ch_names, stats),
        }
        annotations = analyzer.analyze(snapshots)
    """

    DETECTOR_NAMES = ["bus_sag", "contouring", "ring_health", "mechanical_coupling"]

    def __init__(self, name: str = "CrossAxisAnalyzer", enabled: bool = True,
                 config: Optional[Dict[str, Any]] = None):
        super().__init__(name=name, enabled=enabled)
        cfg = config or CROSS_AXIS_CONFIG

        self._bus_sag = BusSagDetector(cfg.get("bus_sag"))
        self._contouring = ContouringDetector(cfg.get("contouring"))
        self._ring_health = RingHealthDetector(cfg.get("ring_health"))
        self._mechanical_coupling = MechanicalCouplingDetector(cfg.get("mechanical_coupling"))

        self._enabled_detectors: Dict[str, bool] = {
            name: True for name in self.DETECTOR_NAMES
        }

        self._last_ring_state: Optional[Dict[int, bool]] = None

    # ── Detector Management ─────────────────────────────────────────

    def enable_detector(self, name: str):
        if name in self._enabled_detectors:
            self._enabled_detectors[name] = True

    def disable_detector(self, name: str):
        if name in self._enabled_detectors:
            self._enabled_detectors[name] = False

    def is_detector_enabled(self, name: str) -> bool:
        return self._enabled_detectors.get(name, False)

    # ── Main Analyze Entry ──────────────────────────────────────────

    def analyze(
        self,
        axes: Dict[str, AxisSnapshot],
        master_error: bool = False,
        slave_errors: Optional[Dict[int, bool]] = None,
    ) -> List[AIAnnotation]:
        """Run all enabled cross-axis detectors.

        Args:
            axes: Dict of axis_id → AxisSnapshot for all axes this frame.
            master_error: True if EtherCAT master reported a bus error.
            slave_errors: {slave_position: has_error} for ring health.

        Returns:
            List of AIAnnotation events (empty if no cross-axis issues).
        """
        annotations: List[AIAnnotation] = []

        # 1. Bus Sag
        if self._enabled_detectors["bus_sag"]:
            try:
                annotations.extend(self._bus_sag.analyze(axes))
            except Exception:
                pass

        # 2. Contouring Error
        if self._enabled_detectors["contouring"]:
            try:
                annotations.extend(self._contouring.analyze(axes))
            except Exception:
                pass

        # 3. Ring Health
        if self._enabled_detectors["ring_health"]:
            try:
                # Build slave error map from axes + explicit errors
                se = slave_errors or {}
                if not se:
                    for snap in axes.values():
                        status = snap.get("DIO")
                        se[snap.slave_position] = (status > 0 and status < 1000)
                annotations.extend(self._ring_health.analyze(se, master_error))
            except Exception:
                pass

        # 4. Mechanical Coupling
        if self._enabled_detectors["mechanical_coupling"]:
            try:
                annotations.extend(self._mechanical_coupling.analyze(axes))
            except Exception:
                pass

        return annotations

    # ── Convenience: integrate with per-axis pipeline output ────────

    def build_snapshots(
        self,
        per_axis_data: Dict[str, Dict[str, Any]],
        channel_names: List[str],
    ) -> Dict[str, AxisSnapshot]:
        """Build AxisSnapshot dict from per-axis data structure.

        Args:
            per_axis_data: {axis_id: {"values": [...], "stats": {...},
                                       "annotations": [...], "slave": 0}}
            channel_names: Standard channel name list.

        Returns:
            Dict of AxisSnapshot ready for analyze().
        """
        snapshots = {}
        for axis_id, data in per_axis_data.items():
            snapshots[axis_id] = AxisSnapshot(
                axis_id=axis_id,
                slave_position=data.get("slave", 0),
                values=data.get("values", [0.0] * len(channel_names)),
                channel_names=channel_names,
                buffer_stats=data.get("stats", {}),
                annotations=data.get("annotations", []),
                timestamp=time.time(),
            )
        return snapshots

    def reset(self):
        """Reset all sub-detector state."""
        super().reset()
        self._bus_sag.reset()
        self._contouring.reset()
        self._ring_health.reset()
        self._mechanical_coupling.reset()
        self._last_ring_state = None

    def status(self) -> dict:
        """Get sub-detector status report."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "detectors": self._enabled_detectors,
            "bus_sag_axes": list(self._bus_sag._current_windows.keys()),
            "contouring_pairs": self._contouring._axis_pairs,
            "coupling_pairs": self._mechanical_coupling._coupling_pairs,
        }

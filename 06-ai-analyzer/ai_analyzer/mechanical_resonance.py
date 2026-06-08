"""
Mechanical Resonance Detector — FFT-based vibration mode identification.

Sliding-window FFT on the velocity and current channels to detect:
  1. Primary resonant frequency peaks (exceeds 3× noise floor)
  2. Harmonic patterns (integer multiples confirming structural resonance)
  3. Frequency shift over time (bearing degradation indicator)

Algorithm:
  - Maintain 1024-sample circular buffer per monitored channel
  - Every 256 samples: run np.fft.rfft, detect peaks, match harmonics
  - Generate annotations with suggested notch filter frequency (0x610B)

Reference: Delta A3 supports 4 notch filters (0x610B-0x6113) and
           low-pass filter (0x610A). Resonance detection enables
           automatic notch filter configuration.
"""

from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    from .analyzer_base import AIAnnotation, AnalyzerBase
    from .config import MECHANICAL_RESONANCE, CHANNEL_NAME_INDEX
except ImportError:
    from analyzer_base import AIAnnotation, AnalyzerBase
    from config import MECHANICAL_RESONANCE, CHANNEL_NAME_INDEX

# ── Mains frequency rejection ──
# 50/60 Hz mains and their harmonics can couple into current sensors
# and appear as strong FFT peaks, but they are NOT mechanical resonance.
_MAINS_FREQUENCIES = [50.0, 60.0]  # Hz — fundamental mains
_MAINS_TOLERANCE = 3.0             # Hz — ±band around each mains frequency
_MAINS_MAX_HARMONIC = 6            # reject up to 6th harmonic (300/360 Hz)


class MechanicalResonanceDetector(AnalyzerBase):
    """FFT-based mechanical resonance detection on velocity/current channels."""

    def __init__(self, name: str = "MechanicalResonance", enabled: bool = True,
                 sample_rate_hz: float = 1000.0):
        super().__init__(name=name, enabled=enabled)
        cfg = MECHANICAL_RESONANCE
        self._fft_size = cfg["fft_window_size"]
        self._stride = cfg["fft_stride"]
        self._peak_ratio = cfg["peak_noise_floor_ratio"]
        self._harmonic_tol = cfg["harmonic_ratio_tolerance"]
        self._min_freq = cfg["min_frequency_hz"]
        self._max_freq = cfg["max_frequency_hz"]
        self._min_harmonics = cfg.get("min_harmonics", 1)
        self._strong_peak_snr = cfg.get("strong_peak_snr", 10.0)
        self._sample_rate = sample_rate_hz

        # Per-channel circular buffers
        self._buffers: Dict[str, Deque[float]] = {
            "Velocity": deque(maxlen=self._fft_size),
            "Current": deque(maxlen=self._fft_size),
        }
        self._samples_since_fft = 0
        self._known_resonances: List[float] = []  # previously detected frequencies
        self._consecutive_count = 0

    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        self._sample_count += 1
        self._samples_since_fft += 1

        # Feed values into per-channel buffers
        for ch_name, buffer in self._buffers.items():
            try:
                ci = channel_names.index(ch_name)
                val = values[ci] if ci < len(values) else 0.0
                buffer.append(val)
            except ValueError:
                continue

        # Only run FFT every stride samples
        if self._samples_since_fft < self._stride:
            return []
        self._samples_since_fft = 0

        annotations: List[AIAnnotation] = []

        for ch_name, buffer in self._buffers.items():
            if len(buffer) < self._fft_size // 2:
                continue

            data = np.array(buffer)
            signal_std = np.std(data)
            if signal_std < 1e-6:
                continue  # no signal energy — skip FFT

            # ── Compute FFT ──
            freqs, magnitudes, noise_floor = self._compute_fft(data)

            # ── Peak detection ──
            peaks = self._find_peaks(freqs, magnitudes, noise_floor)
            if not peaks:
                continue

            # ── Harmonic analysis ──
            harmonic_groups = self._find_harmonics(peaks)

            reported_fundamentals = set()
            for fundamental, harmonics in harmonic_groups:
                if len(harmonics) < self._min_harmonics:
                    continue
                reported_fundamentals.add(fundamental)

                # Check if this is a known resonance (re-detected)
                is_known = any(
                    abs(fundamental - known) / max(known, 1.0) < 0.10
                    for known in self._known_resonances
                )

                if is_known:
                    self._consecutive_count += 1
                else:
                    self._known_resonances.append(fundamental)
                    # Keep last 10 known resonances
                    if len(self._known_resonances) > 10:
                        self._known_resonances = self._known_resonances[-10:]

                harmonic_freqs = [h[0] for h in harmonics]
                confidence = min(1.0, len(harmonics) / 5.0 + 0.4)

                if len(harmonics) >= 4:
                    category = "resonance_harmonic"
                    message = (
                        f"Harmonic resonance on {ch_name}: fundamental {fundamental:.0f} Hz, "
                        f"{len(harmonics)} harmonics ({', '.join(f'{h:.0f}' for h in harmonic_freqs[:4])} Hz). "
                        f"Structural vibration mode likely."
                    )
                else:
                    category = "resonance_detected"
                    message = (
                        f"Resonance peak on {ch_name}: {fundamental:.0f} Hz "
                        f"(magnitude {magnitudes[np.argmin(np.abs(freqs - fundamental))]:.1f}). "
                        f"Consider notch filter at {fundamental:.0f} Hz (0x610B)."
                    )

                annotations.append(AIAnnotation(
                    timestamp=0.0,
                    channel=ch_name,
                    category=category,
                    severity="info",
                    confidence=confidence,
                    message=message,
                    value=fundamental,
                    metadata={
                        "fundamental_hz": fundamental,
                        "harmonics": harmonic_freqs,
                        "noise_floor": noise_floor,
                        "is_known": is_known,
                    },
                ))

            # ── Isolated strong peaks (no harmonics, but still valid resonance) ──
            for freq, mag in peaks:
                if freq in reported_fundamentals:
                    continue  # already reported as harmonic group
                snr = mag / (noise_floor + 1e-6)
                if snr > self._strong_peak_snr:
                    msg = (f"Resonance peak on {ch_name}: {freq:.0f} Hz "
                           f"(SNR {snr:.0f}x, no harmonics detected). "
                           f"Consider notch filter at {freq:.0f} Hz (0x610B).")
                    annotations.append(AIAnnotation(
                        timestamp=0.0, channel=ch_name,
                        category="resonance_detected",
                        severity="info",
                        confidence=min(1.0, snr / 30.0),
                        message=msg, value=freq,
                        metadata={
                            "fundamental_hz": freq,
                            "harmonics": [freq],
                            "noise_floor": noise_floor,
                            "is_known": False,
                            "isolated_peak": True,
                        },
                    ))

        return annotations

    def _compute_fft(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """Compute FFT magnitude spectrum and noise floor.

        Automatically detects intermittent (amplitude-modulated) resonance
        and runs a gated FFT on high-amplitude segments to recover the
        carrier frequency that standard FFT would miss.

        Returns:
            freqs: Frequency bins (Hz)
            magnitudes: FFT magnitude spectrum (standard or gated)
            noise_floor: Median magnitude (noise floor estimate)
        """
        n = len(data)
        # Apply Hann window to reduce spectral leakage
        windowed = data * np.hanning(n)
        fft = np.fft.rfft(windowed)
        magnitudes = np.abs(fft)
        freqs = np.fft.rfftfreq(n, d=1.0 / self._sample_rate)
        noise_floor = float(np.median(magnitudes))
        # Floor: pure sine + DC produces near-zero spectral bins.
        # Median would be ~0, making threshold=0 and any micro-leakage
        # qualifies as a peak. Clamp to a meaningful minimum.
        if noise_floor < 1e-3:
            noise_floor = max(float(np.mean(np.sort(magnitudes)[:max(1, n // 4)])), 1e-3)

        # ── Amplitude-Gated FFT for intermittent resonance ──
        # When resonance only appears during accel/decel (intermittent),
        # the carrier frequency (e.g. 320Hz) is buried under DC + low-freq
        # load component. Standard FFT sees the envelope, not the carrier.
        #
        # Solution: high-pass filter the signal to isolate the HF resonance,
        # then gate on HF energy to extract active segments.
        #
        # GUARD: only activate gated FFT when standard FFT already shows
        # meaningful HF energy (>min_freq). Without this guard, low-frequency
        # signals (e.g. 5Hz current modulation) create false peaks from the
        # concatenation artifacts in the gated segment assembly.
        std_snr = float(np.max(magnitudes)) / (noise_floor + 1e-6)
        std_peak_bin = int(np.argmax(magnitudes[1:])) + 1  # skip DC bin 0
        std_peak_freq = float(freqs[std_peak_bin]) if std_peak_bin < len(freqs) else 0.0
        hf_content = std_peak_freq > self._min_freq and std_snr > self._peak_ratio

        if n >= 16 and hf_content:
            # Simple high-pass: subtract moving average (5-sample window)
            kernel = np.ones(5) / 5
            hp_signal = data - np.convolve(data, kernel, mode='same')
            hp_abs = np.abs(hp_signal)
            hp_mean = np.mean(hp_abs)
            if hp_mean > 1e-9:
                mask = hp_abs > hp_mean
                active_ratio = np.sum(mask) / n
                # Gating useful when 10-80% of samples have HF energy
                if 0.10 < active_ratio < 0.80:
                    idx = np.where(mask)[0]
                    segments = []
                    seg_start = idx[0]
                    for i in range(1, len(idx)):
                        if idx[i] - idx[i-1] > 3:
                            segments.append(data[seg_start:idx[i-1]+1])
                            seg_start = idx[i]
                    segments.append(data[seg_start:idx[-1]+1])

                    if segments:
                        gated_data = np.concatenate(segments)
                        if len(gated_data) > n // 8:
                            target_n = 2 ** int(np.log2(len(gated_data)))
                            if target_n >= 64:
                                gated_data = gated_data[:target_n]
                                gated_windowed = gated_data * np.hanning(target_n)
                                gated_fft = np.fft.rfft(gated_windowed)
                                gated_magnitudes = np.abs(gated_fft)
                                gated_freqs = np.fft.rfftfreq(target_n, d=1.0 / self._sample_rate)
                                gated_noise = float(np.median(gated_magnitudes))
                                gated_snr = float(np.max(gated_magnitudes)) / (gated_noise + 1e-6)
                                if gated_snr > std_snr * 1.5:
                                    return gated_freqs, gated_magnitudes, gated_noise

        return freqs, magnitudes, noise_floor

    @staticmethod
    def _is_mains_frequency(freq: float) -> bool:
        """Check if a frequency falls within a mains rejection band.

        Rejects 50/60 Hz fundamental + harmonics up to _MAINS_MAX_HARMONIC.
        These appear on Current channels via sensor coupling, not mechanics.
        """
        for base in _MAINS_FREQUENCIES:
            for harmonic in range(1, _MAINS_MAX_HARMONIC + 1):
                target = base * harmonic
                if abs(freq - target) <= _MAINS_TOLERANCE:
                    return True
        return False

    def _find_peaks(
        self, freqs: np.ndarray, magnitudes: np.ndarray, noise_floor: float
    ) -> List[Tuple[float, float]]:
        """Find frequency peaks above noise floor threshold.

        Skips mains frequencies (50/60 Hz and harmonics) which couple
        into current sensors electrically, not mechanically.

        Returns:
            List of (frequency_hz, magnitude) sorted by magnitude descending.
        """
        threshold = noise_floor * self._peak_ratio

        # Find local maxima
        peaks: List[Tuple[float, float]] = []
        for i in range(1, len(magnitudes) - 1):
            if magnitudes[i] > magnitudes[i - 1] and magnitudes[i] > magnitudes[i + 1]:
                freq = freqs[i]
                mag = magnitudes[i]
                # Filter by frequency range, threshold, and mains rejection
                if (self._min_freq <= freq <= self._max_freq
                        and mag > threshold
                        and not self._is_mains_frequency(freq)):
                    peaks.append((freq, mag))

        # Sort by magnitude descending
        peaks.sort(key=lambda x: x[1], reverse=True)
        return peaks[:10]  # top 10 peaks

    def _find_harmonics(
        self, peaks: List[Tuple[float, float]]
    ) -> List[Tuple[float, List[Tuple[float, float]]]]:
        """Group peaks into harmonic series.

        A harmonic series has peaks at integer multiples of a fundamental frequency.
        Returns list of (fundamental_freq, [(harmonic_freq, magnitude), ...]).
        """
        if len(peaks) < 2:
            return []

        harmonic_groups: List[Tuple[float, List[Tuple[float, float]]]] = []
        used = set()

        for i, (freq, mag) in enumerate(peaks):
            if i in used:
                continue

            harmonics: List[Tuple[float, float]] = [(freq, mag)]
            used.add(i)

            # Check if other peaks are integer multiples
            for j, (f2, m2) in enumerate(peaks):
                if j in used or j == i:
                    continue
                ratio = f2 / freq
                nearest_int = round(ratio)
                if nearest_int < 2:  # fundamental itself or sub-harmonic
                    continue
                # Check if ratio is close to integer
                if abs(ratio - nearest_int) / nearest_int < self._harmonic_tol:
                    harmonics.append((f2, m2))
                    used.add(j)

            if len(harmonics) >= 2:
                harmonic_groups.append((freq, harmonics))

        return harmonic_groups

    def reset(self):
        super().reset()
        self._samples_since_fft = 0
        self._consecutive_count = 0
        self._known_resonances.clear()
        for buf in self._buffers.values():
            buf.clear()

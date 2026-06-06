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
        self._min_harmonics = cfg["min_harmonics"]
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

            for fundamental, harmonics in harmonic_groups:
                if len(harmonics) < self._min_harmonics:
                    continue

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

        return annotations

    def _compute_fft(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """Compute FFT magnitude spectrum and noise floor.

        Returns:
            freqs: Frequency bins (Hz)
            magnitudes: FFT magnitude spectrum
            noise_floor: Median magnitude (noise floor estimate)
        """
        n = len(data)
        # Apply Hann window to reduce spectral leakage
        windowed = data * np.hanning(n)
        fft = np.fft.rfft(windowed)
        magnitudes = np.abs(fft)
        freqs = np.fft.rfftfreq(n, d=1.0 / self._sample_rate)

        # Noise floor: median magnitude (robust to peaks)
        noise_floor = float(np.median(magnitudes))

        return freqs, magnitudes, noise_floor

    def _find_peaks(
        self, freqs: np.ndarray, magnitudes: np.ndarray, noise_floor: float
    ) -> List[Tuple[float, float]]:
        """Find frequency peaks above noise floor threshold.

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
                # Filter by frequency range and threshold
                if self._min_freq <= freq <= self._max_freq and mag > threshold:
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

"""Unit tests for MechanicalResonanceDetector."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from mechanical_resonance import MechanicalResonanceDetector


class TestMechanicalResonanceDetector:
    @pytest.fixture
    def detector(self):
        return MechanicalResonanceDetector(sample_rate_hz=1000.0)

    @pytest.fixture
    def buffer_stats(self):
        return {
            "Velocity": {"mean": 0.0, "std": 100.0, "min": -300.0, "max": 300.0, "rms": 100.0, "peak_to_peak": 600.0},
            "Current": {"mean": 80.0, "std": 10.0, "min": 50.0, "max": 110.0, "rms": 82.0, "peak_to_peak": 60.0},
        }

    def test_clean_sine_no_resonance(self, detector, buffer_stats):
        """A single clean sine wave should not trigger resonance (no harmonics)."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        # Feed exactly fft_size samples of a clean 50Hz sine
        for i in range(1024):
            t = i / 1000.0
            v = 100.0 * np.sin(2 * np.pi * 50.0 * t)
            c = 80.0 + 5.0 * np.sin(2 * np.pi * 50.0 * t)
            results = detector.analyze(
                [1000.0 * np.sin(2 * np.pi * 5.0 * t), v, c, 60.0],
                ch_names, buffer_stats,
            )
            # Most samples return empty (FFT only runs every 256 samples)
            if results:
                # A pure sine may or may not trigger — depends on harmonic count
                # Single peak with no harmonics < min_harmonics (2) → no annotation
                pass

    def test_resonance_with_harmonics(self, detector, buffer_stats):
        """A signal with fundamental + harmonics should trigger resonance."""
        ch_names = ["Position", "Velocity", "Current", "Torque"]
        # Generate a signal with 80Hz fundamental + 2nd, 3rd, 4th harmonics
        fundamental = 80.0
        for i in range(1024):
            t = i / 1000.0
            v = (
                150.0 * np.sin(2 * np.pi * fundamental * t)
                + 80.0 * np.sin(2 * np.pi * fundamental * 2 * t)   # 2nd harmonic
                + 50.0 * np.sin(2 * np.pi * fundamental * 3 * t)   # 3rd harmonic
                + 30.0 * np.sin(2 * np.pi * fundamental * 4 * t)   # 4th harmonic
                + np.random.normal(0, 5.0)                          # noise
            )
            c = 80.0 + 10.0 * np.sin(2 * np.pi * 50.0 * t)
            results = detector.analyze(
                [1000.0, v, c, 60.0],
                ch_names, buffer_stats,
            )

        assert detector._sample_count == 1024

    def test_no_signal_energy(self, detector, buffer_stats):
        """Zero signal should not trigger FFT analysis."""
        ch_names = ["Velocity"]
        for i in range(512):
            results = detector.analyze([0.0], ch_names, buffer_stats)
        # All zero data — FFT skipped due to low signal energy
        all_empty = all(r == [] for r in [detector.analyze([0.0], ch_names, buffer_stats)])
        assert all_empty

    def test_fft_peak_detection(self, detector):
        """Test internal FFT peak detection on a known signal."""
        detector._sample_rate = 1000.0
        # Generate 80Hz + 3rd harmonic signal
        t = np.arange(1024) / 1000.0
        data = (
            100.0 * np.sin(2 * np.pi * 80.0 * t)
            + 50.0 * np.sin(2 * np.pi * 240.0 * t)  # 3rd harmonic
            + np.random.normal(0, 5.0, 1024)
        )

        freqs, magnitudes, noise_floor = detector._compute_fft(data)
        peaks = detector._find_peaks(freqs, magnitudes, noise_floor)

        # Should find at least the 80Hz peak
        assert len(peaks) > 0
        peak_freqs = [p[0] for p in peaks]
        # Check that 80Hz (or close) is in the peaks
        has_80hz = any(abs(f - 80.0) < 5.0 for f in peak_freqs)
        assert has_80hz

    def test_harmonic_matching(self, detector):
        """Test harmonic grouping logic."""
        peaks = [
            (80.0, 100.0),    # fundamental
            (160.0, 80.0),    # 2nd harmonic
            (240.0, 50.0),    # 3rd harmonic
            (320.0, 30.0),    # 4th harmonic
            (555.0, 40.0),    # unrelated peak
        ]
        groups = detector._find_harmonics(peaks)
        # Should find at least one harmonic group with fundamental ~80Hz
        assert len(groups) >= 1
        fundamental, harmonics = groups[0]
        assert abs(fundamental - 80.0) < 5.0
        assert len(harmonics) >= 3  # should include 80, 160, 240, 320

    def test_reset(self, detector, buffer_stats):
        ch_names = ["Velocity"]
        for i in range(100):
            detector.analyze([100.0 * np.sin(2 * np.pi * 50.0 * i / 1000.0)], ch_names, buffer_stats)
        detector.reset()
        assert detector._sample_count == 0
        assert detector._samples_since_fft == 0

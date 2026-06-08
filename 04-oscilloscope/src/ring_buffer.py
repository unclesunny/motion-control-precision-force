"""
High-Performance Ring Buffer for Oscilloscope Data Acquisition.

Fixed-size circular buffer with O(1) append and numpy array views.
Thread-safe for single-producer, single-consumer use.

Supports:
  - 8 channels × 60 seconds @ 1 kHz = 480,000 samples (~3.8 MB)
  - Zero-copy numpy array access
  - Trigger position tracking
"""

import threading
from typing import List, Optional, Tuple

import numpy as np


class RingBuffer:
    """Fixed-size circular buffer for time-series data.

    Stores N channels × buffer_size samples in a pre-allocated numpy array.
    Append operations are O(1). All access via numpy views (no copy).
    """

    def __init__(self, n_channels: int = 8, buffer_size: int = 60000,
                 channel_names: Optional[List[str]] = None):
        """
        Args:
            n_channels: Number of data channels (default 8)
            buffer_size: Samples per channel (default 60,000 = 60s @ 1kHz)
            channel_names: Optional list of channel labels
        """
        self.n_channels = n_channels
        self.buffer_size = buffer_size
        self.channel_names = channel_names or [f"CH{i+1}" for i in range(n_channels)]

        # Pre-allocated ring buffer: shape (n_channels, buffer_size)
        self._data = np.zeros((n_channels, buffer_size), dtype=np.float32)
        self._timestamps = np.zeros(buffer_size, dtype=np.float64)

        # Write pointer (next write position)
        self._head = 0
        # Total samples written (monotonically increasing)
        self._total_written = 0
        # Has the buffer wrapped around at least once?
        self._full = False

        # Trigger position (index into buffer, or -1 if no trigger)
        self._trigger_pos = -1
        self._lock = threading.Lock()

    def append(self, values: List[float], timestamp: float = 0.0) -> int:
        """Append one sample (all channels at one timestep).

        Args:
            values: List of channel values (must match n_channels)
            timestamp: Sample timestamp in seconds

        Returns:
            Current head position (write index)
        """
        if len(values) < self.n_channels:
            values = list(values) + [0.0] * (self.n_channels - len(values))

        with self._lock:
            self._data[:, self._head] = values[:self.n_channels]
            self._timestamps[self._head] = timestamp
            self._head = (self._head + 1) % self.buffer_size
            self._total_written += 1
            if self._head == 0:
                self._full = True
            return self._head

    def append_many(self, data: np.ndarray, timestamps: np.ndarray):
        """Append multiple samples at once (batch mode, more efficient).

        Args:
            data: shape (n_channels, n_samples) or (n_samples, n_channels)
            timestamps: shape (n_samples,)
        """
        n = data.shape[1] if data.shape[0] == self.n_channels else data.shape[0]
        if data.shape[0] != self.n_channels:
            data = data.T

        with self._lock:
            for i in range(n):
                idx = (self._head + i) % self.buffer_size
                self._data[:, idx] = data[:, i]
                self._timestamps[idx] = timestamps[i]

            self._head = (self._head + n) % self.buffer_size
            self._total_written += n
            if self._head < n:  # wrapped during this batch
                self._full = True

    def get_recent(self, n_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Get the most recent n_samples as (data, timestamps).

        Returns data in chronological order (oldest first).
        data shape: (n_channels, n_samples)
        timestamps shape: (n_samples,)
        """
        n = min(n_samples, self.count)
        with self._lock:
            if not self._full and self._head >= n:
                # Single contiguous segment before head
                start = self._head - n
                return (self._data[:, start:self._head].copy(),
                        self._timestamps[start:self._head].copy())
            else:
                # Wrapped: need two segments
                return self._get_wrapped(n)

    def _get_wrapped(self, n: int) -> Tuple[np.ndarray, np.ndarray]:
        """Get n samples when buffer has wrapped."""
        n = min(n, self.count)
        data = np.zeros((self.n_channels, n), dtype=np.float32)
        ts = np.zeros(n, dtype=np.float64)

        # Segment 1: from head to end of buffer
        seg1_len = self.buffer_size - self._head
        if seg1_len >= n:
            # All in one segment before head
            start = self._head - n
            data[:] = self._data[:, start:self._head]
            ts[:] = self._timestamps[start:self._head]
            return data, ts

        # We need both segments
        seg1_len = min(n, self.buffer_size - self._head)
        if seg1_len > 0:
            data[:, -seg1_len:] = self._data[:, -seg1_len:]
            ts[-seg1_len:] = self._timestamps[-seg1_len:]

        seg2_len = n - seg1_len
        if seg2_len > 0:
            start2 = self._head - seg2_len
            if start2 < 0:
                start2 += self.buffer_size
            data[:, :seg2_len] = self._data[:, start2:start2 + seg2_len]
            ts[:seg2_len] = self._timestamps[start2:start2 + seg2_len]

        return data, ts

    def get_all(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get all stored data in chronological order."""
        return self.get_recent(self.count)

    def get_by_index(self, indices: np.ndarray) -> np.ndarray:
        """Get data at specific buffer indices."""
        return self._data[:, indices % self.buffer_size]

    def mark_trigger(self):
        """Mark current write position as trigger point."""
        with self._lock:
            self._trigger_pos = (self._head - 1) % self.buffer_size

    def get_trigger_region(self, pre_samples: int = 1000,
                           post_samples: int = 3000) -> Tuple[np.ndarray, np.ndarray]:
        """Get data around trigger point."""
        if self._trigger_pos < 0:
            return self.get_recent(pre_samples + post_samples)

        total = pre_samples + post_samples
        start = (self._trigger_pos - pre_samples) % self.buffer_size
        data = np.zeros((self.n_channels, total), dtype=np.float32)
        ts = np.zeros(total, dtype=np.float64)

        for i in range(total):
            idx = (start + i) % self.buffer_size
            data[:, i] = self._data[:, idx]
            ts[i] = self._timestamps[idx]

        return data, ts

    def clear(self):
        """Reset buffer to empty."""
        with self._lock:
            self._data.fill(0.0)
            self._timestamps.fill(0.0)
            self._head = 0
            self._total_written = 0
            self._full = False
            self._trigger_pos = -1

    @property
    def count(self) -> int:
        """Number of samples currently stored."""
        if self._full:
            return self.buffer_size
        return self._head

    @property
    def total_written(self) -> int:
        return self._total_written

    @property
    def is_full(self) -> bool:
        return self._full

    @property
    def head(self) -> int:
        return self._head

    @property
    def head_data(self) -> np.ndarray:
        """Latest sample (all channels)."""
        idx = (self._head - 1) % self.buffer_size
        return self._data[:, idx].copy()

    def channel_stats(self, channel: int) -> dict:
        """Compute statistics for one channel."""
        data, _ = self.get_all()
        ch_data = data[channel]
        return {
            "name": self.channel_names[channel],
            "min": float(np.min(ch_data)),
            "max": float(np.max(ch_data)),
            "mean": float(np.mean(ch_data)),
            "std": float(np.std(ch_data)),
            "rms": float(np.sqrt(np.mean(ch_data ** 2))),
            "peak_to_peak": float(np.max(ch_data) - np.min(ch_data)),
        }

    def stats_summary(self) -> str:
        """One-line stats summary for all channels."""
        parts = []
        for ch in range(self.n_channels):
            s = self.channel_stats(ch)
            parts.append(f"{s['name']}: {s['mean']:.1f}±{s['std']:.1f} "
                         f"[{s['min']:.1f}, {s['max']:.1f}]")
        return " | ".join(parts)

    def to_csv(self, filepath: str, n_samples: int = 0, delimiter: str = ",") -> int:
        """Export buffer contents to CSV file.

        Args:
            filepath: Output CSV file path.
            n_samples: Number of recent samples to export. 0 = all.
            delimiter: CSV delimiter (default comma).

        Returns:
            Number of samples written.
        """
        import csv
        data, ts = self.get_recent(n_samples if n_samples > 0 else self.count)
        n = data.shape[1]

        # Build header: Timestamp, CH1 Name (unit), CH2 Name (unit), ...
        headers = ["Timestamp (s)"]
        for i in range(min(self.n_channels, data.shape[0])):
            name = self.channel_names[i] if i < len(self.channel_names) else f"CH{i+1}"
            headers.append(name)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(headers)
            for i in range(n):
                row = [f"{ts[i]:.6f}"]
                for ch in range(data.shape[0]):
                    row.append(f"{data[ch, i]:.6g}")
                writer.writerow(row)

        return n

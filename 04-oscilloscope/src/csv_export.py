"""
CSV Waveform Export Module — unified export for all 3 oscilloscope frontends.

Provides single-axis, multi-axis, annotation, and session-bundle export with
metadata headers, configurable delimiters, and proper unit annotations.

Usage:
    from csv_export import export_waveform_csv, export_multi_axis_csv, export_annotations_csv

    # Single axis
    export_waveform_csv("scope_X.csv", data, timestamps, CHANNELS,
                        metadata={"sample_rate_hz": 1000, "axis_id": "X"})

    # Multi-axis
    export_multi_axis_csv("session_20260607/", axes_data, metadata={...})

    # Annotations
    export_annotations_csv("events.csv", anomaly_events)

    # Full session bundle
    export_session_bundle("session_20260607/", axes_data, annotations, metadata={...})
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np


# ── Channel definitions (shared across all modules) ──────────

DEFAULT_CHANNELS = [
    {"name": "Position Actual",  "unit": "pulses", "color": "#00FF88"},
    {"name": "Velocity Actual",  "unit": "rpm",    "color": "#FF8800"},
    {"name": "Current Actual",   "unit": "%",      "color": "#FF4444"},
    {"name": "Torque Actual",    "unit": "%",      "color": "#44AAFF"},
    {"name": "Following Error",  "unit": "pulses", "color": "#E066CC"},
    {"name": "Digital Inputs",   "unit": "bits",   "color": "#FFCC00"},
    {"name": "Statusword",       "unit": "hex",    "color": "#22DD88"},
    {"name": "Op Mode Display",  "unit": "code",   "color": "#CCCCCC"},
]


# ── Helpers ──────────────────────────────────────────────────

def _ensure_arrays(data, timestamps):
    """Convert list-of-lists or raw arrays to numpy for consistent access."""
    if not isinstance(data, np.ndarray):
        data = np.array(data, dtype=np.float32)
    if not isinstance(timestamps, np.ndarray):
        timestamps = np.array(timestamps, dtype=np.float64)
    # Ensure data is (n_channels, n_samples)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return data, timestamps


def _build_header_row(channel_config: List[dict]) -> List[str]:
    """Build CSV header row: Timestamp (s), ChannelName (unit), ..."""
    headers = ["Timestamp (s)"]
    for ch in channel_config:
        name = ch.get("name", "CH")
        unit = ch.get("unit", "")
        headers.append(f"{name} ({unit})" if unit else name)
    return headers


def _write_metadata_block(writer, metadata: Optional[dict], delimiter: str):
    """Write metadata comment lines at the top of the CSV file."""
    if not metadata:
        return

    def _row(*values):
        writer.writerow(values)

    _row(f"# Generated: {metadata.get('export_time', datetime.now().isoformat())}")
    _row(f"# Sample Rate: {metadata.get('sample_rate_hz', 'N/A')} Hz")
    _row(f"# Axis: {metadata.get('axis_id', 'N/A')}")

    if metadata.get("brand"):
        _row(f"# Brand: {metadata.get('brand')}")
    if metadata.get("slave_position") is not None:
        _row(f"# Slave Position: {metadata.get('slave_position')}")
    if metadata.get("total_samples") is not None:
        _row(f"# Samples: {metadata.get('total_samples')}")
    if metadata.get("duration_s") is not None:
        _row(f"# Duration: {metadata.get('duration_s'):.3f} s")
    if metadata.get("notes"):
        _row(f"# Notes: {metadata.get('notes')}")

    _row(f"# Delimiter: {repr(delimiter)}")
    _row("#")


# ── Public API ───────────────────────────────────────────────

def export_waveform_csv(
    filepath: Union[str, Path],
    data: Union[np.ndarray, List[List[float]]],
    timestamps: Union[np.ndarray, List[float]],
    channel_config: Optional[List[dict]] = None,
    metadata: Optional[dict] = None,
    delimiter: str = ",",
    n_samples: int = 0,
) -> int:
    """Export single-axis waveform data to a CSV file.

    Args:
        filepath: Output CSV file path.
        data: Waveform data, shape (n_channels, n_samples) or (n_samples, n_channels).
        timestamps: Timestamp array, shape (n_samples,).
        channel_config: List of channel dicts with 'name' and 'unit' keys.
        metadata: Dict with sample_rate_hz, axis_id, brand, etc.
        delimiter: CSV delimiter (default comma). Use '\\t' for TSV.
        n_samples: Limit to last N samples. 0 = all.

    Returns:
        Number of samples written.

    Raises:
        ValueError: If data and timestamps have mismatched sample counts.
    """
    data, timestamps = _ensure_arrays(data, timestamps)

    # Ensure data is (n_channels, n_samples)
    if data.shape[0] > data.shape[1] and data.shape[1] <= 16:
        # Likely transposed — n_channels is usually 8, n_samples is large
        pass  # don't guess; caller should provide correct shape

    n_channels = data.shape[0]
    total_samples = data.shape[1]

    if len(timestamps) != total_samples:
        raise ValueError(
            f"Timestamp count ({len(timestamps)}) does not match sample count ({total_samples})"
        )

    # Limit to last N samples
    if n_samples and n_samples < total_samples:
        data = data[:, -n_samples:]
        timestamps = timestamps[-n_samples:]

    n = data.shape[1]
    if n == 0:
        return 0

    # Default channel config if not provided
    if channel_config is None:
        channel_config = [
            {"name": f"CH{i+1}", "unit": ""} for i in range(n_channels)
        ]
    # Pad channel config if needed
    if len(channel_config) < n_channels:
        for i in range(len(channel_config), n_channels):
            channel_config.append({"name": f"CH{i+1}", "unit": ""})

    # Build enriched metadata
    full_meta = {
        "export_time": datetime.now().isoformat(),
        "total_samples": n,
        "duration_s": float(timestamps[-1] - timestamps[0]) if n > 1 else 0.0,
    }
    if metadata:
        full_meta.update(metadata)

    headers = _build_header_row(channel_config[:n_channels])

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        _write_metadata_block(writer, full_meta, delimiter)
        writer.writerow(headers)

        if delimiter == "\t":
            # TSV: use fixed-precision formatting for readability
            for i in range(n):
                row = [f"{timestamps[i]:.6f}"]
                for ch in range(n_channels):
                    row.append(f"{data[ch, i]:.6g}")
                writer.writerow(row)
        else:
            for i in range(n):
                row = [f"{timestamps[i]:.6f}"]
                for ch in range(n_channels):
                    row.append(f"{data[ch, i]:.6g}")
                writer.writerow(row)

    return n


def export_multi_axis_csv(
    output_dir: Union[str, Path],
    axes_data: Dict[str, Tuple[np.ndarray, np.ndarray]],
    channel_config: Optional[List[dict]] = None,
    metadata: Optional[dict] = None,
    delimiter: str = ",",
    n_samples: int = 0,
) -> Dict[str, int]:
    """Export multi-axis waveform data — one CSV file per axis.

    Also writes a ``_session.json`` manifest with metadata for all axes.

    Args:
        output_dir: Directory to write CSV files into (created if needed).
        axes_data: Dict mapping axis_id → (data, timestamps).
        channel_config: Shared channel definitions.
        metadata: Base metadata (per-axis fields added automatically).
        delimiter: CSV delimiter.
        n_samples: Limit each axis to last N samples (0 = all).

    Returns:
        Dict mapping axis_id → sample count written.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    axis_metas = []

    for axis_id, (data, timestamps) in axes_data.items():
        axis_meta = dict(metadata or {})
        axis_meta["axis_id"] = axis_id
        axis_meta["export_time"] = datetime.now().isoformat()

        fname = output_dir / f"waveform_{axis_id}.csv"
        count = export_waveform_csv(
            fname, data, timestamps,
            channel_config=channel_config,
            metadata=axis_meta,
            delimiter=delimiter,
            n_samples=n_samples,
        )
        results[axis_id] = count
        axis_metas.append({
            "axis_id": axis_id,
            "file": str(fname.name),
            "samples": count,
            "channels": len(channel_config or DEFAULT_CHANNELS),
        })

    # Write session manifest
    manifest = {
        "export_time": datetime.now().isoformat(),
        "sample_rate_hz": (metadata or {}).get("sample_rate_hz", "N/A"),
        "brand": (metadata or {}).get("brand", ""),
        "axes": axis_metas,
        "total_axes": len(results),
        "total_samples": sum(results.values()),
    }
    manifest_path = output_dir / "_session.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return results


def export_annotations_csv(
    filepath: Union[str, Path],
    annotations: List[Any],
    delimiter: str = ",",
) -> int:
    """Export AI anomaly annotations to a CSV file.

    Each annotation should be an object with attributes:
    timestamp, channel, severity, message, value, suggestion, category.

    Also accepts plain dicts with the same keys.

    Args:
        filepath: Output CSV file path.
        annotations: List of annotation objects or dicts.
        delimiter: CSV delimiter.

    Returns:
        Number of annotations written.
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "Timestamp (s)", "Channel", "Severity", "Category",
        "Value", "Confidence", "Message", "Suggestion",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)

        # Metadata header
        writer.writerow([f"# AI Annotations Export — {datetime.now().isoformat()}"])
        writer.writerow([f"# Total Annotations: {len(annotations)}"])
        writer.writerow(["#"])

        writer.writerow(headers)

        count = 0
        for ann in annotations:
            # Support both object attributes and dict keys
            get = (lambda a, k, d="": getattr(a, k, d)) if hasattr(ann, 'timestamp') else (lambda a, k, d="": a.get(k, d))

            row = [
                f"{get(ann, 'timestamp', 0.0):.6f}",
                str(get(ann, 'channel', '')),
                str(get(ann, 'severity', 'info')),
                str(get(ann, 'category', '')),
                f"{get(ann, 'value', 0.0):.6g}",
                f"{get(ann, 'confidence', 0.0):.2f}",
                str(get(ann, 'message', '')),
                str(get(ann, 'suggestion', '')),
            ]
            writer.writerow(row)
            count += 1

    return count


def export_session_bundle(
    output_dir: Union[str, Path],
    axes_data: Dict[str, Tuple[np.ndarray, np.ndarray]],
    annotations: Optional[List[Any]] = None,
    channel_config: Optional[List[dict]] = None,
    metadata: Optional[dict] = None,
    delimiter: str = ",",
    n_samples: int = 0,
) -> dict:
    """Export a complete session bundle: waveforms + annotations + manifest.

    Directory structure::

        session_YYYYMMDD_HHMMSS/
        ├── _session.json          ← manifest (axes, sample rate, total counts)
        ├── waveform_X.csv
        ├── waveform_Y.csv
        ├── waveform_Z.csv
        └── annotations.csv        ← AI events (if any)

    Args:
        output_dir: Target directory (created if needed).
        axes_data: Dict of axis_id → (data, timestamps).
        annotations: Optional list of AI annotation events.
        channel_config: Channel definitions.
        metadata: Base metadata.
        delimiter: CSV delimiter.
        n_samples: Limit per-axis samples (0 = all).

    Returns:
        Manifest dict with file paths and counts.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    channel_config = channel_config or DEFAULT_CHANNELS

    # Export per-axis waveforms
    axis_results = export_multi_axis_csv(
        output_dir, axes_data,
        channel_config=channel_config,
        metadata=metadata,
        delimiter=delimiter,
        n_samples=n_samples,
    )

    # Export annotations
    ann_count = 0
    ann_path = ""
    if annotations:
        ann_path = str(output_dir / "annotations.csv")
        ann_count = export_annotations_csv(ann_path, annotations, delimiter=delimiter)

    # Write consolidated manifest
    manifest = {
        "export_time": datetime.now().isoformat(),
        "sample_rate_hz": (metadata or {}).get("sample_rate_hz", "N/A"),
        "brand": (metadata or {}).get("brand", ""),
        "total_axes": len(axis_results),
        "total_waveform_samples": sum(axis_results.values()),
        "total_annotations": ann_count,
        "files": {
            "manifest": "_session.json",
            "annotations": str(Path(ann_path).name) if ann_path else None,
            "waveforms": {aid: f"waveform_{aid}.csv" for aid in axis_results},
        },
    }

    manifest_path = output_dir / "_session.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest


def export_from_scope_engine(
    engine,
    filepath: Union[str, Path],
    axis_id: Optional[str] = None,
    n_samples: int = 0,
    include_annotations: bool = True,
    delimiter: str = ",",
) -> int:
    """Convenience: export waveform from a ScopeEngine instance.

    Args:
        engine: ScopeEngine instance (from scope_engine.py).
        filepath: Output CSV file path.
        axis_id: Specific axis to export (default: primary axis).
        n_samples: Limit samples (0 = all).
        include_annotations: If True, also write annotations CSV alongside.
        delimiter: CSV delimiter.

    Returns:
        Number of samples written.
    """
    filepath = Path(filepath)

    if axis_id is None:
        axis_id = engine._axis_ids[0] if hasattr(engine, '_axis_ids') else "Axis0"

    try:
        data, timestamps = engine.get_waveform(n_samples if n_samples > 0 else 60000, axis_id=axis_id)
    except Exception:
        # Fallback: single-axis engine
        data, timestamps = engine.get_waveform(n_samples if n_samples > 0 else 60000)

    channel_names = [
        "Position Actual", "Velocity Actual", "Current Actual", "Torque Actual",
        "Following Error", "Digital Inputs", "Statusword", "Op Mode Display",
    ]
    channel_config = [
        {"name": n, "unit": u} for n, u in zip(channel_names,
        ["pulses", "rpm", "%", "%", "pulses", "bits", "hex", "code"])
    ]

    metadata = {
        "sample_rate_hz": getattr(engine, 'sample_rate_hz', 1000),
        "axis_id": axis_id,
    }

    count = export_waveform_csv(
        filepath, data, timestamps,
        channel_config=channel_config,
        metadata=metadata,
        delimiter=delimiter,
        n_samples=n_samples if n_samples > 0 else 0,
    )

    # Export annotations alongside
    if include_annotations and hasattr(engine, 'anomaly_events') and engine.anomaly_events:
        ann_path = filepath.with_suffix("").with_name(filepath.stem + "_annotations.csv")
        export_annotations_csv(ann_path, engine.anomaly_events, delimiter=delimiter)

    return count

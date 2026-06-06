"""
Base classes for AI analyzers.

All analyzers inherit from AnalyzerBase (ABC). Each analyzer produces
AIAnnotation dataclass instances consumed by the oscilloscope GUI.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AIAnnotation:
    """Single AI-generated annotation event.

    Produced by analyzers, consumed by scope_engine.py → scope_app.py.
    """
    timestamp: float
    channel: str
    category: str               # key into config.ANOMALY_CATEGORIES
    severity: str               # "info" | "warning" | "critical"
    confidence: float           # 0.0 - 1.0
    message: str                # human-readable description
    suggestion: str = ""        # actionable recommendation
    value: float = 0.0          # triggering measurement value
    metadata: Dict[str, Any] = field(default_factory=dict)  # detector-specific diagnostics

    def __repr__(self) -> str:
        sev_icon = {"info": "ℹ", "warning": "⚠", "critical": "🔴"}.get(self.severity, "?")
        return f"{sev_icon} [{self.category}] {self.channel}: {self.message} ({self.confidence:.0%})"


class AnalyzerBase(ABC):
    """Abstract base class for all AI analyzers.

    Each analyzer accepts per-sample values + contextual buffer statistics
    and returns a list of AIAnnotation events (empty list = no anomaly).
    """

    def __init__(self, name: str = "", enabled: bool = True):
        self._name = name or self.__class__.__name__
        self._enabled = enabled
        self._sample_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @abstractmethod
    def analyze(
        self,
        values: List[float],
        channel_names: List[str],
        buffer_stats: Dict[str, dict],
    ) -> List[AIAnnotation]:
        """Analyze one sample frame.

        Args:
            values: Channel values for the current sample (matches channel_names order)
            channel_names: Active channel names (e.g. ["Position", "Velocity", ...])
            buffer_stats: Per-channel statistics from RingBuffer.channel_stats()
                          e.g. {"Current": {"mean": 85.0, "std": 12.0, ...}}

        Returns:
            List of AIAnnotation events (empty if nothing detected).
        """
        ...

    def reset(self):
        """Reset internal state (e.g., streaming statistics, CUSUM accumulators)."""
        self._sample_count = 0

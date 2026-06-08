"""
Action Logger — Free shell.

Pro license required for the full immutable audit trail with JSON export,
session summaries, and authorization tracking.
"""

import uuid
from datetime import datetime


class ActionLogger:
    """Immutable audit log (Pro license required for full tracking)."""

    def __init__(self, brand: str = None):
        self.session_id = str(uuid.uuid4())[:8]
        self.brand = brand
        self._events: list = []

    def log_authorized(self, action):
        """No-op — Pro license required."""
        pass

    def log_rejected(self, action):
        """No-op — Pro license required."""
        pass

    def log_feedback(self, feedback):
        """No-op — Pro license required."""
        pass

    def export_session(self) -> dict:
        return {
            "session_id": self.session_id,
            "events": self._events,
            "summary": {
                "total_events": 0,
                "prompts_issued": 0,
                "feedbacks_received": 0,
                "actions_authorized": 0,
                "actions_rejected": 0,
                "authorization_rate": 0.0,
            },
        }

    def save(self, filepath: str = None) -> str:
        """No-op save — Pro license required."""
        path = filepath or f"audit_{self.session_id}.json"
        return path

    def reset(self):
        self._events.clear()

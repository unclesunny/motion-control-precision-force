"""
Action Logger — immutable audit trail for AI decisions and engineer authorizations.

Every AI suggestion, engineer prompt, feedback, and authorized action is logged
with timestamps and unique IDs. The log is JSON-exportable for compliance,
post-incident analysis, and continuous improvement of tuning rules.

Design principle:
    "Audit trail is immutable. All AI suggestions + human decisions must be
     completely recorded and traceable."

Usage:
    from action_logger import ActionLogger

    logger = ActionLogger()
    logger.log_prompt(prompt)
    logger.log_feedback(feedback)
    logger.log_authorized(action)
    logger.log_rejected(rec, feedback, "Engineer disagrees — noise, not wear")

    # Export for compliance
    report = logger.export_session()
    print(json.dumps(report, indent=2, ensure_ascii=False))
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
except ImportError:
    from hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt


class ActionLogger:
    """Immutable audit log for HITL diagnostic sessions.

    Records:
      - Prompts issued by the AI to the engineer
      - Engineer feedback (including media references)
      - Authorized actions (parameter changes approved)
      - Rejected recommendations (with rejection reason)
      - Session metadata (start time, brand, system info)
    """

    def __init__(self, session_id: Optional[str] = None, brand: Optional[str] = None):
        self.session_id = session_id or f"session-{int(time.time())}"
        self.brand = brand
        self.session_start = time.time()
        self._entries: List[Dict[str, Any]] = []
        self._prompts: List[Dict[str, Any]] = []
        self._feedbacks: List[Dict[str, Any]] = []
        self._authorized: List[Dict[str, Any]] = []
        self._rejected: List[Dict[str, Any]] = []

        self._log_event("session_start", {
            "session_id": self.session_id,
            "brand": self.brand,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

    # ── Logging Methods ────────────────────────────────────────────

    def log_prompt(self, prompt: EngineerPrompt):
        """Log an engineer prompt issued by the AI."""
        entry = {
            "event": "prompt_issued",
            "timestamp": prompt.timestamp,
            "timestamp_utc": datetime.fromtimestamp(
                prompt.timestamp, tz=timezone.utc
            ).isoformat(),
            "prompt_id": prompt.prompt_id,
            "category": prompt.category,
            "classification": prompt.classification,
            "question": prompt.question,
            "context": prompt.context,
            "suggested_checks_count": len(prompt.suggested_checks),
            "expected_modalities": prompt.expected_modalities,
            "urgency": prompt.urgency,
            "parameter_preview_count": len(prompt.parameter_preview),
        }
        self._entries.append(entry)
        self._prompts.append(entry)

    def log_feedback(self, feedback: EngineerFeedback):
        """Log engineer feedback."""
        entry = {
            "event": "feedback_received",
            "timestamp": feedback.timestamp,
            "timestamp_utc": datetime.fromtimestamp(
                feedback.timestamp, tz=timezone.utc
            ).isoformat(),
            "prompt_id": feedback.prompt_id,
            "authorization": feedback.authorization,
            "authorized_by": feedback.authorized_by,
            "has_response_text": bool(feedback.response_text),
            "response_length": len(feedback.response_text),
            "media_count": len(feedback.media_paths),
            "media_paths": feedback.media_paths,
            "selected_observation": feedback.selected_observation[:200] if feedback.selected_observation else "",
        }
        self._entries.append(entry)
        self._feedbacks.append(entry)

    def log_authorized(self, action: AuthorizedAction):
        """Log an authorized parameter action."""
        rec = action.recommendation
        rec_dict = {}
        if rec is not None and hasattr(rec, "to_dict"):
            rec_dict = rec.to_dict()
        elif rec is not None:
            rec_dict = {
                "index": getattr(rec, "index", None),
                "action": getattr(rec, "action", ""),
                "reason": getattr(rec, "reason", ""),
            }

        entry = {
            "event": "action_authorized",
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "recommendation": rec_dict,
            "authorized_by": (
                action.authorization.authorized_by if action.authorization else ""
            ),
            "safety_acknowledged": action.safety_acknowledged,
            "rollback_plan": action.rollback_plan,
            "executed": action.executed,
            "executed_at": action.executed_at,
            "result": action.result,
        }
        self._entries.append(entry)
        self._authorized.append(entry)

    def log_rejected(
        self,
        recommendation: Any,
        feedback: EngineerFeedback,
        reason: str = "",
    ):
        """Log a rejected recommendation."""
        rec_dict = {}
        if recommendation is not None and hasattr(recommendation, "to_dict"):
            rec_dict = recommendation.to_dict()

        entry = {
            "event": "action_rejected",
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "recommendation": rec_dict,
            "rejected_by": feedback.authorized_by,
            "reason": reason or feedback.notes or "No reason provided",
        }
        self._entries.append(entry)
        self._rejected.append(entry)

    def log_event(self, event_type: str, data: Dict[str, Any]):
        """Log a custom event."""
        entry = {
            "event": event_type,
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        self._entries.append(entry)

    _log_event = log_event  # alias for internal use

    def log_annotation(self, annotation: Any):
        """Log an AI annotation (for traceability)."""
        entry = {
            "event": "annotation_detected",
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "category": getattr(annotation, "category", ""),
            "severity": getattr(annotation, "severity", ""),
            "confidence": getattr(annotation, "confidence", 0.0),
            "channel": getattr(annotation, "channel", ""),
            "message": getattr(annotation, "message", "")[:300],
            "hitl_classification": getattr(annotation, "hitl_classification", ""),
            "requires_authorization": getattr(annotation, "requires_authorization", False),
        }
        self._entries.append(entry)

    # ── Export ──────────────────────────────────────────────────────

    def export_session(self) -> dict:
        """Export the complete session audit trail as a JSON-serializable dict.

        Returns:
            {
                "session": {...},
                "summary": {
                    "total_events": int,
                    "prompts_issued": int,
                    "feedbacks_received": int,
                    "actions_authorized": int,
                    "actions_rejected": int,
                    "authorization_rate": float,
                },
                "events": [...],
            }
        """
        total_authorized = len(self._authorized)
        total_rejected = len(self._rejected)
        total_decisions = total_authorized + total_rejected

        return {
            "session": {
                "session_id": self.session_id,
                "brand": self.brand,
                "start_time": self.session_start,
                "start_time_utc": datetime.fromtimestamp(
                    self.session_start, tz=timezone.utc
                ).isoformat(),
                "duration_seconds": time.time() - self.session_start,
            },
            "summary": {
                "total_events": len(self._entries),
                "prompts_issued": len(self._prompts),
                "feedbacks_received": len(self._feedbacks),
                "actions_authorized": total_authorized,
                "actions_rejected": total_rejected,
                "authorization_rate": (
                    total_authorized / max(total_decisions, 1)
                ),
                "pending_prompts": len(self._prompts) - len(self._feedbacks),
            },
            "events": self._entries,
        }

    def save(self, filepath: Optional[str] = None) -> str:
        """Save the audit trail to a JSON file.

        Args:
            filepath: Target path. If None, saves to
                     ./logs/hitl_{session_id}.json relative to cwd.

        Returns:
            Absolute path to the saved file.
        """
        if filepath is None:
            log_dir = Path.home() / ".servo" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            filepath = str(log_dir / f"hitl_{self.session_id}.json")

        report = self.export_session()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        return str(Path(filepath).resolve())

    def summary(self) -> str:
        """Return a human-readable session summary."""
        report = self.export_session()
        s = report["summary"]
        return (
            f"HITL Session: {self.session_id}\n"
            f"  Prompts issued:    {s['prompts_issued']}\n"
            f"  Feedbacks:         {s['feedbacks_received']}\n"
            f"  Authorized:        {s['actions_authorized']}\n"
            f"  Rejected:          {s['actions_rejected']}\n"
            f"  Authorization rate: {s['authorization_rate']:.0%}\n"
            f"  Pending:           {s['pending_prompts']}\n"
            f"  Total events:      {s['total_events']}"
        )

    def reset(self):
        """Reset the logger for a new session."""
        self.session_start = time.time()
        self._entries.clear()
        self._prompts.clear()
        self._feedbacks.clear()
        self._authorized.clear()
        self._rejected.clear()
        self._log_event("session_start", {
            "session_id": self.session_id,
            "brand": self.brand,
        })

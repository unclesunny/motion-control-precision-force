"""
HITL Data Types — Free shell.

Pro license required for the full HITL type system with multi-modal feedback,
check lists, and authorization workflows.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EngineerFeedback:
    """Engineer feedback (Free shell)."""
    prompt_id: str = ""
    response_text: str = ""
    media_paths: List[str] = field(default_factory=list)
    selected_observation: str = ""
    authorization: str = "pending"
    authorized_by: str = ""
    notes: str = ""


@dataclass
class EngineerPrompt:
    """Engineer prompt (Free shell)."""
    prompt_id: str = ""
    category: str = ""
    classification: str = "safe"
    question: str = ""
    context: str = ""
    suggested_checks: List[str] = field(default_factory=list)
    urgency: str = "routine"
    parameter_preview: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "category": self.category,
            "classification": self.classification,
            "question": self.question,
            "context": self.context,
            "suggested_checks": self.suggested_checks,
            "urgency": self.urgency,
            "parameter_preview": self.parameter_preview,
        }


@dataclass
class AuthorizedAction:
    """Authorized parameter modification (Free shell)."""
    action_id: str = ""
    prompt_id: str = ""
    parameter: str = ""
    current_value: float = 0.0
    target_value: float = 0.0
    reason: str = ""
    authorized_by: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "prompt_id": self.prompt_id,
            "parameter": self.parameter,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "reason": self.reason,
            "authorized_by": self.authorized_by,
            "timestamp": self.timestamp,
        }

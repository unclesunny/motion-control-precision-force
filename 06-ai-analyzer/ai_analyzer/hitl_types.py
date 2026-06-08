"""
Human-in-the-Loop (HITL) type definitions.

Dataclasses for the engineer feedback loop:
  - EngineerPrompt: AI asks the engineer a question with a diagnostic checklist
  - EngineerFeedback: engineer's multi-modal response (text, images, audio, video)
  - AuthorizedAction: a parameter action approved by the engineer

These types form the contract between the HITL gate, the web UI, and the
parameter recommender. They are intentionally decoupled from the analyzer
pipeline so the HITL layer can be used independently (e.g., from an MCP server).

Design principle (per user requirement):
  "No authorization = no invasive code operation. AI's job is to bridge
   what sensors can detect with what requires human sensory input."
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Forward reference — ParameterRecommendation is defined in parameter_recommender.py.
# We accept it as Any here to avoid circular imports; the HITL gate resolves it lazily.


@dataclass
class EngineerPrompt:
    """A diagnostic question issued by the AI to the engineer.

    Generated when the AI detects an anomaly that either:
      - Requires human authorization before acting (actionable), or
      - Requires human sensory input to narrow the diagnosis (ambiguous).

    Attributes:
        prompt_id: Unique identifier for tracking the feedback loop.
        category: Anomaly category that triggered this prompt (key into
                 config.ANOMALY_CATEGORIES).
        classification: "actionable" (AI can fix, needs auth) or
                       "ambiguous" (AI needs human observation first).
        question: The core question for the engineer, in their language.
        context: What the AI detected — measurement values, trend, confidence.
        suggested_checks: Concrete checklist items the engineer should inspect.
                         Each item ends with a modality hint like [可拍照].
        expected_modalities: Subset of ["text", "image", "audio", "video"].
        urgency: "routine" | "soon" | "immediate".
        parameter_preview: Parameter recommendations that will be applied
                          IF the engineer approves. Empty for ambiguous prompts
                          (need feedback first).
        timestamp: When this prompt was created (epoch seconds).
        metadata: Arbitrary extra data (detector-specific diagnostics).
    """
    prompt_id: str = ""
    category: str = ""
    classification: str = ""       # "actionable" | "ambiguous"
    question: str = ""
    context: str = ""
    suggested_checks: List[str] = field(default_factory=list)
    expected_modalities: List[str] = field(default_factory=lambda: ["text"])
    urgency: str = "routine"       # "routine" | "soon" | "immediate"
    parameter_preview: List[Any] = field(default_factory=list)
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.prompt_id:
            self.prompt_id = f"hitl-{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "category": self.category,
            "classification": self.classification,
            "question": self.question,
            "context": self.context,
            "suggested_checks": self.suggested_checks,
            "expected_modalities": self.expected_modalities,
            "urgency": self.urgency,
            "parameter_preview": [
                p.to_dict() if hasattr(p, "to_dict") else str(p)
                for p in self.parameter_preview
            ],
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class EngineerFeedback:
    """The engineer's response to an EngineerPrompt.

    Supports multi-modal feedback: text description, image snapshots,
    audio recordings (machine sound), and video clips (motion behavior).

    Attributes:
        prompt_id: Matches the EngineerPrompt this responds to.
        response_text: Free-text description from the engineer.
        media_paths: Local file paths to images, audio, or video.
        selected_observation: Which check-list item the engineer confirmed
                              (index into suggested_checks, or custom string).
        authorization: "pending" | "approved" | "rejected" | "delegated".
                      "delegated" means another engineer needs to review.
        authorized_by: Engineer name, badge ID, or login.
        notes: Any additional remarks.
        timestamp: When the feedback was submitted.
    """
    prompt_id: str = ""
    response_text: str = ""
    media_paths: List[str] = field(default_factory=list)
    selected_observation: str = ""
    authorization: str = "pending"    # "pending" | "approved" | "rejected" | "delegated"
    authorized_by: str = ""
    notes: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def is_approved(self) -> bool:
        return self.authorization == "approved"

    @property
    def is_rejected(self) -> bool:
        return self.authorization == "rejected"

    @property
    def has_media(self) -> bool:
        return len(self.media_paths) > 0

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "response_text": self.response_text,
            "media_paths": self.media_paths,
            "selected_observation": self.selected_observation,
            "authorization": self.authorization,
            "authorized_by": self.authorized_by,
            "notes": self.notes,
            "timestamp": self.timestamp,
        }


@dataclass
class AuthorizedAction:
    """A parameter adjustment that has been explicitly approved by the engineer.

    This is the ONLY type that should be passed to a parameter-write function.
    Unauthorized ParameterRecommendation instances are read-only suggestions.

    Attributes:
        recommendation: The parameter recommendation that was approved.
        authorization: The engineer's feedback containing the approval.
        safety_acknowledged: Whether the engineer explicitly acknowledged
                            the safety warning.
        rollback_plan: How to undo this change if it causes problems.
        executed: Whether the action has been carried out.
        executed_at: When the action was executed (epoch seconds).
        result: Result of execution (e.g., "OK", "Err: timeout").
    """
    recommendation: Any = None       # ParameterRecommendation
    authorization: Optional[EngineerFeedback] = None
    safety_acknowledged: bool = False
    rollback_plan: str = ""
    executed: bool = False
    executed_at: float = 0.0
    result: str = ""

    def to_dict(self) -> dict:
        rec_dict = {}
        if self.recommendation is not None and hasattr(self.recommendation, "to_dict"):
            rec_dict = self.recommendation.to_dict()
        return {
            "recommendation": rec_dict,
            "authorization": self.authorization.to_dict() if self.authorization else {},
            "safety_acknowledged": self.safety_acknowledged,
            "rollback_plan": self.rollback_plan,
            "executed": self.executed,
            "executed_at": self.executed_at,
            "result": self.result,
        }

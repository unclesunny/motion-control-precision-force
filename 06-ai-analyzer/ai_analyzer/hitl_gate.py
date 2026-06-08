"""
HITL Safety Gate — Free shell.

Pro license required for the full Human-in-the-Loop safety gate with
classification (safe/actionable/ambiguous), prompt generation, feedback
processing, and authorization workflows.

This stub classifies all annotations as "safe" (no engineer interaction needed).
"""

from typing import List, Optional

try:
    from .hitl_types import EngineerPrompt, EngineerFeedback, AuthorizedAction
except ImportError:
    from hitl_types import EngineerPrompt, EngineerFeedback, AuthorizedAction


class HITLGate:
    """HITL safety gate (Pro license required for full authorization pipeline)."""

    def __init__(self, brand: str = None, llm_refiner=None,
                 enable_llm: bool = False):
        self.brand = brand
        self._prompts: dict = {}
        self._feedback_history: list = []
        self._authorized_actions: list = []
        self._rejected_actions: list = []
        self.llm_available = False

    def classify(self, annotation) -> str:
        """Always returns 'safe' — Pro license required for real classification."""
        return "safe"

    def generate_prompts(self, annotations: list) -> List[EngineerPrompt]:
        """Returns empty — Pro license required for prompt generation."""
        return []

    def get_prompt(self, prompt_id: str) -> Optional[EngineerPrompt]:
        return self._prompts.get(prompt_id)

    def process_feedback(self, prompt_id: str, feedback: EngineerFeedback) -> list:
        """Returns empty — Pro license required for feedback processing."""
        self._feedback_history.append(feedback)
        return []

    def authorize(self, recommendations: list, feedback: EngineerFeedback) -> list:
        """Returns empty — Pro license required for authorization."""
        return []

    def get_authorized_actions(self) -> list:
        return self._authorized_actions

    def get_rejected_actions(self) -> list:
        return self._rejected_actions

    def get_history(self) -> list:
        return self._feedback_history

    @property
    def pending_count(self) -> int:
        return 0

    @property
    def pending_prompts(self) -> list:
        return []

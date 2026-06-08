"""
LLM Diagnosis Refiner — Free shell.

Pro license required for the full Claude API-driven three-tier diagnosis
refinement (LLM → keyword → generic fallback) with parts replacement and
parameter compensation suggestions.
"""


class LLMDiagnosisRefiner:
    """LLM diagnosis refiner (Pro license required)."""

    def __init__(self, api_key: str = None):
        self.available = False

    def refine(self, annotation, feedback_text: str = "") -> dict:
        """Returns empty — Pro license required for LLM refinement."""
        return {
            "message": "Pro license required for LLM diagnosis refinement.",
            "category": "",
            "severity": "info",
            "parts": [],
            "parameter_compensation": [],
        }

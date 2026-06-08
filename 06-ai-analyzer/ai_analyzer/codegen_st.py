"""
CODESYS ST Code Generator — Free shell.

Pro license required for automated generation of FB_ServoDiag, FB_ServoTune,
and DUT_ServoDiag ST code from AI annotations and parameter recommendations.
"""


class CodegenST:
    """CODESYS Structured Text code generator (Pro license required)."""

    def __init__(self, brand: str = None):
        self.brand = brand or "default"

    def export_all(self, output_dir: str, annotations: list,
                   recommendations: list) -> dict:
        """Returns empty — Pro license required for code generation."""
        return {}

    def generate_fb_diag(self, annotations: list) -> str:
        """Returns empty string."""
        return "(* Pro license required for FB_ServoDiag generation *)"

    def generate_fb_tune(self, recommendations: list) -> str:
        """Returns empty string."""
        return "(* Pro license required for FB_ServoTune generation *)"

    def generate_dut(self) -> str:
        """Returns empty string."""
        return "(* Pro license required for DUT generation *)"

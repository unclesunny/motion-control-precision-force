"""Unit tests for CODESYS ST Code Generator."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from analyzer_base import AIAnnotation
from codegen_st import CodegenST
from parameter_recommender import ParameterRecommendation


class TestCodegenST:
    """Test ST code generation."""

    @pytest.fixture
    def gen(self):
        return CodegenST(brand="delta-a3")

    @pytest.fixture
    def sample_annotations(self):
        return [
            AIAnnotation(timestamp=0, channel="Current",
                        category="current_saturation", severity="critical",
                        confidence=0.98, message="Current 250%", value=250.0),
            AIAnnotation(timestamp=0, channel="Current",
                        category="current_wear", severity="warning",
                        confidence=0.85, message="CUSUM drift", value=160.0),
            AIAnnotation(timestamp=0, channel="Foll.Err",
                        category="tracking_gain_deficiency", severity="warning",
                        confidence=0.9, message="Gain low", value=500.0),
        ]

    @pytest.fixture
    def sample_recs(self):
        return [
            ParameterRecommendation(
                index=0x610B, subindex=0, name="Notch Filter",
                action="set", target_value=320.0,
                reason="Resonance at 320Hz", safety="Test carefully",
                priority=1, triggered_by="resonance_detected",
            ),
            ParameterRecommendation(
                index=0x60FB, subindex=0, name="Position Gain",
                action="increase", step_pct=25,
                reason="Gain too low", safety="Watch oscillation",
                priority=1, triggered_by="tracking_gain_deficiency",
            ),
        ]

    # ── FB_ServoDiag ───────────────────────────────────

    def test_generate_fb_diag_structure(self, gen, sample_annotations):
        """Generated FB has required ST structural elements."""
        code = gen.generate_fb_diag(sample_annotations)
        assert "FUNCTION_BLOCK" in code
        assert "VAR_INPUT" in code
        assert "VAR_OUTPUT" in code
        assert "END_VAR" in code
        assert "IF NOT bEnable THEN" in code
        assert "iFaultCode" in code
        assert "bAlarm" in code
        assert "bOperatorConfirmed" in code  # HITL gate

    def test_generate_fb_diag_detection_blocks(self, gen, sample_annotations):
        """Each annotation category generates a detection block."""
        code = gen.generate_fb_diag(sample_annotations)
        for ann in sample_annotations:
            safe_name = gen._safe_var_name(ann.category)
            assert f"i{safe_name}Cnt" in code, f"Missing counter for {ann.category}"

    def test_generate_fb_diag_fault_aggregation(self, gen, sample_annotations):
        """Fault aggregation uses IF-ELSIF chain with priority."""
        code = gen.generate_fb_diag(sample_annotations)
        assert "iFaultCode :=" in code
        assert "ELSIF" in code

    def test_generate_fb_diag_empty(self, gen):
        """Empty annotations produce valid FB shell."""
        code = gen.generate_fb_diag([])
        assert "FUNCTION_BLOCK" in code
        assert "VAR_INPUT" in code

    def test_generate_fb_diag_custom_name(self, gen, sample_annotations):
        """Custom FB name is used."""
        code = gen.generate_fb_diag(sample_annotations, fb_name="FB_MyDiag")
        assert "FB_MyDiag" in code

    # ── FB_ServoTune ────────────────────────────────────

    def test_generate_fb_tune_structure(self, gen, sample_recs):
        """Tune FB has state machine and authorization gate."""
        code = gen.generate_fb_tune(sample_recs)
        assert "FUNCTION_BLOCK" in code
        assert "bAuthorized" in code
        assert "bExecute" in code
        assert "CASE iStep OF" in code
        assert "iStep := 0" in code or "iStep  := 0" in code  # idle state

    def test_generate_fb_tune_authorization_gate(self, gen, sample_recs):
        """Authorization must be TRUE before execution."""
        code = gen.generate_fb_tune(sample_recs)
        assert "bAuthorized AND bExecuteRising" in code

    def test_generate_fb_tune_empty(self, gen):
        """Empty recs produce valid shell."""
        code = gen.generate_fb_tune([])
        assert "FUNCTION_BLOCK" in code

    # ── DUT ─────────────────────────────────────────────

    def test_generate_dut(self, gen):
        """DUT contains enumeration types."""
        code = gen.generate_dut()
        assert "TYPE E_ServoFault" in code
        assert "TYPE E_HITLState" in code
        assert "TYPE ST_ServoSession" in code
        assert "eFault_None" in code
        assert "eHITL_Pending" in code
        assert "eHITL_Approved" in code

    # ── Export ──────────────────────────────────────────

    def test_export_all_creates_files(self, gen, sample_annotations, sample_recs):
        """export_all writes ST files to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            files = gen.export_all(tmp, sample_annotations, sample_recs)
            # Versioned filenames: DUT_ServoDiag_v1.st, FB_ServoDiag_v1.st, FB_ServoTune_v1.st
            assert any("DUT_ServoDiag_v" in k for k in files)
            assert any("FB_ServoDiag_v" in k for k in files)
            assert any("FB_ServoTune_v" in k for k in files)

            for name in files:
                path = os.path.join(tmp, name)
                assert os.path.exists(path), f"{path} not found"
                assert os.path.getsize(path) > 100

    def test_export_all_no_annotations(self, gen):
        """export_all without annotations only creates DUT (versioned)."""
        with tempfile.TemporaryDirectory() as tmp:
            files = gen.export_all(tmp, annotations=None, recommendations=None)
            assert any("DUT_ServoDiag_v" in k for k in files)
            assert not any("FB_ServoDiag_v" in k for k in files)
            assert not any("FB_ServoTune_v" in k for k in files)

    def test_export_all_versioning_no_overwrite(self, gen, sample_annotations):
        """Multiple exports create incremented versions, never overwrite."""
        with tempfile.TemporaryDirectory() as tmp:
            files1 = gen.export_all(tmp, sample_annotations, [])
            files2 = gen.export_all(tmp, sample_annotations, [])
            files3 = gen.export_all(tmp, sample_annotations, [])
            # Each run creates new versioned files
            all_names = list(files1.keys()) + list(files2.keys()) + list(files3.keys())
            # v1, v2, v3 should all exist
            assert any("_v1.st" in n for n in all_names)
            assert any("_v2.st" in n for n in all_names)
            assert any("_v3.st" in n for n in all_names)
            # All 6 files should exist on disk
            for files in [files1, files2, files3]:
                for name, content in files.items():
                    path = os.path.join(tmp, name)
                    assert os.path.exists(path), f"{path} missing"
            # Total files on disk = 6 (3 DUTs + 3 FBs)
            st_files = [f for f in os.listdir(tmp) if f.endswith('.st')]
            assert len(st_files) == 6, f"Expected 6 versioned files, got {len(st_files)}: {st_files}"

    # ── Helpers ──────────────────────────────────────────

    def test_safe_var_name(self, gen):
        """Category names map to valid CODESYS identifiers."""
        assert gen._safe_var_name("current_saturation") == "CurrentSaturation"
        assert gen._safe_var_name("tracking_gain_deficiency") == "TrackingGainDeficiency"
        assert gen._safe_var_name("current_wear") == "CurrentWear"

    def test_channel_to_var(self, gen):
        """Channel names map to CODESYS variable names."""
        assert "Current" in gen._channel_to_var("Current") or "iActualCurrent" == gen._channel_to_var("Current")
        assert gen._channel_to_var("Velocity") == "iActualVelocity"
        assert gen._channel_to_var("Foll.Err") == "iFollowingError"

    def test_header_includes_brand(self, gen):
        """Header comment includes brand info."""
        header = gen._header("Test", "desc")
        assert "delta-a3" in header
        assert "Test" in header

    def test_generate_cli_export(self, gen, sample_annotations, sample_recs):
        """Combined export contains all three sections."""
        code = gen.generate_cli_export(sample_annotations, sample_recs)
        assert "TYPE E_ServoFault" in code
        assert "FB_ServoDiag" in code
        assert "FB_ServoTune" in code

    # ── Edge cases ───────────────────────────────────────

    def test_all_categories_generate_valid_code(self, gen):
        """Every anomaly category produces valid ST."""
        categories = [
            "current_saturation", "current_sensor_fault", "current_wear",
            "tracking_absolute_limit", "tracking_mechanical_bind",
            "tracking_gain_deficiency", "resonance_detected",
            "resonance_harmonic", "current_ripple", "velocity_ripple",
            "system_overload",
        ]
        anns = [
            AIAnnotation(timestamp=0, channel="Current", category=cat,
                        severity="warning", confidence=0.8,
                        message=f"Test {cat}", value=100.0)
            for cat in categories
        ]
        code = gen.generate_fb_diag(anns)
        # Should not crash
        assert "FUNCTION_BLOCK" in code
        # Each category gets a counter
        for cat in categories:
            safe_name = gen._safe_var_name(cat)
            assert f"i{safe_name}Cnt" in code or f"b{safe_name}Detected" in code

    def test_wear_category_sorted_by_severity(self, gen):
        """Critical faults appear before warnings in IF-ELSIF chain."""
        anns = [
            AIAnnotation(timestamp=0, channel="Current",
                        category="current_wear", severity="warning",
                        confidence=0.8, message="Wear", value=100.0),
            AIAnnotation(timestamp=0, channel="Current",
                        category="current_saturation", severity="critical",
                        confidence=0.98, message="Sat", value=250.0),
        ]
        code = gen.generate_fb_diag(anns)
        # Critical should come first in the IF-ELSIF
        sat_pos = code.find("CurrentSaturationCnt >= iDebounceLimit")
        wear_pos = code.find("CurrentWearCnt >= iDebounceLimit")
        assert sat_pos < wear_pos, "Critical saturation should appear before warning wear"

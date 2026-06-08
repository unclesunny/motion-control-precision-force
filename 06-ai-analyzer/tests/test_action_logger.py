"""Unit tests for ActionLogger — audit trail system."""

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))

from action_logger import ActionLogger
from hitl_types import AuthorizedAction, EngineerFeedback, EngineerPrompt
from parameter_recommender import ParameterRecommendation


class TestActionLoggerBasic:
    """Test basic logging and event recording."""

    @pytest.fixture
    def logger(self):
        return ActionLogger(session_id="test-session", brand="delta-a3")

    def test_session_metadata(self, logger):
        """Session start is logged automatically."""
        report = logger.export_session()
        assert report["session"]["session_id"] == "test-session"
        assert report["session"]["brand"] == "delta-a3"
        assert report["session"]["start_time"] > 0

    def test_log_prompt(self, logger):
        """Prompt logging records all fields."""
        prompt = EngineerPrompt(
            category="current_wear",
            classification="ambiguous",
            question="Check coupling",
            context="Current drift from 80% to 160%",
            suggested_checks=["check coupling", "check bearing"],
            expected_modalities=["text", "image", "audio"],
            urgency="soon",
        )
        logger.log_prompt(prompt)
        report = logger.export_session()
        assert report["summary"]["prompts_issued"] == 1
        assert report["summary"]["total_events"] >= 2  # session_start + prompt

    def test_log_feedback(self, logger):
        """Feedback logging records authorization and media."""
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            response_text="Coupling has rubber dust",
            media_paths=["/tmp/photo.jpg"],
            authorization="approved",
            authorized_by="engineer-zhang",
        )
        logger.log_feedback(feedback)
        report = logger.export_session()
        assert report["summary"]["feedbacks_received"] == 1
        assert report["summary"]["actions_authorized"] == 0  # not yet authorized

    def test_log_authorized_action(self, logger):
        """Authorized action logging records the recommendation."""
        rec = ParameterRecommendation(
            index=0x610B, subindex=0, name="Notch Filter",
            action="set", target_value=320.0, reason="Resonance",
            safety="Test carefully", priority=1, triggered_by="resonance_detected",
        )
        auth = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="approved",
            authorized_by="engineer-zhang",
        )
        action = AuthorizedAction(
            recommendation=rec,
            authorization=auth,
            safety_acknowledged=True,
            rollback_plan="Restore original notch frequency",
            executed=True,
            result="OK",
        )
        logger.log_authorized(action)
        report = logger.export_session()
        assert report["summary"]["actions_authorized"] == 1

    def test_log_rejected(self, logger):
        """Rejected recommendations are tracked."""
        rec = ParameterRecommendation(
            index=0x60FB, action="increase", reason="Improve tracking",
            safety="Watch for oscillation",
        )
        feedback = EngineerFeedback(
            prompt_id="hitl-test",
            authorization="rejected",
            authorized_by="engineer-li",
            notes="Already at stability limit",
        )
        logger.log_rejected(rec, feedback, "Engineer says already at limit")
        report = logger.export_session()
        assert report["summary"]["actions_rejected"] == 1

    def test_log_annotation(self, logger):
        """AI annotations are loggable."""
        from analyzer_base import AIAnnotation

        ann = AIAnnotation(
            timestamp=time.time(), channel="Current",
            category="current_wear", severity="warning",
            confidence=0.9, message="Gradual drift detected",
            value=160.0,
        )
        logger.log_annotation(ann)
        report = logger.export_session()
        # Annotation logged but doesn't change summary counters
        assert report["summary"]["total_events"] >= 2

    def test_log_custom_event(self, logger):
        """Custom events can be logged with arbitrary data."""
        logger.log_event("parameter_written", {
            "index": "0x610B",
            "value": 320.0,
            "result": "OK",
        })
        report = logger.export_session()
        assert report["summary"]["total_events"] >= 2


class TestActionLoggerExport:
    """Test session export and persistence."""

    @pytest.fixture
    def logger(self):
        return ActionLogger(session_id="export-test")

    def test_export_structure(self, logger):
        """Export returns complete session structure."""
        report = logger.export_session()
        assert "session" in report
        assert "summary" in report
        assert "events" in report
        assert isinstance(report["events"], list)

    def test_export_summary_counts(self, logger):
        """Summary counters are accurate."""
        for i in range(3):
            prompt = EngineerPrompt(
                category="current_wear",
                classification="ambiguous",
                question=f"Test {i}",
            )
            logger.log_prompt(prompt)

        for i in range(2):
            feedback = EngineerFeedback(
                prompt_id=f"hitl-{i}",
                authorization="approved" if i == 0 else "rejected",
                authorized_by="test",
            )
            logger.log_feedback(feedback)

        # Authorize one, reject one
        rec = ParameterRecommendation(index=0x610B, action="set")
        auth_fb = EngineerFeedback(prompt_id="hitl-0", authorization="approved", authorized_by="test")
        action = AuthorizedAction(recommendation=rec, authorization=auth_fb)
        logger.log_authorized(action)

        rec2 = ParameterRecommendation(index=0x60FB, action="increase")
        rej_fb = EngineerFeedback(prompt_id="hitl-1", authorization="rejected", authorized_by="test")
        logger.log_rejected(rec2, rej_fb, "Not needed")

        report = logger.export_session()
        s = report["summary"]
        assert s["prompts_issued"] == 3
        assert s["feedbacks_received"] == 2
        assert s["actions_authorized"] == 1
        assert s["actions_rejected"] == 1
        assert s["authorization_rate"] == 0.5  # 1 authorized, 1 rejected
        assert s["total_events"] >= 6  # session_start + 3 prompts + 2 feedbacks + 1 action

    def test_save_to_file(self, logger):
        """Session can be saved to a JSON file."""
        prompt = EngineerPrompt(category="current_wear", question="Test")
        logger.log_prompt(prompt)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = logger.save(str(Path(tmpdir) / "test_log.json"))
            assert Path(filepath).exists()

            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["session"]["session_id"] == "export-test"
            assert data["summary"]["prompts_issued"] == 1

    def test_save_default_path(self, logger):
        """Default save path creates logs/ directory."""
        import os
        cwd = os.getcwd()
        try:
            filepath = logger.save()
            assert Path(filepath).exists()
            assert "logs" in filepath
            assert "hitl_export-test.json" in filepath
        finally:
            # Cleanup
            log_file = Path(filepath)
            if log_file.exists():
                log_file.unlink()
            log_dir = log_file.parent
            if log_dir.exists() and log_dir.name == "logs":
                try:
                    log_dir.rmdir()
                except OSError:
                    pass

    def test_summary_string(self, logger):
        """summary() returns human-readable string."""
        s = logger.summary()
        assert "export-test" in s
        assert "Prompts issued" in s
        assert "Authorization rate" in s


class TestActionLoggerEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def logger(self):
        return ActionLogger()

    def test_empty_session_export(self, logger):
        """Empty session exports without error."""
        report = logger.export_session()
        assert report["summary"]["total_events"] == 1  # session_start only
        assert report["summary"]["prompts_issued"] == 0
        assert report["summary"]["authorization_rate"] == 0.0  # 0/1 rounds to 0

    def test_reset_clears_entries(self, logger):
        """Reset clears all entries and starts new session."""
        prompt = EngineerPrompt(category="test", question="Test")
        logger.log_prompt(prompt)

        logger.reset()
        report = logger.export_session()
        assert report["summary"]["total_events"] == 1  # new session_start
        assert report["summary"]["prompts_issued"] == 0

    def test_export_is_json_serializable(self, logger):
        """Exported session is JSON-serializable."""
        prompt = EngineerPrompt(
            category="current_wear",
            classification="ambiguous",
            question="Test",
            suggested_checks=["check 1"],
        )
        logger.log_prompt(prompt)

        report = logger.export_session()
        # Should not raise
        json_str = json.dumps(report, ensure_ascii=False, default=str)
        assert len(json_str) > 0

    def test_feedback_with_empty_fields(self, logger):
        """Feedback with minimal fields logs without error."""
        feedback = EngineerFeedback()
        logger.log_feedback(feedback)
        report = logger.export_session()
        assert report["summary"]["feedbacks_received"] == 1

    def test_prompt_with_no_checks(self, logger):
        """Prompt without suggested_checks logs fine."""
        prompt = EngineerPrompt(category="test", classification="safe")
        logger.log_prompt(prompt)
        report = logger.export_session()
        assert report["summary"]["prompts_issued"] == 1

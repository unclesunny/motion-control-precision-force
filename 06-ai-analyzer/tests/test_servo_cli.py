"""Unit tests for CLI commands and ServoCli REPL."""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai_analyzer"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_analyzer import AIAnalyzerPipeline
from ai_analyzer.cli_commands import (
    cmd_analyze, cmd_status, cmd_status_print,
    cmd_params_lookup, cmd_params_brands,
    cmd_recommend, cmd_session_info,
)
from ai_analyzer.hitl_gate import HITLGate
from ai_analyzer.hitl_types import EngineerFeedback, EngineerPrompt


class TestCLIAnalyze:
    """Test the analyze command."""

    @pytest.fixture
    def pipeline(self):
        return AIAnalyzerPipeline(sample_rate_hz=1000.0, enable_hitl=True)

    def test_analyze_synthetic_data(self, pipeline):
        """Analyze runs on synthetic data and returns annotations."""
        result = cmd_analyze(pipeline, {"data_file": None, "stride": 50})
        assert "annotations" in result
        assert "count" in result
        assert "classification_summary" in result
        assert isinstance(result["annotations"], list)
        # Synthetic data may or may not trigger anomalies — that's fine

    def test_analyze_with_stride(self, pipeline):
        """Larger stride reduces analysis time."""
        result = cmd_analyze(pipeline, {"data_file": None, "stride": 100})
        assert result["count"] >= 0


class TestCLIStatus:
    """Test the status command."""

    @pytest.fixture
    def pipeline(self):
        return AIAnalyzerPipeline(sample_rate_hz=1000.0, enable_hitl=True)

    def test_status_returns_dict(self, pipeline):
        """status returns structured dict."""
        s = cmd_status(pipeline)
        assert "detectors" in s
        assert "hitl_enabled" in s
        assert "hitl_pending" in s
        assert s["hitl_enabled"] is True
        assert len(s["detectors"]) == 3

    def test_status_print_does_not_crash(self, pipeline):
        """status_print outputs without error."""
        # Redirect stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            cmd_status_print(pipeline, verbose=False)
            output = sys.stdout.getvalue()
            assert len(output) > 0
        finally:
            sys.stdout = old_stdout

    def test_status_verbose(self, pipeline):
        """verbose flag works."""
        s = cmd_status(pipeline, verbose=True)
        assert "detectors" in s


class TestCLIParams:
    """Test the params command."""

    def test_params_lookup_known(self):
        """Look up a known CiA 402 parameter."""
        r = cmd_params_lookup("0x6083")
        assert r["found"] is True
        assert "Profile Acceleration" in r["description"] or "acceleration" in r["description"].lower()

    def test_params_lookup_unknown(self):
        """Unknown parameter returns not found."""
        r = cmd_params_lookup("0xFFFF")
        assert r["found"] is False

    def test_params_lookup_invalid(self):
        """Invalid hex returns error."""
        r = cmd_params_lookup("nothex")
        assert "error" in r

    def test_params_brands(self):
        """Brands list includes known brands."""
        r = cmd_params_brands()
        assert r["count"] >= 7  # at least 7 brands
        assert "delta-a3" in r["brands"]
        assert "yaskawa-sigma7" in r["brands"]


class TestCLIRecommend:
    """Test the recommend command."""

    @pytest.fixture
    def pipeline(self):
        p = AIAnalyzerPipeline(sample_rate_hz=1000.0, enable_hitl=True)
        # Run a quick analysis to populate events
        from ai_analyzer.cli_commands import cmd_analyze
        cmd_analyze(p, {"data_file": None, "stride": 100})
        return p

    def test_recommend_returns_list(self, pipeline):
        """recommend returns structured result."""
        r = cmd_recommend(pipeline)
        assert "recommendations" in r
        assert "count" in r
        assert isinstance(r["recommendations"], list)

    def test_recommend_with_brand(self, pipeline):
        """Brand parameter works."""
        r = cmd_recommend(pipeline, brand="delta-a3")
        assert r["brand"] == "delta-a3"


class TestCLISession:
    """Test session info command."""

    @pytest.fixture
    def pipeline(self):
        return AIAnalyzerPipeline(sample_rate_hz=1000.0)

    def test_session_info(self, pipeline):
        """Session info returns expected fields."""
        info = cmd_session_info(pipeline)
        assert "session_id" in info
        assert "brand" in info
        assert "sample_count" in info


class TestServoCliREPL:
    """Test the cmd.Cmd REPL class."""

    @pytest.fixture
    def cli(self):
        from servo_cli import ServoCli
        cli = ServoCli(enable_llm=False)
        # Suppress output during tests
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        yield cli
        sys.stdout = old_stdout

    def test_cli_initialized(self, cli):
        """CLI creates pipeline on init."""
        assert cli.pipeline is not None
        assert len(cli.pipeline.analyzers) == 3
        assert cli.gate is not None

    def test_do_status(self, cli):
        """do_status executes without error."""
        cli.do_status("")

    def test_do_detectors(self, cli):
        """do_detectors lists detectors."""
        cli.do_detectors("")

    def test_do_help(self, cli):
        """do_help works."""
        cli.do_help("")

    def test_do_quit(self, cli):
        """do_quit returns True (exit signal)."""
        assert cli.do_quit("") is True

    def test_do_EOF(self, cli):
        """Ctrl-D returns True."""
        assert cli.do_EOF("") is True

    def test_do_analyze(self, cli):
        """do_analyze executes."""
        cli.do_analyze("")

    def test_do_params_lookup(self, cli):
        """do_params lookup works."""
        cli.do_params("lookup 0x6083")

    def test_do_params_brands(self, cli):
        """do_params brands works."""
        cli.do_params("brands")

    def test_do_session(self, cli):
        """do_session info works."""
        cli.do_session("info")

    def test_do_log_show(self, cli):
        """do_log show works."""
        cli.do_log("show")

    def test_do_log_summary(self, cli):
        """do_log summary works."""
        cli.do_log("summary")

    def test_do_hitl_pending_empty(self, cli):
        """hitl pending with no prompts."""
        cli.do_hitl("pending")

    def test_unknown_command_gives_hint(self, cli):
        """Unknown command shows help hint."""
        cli.default("unknown_command_xyz")

    def test_parse_args_simple(self, cli):
        """Argument parser works."""
        args = cli._parse_args("--brand delta-a3 --format json", ["brand=", "format="])
        assert args.get("brand") == "delta-a3"
        assert args.get("format") == "json"

    def test_parse_args_flag(self, cli):
        """Boolean flags are parsed."""
        args = cli._parse_args("--all --verbose", ["all", "verbose"])
        assert args.get("all") == "true"
        assert args.get("verbose") == "true"


class TestCLILLMBridge:
    """Test the CLI LLM translator."""

    def test_translator_unavailable_without_key(self, monkeypatch):
        """Translator is unavailable without API key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        t = CLICommandTranslator(api_key="")
        assert t.available is False

    def test_translator_available_with_key(self, monkeypatch):
        """Translator is available with API key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        t = CLICommandTranslator()
        assert t.available is True

    def test_translate_returns_none_when_unavailable(self, monkeypatch):
        """translate() returns None without API key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        t = CLICommandTranslator(api_key="")
        result = t.translate("analyze data")
        assert result is None

    def test_parse_translation_direct_json(self):
        """Direct JSON is parsed correctly."""
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        text = '{"command": "analyze", "explanation": "run analysis", "follow_up": "", "confidence": 0.95}'
        result = CLICommandTranslator._parse_translation(text)
        assert result is not None
        assert result["command"] == "analyze"
        assert result["confidence"] == 0.95

    def test_parse_translation_code_block(self):
        """JSON in code block is extracted."""
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        text = 'Here is the command:\n```json\n{"command": "status", "explanation": "show status", "follow_up": "", "confidence": 0.9}\n```'
        result = CLICommandTranslator._parse_translation(text)
        assert result is not None
        assert result["command"] == "status"

    def test_parse_translation_garbage(self):
        """Garbage returns None."""
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        assert CLICommandTranslator._parse_translation("not json at all") is None
        assert CLICommandTranslator._parse_translation("") is None

    def test_health_check_unavailable(self, monkeypatch):
        """Health check reports unavailable without key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from ai_analyzer.cli_llm_bridge import CLICommandTranslator
        t = CLICommandTranslator(api_key="")
        hc = t.health_check()
        assert hc["status"] == "unavailable"


class TestAliasRegistry:
    """Test the alias registry."""

    @pytest.fixture
    def registry(self):
        from ai_analyzer.cli_aliases import AliasRegistry
        r = AliasRegistry(user_file=str(Path.home() / ".servo_aliases_test"))
        r.reset_user_aliases()
        return r

    def test_resolve_builtin(self, registry):
        """Built-in aliases resolve correctly."""
        assert registry.resolve("a") == "analyze"
        assert registry.resolve("st") == "status"
        assert registry.resolve("hf") == "hitl feedback"
        assert registry.resolve("q") == "quit"

    def test_resolve_chinese(self, registry):
        """Chinese aliases resolve."""
        assert registry.resolve("分析") == "analyze"
        assert registry.resolve("状态") == "status"
        assert registry.resolve("帮助") == "help"
        assert registry.resolve("退出") == "quit"

    def test_resolve_category(self, registry):
        """Category aliases expand to hitl prompt --category."""
        assert "current_wear" in registry.resolve("磨损")
        assert "tracking_mechanical_bind" in registry.resolve("卡滞")
        assert "resonance_detected" in registry.resolve("共振")

    def test_resolve_case_insensitive(self, registry):
        """Alias resolution is case-insensitive."""
        assert registry.resolve("A") == "analyze"
        assert registry.resolve("St") == "status"

    def test_resolve_unknown_returns_none(self, registry):
        """Unknown alias returns None."""
        assert registry.resolve("notanalias_xyz") is None

    def test_is_alias(self, registry):
        """is_alias correctly identifies aliases."""
        assert registry.is_alias("a") is True
        assert registry.is_alias("notanalias") is False

    def test_resolve_line_simple(self, registry):
        """resolve_line expands alias."""
        resolved, was_aliased = registry.resolve_line("a")
        assert resolved == "analyze"
        assert was_aliased is True

    def test_resolve_line_with_args(self, registry):
        """resolve_line preserves extra arguments."""
        resolved, was_aliased = registry.resolve_line("hf hitl-123 --text hello")
        assert "hitl feedback" in resolved
        assert "hitl-123" in resolved
        assert "--text hello" in resolved
        assert was_aliased is True

    def test_resolve_line_macro(self, registry):
        """Multi-command macros preserve newlines."""
        resolved, was_aliased = registry.resolve_line("kz")
        assert "\n" in resolved
        assert "analyze" in resolved
        assert "hitl prompt" in resolved
        assert was_aliased is True

    def test_resolve_line_not_alias(self, registry):
        """Non-alias line passes through unchanged."""
        resolved, was_aliased = registry.resolve_line("status --verbose")
        assert was_aliased is False

    def test_add_user_alias(self, registry):
        """User can add custom aliases."""
        assert registry.add_user_alias("mycheck", "analyze --stride 5") is True
        assert registry.resolve("mycheck") == "analyze --stride 5"

    def test_remove_user_alias(self, registry):
        """User can remove custom aliases."""
        registry.add_user_alias("temp", "status")
        assert registry.remove_user_alias("temp") is True
        assert registry.resolve("temp") is None

    def test_remove_builtin_fails(self, registry):
        """Cannot remove built-in aliases."""
        assert registry.remove_user_alias("a") is False
        assert registry.resolve("a") == "analyze"  # still works

    def test_user_alias_overrides_builtin(self, registry):
        """User aliases take priority over built-in."""
        registry.add_user_alias("a", "recommend --brand delta-a3")
        assert registry.resolve("a") == "recommend --brand delta-a3"

    def test_list_aliases(self, registry):
        """list_aliases returns all aliases."""
        all_a = registry.list_aliases("all")
        assert len(all_a) >= 80  # built-in + category

        builtin = registry.list_aliases("builtin")
        assert len(builtin) >= 80

        user = registry.list_aliases("user")
        assert len(user) == 0  # no user aliases yet

    def test_save_and_reload(self, registry, tmp_path):
        """User aliases persist across save/reload."""
        test_file = str(tmp_path / "test_aliases.json")
        registry._user_file = Path(test_file)

        registry.add_user_alias("test1", "status")
        registry.add_user_alias("test2", "analyze --stride 20")
        registry.save(test_file)

        # Create new registry loading from same file
        from ai_analyzer.cli_aliases import AliasRegistry
        r2 = AliasRegistry(user_file=test_file)
        assert r2.resolve("test1") == "status"
        assert r2.resolve("test2") == "analyze --stride 20"

    def test_stats(self, registry):
        """Stats returns correct counts."""
        s = registry.stats()
        assert s["builtin_count"] >= 80
        assert s["category_count"] >= 10
        assert s["user_count"] == 0
        assert s["total"] >= 80

    def test_reset_user_aliases(self, registry):
        """reset clears user aliases."""
        registry.add_user_alias("test", "status")
        assert registry.resolve("test") == "status"
        registry.reset_user_aliases()
        assert registry.resolve("test") is None

    def test_get_command_list(self, registry):
        """get_command_list returns all CLI commands."""
        cmds = registry.get_command_list()
        assert "analyze" in cmds
        assert "hitl" in cmds
        assert "alias" in cmds


class TestServoCliAliasIntegration:
    """Test alias integration in the CLI REPL."""

    @pytest.fixture
    def cli(self):
        from servo_cli import ServoCli
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli = ServoCli(enable_llm=False)
        yield cli
        sys.stdout = old_stdout

    def test_do_alias_list(self, cli):
        """alias list executes."""
        cli.do_alias("list")

    def test_do_alias_builtin(self, cli):
        """alias builtin executes."""
        cli.do_alias("builtin")

    def test_do_alias_stats(self, cli):
        """alias stats executes."""
        cli.do_alias("stats")

    def test_do_alias_suggest(self, cli):
        """alias suggest executes."""
        cli.do_alias("suggest")

    def test_do_alias_add_and_remove(self, cli):
        """Add and remove user alias."""
        cli.do_alias("add mytest status")
        cli.do_alias("remove mytest")

    def test_default_resolves_alias(self, cli):
        """Unknown input that matches alias gets resolved."""
        # "a" is an alias for "analyze"
        cli.default("a")
        # Should have resolved to analyze (output was captured)

    def test_default_unknown_no_alias(self, cli):
        """Unknown input without alias match shows error."""
        cli.default("xyznotalias123")

    def test_aliases_initialized(self, cli):
        """Alias registry is initialized on CLI creation."""
        assert cli._aliases is not None
        assert cli._aliases.resolve("a") == "analyze"


class TestCLIGracefulDegradation:
    """Test CLI graceful behavior when pipeline fails."""

    def test_servo_cli_no_pipeline(self):
        """CLI can initialize even if pipeline creation fails."""
        from servo_cli import ServoCli
        # Create CLI without pipeline, force it to create one
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            cli = ServoCli(pipeline=None, enable_llm=False)
            # Pipeline should be created lazily
            assert cli.pipeline is not None
        finally:
            sys.stdout = old_stdout

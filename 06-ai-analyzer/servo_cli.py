#!/usr/bin/env python3
"""
Servo Diagnostic CLI — offline command-line interface for the AI analyzer pipeline.

Supports four modes:
  REPL:        python servo_cli.py
  REPL multi:  python servo_cli.py --axes X,Y,Z
  Single cmd:  python servo_cli.py -c "analyze --axis X"
  Script:      python servo_cli.py --script commands.txt
  Pipe:        echo "status" | python servo_cli.py

All commands work offline. When ANTHROPIC_API_KEY is set, the CLI accepts
natural language input and uses an LLM to translate it to precise commands.

Multi-axis: use --axes X,Y,Z to create per-axis pipelines. Commands accept
--axis <name> or --axis all to scope operations.

Quickstart:
    python servo_cli.py
    servo> help
    servo> analyze
    servo> status --axis all
"""

import argparse
import cmd
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure ai_analyzer package is importable
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

try:
    from ai_analyzer import AIAnalyzerPipeline
    from ai_analyzer.cli_commands import (
        C, _print, _print_annotation,
        cmd_analyze, cmd_analyze_print,
        cmd_hitl_classify, cmd_hitl_prompt, cmd_hitl_prompt_print,
        cmd_hitl_feedback, cmd_hitl_authorize, cmd_hitl_pending,
        cmd_recommend, cmd_recommend_print,
        cmd_params_lookup, cmd_params_brands,
        cmd_log_show, cmd_log_summary, cmd_log_export,
        cmd_status, cmd_status_print, cmd_session_info,
    )
    _CLI_CMDS_AVAILABLE = True
except ImportError as e:
    _CLI_CMDS_AVAILABLE = False
    _CLI_IMPORT_ERROR = str(e)


# ── Color helpers ──────────────────────────────────────────────

def _colored(text: str, color: str = "", bold: bool = False) -> str:
    prefix = C.get(color, "") + (C["bold"] if bold else "")
    return f"{prefix}{text}{C['reset']}"


# ── CLI REPL ───────────────────────────────────────────────────

class ServoCli(cmd.Cmd):
    """Servo Diagnostic CLI — REPL interface to the AI analyzer pipeline.

    Built on Python stdlib cmd.Cmd (zero external dependencies).
    Supports command history via readline when available.

    Multi-axis: pass axis_ids=["X","Y","Z"] to create per-axis pipelines.
    Commands accept --axis <name> or --axis all to scope operations.
    """

    intro = f"""
{C['bold']}{C['C']}+==============================================+
|   Servo Diagnostic CLI v1.1                    |
|   Offline Commands + AI + HITL Collaboration   |
+==============================================+
|   Type {C['Y']}help{C['C']} for commands    {C['Y']}analyze{C['C']} to run    |
|   Type {C['Y']}status{C['C']} for status    {C['Y']}quit{C['C']} to exit     |
|   Multi-axis: {C['Y']}--axis all{C['C']} on any command     |
+==============================================+{C['reset']}
"""

    prompt = _colored("servo> ", "C", bold=True)

    def __init__(self, pipeline=None, brand=None, enable_llm=True,
                 axis_ids: list = None):
        super().__init__()
        self._pipeline = pipeline
        self._brand = brand
        self._enable_llm = enable_llm
        self._translator = None
        self._last_analysis_result = None

        # Multi-axis: per-axis pipelines
        self._axis_ids = axis_ids or []
        self._pipelines: dict = {}  # {axis_id: AIAnalyzerPipeline}
        self._cross_axis = None

        # Alias registry
        from ai_analyzer.cli_aliases import AliasRegistry
        self._aliases = AliasRegistry()

        self._init_pipeline()

    def _init_pipeline(self):
        """Lazy-init the pipeline(s)."""
        if self._axis_ids:
            # Multi-axis: create per-axis pipelines + cross-axis
            for i, aid in enumerate(self._axis_ids):
                try:
                    self._pipelines[aid] = AIAnalyzerPipeline(
                        brand=self._brand, enable_hitl=True,
                        axis_id=aid, slave_position=i,
                    )
                except Exception as e:
                    _print(f"  管线 {aid} 初始化失败: {e}", color="R")
            if len(self._pipelines) >= 2:
                try:
                    from ai_analyzer import CrossAxisAnalyzer
                    self._cross_axis = CrossAxisAnalyzer()
                except Exception:
                    pass
            # Primary pipeline for backwards compat
            self._pipeline = next(iter(self._pipelines.values())) if self._pipelines else None
            if self._pipeline:
                _print(f"  多轴管线就绪: {len(self._pipelines)} 轴 "
                       f"({', '.join(self._pipelines.keys())}), "
                       f"跨轴检测: {'启用' if self._cross_axis else '禁用'}",
                       color="dim")
        else:
            # Single-axis (backwards compat)
            if self._pipeline is None:
                try:
                    self._pipeline = AIAnalyzerPipeline(
                        brand=self._brand, enable_hitl=True)
                    _print(f"  管线就绪: {len(self._pipeline.analyzers)} 检测器, "
                           f"HITL {'启用' if self._pipeline.enable_hitl else '禁用'}",
                           color="dim")
                except Exception as e:
                    _print(f"  管线初始化失败: {e}", color="R")
                    self._pipeline = None

    def _resolve_axis(self, arg: str):
        """Parse --axis flag from command argument string.

        Returns:
            (axis_ids: list|None, remaining_arg: str)
            None axis_ids means "primary axis only" (backwards compat).
            If --axis all → all self._axis_ids.
            If --axis X → ["X"].
        """
        axis_ids = None
        remaining = arg

        # Handle --axis all
        if "--axis all" in arg or "--axis=all" in arg:
            if self._axis_ids:
                axis_ids = list(self._axis_ids)
            remaining = arg.replace("--axis all", "").replace("--axis=all", "").strip()
        else:
            # Handle --axis X
            import re
            m = re.search(r'--axis[= ](\w+)', arg)
            if m:
                requested = m.group(1)
                if self._axis_ids and requested in self._axis_ids:
                    axis_ids = [requested]
                remaining = re.sub(r'--axis[= ]\w+', '', arg).strip()

        return axis_ids, remaining

    def _get_pipelines(self, axis_ids: list = None):
        """Get ordered list of (axis_id, pipeline) for iteration."""
        if axis_ids:
            return [(aid, self._pipelines[aid]) for aid in axis_ids if aid in self._pipelines]
        if self._pipelines:
            return list(self._pipelines.items())
        if self._pipeline:
            return [("", self._pipeline)]
        return []

    @property
    def pipeline(self):
        if self._pipeline is None and not self._pipelines:
            self._init_pipeline()
        return self._pipeline

    @property
    def gate(self):
        p = self.pipeline
        return p.hitl_gate if p else None

    @property
    def logger(self):
        p = self.pipeline
        return p.action_logger if p else None

    @property
    def translator(self):
        """Lazy-init the LLM translator."""
        if self._translator is None and self._enable_llm:
            try:
                from ai_analyzer.cli_llm_bridge import CLICommandTranslator
                self._translator = CLICommandTranslator()
            except Exception:
                pass
        return self._translator

    @property
    def axis_ids(self) -> list:
        return list(self._axis_ids)

    @property
    def cross_axis(self):
        return self._cross_axis

    # ── Command: analyze ───────────────────────────────────

    def do_analyze(self, arg: str):
        """analyze [--data <file>] [--stride <n>] [--axis <name|all>] — 运行 AI 分析"""
        axis_ids, arg = self._resolve_axis(arg)
        args = self._parse_args(arg, ["data=", "stride="])

        for aid, pipeline in self._get_pipelines(axis_ids):
            axis_label = f" [{aid}]" if aid else ""
            _print(f"\n┌─── AI Analysis{axis_label} ───┐", color="C", bold=True)
            result = cmd_analyze_print(pipeline, {
                "data_file": args.get("data"),
                "stride": int(args.get("stride", 10)),
            })
            self._last_analysis_result = result

        # Cross-axis analysis
        if self._cross_axis and len(self._get_pipelines(axis_ids)) >= 2:
            _print(f"\n┌─── Cross-Axis Analysis ───┐", color="M", bold=True)
            try:
                from ai_analyzer import AxisSnapshot
                snapshots = {}
                for aid, pipeline in self._get_pipelines(axis_ids):
                    stats = {}
                    for ann in pipeline.recent_events[-8:]:
                        ch = ann.channel
                        if ch not in stats:
                            stats[ch] = {"fft_peak_magnitude": 0.0}
                    snapshots[aid] = AxisSnapshot(
                        axis_id=aid,
                        slave_position=self._axis_ids.index(aid) if aid in self._axis_ids else -1,
                        values=[0.0]*8,
                        channel_names=["Position","Velocity","Current","Torque",
                                      "Foll.Err","DIO","Status","OpMode"],
                        buffer_stats=stats,
                    )
                cross_anns = self._cross_axis.analyze(snapshots)
                if cross_anns:
                    for a in cross_anns:
                        _print_annotation(a)
                else:
                    _print("  ✓ No cross-axis issues", color="G")
            except Exception:
                pass

    # ── Command: hitl ──────────────────────────────────────

    def do_hitl(self, arg: str):
        """hitl prompt|feedback|authorize|pending|history — HITL 工作流

Subcommands:
  hitl prompt [--all] [--category <c>]  为异常生成工程师提问
  hitl feedback <id> --text "<desc>" --observation "<item>" [--auth approved|rejected|pending]
  hitl authorize <id>                   授权参数修改
  hitl pending                          列出待处理提问
  hitl history                          查看反馈历史
"""
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else ""
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub == "prompt":
            sargs = self._parse_args(sub_args, ["category=", "all"])
            cmd_hitl_prompt_print(
                self.gate, self.pipeline,
                category=sargs.get("category"),
                prompt_all="all" in sub_args or "--all" in sub_args,
            )
        elif sub == "feedback":
            self._hitl_feedback(sub_args)
        elif sub == "authorize":
            prompt_id = sub_args.strip().split()[0] if sub_args.strip() else ""
            if not prompt_id:
                _print("  用法: hitl authorize <prompt-id>", color="R")
                return
            result = cmd_hitl_authorize(self.gate, self.pipeline, prompt_id)
            if result["status"] == "ok":
                _print(f"  ✓ 已授权 {result['count']} 个参数修改", color="G")
            else:
                _print(f"  ✗ {result['message']}", color="R")
        elif sub == "pending":
            result = cmd_hitl_pending(self.gate)
            if result["count"] == 0:
                _print("  无待处理 prompts", color="dim")
            else:
                for p in result["pending"]:
                    _print(f"  [{p['classification']}] {p['prompt_id']} — "
                           f"{p['category']} ({p['urgency']})", color="Y")
        elif sub == "history":
            fb_history = self.gate.get_history() if self.gate else []
            if not fb_history:
                _print("  无反馈历史", color="dim")
            else:
                for f in fb_history[-10:]:
                    _print(f"  [{f.authorization}] {f.prompt_id} — "
                           f"{f.response_text[:80]}", color="dim")
        else:
            _print(f"  未知子命令: {sub}。试试: hitl prompt | feedback | authorize | pending | history", color="R")

    def _hitl_feedback(self, arg: str):
        """Parse and execute hitl feedback."""
        sargs = self._parse_args(arg, ["text=", "observation=", "auth=", "by="])
        prompt_id = arg.split()[0] if arg and not arg.startswith("-") else ""
        if not prompt_id:
            _print("  用法: hitl feedback <prompt-id> --text \"...\" [--observation \"...\"] [--auth approved|rejected|pending]", color="R")
            return

        result = cmd_hitl_feedback(
            self.gate, self.pipeline,
            prompt_id=prompt_id,
            response_text=sargs.get("text", ""),
            observation=sargs.get("observation", ""),
            auth=sargs.get("auth", "pending"),
            authorized_by=sargs.get("by", "cli-user"),
        )

        if result["status"] == "ok":
            auth = result["authorization"]
            icon = {"approved": "✓", "rejected": "✗", "pending": "📤"}.get(auth, "?")
            _print(f"  {icon} 反馈已处理 ({auth})", color="G")
            for a in result.get("refined_annotations", []):
                _print(f"    精化: [{a['category']}] {a['message'][:120]}", color="dim")
        else:
            _print(f"  ✗ {result.get('message', 'Unknown error')}", color="R")

    # ── Command: recommend ─────────────────────────────────

    def do_recommend(self, arg: str):
        """recommend [--brand <name>] [--format table|json] [--axis <name|all>] — 参数建议"""
        axis_ids, arg = self._resolve_axis(arg)
        sargs = self._parse_args(arg, ["brand=", "format="])
        brand = sargs.get("brand") or self._brand
        fmt = sargs.get("format", "table")

        for aid, pipeline in self._get_pipelines(axis_ids):
            axis_label = f"【{aid}】" if aid else ""
            if fmt == "json":
                import json
                result = cmd_recommend(pipeline, brand=brand)
                if axis_label:
                    result["axis_id"] = aid
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                if axis_label:
                    _print(f"\n{axis_label}", color="C", bold=True)
                cmd_recommend_print(pipeline, brand=brand)

    # ── Command: params ────────────────────────────────────

    def do_params(self, arg: str):
        """params lookup <index> | brands — 查询参数或列出品牌"""
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else ""
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub == "lookup":
            idx = sub_args.strip()
            if not idx:
                _print("  用法: params lookup <0x6083>", color="R")
                return
            result = cmd_params_lookup(idx)
            if "error" in result:
                _print(f"  ✗ {result['error']}", color="R")
            else:
                _print(f"  {result['index']} ({result['decimal']}): {result['description']}", color="G" if result["found"] else "Y")
        elif sub == "brands":
            result = cmd_params_brands()
            _print(f"  支持 {result['count']} 个品牌:", color="C")
            for b in result["brands"]:
                _print(f"    • {b}", color="dim")
        else:
            _print("  用法: params lookup <0x6083> | params brands", color="R")

    # ── Command: log ───────────────────────────────────────

    def do_log(self, arg: str):
        """log show|summary|export — 审计日志操作"""
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else "show"
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub == "show" or sub == "":
            sargs = self._parse_args(sub_args, ["last="])
            last = int(sargs.get("last", 10))
            result = cmd_log_show(self.logger, last=last)
            if result["count"] == 0:
                _print("  无日志事件", color="dim")
            else:
                for e in result["events"]:
                    _print(f"  [{e.get('event', '?')}] {e.get('category', e.get('authorization', ''))}", color="dim")
                _print(f"  显示 {result['count']}/{result['total']} 条事件", color="dim")
        elif sub == "summary":
            s = cmd_log_summary(self.logger)
            _print(f"  Prompts: {s.get('prompts_issued', 0)} | Feedbacks: {s.get('feedbacks_received', 0)}", color="C")
            _print(f"  Authorized: {s.get('actions_authorized', 0)} | Rejected: {s.get('actions_rejected', 0)}", color="C")
            _print(f"  Authorization rate: {s.get('authorization_rate', 0):.0%}", color="C")
        elif sub == "export":
            sargs = self._parse_args(sub_args, ["file="])
            path = cmd_log_export(self.logger, sargs.get("file"))
            _print(f"  ✓ 日志已导出: {path}", color="G")
        else:
            _print("  用法: log show | summary | export", color="R")

    # ── Command: status ────────────────────────────────────

    def do_status(self, arg: str):
        """status [--verbose] [--axis <name|all>] — 显示系统状态"""
        axis_ids, arg = self._resolve_axis(arg)
        verbose = "--verbose" in arg or "-v" in arg

        for aid, pipeline in self._get_pipelines(axis_ids):
            axis_label = f"【{aid}】 " if aid else ""
            if axis_label:
                _print(f"\n{axis_label}", color="C", bold=True)
            cmd_status_print(pipeline, verbose=verbose)

        if self._cross_axis and len(self._get_pipelines(axis_ids)) >= 2:
            status = self._cross_axis.status()
            parts = []
            for det, enabled in status["detectors"].items():
                icon = "v" if enabled else "x"
                parts.append(f"{icon} {det}")
            _print(f"  跨轴检测器: {' | '.join(parts)}", color="M")

    # ── Command: detectors ─────────────────────────────────

    def do_detectors(self, arg: str):
        """detectors [--enable <name>] [--disable <name>] — 管理检测器"""
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else ""

        if sub == "--enable" or sub == "-e":
            name = parts[1].strip() if len(parts) > 1 else ""
            if name:
                self.pipeline.enable_analyzer(name)
                _print(f"  ✓ 已启用: {name}", color="G")
        elif sub == "--disable" or sub == "-d":
            name = parts[1].strip() if len(parts) > 1 else ""
            if name:
                self.pipeline.disable_analyzer(name)
                _print(f"  ✓ 已禁用: {name}", color="Y")
        else:
            # List detectors
            for a in self.pipeline.analyzers:
                icon = "✓" if a.enabled else "✗"
                color = "G" if a.enabled else "R"
                _print(f"  {_colored(icon, color)} {a.name}", color="dim")

    # ── Command: session ───────────────────────────────────

    def do_session(self, arg: str):
        """session info|reset|save|load — 会话管理"""
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else "info"

        if sub == "info" or sub == "":
            info = cmd_session_info(self.pipeline)
            _print(f"  Session: {info['session_id']}", color="C")
            _print(f"  Brand: {info['brand'] or 'default'}", color="dim")
            _print(f"  Samples analyzed: {info['sample_count']}", color="dim")
            _print(f"  Recent events: {info['recent_event_count']}", color="dim")
        elif sub == "reset":
            self.pipeline.reset()
            _print("  ✓ 会话已重置", color="G")
        else:
            _print(f"  用法: session info | reset", color="R")

    # ── Command: alias ─────────────────────────────────────

    def do_alias(self, arg: str):
        """alias list|add|remove|builtin|user|save|reload|stats — 管理命令别名

别名让工程师用自己习惯的名字记忆 CLI 命令:
  alias list             列出所有别名 (内置 + 自定义)
  alias builtin          仅列出内置别名
  alias user             仅列出你的自定义别名
  alias add <name> <cmd> 添加自定义别名 (如: alias add kz "analyze\\nhitl prompt --all")
  alias remove <name>    删除自定义别名
  alias save             保存自定义别名到 ~/.servo_aliases
  alias reload           重新从文件加载
  alias stats            别名统计
  alias suggest          查看哪些命令还没有别名

快捷别名示例:
  a     → analyze         分析 → analyze
  st    → status          状态 → status
  hf    → hitl feedback   反馈 → hitl feedback
  kz    → analyze + hitl  快诊 → 一键诊断
"""
        parts = arg.split(maxsplit=2)
        sub = parts[0] if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""
        rest2 = parts[2] if len(parts) > 2 else ""

        if sub == "list" or sub == "ls" or sub == "":
            self._alias_list("all")
        elif sub == "builtin" or sub == "bt":
            self._alias_list("builtin")
        elif sub == "user" or sub == "my":
            self._alias_list("user")
        elif sub == "add" or sub == "a":
            if not rest:
                _print("  用法: alias add <name> <command>", color="R")
                _print("  示例: alias add kz \"analyze\\nhitl prompt --all\"", color="dim")
                return
            cmd = rest2 if rest2 else rest
            name = rest if rest2 else rest.split()[0] if rest else ""
            if self._aliases.add_user_alias(name.strip(), cmd.strip()):
                _print(f"  + alias '{name}' -> '{cmd[:60]}'", color="G")
            else:
                _print(f"  x 添加失败", color="R")
        elif sub == "remove" or sub == "rm" or sub == "del":
            if not rest:
                _print("  用法: alias remove <name>", color="R")
                return
            if self._aliases.remove_user_alias(rest.strip()):
                _print(f"  - alias '{rest}' removed", color="G")
            else:
                _print(f"  x 未找到 '{rest}' (或为内置别名，不可删除)", color="Y")
        elif sub == "save" or sub == "sv":
            path = self._aliases.save()
            _print(f"  saved: {path}", color="G")
        elif sub == "reload" or sub == "rl":
            self._aliases.reload()
            _print(f"  reloaded: {len(self._aliases.get_user_aliases())} user aliases", color="G")
        elif sub == "stats" or sub == "st":
            s = self._aliases.stats()
            _print(f"  builtin: {s['builtin_count']} | category: {s['category_count']} | "
                   f"user: {s['user_count']} | total: {s['total']}", color="C")
            _print(f"  user file: {s['user_file']}", color="dim")
        elif sub == "suggest" or sub == "sg":
            suggestions = self._aliases.get_missing_alias_suggestions()
            if suggestions:
                _print("  暂无别名的命令:", color="Y")
                for s in suggestions:
                    _print(f"    {s}", color="dim")
            else:
                _print("  all commands have aliases", color="G")
        else:
            _print(f"  unknown: alias {sub}. try: list | add | remove | save | reload | stats | suggest", color="R")

    def _alias_list(self, source: str):
        """Display alias list."""
        aliases = self._aliases.list_aliases(source)
        if not aliases:
            _print("  (none)", color="dim")
            return

        source_label = {"all": "All", "builtin": "Built-in", "user": "User"}
        _print(f"\n  --- {source_label.get(source, source)} Aliases ({len(aliases)}) ---", color="C", bold=True)

        # Group by command category
        for name, (cmd, src) in sorted(aliases.items(), key=lambda x: x[1][1] + x[0]):
            src_tag = {"builtin": "", "user": " *"}.get(src, "")
            # Skip case-duplicates (show only lowercase)
            if name != name.lower() and name.lower() in aliases:
                continue
            cmd_display = cmd[:70].replace("\n", " | ")
            _print(f"  {C['Y']}{name:12s}{C['reset']} -> {cmd_display}{C['dim']}{src_tag}{C['reset']}", color="")

        if source in ("all", "builtin"):
            _print(f"\n  {C['dim']}(*) = user-defined alias (overrides built-in){C['reset']}", color="dim")
            _print(f"  {C['dim']}alias add <name> <cmd> to customize | alias save to persist{C['reset']}", color="dim")

    # ── Command: cross ─────────────────────────────────────

    def do_cross(self, arg: str):
        """cross [status|enable|disable] — cross-axis analysis management"""
        if not self._cross_axis:
            _print("  跨轴分析器未启用（需要 ≥2 轴）。启动时使用 --axes X,Y,Z", color="R")
            return

        parts = arg.split()
        sub = parts[0] if parts else "status"

        if sub == "status" or sub == "":
            status = self._cross_axis.status()
            _print(f"\n  跨轴分析器: {status['name']}", color="C", bold=True)
            for det, enabled in status["detectors"].items():
                icon = "✓" if enabled else "✗"
                color = "G" if enabled else "R"
                _print(f"    {_colored(icon, color)} {det}", color="dim")
            _print(f"  配对: contouring={status['contouring_pairs']}, "
                   f"coupling={status['coupling_pairs']}", color="dim")
        elif sub == "enable":
            name = parts[1] if len(parts) > 1 else ""
            if name:
                self._cross_axis.enable_detector(name)
                _print(f"  ✓ 已启用跨轴检测器: {name}", color="G")
        elif sub == "disable":
            name = parts[1] if len(parts) > 1 else ""
            if name:
                self._cross_axis.disable_detector(name)
                _print(f"  ✓ 已禁用跨轴检测器: {name}", color="Y")
        else:
            _print("  usage: cross status | enable <name> | disable <name>", color="R")

    # ── Command: export ────────────────────────────────────

    def do_export(self, arg: str):
        """export annotations|recommendations|all [--dir <path>] — 导出 AI 分析结果到 CSV

        将 AI 分析结果导出为 CSV 文件，可用 Excel/Python 进一步处理。

        用法:
          export annotations [--dir <path>]   导出 AI 标注事件
          export recommendations [--dir <path>] 导出参数调参建议
          export all [--dir <path>]           导出标注 + 建议

        示例:
          export annotations --dir ./reports
          export all
        """
        sargs = self._parse_args(arg, ["dir="])
        output_dir = Path(sargs.get("dir", "."))
        sub = arg.split()[0] if arg.split() else ""

        import csv
        from datetime import datetime

        do_ann = sub in ("annotations", "ann", "all", "")
        do_rec = sub in ("recommendations", "rec", "all", "")

        if sub not in ("annotations", "ann", "recommendations", "rec", "all", ""):
            _print(f"  用法: export annotations | recommendations | all", color="R")
            return

        files_written = []

        if do_ann:
            annotations = getattr(self.pipeline, 'recent_events', [])
            if annotations:
                fname = output_dir / datetime.now().strftime("annotations_%Y%m%d_%H%M%S.csv")
                headers = [
                    "Timestamp (s)", "Channel", "Severity", "Category",
                    "Value", "Confidence", "Message", "Suggestion",
                ]
                with open(fname, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([f"# AI Annotations Export — {datetime.now().isoformat()}"])
                    writer.writerow([f"# Count: {len(annotations)}"])
                    writer.writerow(["#"])
                    writer.writerow(headers)
                    for ann in annotations:
                        writer.writerow([
                            f"{getattr(ann, 'timestamp', 0.0):.6f}",
                            str(getattr(ann, 'channel', '')),
                            str(getattr(ann, 'severity', 'info')),
                            str(getattr(ann, 'category', '')),
                            f"{getattr(ann, 'value', 0.0):.6g}",
                            f"{getattr(ann, 'confidence', 0.0):.2f}",
                            str(getattr(ann, 'message', '')),
                            str(getattr(ann, 'suggestion', '')),
                        ])
                files_written.append((fname, len(annotations), "annotations"))
            else:
                _print("  No annotations to export. Run 'analyze' first.", color="dim")

        if do_rec:
            recs = getattr(self.pipeline, 'last_recommendations', [])
            if not recs and hasattr(self.pipeline, 'recommender'):
                try:
                    recs = self.pipeline.recommender.recommend(
                        getattr(self.pipeline, 'recent_events', [])
                    )
                except Exception:
                    recs = []

            if recs:
                fname = output_dir / datetime.now().strftime("recommendations_%Y%m%d_%H%M%S.csv")
                headers = ["Parameter", "Current Value", "Suggested Value", "Reason", "Confidence", "Brand"]
                with open(fname, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([f"# Parameter Recommendations — {datetime.now().isoformat()}"])
                    writer.writerow([f"# Count: {len(recs)}"])
                    writer.writerow(["#"])
                    writer.writerow(headers)
                    for rec in recs:
                        writer.writerow([
                            str(getattr(rec, 'parameter', getattr(rec, 'index', ''))),
                            str(getattr(rec, 'current_value', '')),
                            str(getattr(rec, 'suggested_value', '')),
                            str(getattr(rec, 'reason', '')),
                            f"{getattr(rec, 'confidence', 0.0):.2f}",
                            str(getattr(rec, 'brand', '')),
                        ])
                files_written.append((fname, len(recs), "recommendations"))
            else:
                _print("  No recommendations to export. Run 'recommend' first.", color="dim")

        if files_written:
            _print(f"\n  Exported {len(files_written)} file(s):", color="G", bold=True)
            for fname, count, kind in files_written:
                _print(f"    {fname} ({count} {kind})", color="dim")
        elif not sub:
            _print(f"  No data to export. Run 'analyze' then 'recommend' first.", color="Y")

    # ── Command: codesys ───────────────────────────────────

    def do_codesys(self, arg: str):
        """codesys export [--dir <path>] [--brand <name>] — 导出 CODESYS ST 代码"""
        sargs = self._parse_args(arg, ["dir=", "brand="])
        output_dir = sargs.get("dir", "07-codesys-fb")

        annotations = self.pipeline.recent_events
        recs = self.pipeline.recommender.recommend(annotations)

        try:
            from ai_analyzer.codegen_st import CodegenST
            gen = CodegenST(brand=sargs.get("brand") or self._brand or "delta-a3")
            files = gen.export_all(output_dir, annotations, recs)

            _print(f"\n  CODESYS ST export: {len(files)} files -> {output_dir}", color="G", bold=True)
            for name, content in files.items():
                lines = content.count('\n') + 1
                _print(f"    {name}: {lines} lines", color="dim")
            _print(f"\n  Import into CODESYS IDE: Project -> Add Object -> POU", color="dim")
            _print(f"  HITL gate: set bAuthorized:=TRUE after engineer confirms", color="dim")
        except Exception as e:
            _print(f"  export failed: {e}", color="R")

    # ── Command: scope ─────────────────────────────────────

    def do_scope(self, arg: str):
        """scope [--tk|--qt|--web|--demo] [--axes <n>] — 启动实时示波器

        一键启动示波器前端，自动选择最佳可用后端。

        用法:
          scope              自动选择 (pyqtgraph > tkinter)
          scope --tk         强制 tkinter (143 FPS, 0 依赖)
          scope --qt         强制 pyqtgraph (381 FPS, GPU 加速)
          scope --web        强制 Web 服务器 (http://localhost:8888)
          scope --demo       AI 模拟演示模式
          scope --axes 3    多轴模式 (3 轴)
        """
        import subprocess
        import os

        # Resolve run_scope.py from the project root
        _project_root = Path(__file__).resolve().parent  # 06-ai-analyzer/
        _launcher = _project_root.parent / "run_scope.py"  # motion-control-precision-force/
        if not _launcher.exists():
            _print(f"  ✗ 找不到示波器启动脚本: {_launcher}", color="R")
            return

        # Build args
        scope_args = [sys.executable, str(_launcher)]
        for flag in ["--tk", "--qt", "--web", "--demo"]:
            if flag in arg:
                scope_args.append(flag)
                break

        # Forward --axes N
        import re
        m = re.search(r'--axes[= ](\d+)', arg)
        if m:
            scope_args.extend(["--axes", m.group(1)])

        _print(f"  启动示波器: {' '.join(scope_args[1:])}", color="C")
        _print(f"  (在新窗口中打开，按 Ctrl+C 返回 CLI)", color="dim")

        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            subprocess.run(scope_args, env=env)
        except KeyboardInterrupt:
            _print("\n  示波器已关闭", color="dim")

    # ── Command: help ──────────────────────────────────────

    def do_help(self, arg: str):
        """help [<command>] — 显示命令帮助"""
        if arg:
            super().do_help(arg)
        else:
            axis_info = ""
            if self._axis_ids:
                axis_info = f"\n{C['dim']}Axes: {', '.join(self._axis_ids)}. "
                axis_info += f"Use --axis <name> or --axis all on any command.{C['reset']}"
            _print(f"""
{C['bold']}{C['C']}Commands:{C['reset']}

{C['Y']}scope{C['reset']}     Launch real-time oscilloscope (GUI) [--tk|--qt|--web|--demo] [--axes <n>]
{C['Y']}analyze{C['reset']}     Run AI 3-detector analysis [--axis <name|all>]
{C['Y']}hitl{C['reset']}       HITL engineer interaction (prompt|feedback|authorize|pending|history)
{C['Y']}recommend{C['reset']}   Generate tuning recommendations [--axis <name|all>]
{C['Y']}params{C['reset']}      Query parameter descriptions / list servo brands
{C['Y']}detectors{C['reset']}   Manage detectors (enable/disable) [--axis <name>]
{C['Y']}log{C['reset']}        Audit log (show|summary|export)
{C['Y']}status{C['reset']}     System status [--axis <name|all>]
{C['Y']}session{C['reset']}    Session management (info|reset)
{C['Y']}alias{C['reset']}      Alias management (list|add|remove|save|reload|stats)
{C['Y']}export{C['reset']}     Export AI results to CSV (annotations|recommendations|all)
{C['Y']}codesys{C['reset']}    Export CODESYS ST code (FB_ServoDiag + FB_ServoTune + DUT)
{C['Y']}cross{C['reset']}      Cross-axis analysis status (multi-axis only)
{C['Y']}help{C['reset']}       Show this help
{C['Y']}quit{C['reset']}       Exit
{axis_info}
{C['dim']}Type help <cmd> for details. alias list for shortcuts.{C['reset']}
{C['dim']}Set ANTHROPIC_API_KEY for natural language input.{C['reset']}
""")

    # ── Command: quit/exit ─────────────────────────────────

    def do_quit(self, arg: str):
        """退出 CLI"""
        _print("再见。", color="dim")
        return True

    def do_exit(self, arg: str):
        """退出 CLI"""
        return self.do_quit(arg)

    def do_EOF(self, arg: str):
        """Ctrl-D 退出"""
        print()
        return True

    # ── Default: try alias → NL translation ────────────────

    def default(self, line: str):
        """Handle unrecognized input — try alias, then LLM translation."""
        if not line.strip():
            return

        # 1. Try alias resolution
        resolved, was_aliased = self._aliases.resolve_line(line)
        if was_aliased:
            _print(f"  ↳ {resolved[:100]}", color="dim")
            # Multi-command macros (contain \n): execute each line
            if "\n" in resolved:
                for sub_cmd in resolved.split("\n"):
                    sub_cmd = sub_cmd.strip()
                    if sub_cmd:
                        self.onecmd(sub_cmd)
            else:
                self.onecmd(resolved)
            return

        # 2. Try LLM translation
        translator = self.translator
        if translator and translator.available:
            _print("  ... translating ...", color="dim")
            result = translator.translate(line)
            if result and result.get("command"):
                cmd_str = result["command"].strip()
                confidence = result.get("confidence", 0)
                _print(f"  -> {cmd_str} (confidence: {confidence:.0%})", color="dim")
                if result.get("explanation"):
                    _print(f"     {result['explanation']}", color="dim")
                if confidence > 0.5:
                    self.onecmd(cmd_str)
                if result.get("follow_up"):
                    _print(f"  hint: {result['follow_up']}", color="Y")
                return

        _print(f"  unknown: {line}. Type help for commands, alias list for aliases.", color="R")

    # ── Tab completion ─────────────────────────────────────

    def completenames(self, text, *ignored):
        """Tab-complete command names + brand names."""
        base = super().completenames(text, *ignored)
        # Add brand names for relevant commands
        try:
            from ai_analyzer.tuning_rules import BRAND_ALIASES
            if text:
                brands = [b for b in BRAND_ALIASES if b.startswith(text)]
                return base + brands
        except Exception:
            pass
        return base

    # ── Argument Parser (simple key=value) ─────────────────

    @staticmethod
    def _parse_args(arg: str, known_keys: list) -> dict:
        """Simple argument parser for --key value and --key=value patterns.

        Args:
            arg: Raw argument string.
            known_keys: List of "key=" (flag) or "key=" (value) patterns.

        Returns:
            Dict of parsed key→value.
        """
        result = {}
        parts = arg.split()
        i = 0
        while i < len(parts):
            p = parts[i]
            for k in known_keys:
                clean_k = k.rstrip("=")
                if p == f"--{clean_k}":
                    if k.endswith("="):
                        # --key value
                        if i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                            result[clean_k] = parts[i + 1]
                            i += 1
                        else:
                            result[clean_k] = ""
                    else:
                        result[clean_k] = "true"
                    break
                elif p.startswith(f"--{clean_k}="):
                    result[clean_k] = p.split("=", 1)[1]
                    break
            i += 1

        # Also handle bare positional args
        positional = [p for p in parts if not p.startswith("--")]
        if positional and "positional" not in result:
            pass  # positional args handled per-command

        return result


# ── Entry Points ──────────────────────────────────────────────

def run_repl(brand: str = None, enable_llm: bool = True, axis_ids: list = None):
    """Launch the interactive REPL."""
    try:
        cli = ServoCli(brand=brand, enable_llm=enable_llm, axis_ids=axis_ids)
        cli.cmdloop()
    except KeyboardInterrupt:
        _print("\n再见。", color="dim")
    except Exception as e:
        _print(f"\n错误: {e}", color="R")
        import traceback
        traceback.print_exc()


def run_single_command(cmd_str: str, brand: str = None, axis_ids: list = None):
    """Execute a single command and exit."""
    cli = ServoCli(brand=brand, axis_ids=axis_ids)
    cli.onecmd(cmd_str)


def run_script(script_path: str, brand: str = None, axis_ids: list = None):
    """Execute commands from a file."""
    cli = ServoCli(brand=brand, axis_ids=axis_ids)
    with open(script_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                _print(f"{cli.prompt}{line}", color="dim")
                cli.onecmd(line)


# ── CLI Argument Parser ──────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Servo Diagnostic CLI — 离线命令系统 + AI 诊断",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python servo_cli.py                           交互式 REPL (单轴)
  python servo_cli.py --axes X,Y,Z              交互式 REPL (3轴 + 跨轴检测)
  python servo_cli.py -c "analyze --axis X"      执行单条命令
  python servo_cli.py -c "status --axis all"     查看所有轴状态
  python servo_cli.py --script cmds.txt          运行脚本文件
  echo "status" | python servo_cli.py            管道输入
        """,
    )
    parser.add_argument("-c", "--command", type=str, help="执行单条命令后退出")
    parser.add_argument("--script", type=str, help="从文件执行命令")
    parser.add_argument("--brand", type=str, default=None, help="默认伺服品牌")
    parser.add_argument("--axes", type=str, default=None,
                       help="逗号分隔的轴名称 (e.g. X,Y,Z). 启用跨轴检测。")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM 自然语言翻译")

    args = parser.parse_args()

    if not _CLI_CMDS_AVAILABLE:
        _print(f"错误: 无法导入 CLI 命令模块: {_CLI_IMPORT_ERROR}", color="R")
        _print("请确认 ai_analyzer 包已正确安装。", color="R")
        sys.exit(1)

    # Parse --axes
    axis_ids = None
    if args.axes:
        axis_ids = [a.strip() for a in args.axes.split(",") if a.strip()]

    if args.command:
        run_single_command(args.command, brand=args.brand, axis_ids=axis_ids)
    elif args.script:
        script_path = Path(args.script)
        if not script_path.exists():
            _print(f"错误: 脚本文件不存在: {args.script}", color="R")
            sys.exit(1)
        run_script(str(script_path), brand=args.brand, axis_ids=axis_ids)
    elif not sys.stdin.isatty():
        # Pipe mode
        cli = ServoCli(brand=args.brand, enable_llm=not args.no_llm, axis_ids=axis_ids)
        for line in sys.stdin:
            line = line.strip()
            if line:
                _print(f"{cli.prompt}{line}", color="dim")
                cli.onecmd(line)
    else:
        run_repl(brand=args.brand, enable_llm=not args.no_llm, axis_ids=axis_ids)


if __name__ == "__main__":
    main()

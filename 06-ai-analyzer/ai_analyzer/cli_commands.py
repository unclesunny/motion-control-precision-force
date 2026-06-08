"""
CLI Command Engine — pure functions that execute servo diagnostic commands.

Each function is independently callable (no dependency on cmd.Cmd),
making them reusable from:
  - servo_cli.py (REPL)
  - cli_llm_bridge.py (LLM → command translation)
  - MCP servers
  - Web API endpoints

All functions return structured dicts for easy JSON serialization.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Color helpers (ANSI terminal) ──────────────────────────────

C = {
    "R": "\033[91m", "G": "\033[92m", "Y": "\033[93m",
    "B": "\033[94m", "M": "\033[95m", "C": "\033[96m",
    "W": "\033[97m", "dim": "\033[2m", "bold": "\033[1m",
    "reset": "\033[0m",
}
# ASCII-safe icons (fallback when Unicode fails)
SEV_ICON = {"info": "i", "warning": "!", "critical": "!!"}

# Box drawing chars: try Unicode, fall back to ASCII
try:
    _test = "─"
    BOX = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
           "h": "─", "v": "│", "cl": "├", "cr": "┤",
           "ch": "╔", "dh": "╗", "bh": "╚", "ah": "╝",
           "cv": "║", "cs": "╠", "ct": "╦", "cb": "╩", "ce": "╣", "cc": "╬"}
except Exception:
    BOX = {"tl": "+", "tr": "+", "bl": "+", "br": "+",
           "h": "-", "v": "|", "cl": "+", "cr": "+",
           "ch": "+", "dh": "+", "bh": "+", "ah": "+",
           "cv": "|", "cs": "+", "ct": "+", "cb": "+", "ce": "+", "cc": "+"}


def _print(text: str = "", color: str = "", bold: bool = False):
    """Print colored text to terminal, safe for Windows GBK."""
    prefix = C.get(color, "") + (C["bold"] if bold else "")
    try:
        print(f"{prefix}{text}{C['reset']}")
    except UnicodeEncodeError:
        # Fall back to ASCII
        text_ascii = text.encode("ascii", errors="replace").decode("ascii")
        print(f"{prefix}{text_ascii}{C['reset']}")


def _print_annotation(ann, index: int = 0):
    """Print a single AIAnnotation."""
    icon = SEV_ICON.get(ann.severity, "?")
    color = C.get({"info": "B", "warning": "Y", "critical": "R"}.get(ann.severity, "W"))
    hclass = getattr(ann, "hitl_classification", "")
    htag = f" [{hclass}]" if hclass else ""
    _print(f"  {icon} [{ann.category}]{htag} {ann.channel}: {ann.message}", color=color)
    if ann.suggestion:
        _print(f"    → {ann.suggestion[:120]}", color="dim")


# ── Analyze Command (Pro stub) ────────────────────────────────

def cmd_analyze(pipeline, args: dict) -> dict:
    """Run AI analysis — Pro license required."""
    return {
        "annotations": [],
        "count": 0,
        "classification_summary": {"safe": 0, "actionable": 0, "ambiguous": 0},
        "message": "Pro license required for AI analysis",
    }


def cmd_analyze_print(pipeline, args: dict):
    """Print analysis — Pro license required."""
    _print("\n┌─── AI Analysis ───┐", color="C", bold=True)
    _print("  Pro license required for ML-based servo analysis", color="Y")
    _print("└──────────────────┘", color="C")
    return cmd_analyze(pipeline, args)


# ── HITL Commands (Pro stubs) ─────────────────────────────────

def cmd_hitl_classify(gate, annotation_data: dict) -> dict:
    return {"category": "", "classification": "safe", "requires_authorization": False}

def cmd_hitl_prompt(gate, pipeline, category: str = None,
                    prompt_all: bool = False) -> dict:
    return {"prompts": [], "count": 0, "message": "Pro license required for HITL"}

def cmd_hitl_prompt_print(gate, pipeline, category: str = None,
                          prompt_all: bool = False):
    _print("  Pro license required for HITL engineer prompts", color="Y")
    return cmd_hitl_prompt(gate, pipeline, category, prompt_all)

def cmd_hitl_feedback(gate, pipeline, prompt_id: str, response_text: str = "",
                      observation: str = "", auth: str = "pending",
                      authorized_by: str = "cli-user") -> dict:
    return {"status": "ok", "authorization": auth, "refined_annotations": [],
            "pending_remaining": 0}

def cmd_hitl_authorize(gate, pipeline, prompt_id: str) -> dict:
    return {"status": "error", "message": "Pro license required for HITL authorization"}

def cmd_hitl_pending(gate) -> dict:
    return {"pending": [], "count": 0}


# ── Recommend Command (Pro stub) ──────────────────────────────

def cmd_recommend(pipeline, brand: str = None, fmt: str = "table") -> dict:
    return {"recommendations": [], "count": 0, "brand": brand or "default",
            "message": "Pro license required for parameter recommendations"}

def cmd_recommend_print(pipeline, brand: str = None):
    _print("\n┌─── 参数建议 ───┐", color="C", bold=True)
    _print("  Pro license required for tuning recommendations", color="Y")
    _print("└──────────────────┘", color="C")
    return cmd_recommend(pipeline, brand)


# ── Params Commands ────────────────────────────────────────────

def cmd_params_lookup(index_hex: str) -> dict:
    """Look up a CiA 402 parameter by hex index."""
    from tuning_rules import PARAM_DESCRIPTIONS
    try:
        idx = int(index_hex, 16)
    except ValueError:
        return {"error": f"Invalid index: {index_hex}"}

    desc = PARAM_DESCRIPTIONS.get(idx, "")
    return {
        "index": index_hex,
        "decimal": idx,
        "description": desc or f"未知参数 {index_hex}",
        "found": bool(desc),
    }


def cmd_params_brands() -> dict:
    """List supported servo brands."""
    from tuning_rules import BRAND_ALIASES
    return {
        "brands": list(BRAND_ALIASES.keys()),
        "count": len(BRAND_ALIASES),
    }


# ── Log Commands ───────────────────────────────────────────────

def cmd_log_show(logger, last: int = 20) -> dict:
    """Show recent audit log events."""
    report = logger.export_session()
    events = report["events"][-last:]
    return {"events": events, "count": len(events), "total": len(report["events"])}


def cmd_log_summary(logger) -> dict:
    """Show audit log summary."""
    return logger.export_session()["summary"]


def cmd_log_export(logger, filepath: str = None) -> str:
    """Export audit log to JSON file."""
    return logger.save(filepath)


# ── Status Command ─────────────────────────────────────────────

def cmd_status(pipeline, verbose: bool = False) -> dict:
    """Get system/session status."""
    detectors = {}
    for a in pipeline.analyzers:
        detectors[a.name] = a.enabled

    hitl_gate = pipeline.hitl_gate
    action_logger = pipeline.action_logger

    log_summary = {}
    if action_logger:
        log_summary = action_logger.export_session().get("summary", {})

    status = {
        "detectors": detectors,
        "hitl_enabled": pipeline.enable_hitl,
        "hitl_pending": hitl_gate.pending_count if hitl_gate else 0,
        "hitl_authorized": len(hitl_gate.get_authorized_actions()) if hitl_gate else 0,
        "hitl_rejected": len(hitl_gate.get_rejected_actions()) if hitl_gate else 0,
        "log_events": log_summary.get("total_events", 0),
        "llm_available": hitl_gate.llm_available if hitl_gate else False,
    }
    return status


def cmd_status_print(pipeline, verbose: bool = False):
    """Print system status."""
    s = cmd_status(pipeline, verbose)

    width = 44
    _print(f"\n{BOX['ch']}{BOX['h'] * width}{BOX['dh']}", color="C")
    _print(f"{BOX['cv']}  Servo Diagnostic Session{' ' * (width - 27)}{BOX['cv']}", color="C", bold=True)
    _print(f"{BOX['cs']}{BOX['h'] * width}{BOX['ce']}", color="C")

    # Detectors line
    det_parts = []
    for k, v in s["detectors"].items():
        icon = "v" if v else "x"
        det_parts.append(f"{icon} {k}")
    det_str = " | ".join(det_parts)
    _print(f"{BOX['cv']}  Detectors: {det_str}{' ' * max(0, width - 14 - len(det_str))}{BOX['cv']}")

    hitl_status = "ON" if s["hitl_enabled"] else "OFF"
    _print(f"{BOX['cv']}  HITL: {hitl_status} | pending: {s['hitl_pending']} | auth: {s['hitl_authorized']} | rej: {s['hitl_rejected']}{' ' * max(0, width - 40 - len(str(s['hitl_pending'])))}{BOX['cv']}")

    _print(f"{BOX['cv']}  Log events: {s['log_events']}{' ' * (width - 14 - len(str(s['log_events'])))}{BOX['cv']}")

    llm_status = "available" if s.get("llm_available") else "unavailable"
    _print(f"{BOX['cv']}  LLM: {llm_status}{' ' * (width - 8 - len(llm_status))}{BOX['cv']}")

    _print(f"{BOX['bh']}{BOX['h'] * width}{BOX['ah']}", color="C")
    return s


# ── Session Commands ───────────────────────────────────────────

def cmd_session_info(pipeline) -> dict:
    """Get session information."""
    logger = pipeline.action_logger
    return {
        "session_id": logger.session_id if logger else "N/A",
        "brand": logger.brand if logger else None,
        "sample_count": pipeline._sample_count,
        "recent_event_count": len(pipeline._events),
    }

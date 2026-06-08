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


# ── Analyze Command ────────────────────────────────────────────

def cmd_analyze(pipeline, args: dict) -> dict:
    """Run AI analysis on scope data.

    Args:
        pipeline: AIAnalyzerPipeline instance.
        args: {"data_file": str|None, "channels": str|None, "brand": str|None,
               "stride": int, "buffer_stats": dict|None}

    Returns:
        {"annotations": [...], "count": int, "classification_summary": dict}
    """
    import numpy as np

    data_file = args.get("data_file")
    channels_str = args.get("channels", "")
    stride = args.get("stride", 10)

    ch_names = ["Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode"]

    if data_file and Path(data_file).exists():
        # Load from file
        if data_file.endswith(".json"):
            with open(data_file, "r") as f:
                raw = json.load(f)
            data = np.array(raw.get("data", raw if isinstance(raw, list) else []))
        elif data_file.endswith(".csv"):
            import csv
            rows = []
            with open(data_file, "r") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    rows.append([float(v) for v in row[:8]])
            data = np.array(rows).T if rows else np.zeros((8, 1))
        else:
            data = np.zeros((8, 1))
    else:
        # Use synthetic demo data
        n_samples = 2000
        data = np.zeros((8, n_samples), dtype=np.float32)
        for i in range(n_samples):
            t = i / 1000.0
            data[0, i] = 1000.0 * np.sin(2 * np.pi * 2.0 * t)          # Position
            data[1, i] = 500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5)     # Velocity
            data[2, i] = 80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t)     # Current
            data[3, i] = 60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2)      # Torque
            data[4, i] = 10.0 + 5.0 * np.sin(2 * np.pi * 7.0 * t)      # Foll.Err
            data[5, i] = float(i % 100 > 50)
            data[6, i] = 0x0237 if i % 200 < 100 else 0x0007
            data[7, i] = (i // 50) % 8

    # Build buffer stats
    buffer_stats = {}
    for i, name in enumerate(ch_names):
        if i < data.shape[0]:
            col = data[i, -2000:] if data.shape[0] > 2000 else data[i]
            buffer_stats[name] = {
                "mean": float(np.mean(col)),
                "std": float(np.std(col)),
                "min": float(np.min(col)),
                "max": float(np.max(col)),
                "rms": float(np.sqrt(np.mean(col ** 2))),
                "peak_to_peak": float(np.max(col) - np.min(col)),
            }

    # Run analysis with stride
    all_annotations = []
    n_samples = data.shape[1]
    sample_stride = max(1, n_samples // min(n_samples, 500))
    for idx in range(0, n_samples, sample_stride):
        values = data[:, idx].tolist()
        anns = pipeline.analyze(values, ch_names, buffer_stats)
        all_annotations.extend(anns)

    # Deduplicate: use pipeline's own dedup method
    deduped = pipeline._deduplicate(all_annotations)

    # Classification summary
    groups = {"safe": 0, "actionable": 0, "ambiguous": 0}
    for a in deduped:
        hc = getattr(a, "hitl_classification", "")
        if hc in groups:
            groups[hc] += 1

    return {
        "annotations": [
            {
                "category": a.category, "severity": a.severity,
                "confidence": a.confidence, "channel": a.channel,
                "message": a.message, "suggestion": a.suggestion,
                "hitl_classification": getattr(a, "hitl_classification", ""),
            }
            for a in deduped
        ],
        "count": len(deduped),
        "classification_summary": groups,
    }


def cmd_analyze_print(pipeline, args: dict):
    """Run analysis and print results to terminal."""
    _print("\n┌─── AI Analysis ───┐", color="C", bold=True)

    result = cmd_analyze(pipeline, args)

    if result["count"] == 0:
        _print("  ✓ 未检测到异常 — 所有通道正常", color="G")
    else:
        for i, a in enumerate(result["annotations"]):
            # Create a lightweight annotation-like object for printing
            class _Ann:
                pass
            obj = _Ann()
            obj.category = a["category"]
            obj.severity = a["severity"]
            obj.confidence = a["confidence"]
            obj.channel = a["channel"]
            obj.message = a["message"]
            obj.suggestion = a["suggestion"]
            obj.hitl_classification = a.get("hitl_classification", "")
            _print_annotation(obj, i)

    groups = result["classification_summary"]
    total = sum(groups.values())
    _print(f"\n  总计: {total} 异常 | "
           f"🔵 safe: {groups['safe']} | "
           f"🟡 actionable: {groups['actionable']} | "
           f"🟠 ambiguous: {groups['ambiguous']}",
           color="dim")
    _print("└──────────────────┘", color="C")
    return result


# ── HITL Commands ──────────────────────────────────────────────

def cmd_hitl_classify(gate, annotation_data: dict) -> dict:
    """Classify an annotation."""
    from analyzer_base import AIAnnotation

    ann = AIAnnotation(
        timestamp=time.time(),
        channel=annotation_data.get("channel", "Unknown"),
        category=annotation_data.get("category", ""),
        severity=annotation_data.get("severity", "info"),
        confidence=annotation_data.get("confidence", 0.5),
        message=annotation_data.get("message", ""),
        value=annotation_data.get("value", 0.0),
    )
    classification = gate.classify(ann)
    return {
        "category": ann.category,
        "classification": classification,
        "requires_authorization": ann.requires_authorization,
    }


def cmd_hitl_prompt(gate, pipeline, category: str = None,
                    prompt_all: bool = False) -> dict:
    """Generate HITL prompts from recent events."""
    events = pipeline.recent_events
    if not events:
        return {"prompts": [], "count": 0, "message": "No recent events"}

    if category:
        events = [e for e in events if e.category == category]

    prompts = gate.generate_prompts(events)
    return {
        "prompts": [p.to_dict() for p in prompts],
        "count": len(prompts),
        "pending_total": gate.pending_count,
    }


def cmd_hitl_prompt_print(gate, pipeline, category: str = None,
                          prompt_all: bool = False):
    """Generate and print HITL prompts."""
    result = cmd_hitl_prompt(gate, pipeline, category, prompt_all)

    if result["count"] == 0:
        _print("  无待处理的 HITL prompts", color="dim")
        return result

    for i, p in enumerate(result["prompts"]):
        cls_icon = {"ambiguous": "🟠", "actionable": "🟡"}.get(
            p.get("classification", ""), "🔵")
        _print(f"\n{cls_icon} Prompt #{i+1} [{p.get('classification')}]: "
               f"{p.get('question', '')[:100]}", color="Y")
        if p.get("context"):
            _print(f"   {p['context'][:200]}", color="dim")
        checks = p.get("suggested_checks", [])
        if checks:
            _print("   检查清单:", color="dim")
            for c in checks[:8]:
                _print(f"     • {c}", color="dim")
        _print(f"   ID: {p.get('prompt_id', '')} | 紧急度: {p.get('urgency', 'routine')}",
               color="dim")

    _print(f"\n  共 {result['count']} 个 prompts (总计 {result['pending_total']} 待处理)",
           color="dim")
    return result


def cmd_hitl_feedback(gate, pipeline, prompt_id: str, response_text: str = "",
                      observation: str = "", auth: str = "pending",
                      authorized_by: str = "cli-user") -> dict:
    """Submit engineer feedback."""
    from hitl_types import EngineerFeedback

    feedback = EngineerFeedback(
        prompt_id=prompt_id,
        response_text=response_text,
        selected_observation=observation,
        authorization=auth,
        authorized_by=authorized_by,
    )
    refined = pipeline.process_engineer_feedback(prompt_id, feedback)

    return {
        "status": "ok",
        "authorization": auth,
        "refined_annotations": [
            {
                "category": a.category, "severity": a.severity,
                "message": a.message, "confidence": a.confidence,
                "refined_by": a.metadata.get("refined_by", "unknown"),
            }
            for a in refined
        ],
        "pending_remaining": gate.pending_count,
    }


def cmd_hitl_authorize(gate, pipeline, prompt_id: str) -> dict:
    """Authorize parameter changes for an actionable prompt."""
    prompt = gate.get_prompt(prompt_id)
    if prompt is None:
        return {"status": "error", "message": f"Prompt {prompt_id} not found"}

    if prompt.classification != "actionable":
        return {"status": "error",
                "message": f"Prompt is {prompt.classification}, not actionable"}

    from hitl_types import EngineerFeedback
    feedback = EngineerFeedback(
        prompt_id=prompt_id,
        authorization="approved",
        authorized_by="cli-user",
    )
    recs = prompt.parameter_preview or []
    if not recs:
        matching = [a for a in pipeline.recent_events
                    if a.category == prompt.category]
        recs = pipeline.recommender.recommend(matching[-3:] if matching else [])

    actions = gate.authorize(recs, feedback)
    for a in actions:
        try:
            pipeline.action_logger.log_authorized(a)
        except Exception:
            pass

    return {
        "status": "ok",
        "authorized_actions": [a.to_dict() for a in actions],
        "count": len(actions),
    }


def cmd_hitl_pending(gate) -> dict:
    """List pending HITL prompts."""
    prompts = gate.pending_prompts
    return {
        "pending": [{"prompt_id": p.prompt_id, "category": p.category,
                      "classification": p.classification, "urgency": p.urgency}
                    for p in prompts],
        "count": len(prompts),
    }


# ── Recommend Command ──────────────────────────────────────────

def cmd_recommend(pipeline, brand: str = None, fmt: str = "table") -> dict:
    """Generate parameter recommendations."""
    if brand:
        from parameter_recommender import ParameterRecommender
        pipeline._recommender = ParameterRecommender(brand=brand)

    events = pipeline.recent_events
    safe_events = [e for e in events
                   if getattr(e, "hitl_classification", "") == "safe"
                   or not getattr(e, "requires_authorization", False)]
    recs = pipeline._recommender.recommend(safe_events if safe_events else events)
    return {
        "recommendations": [r.to_dict() for r in recs],
        "count": len(recs),
        "brand": brand or pipeline._recommender.brand,
    }


def cmd_recommend_print(pipeline, brand: str = None):
    """Generate and print parameter recommendations."""
    result = cmd_recommend(pipeline, brand)

    if result["count"] == 0:
        _print("  无需参数调整", color="dim")
        return result

    _print(f"\n┌─── 参数建议 ({result['brand'] or 'default'}) ───┐", color="C", bold=True)
    for i, r in enumerate(result["recommendations"]):
        action_icon = {"increase": "+", "decrease": "-", "set": "→",
                       "check": "?", "consider": "○"}.get(r.get("action", ""), "?")
        _print(f"  {C['Y']}{action_icon}{C['reset']} {r['index']} {r.get('name', '')[:45]}")
        _print(f"    {C['dim']}{r.get('reason', '')}{C['reset']}")
        if r.get("target_value"):
            _print(f"    目标值: {r['target_value']:.0f}", color="dim")
        if r.get("safety"):
            _print(f"    安全: {r['safety']}", color="dim")
    _print("└────────────────────────────┘", color="C")
    return result


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

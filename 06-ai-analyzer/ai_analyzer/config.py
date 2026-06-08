"""
Shared constants — Free edition (CiA 402 channel mapping only).

Pro license required for detection thresholds, HITL classification rules,
cross-axis analysis configuration, suggestion templates, and LLM parameters.
"""

# ── Channel index mapping (CiA 402 standard — public IEC 61800-7) ──
CIA402_CHANNEL_MAP: dict = {
    0x6064: "Position",
    0x606C: "Velocity",
    0x6078: "Current",
    0x6077: "Torque",
    0x60F4: "Foll.Err",
    0x60FD: "DIO",
    0x6041: "Status",
    0x6061: "OpMode",
}

CHANNEL_NAME_INDEX: dict = {
    name: i for i, name in enumerate([
        "Position", "Velocity", "Current", "Torque",
        "Foll.Err", "DIO", "Status", "OpMode",
    ])
}

# ── Pro placeholders (filled if pro/ai_analyzer/config.py exists) ──
import importlib.util as _util
from pathlib import Path as _Path

_PRO_CFG = _Path(__file__).resolve().parent.parent.parent / "pro" / "ai_analyzer" / "config.py"
if _PRO_CFG.exists():
    try:
        spec = _util.spec_from_file_location("pro_config", _PRO_CFG)
        mod = _util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for _attr in dir(mod):
            if not _attr.startswith("_"):
                globals()[_attr] = getattr(mod, _attr)
    except Exception:
        pass

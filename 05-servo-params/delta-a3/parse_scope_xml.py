"""
ASDA-Soft Scope.xml Parser → Delta A3 Signal Catalog.

Extracts Delta's proprietary monitor index system from ASDA-Soft's
Scope.xml and maps each signal to:
  - Monitor Index (Delta's internal code)
  - CoE Object Index (from ESI XML)
  - Delta Parameter (P0-02, P0-09-P0-12 monitor selection)
  - Scaler + Format (from ASDA-Soft)
  - Chinese/English names

Output: delta-a3-scope-signals.json — complete signal catalog for scope.

Usage:
  python parse_scope_xml.py
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional


# ASDA-Soft monitor code → CoE object mapping (reverse-engineered)
# Format: mon_index → {coe_index, param, signal_name}
MONITOR_TO_COE = {
    # Position
    "0":   {"coe": 0x6064, "param": None,     "name": "Feedback Position", "unit": "PUU"},
    "1":   {"coe": 0x607A, "param": None,     "name": "Command Position", "unit": "PUU"},
    "2":   {"coe": 0x60F4, "param": None,     "name": "Following Error", "unit": "PUU"},
    "5":   {"coe": 0x60F4, "param": None,     "name": "Following Error", "unit": "Pulse"},
    "0x20":{"coe": None,    "param": "P0-04", "name": "Position Error", "unit": "PUU"},
    "0x21":{"coe": None,    "param": "P0-05", "name": "Position Error", "unit": "Pulse"},

    # Speed
    "6":   {"coe": None,    "param": "P0-06", "name": "Pulse Cmd Frequency", "unit": "kHz"},
    "7":   {"coe": 0x606C, "param": None,     "name": "Motor Speed (LPF)", "unit": "r/min"},
    "8":   {"coe": 0x60FF, "param": None,     "name": "Speed Command", "unit": "Volt"},
    "9":   {"coe": 0x60FF, "param": None,     "name": "Speed Command", "unit": "r/min"},
    "0x33":{"coe": 0x606C, "param": None,     "name": "Motor Speed", "unit": "r/min"},

    # Torque / Current
    "10":  {"coe": 0x6071, "param": None,     "name": "Torque Command", "unit": "Volt"},
    "0x35":{"coe": 0x6071, "param": None,     "name": "Torque Command", "unit": "%"},
    "0x36":{"coe": 0x6078, "param": None,     "name": "Motor Current", "unit": "%"},
    "0x37":{"coe": 0x6078, "param": None,     "name": "Motor Current", "unit": "Amp"},

    # Digital IO
    "0x27":{"coe": 0x60FD, "param": None,     "name": "DI Status", "unit": "bitfield"},
    "0x28":{"coe": 0x60FE, "param": None,     "name": "DO Status", "unit": "bitfield"},

    # Power
    "0x38":{"coe": None,    "param": "P0-08", "name": "V Bus Voltage", "unit": "Volt"},

    # Load
    "0xF": {"coe": None,    "param": "P0-0F", "name": "Load Inertia Ratio", "unit": "times"},
    "12":  {"coe": None,    "param": "P0-12", "name": "Average Load Rate", "unit": "%"},

    # Monitor mapping
    "0x17":{"coe": None,    "param": "P0-09", "name": "Monitor #1", "unit": "—"},
    "0x18":{"coe": None,    "param": "P0-10", "name": "Monitor #2", "unit": "—"},
    "0x19":{"coe": None,    "param": "P0-11", "name": "Monitor #3", "unit": "—"},
    "0x1A":{"coe": None,    "param": "P0-12", "name": "Monitor #4", "unit": "—"},

    # Protection
    "0x5B7F":{"coe": None,  "param": None,     "name": "Overload (AL006) Counter", "unit": "count"},
    "0x6F7F":{"coe": None,  "param": None,     "name": "Regeneration (AL005) Counter", "unit": "count"},

    # Aux encoder
    "0x1D":{"coe": None,    "param": "P0-1D", "name": "Aux Encoder Feedback", "unit": "PUU"},
    "0x1E":{"coe": None,    "param": "P0-1E", "name": "Aux Encoder Pos Error", "unit": "PUU"},
    "0x1F":{"coe": None,    "param": "P0-1F", "name": "Main/Aux Pos Error", "unit": "PUU"},
    "0x30":{"coe": None,    "param": "P0-30", "name": "Aux Encoder Feedback", "unit": "Pulse"},

    # Advanced
    "0x2C":{"coe": None,    "param": None,     "name": "Total Current Feedback", "unit": "%"},
    "0xB87F":{"coe": None,  "param": None,     "name": "Total Current Feedback", "unit": "AMP"},
    "0xBC7F":{"coe": None,  "param": None,     "name": "Magnetizing Current Command", "unit": "%"},
    "0xBD7F":{"coe": None,  "param": None,     "name": "Magnetizing Current Feedback", "unit": "%"},
    "0xBE7F":{"coe": None,  "param": None,     "name": "Magnetizing Current Feedback", "unit": "AMP"},
    "0xB97F":{"coe": None,  "param": None,     "name": "Voltage Limit", "unit": "Volt"},
    "0xBA7F":{"coe": None,  "param": None,     "name": "Output Voltage", "unit": "Volt"},
    "0xBB7F":{"coe": None,  "param": None,     "name": "Output Voltage (LPF)", "unit": "Volt"},

    # Special
    "0x6B7F":{"coe": 0x6064, "param": None,    "name": "Feedback Position", "unit": "PULSE"},
    "0x697F":{"coe": None,  "param": None,     "name": "Main/Aux Pos Error", "unit": "Pulse"},
    "0xD57F":{"coe": None,  "param": None,     "name": "Linear Scale Signal Quality", "unit": "—"},
    "3":     {"coe": 0x6064, "param": None,     "name": "Feedback Position", "unit": "Enc"},
    "0x2A":  {"coe": None,   "param": "P0-2A", "name": "PR Command Path Index", "unit": "—"},
}


def parse_scope_xml(xml_path: str) -> List[dict]:
    """Parse ASDA-Soft Scope.xml and extract all monitor signals."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    signals = []

    for version_elem in root.iter("OrigVersion"):
        fw_ver = version_elem.get("FWVer", "")
        motor_type = version_elem.get("MotorType", "")

        items = version_elem.find("Items")
        if items is None:
            continue

        for item_elem in items:
            mon_idx = item_elem.get("MonIndex", "")
            scaler = item_elem.get("Scaler", "") or "1.0"
            fmt = item_elem.get("Format", "") or "%d"
            name = item_elem.get("Name", "").strip()

            # Map to CoE
            coe_info = MONITOR_TO_COE.get(mon_idx, {})
            coe_idx = coe_info.get("coe")
            param = coe_info.get("param")
            unit = coe_info.get("unit", "")

            signals.append({
                "monitor_index": mon_idx,
                "monitor_index_dec": int(mon_idx, 16) if mon_idx.startswith("0x") else (
                    int(mon_idx) if mon_idx.isdigit() else None
                ),
                "name": name,
                "name_cn": _extract_chinese_comment(item_elem),
                "scaler": float(scaler) if scaler.replace(".", "").replace("-", "").isdigit() else 1.0,
                "format": fmt,
                "coe_index": f"0x{coe_idx:04X}" if coe_idx else None,
                "delta_param": param,
                "unit": unit,
                "fw_version": fw_ver,
                "motor_type": motor_type,
            })

    return signals


def _extract_chinese_comment(elem: ET.Element) -> str:
    """Extract Chinese comment from <!-- --> in element XML."""
    # ET doesn't preserve comments in the tree, so we need the raw string
    tail = elem.tail or ""
    # Look for comment patterns in the raw XML
    raw = ET.tostring(elem, encoding="unicode")
    m = re.search(r"<!--(.+?)-->", raw)
    return m.group(1).strip() if m else ""


def main():
    # Auto-detect ASDA-Soft paths
    scope_xml_paths = [
        Path(r"D:\MyDeskWORKS\desk2\ASDA_Soft_V7.0.0.7\Data\ScopeMonItems\Scope.xml"),
    ]
    scope_xml = None
    for p in scope_xml_paths:
        if p.exists():
            scope_xml = p
            break

    if not scope_xml:
        print("Scope.xml not found. Specify path as argument.")
        return 1

    output_dir = Path(__file__).resolve().parent

    print(f"Parsing: {scope_xml}")
    signals = parse_scope_xml(str(scope_xml))

    # Deduplicate by (mon_idx, fw_ver, motor_type) — keep latest
    seen = {}
    unique = []
    for s in signals:
        key = (s["monitor_index"], s["fw_version"], s["motor_type"])
        if key not in seen:
            seen[key] = s
            unique.append(s)

    # Export signal catalog
    catalog_path = output_dir / "delta-a3-scope-signals.json"
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)
    print(f"\nExported: {catalog_path} ({len(unique)} signals)")

    # Summary
    coe_mapped = [s for s in unique if s["coe_index"]]
    param_mapped = [s for s in unique if s["delta_param"]]
    print(f"  CoE-mapped: {len(coe_mapped)}")
    print(f"  Param-mapped: {len(param_mapped)}")
    print(f"  Unmapped: {len(unique) - len(coe_mapped) - len(param_mapped)}")

    # Generate scope channel quick-reference
    print(f"\n=== Recommended Scope Channels ===")
    recommended = [
        ("0", "Feedback Position [PUU]"),
        ("9", "Speed Command [r/min]"),
        ("0x36", "Motor Current [%]"),
        ("0x35", "Torque Command [%]"),
        ("2", "Following Error [PUU]"),
        ("0x38", "V Bus Voltage [Volt]"),
        ("0x27", "DI Status"),
        ("0x28", "DO Status"),
    ]
    for mon_idx, desc in recommended:
        coe = MONITOR_TO_COE.get(mon_idx, {})
        coe_str = f"CoE=0x{coe['coe']:04X}" if coe.get("coe") else f"Param={coe.get('param')}"
        print(f"  MonIndex={mon_idx:<6s} → {desc:<30s} ({coe_str})")

    return 0


if __name__ == "__main__":
    sys.exit(main())

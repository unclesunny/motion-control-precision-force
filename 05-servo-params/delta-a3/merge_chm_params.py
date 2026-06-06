"""
Delta A3 CHM Parameter Scraper + ESI Merger
=============================================
Scrapes human-readable parameter descriptions from decompiled ASDA-Soft CHM
help files, merges with ESI XML CoE object data, and generates a complete
parameter reference CSV.

Usage:
  python merge_chm_params.py
"""

import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional


# ============================================================================
# CHM HTML Parser
# ============================================================================


class ParameterHTMLParser(HTMLParser):
    """Extract parameter metadata from a single A3_Px.xxx.html file."""

    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self.in_strong = False
        self.param_number: str = ""
        self.chinese_name: str = ""
        self.raw_rows: Dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag == "strong":
            self.in_strong = True

    def handle_endtag(self, tag):
        if tag == "strong":
            self.in_strong = False

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        self.text_parts.append(data)

    def parse(self) -> dict:
        """After feeding HTML, extract structured parameter data."""
        result = {
            "param_number": "",
            "chinese_name": "",
            "comm_address": "",
            "default_value": "",
            "control_mode": "",
            "unit": "",
            "range": "",
            "data_format": "",
            "data_size": "",
            "function_desc": "",
        }

        text = " | ".join(self.text_parts)

        # Extract parameter number: P0.002
        m = re.search(r"(P\d+\.\d+)", text)
        if m:
            result["param_number"] = m.group(1)

        # Extract Chinese name: the text right after parameter number in <strong>
        # Pattern: "P0.002 | 驱动器状态显示 | 通讯地址"
        for i, part in enumerate(self.text_parts):
            if re.match(r"P\d+\.\d+", part) and i + 1 < len(self.text_parts):
                if "通讯地址" not in self.text_parts[i + 1]:
                    result["chinese_name"] = self.text_parts[i + 1]
                break

        # Extract communication address
        m = re.search(r"通讯地址[：:]\s*(\w+)", text)
        if m:
            result["comm_address"] = m.group(1)

        # Extract default value
        m = re.search(r"初值[：:]\s*(.+?)\s*控制模式", text)
        if m:
            result["default_value"] = m.group(1).strip()

        # Extract control mode
        m = re.search(r"控制模式[：:]\s*(.+?)\s*单位", text)
        if m:
            result["control_mode"] = m.group(1).strip()

        # Extract unit
        m = re.search(r"单位[：:]\s*(.+?)\s*设定范围", text)
        if m:
            result["unit"] = m.group(1).strip()

        # Extract range
        m = re.search(r"设定范围[：:]\s*(.+?)\s*数据格式", text)
        if m:
            result["range"] = m.group(1).strip()

        # Extract data format
        m = re.search(r"数据格式[：:]\s*(.+?)\s*资料大小", text)
        if m:
            result["data_format"] = m.group(1).strip()

        # Extract data size
        m = re.search(r"资料大小[：:]\s*(.+?)$", text.split("参数功能")[0] if "参数功能" in text else text)
        if m:
            result["data_size"] = m.group(1).strip()
        else:
            # Try alternative pattern
            m = re.search(r"资料大小[：:]\s*(.+?)(?:\||$)", text)
            if m:
                result["data_size"] = m.group(1).strip()

        # Extract function description
        if "参数功能" in text:
            func_part = text.split("参数功能")[1]
            func_part = func_part.split("</p>")[0] if "</p>" in func_part else func_part
            # Strip HTML
            func_part = re.sub(r"<[^>]+>", "", func_part)
            result["function_desc"] = func_part.strip().lstrip("：:").strip()

        return result


def scrape_all_params(chm_html_dir: Path) -> List[dict]:
    """Scrape all A3 parameter HTML files in the decompiled CHM directory."""
    param_dir = chm_html_dir / "Parameter"
    if not param_dir.exists():
        print(f"[error] Parameter directory not found: {param_dir}")
        return []

    html_files = sorted(param_dir.glob("A3_P*.html"))
    print(f"[scrape] Found {len(html_files)} parameter HTML files")

    params = []
    for html_file in html_files:
        try:
            with open(html_file, encoding="utf-8") as f:
                html_content = f.read()
        except Exception:
            continue

        parser = ParameterHTMLParser()
        parser.feed(html_content)
        data = parser.parse()

        if data["param_number"]:
            params.append(data)

    print(f"[scrape] Extracted {len(params)} parameters with descriptions")
    return params


# ============================================================================
# ESI + CHM Merger
# ============================================================================


def merge_with_esi(chm_params: List[dict], esi_json_path: Path) -> List[dict]:
    """Merge CHM human-readable data with ESI CoE object dictionary."""
    with open(esi_json_path, encoding="utf-8") as f:
        esi_objects = json.load(f)

    # Build lookup: param number → CHM data
    chm_lookup: Dict[str, dict] = {}
    for p in chm_params:
        # Normalize: "P0.002" → "P0-02"
        m = re.match(r"P(\d+)\.(\d+)", p["param_number"])
        if m:
            key = f"P{m.group(1)}-{int(m.group(2)):02d}"
            chm_lookup[key] = p

    # Merge
    merged = []
    for index_hex, obj in esi_objects.items():
        delta_param = obj.get("delta_param")
        if delta_param and delta_param in chm_lookup:
            chm_data = chm_lookup[delta_param]
            merged.append({
                **obj,
                "chinese_name": chm_data["chinese_name"],
                "unit": chm_data["unit"],
                "range": chm_data["range"],
                "default_value_chm": chm_data["default_value"],
                "control_mode": chm_data["control_mode"],
                "function_desc": chm_data["function_desc"],
            })
        elif obj.get("category") in ("cia402", "communication"):
            merged.append(obj)
        else:
            merged.append(obj)

    print(f"[merge] {len(merged)} total objects ({len(chm_lookup)} with CHM descriptions)")
    return merged


# ============================================================================
# Enhanced CSV Generator
# ============================================================================


def generate_enhanced_csv(merged: List[dict], output_path: Path):
    """Generate enhanced parameter CSV with Chinese descriptions."""
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "参数编号", "CoE Index", "中文名称", "英文名称", "类型", "位宽",
            "访问", "PDO映射", "单位", "设定范围", "默认值", "控制模式",
            "所属组", "示波器通道", "功能说明",
        ])

        # Sort: Delta parameters first (by group), then CiA 402
        def sort_key(obj):
            dp = obj.get("delta_param", "")
            if dp:
                m = re.match(r"P(\d+)-(\d+)", dp)
                if m:
                    return (0, int(m.group(1)), int(m.group(2)))
            return (1, int(obj.get("index", "0xFFFF"), 16), 0)

        for obj in sorted(merged, key=sort_key):
            scope_ch = _scope_channel(obj.get("name", ""))
            writer.writerow([
                obj.get("delta_param", "—"),
                obj.get("index", "—"),
                obj.get("chinese_name", obj.get("name", "")),
                obj.get("name", ""),
                obj.get("type", ""),
                obj.get("bit_size", ""),
                obj.get("access", ""),
                obj.get("pdo_mapping", "—") or "—",
                obj.get("unit", "—"),
                obj.get("range", "—"),
                obj.get("default_value_chm", obj.get("default_data", "—")),
                obj.get("control_mode", "—"),
                obj.get("delta_group", "—"),
                scope_ch,
                obj.get("function_desc", "")[:200],
            ])

    print(f"  [csv]  {output_path}")


def _scope_channel(name: str) -> str:
    name_lower = name.lower()
    ch_map = [
        (["position", "位置"], "CH1 (Position)"),
        (["velocity", "speed", "速度", "转速"], "CH2 (Velocity)"),
        (["current", "电流"], "CH3 (Current)"),
        (["torque", "转矩", "扭矩"], "CH4 (Torque)"),
        (["error", "following", "偏差", "误差"], "CH5 (Error)"),
        (["digital", "input", "output", "di", "do", "输入", "输出"], "CH6 (Digital IO)"),
        (["status", "control", "mode", "状态", "控制", "模式"], "CH8 (Status)"),
        (["gain", "增益", "刚性", "频宽"], "Tuning"),
        (["filter", "notch", "滤波", "陷波", "共振"], "Tuning"),
    ]
    for keywords, ch in ch_map:
        if any(kw in name_lower for kw in keywords):
            return ch
    return "—"


# ============================================================================
# Tuning Parameter Quick Guide
# ============================================================================


def generate_tuning_guide(merged: List[dict], output_path: Path):
    """Generate a tuning parameter quick-reference guide (Markdown)."""
    # Filter: parameters relevant for servo tuning
    tuning_keywords = [
        "增益", "刚性", "频宽", "滤波", "陷波", "共振", "惯量",
        "前馈", "积分", "比例", "微分", "加减速", "平滑",
        "gain", "bandwidth", "filter", "notch", "inertia",
        "feedforward", "integral", "accel", "decel", "smooth",
    ]

    tuning_params = []
    for obj in merged:
        name = obj.get("chinese_name", "") + " " + obj.get("name", "")
        name_lower = name.lower()
        if any(kw.lower() in name_lower for kw in tuning_keywords):
            tuning_params.append(obj)

    # Sort by group
    def sort_key(obj):
        dp = obj.get("delta_param", "")
        if dp:
            m = re.match(r"P(\d+)-(\d+)", dp)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return (99, 0)

    tuning_params.sort(key=sort_key)

    lines = [
        "# Delta A3 — Tuning Parameter Quick Reference",
        "",
        f"> Auto-generated from ASDA-Soft V7.0 CHM + ESI XML. {len(tuning_params)} tuning-relevant parameters.",
        "",
        "| 参数 | CoE | 名称 | 单位 | 范围 | 默认值 | 功能 |",
        "|------|-----|------|------|------|--------|------|",
    ]

    for obj in tuning_params[:80]:
        param = obj.get("delta_param", "—")
        index = obj.get("index", "—")
        name = obj.get("chinese_name", obj.get("name", ""))
        unit = obj.get("unit", "—")
        rng = obj.get("range", "—")
        default = obj.get("default_value_chm", obj.get("default_data", "—"))
        func = (obj.get("function_desc", "") or "")[:60]

        lines.append(f"| {param} | {index} | {name} | {unit} | {rng} | {default} | {func} |")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [tune] {output_path} ({len(tuning_params)} tuning parameters)")


# ============================================================================
# CLI
# ============================================================================


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Delta A3 CHM Parameter Scraper + ESI Merger"
    )
    parser.add_argument("--chm-dir", default=None)
    parser.add_argument("--esi-json", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    # Defaults
    base_dir = Path(__file__).resolve().parent
    chm_dir = Path(args.chm_dir) if args.chm_dir else base_dir / "chm_html"
    esi_json = Path(args.esi_json) if args.esi_json else base_dir / "delta-a3-coe-objects.json"
    output_dir = Path(args.output) if args.output else base_dir

    print("=" * 60)
    print("  Delta A3 CHM Parameter Scraper + ESI Merger")
    print(f"  CHM HTML: {chm_dir}")
    print(f"  ESI JSON: {esi_json}")
    print("=" * 60)

    # Scrape CHM
    print("\n[1/3] Scraping CHM parameter descriptions...")
    chm_params = scrape_all_params(chm_dir)
    if not chm_params:
        print("[error] No parameters extracted from CHM!")
        return 1

    # Sample
    for p in chm_params[:5]:
        print(f"  {p['param_number']}: {p['chinese_name'][:40]} "
              f"(default={p['default_value']}, range={p['range']})")

    # Merge with ESI
    print("\n[2/3] Merging with ESI CoE data...")
    merged = merge_with_esi(chm_params, esi_json)

    # Enhanced CSV
    print("\n[3/3] Generating output files...")
    csv_path = output_dir / "delta-a3-params-full.csv"
    generate_enhanced_csv(merged, csv_path)

    # Tuning guide
    tune_path = output_dir / "delta-a3-tuning-guide.md"
    generate_tuning_guide(merged, tune_path)

    # Merged JSON
    merged_json_path = output_dir / "delta-a3-merged.json"
    with open(merged_json_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"  [json] {merged_json_path}")

    print("\n" + "=" * 60)
    print(f"  Done. {len(merged)} total objects in parameter library.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

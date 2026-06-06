"""
Delta A3 EtherCAT CoE Object Dictionary Extractor
==================================================
Parses Delta ASDA-x3-E ESI XML and extracts complete CoE object dictionary.

Outputs:
  - delta-a3-coe-objects.json   — Full object dictionary (all 2,079 objects)
  - delta-a3-pdo-mapping.json   — PDO-mappable objects (RxPDO + TxPDO)
  - delta-a3-params.csv         — Human-readable parameter CSV (Delta P0-P9 format)
  - delta-a3-quickref.json      — Quick-reference: key CiA 402 + scope-relevant objects

Usage:
  python extract_esi.py
  python extract_esi.py --xml "path/to/Delta ASDA-x3-E rev0.05.xml"
"""

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class SubItem:
    """A sub-index entry within a complex DataType."""
    sub_idx: int
    name: str
    type_name: str
    bit_size: int
    bit_offs: int
    access: str = "ro"
    pdo_mapping: str = ""  # "R", "T", "RT", or ""


@dataclass
class CoEObject:
    """A single CoE object dictionary entry."""
    index: int  # hex index, e.g. 0x6078
    name: str
    type_name: str  # e.g. "INT", "UDINT", "DT607D"
    bit_size: int
    access: str = "ro"
    pdo_mapping: str = ""  # "R", "T", "RT", or ""
    default_data: Optional[str] = None
    sub_items: List[SubItem] = field(default_factory=list)
    category: str = ""  # "communication", "delta_param", "cia402", "manufacturer"

    # Inferred Delta parameter mapping
    delta_param: Optional[str] = None  # e.g. "P0-01"
    delta_group: Optional[str] = None  # e.g. "P0", "P1", ...

    @property
    def index_hex(self) -> str:
        return f"0x{self.index:04X}"

    @property
    def is_pdo_mappable(self) -> bool:
        return bool(self.pdo_mapping)

    @property
    def is_readable(self) -> bool:
        return "ro" in self.access or "rw" in self.access

    @property
    def is_writable(self) -> bool:
        return "rw" in self.access or "wo" in self.access

    def to_dict(self) -> dict:
        d = {
            "index": self.index_hex,
            "name": self.name,
            "type": self.type_name,
            "bit_size": self.bit_size,
            "access": self.access,
            "pdo_mapping": self.pdo_mapping or None,
            "default_data": self.default_data,
            "category": self.category,
            "delta_param": self.delta_param,
            "delta_group": self.delta_group,
        }
        if self.sub_items:
            d["sub_items"] = [
                {
                    "sub_idx": si.sub_idx,
                    "name": si.name,
                    "type": si.type_name,
                    "bit_size": si.bit_size,
                    "access": si.access,
                    "pdo_mapping": si.pdo_mapping or None,
                }
                for si in self.sub_items
            ]
        return d


# ============================================================================
# ESI XML Parser
# ============================================================================


class ESIParser:
    """Parse Delta ASDA-x3-E ESI XML and extract CoE object dictionary."""

    # Delta param range: P0-xx → 0x2000+xx, P1-xx → 0x2100+xx, ..., P9-xx → 0x2900+xx
    DELTA_PARAM_BASE = {i: 0x2000 + i * 0x100 for i in range(10)}

    # CiA 402 drive profile objects
    CIA402_RANGE = (0x6000, 0x6FFF)
    COMMUNICATION_RANGE = (0x1000, 0x1FFF)
    MANUFACTURER_RANGE = (0x2000, 0x5FFF)

    # Key objects for oscilloscope (what we care about most)
    SCOPE_OBJECTS = {
        0x6040: "Control word",
        0x6041: "Status word",
        0x6060: "Modes of operation",
        0x6061: "Modes of operation display",
        0x6062: "Position demand value",
        0x6063: "Position actual internal value",
        0x6064: "Position actual value",
        0x6068: "Position window",
        0x606C: "Velocity actual value",
        0x6071: "Target torque",
        0x6074: "Torque demand",
        0x6077: "Torque actual value",
        0x6078: "Current actual value",
        0x607A: "Target position",
        0x607F: "Max profile velocity",
        0x6081: "Profile velocity",
        0x6083: "Profile acceleration",
        0x6084: "Profile deceleration",
        0x6085: "Quick stop deceleration",
        0x60B1: "Velocity offset",
        0x60B2: "Torque offset",
        0x60C1: "Interpolation data record",
        0x60F4: "Following error actual value",
        0x60FC: "Position demand internal value",
        0x60FD: "Digital inputs",
        0x60FE: "Digital outputs",
        0x6502: "Supported drive modes",
    }

    def __init__(self, xml_path: str):
        self.xml_path = Path(xml_path)
        self.tree = None
        self.data_types: Dict[str, List[SubItem]] = {}  # DataType name → sub items
        self.objects: List[CoEObject] = []

    def parse(self) -> List[CoEObject]:
        """Parse the ESI XML and return all CoE objects."""
        print(f"[parse] Loading: {self.xml_path}")
        self.tree = ET.parse(self.xml_path)
        root = self.tree.getroot()

        # Step 1: Parse DataTypes (complex types with SubItems)
        self._parse_data_types(root)

        # Step 2: Parse Objects
        self._parse_objects(root)

        print(f"[parse] Extracted: {len(self.data_types)} complex types, "
              f"{len(self.objects)} objects")
        return self.objects

    def _parse_data_types(self, root: ET.Element):
        """Parse DataType definitions (DTxxxx) with SubItems."""
        ns = self._get_ns(root)
        dict_elem = root.find(f".//{{{ns}}}Dictionary")
        if dict_elem is None:
            # Try without namespace
            dict_elem = root.find(".//Dictionary")
        if dict_elem is None:
            print("[warn] No Dictionary element found")
            return

        data_types_elem = dict_elem.find(f"{{{ns}}}DataTypes")
        if data_types_elem is None:
            data_types_elem = dict_elem.find("DataTypes")
        if data_types_elem is None:
            return

        for dt in data_types_elem.findall(f"{{{ns}}}DataType") or data_types_elem.findall("DataType"):
            name_elem = dt.find(f"{{{ns}}}Name") or dt.find("Name")
            if name_elem is None or not name_elem.text:
                continue
            name = name_elem.text.strip()

            sub_items = []
            for si in dt.findall(f"{{{ns}}}SubItem") or dt.findall("SubItem"):
                sub_idx_elem = si.find(f"{{{ns}}}SubIdx") or si.find("SubIdx")
                si_name_elem = si.find(f"{{{ns}}}Name") or si.find("Name")
                si_type_elem = si.find(f"{{{ns}}}Type") or si.find("Type")
                si_bitsize_elem = si.find(f"{{{ns}}}BitSize") or si.find("BitSize")
                si_bitoffs_elem = si.find(f"{{{ns}}}BitOffs") or si.find("BitOffs")
                flags_elem = si.find(f"{{{ns}}}Flags") or si.find("Flags")

                access = "ro"
                pdo_mapping = ""
                if flags_elem is not None:
                    acc = flags_elem.find(f"{{{ns}}}Access") or flags_elem.find("Access")
                    pdo = flags_elem.find(f"{{{ns}}}PdoMapping") or flags_elem.find("PdoMapping")
                    if acc is not None and acc.text:
                        access = acc.text.strip()
                    if pdo is not None and pdo.text:
                        pdo_mapping = pdo.text.strip()

                sub_items.append(SubItem(
                    sub_idx=int(sub_idx_elem.text) if sub_idx_elem is not None and sub_idx_elem.text else 0,
                    name=si_name_elem.text.strip() if si_name_elem is not None and si_name_elem.text else "",
                    type_name=si_type_elem.text.strip() if si_type_elem is not None and si_type_elem.text else "",
                    bit_size=int(si_bitsize_elem.text) if si_bitsize_elem is not None and si_bitsize_elem.text else 0,
                    bit_offs=int(si_bitoffs_elem.text) if si_bitoffs_elem is not None and si_bitoffs_elem.text else 0,
                    access=access,
                    pdo_mapping=pdo_mapping,
                ))

            self.data_types[name] = sub_items

    def _parse_objects(self, root: ET.Element):
        """Parse all Object entries in the dictionary."""
        ns = self._get_ns(root)
        objects_elem = root.find(f".//{{{ns}}}Objects")
        if objects_elem is None:
            objects_elem = root.find(".//Objects")
        if objects_elem is None:
            return

        for obj in objects_elem.findall(f"{{{ns}}}Object") or objects_elem.findall("Object"):
            coe = self._parse_single_object(obj, ns)
            if coe:
                self.objects.append(coe)

    def _parse_single_object(self, obj_elem: ET.Element, ns: str) -> Optional[CoEObject]:
        """Parse a single Object element."""
        index_elem = obj_elem.find(f"{{{ns}}}Index") or obj_elem.find("Index")
        name_elem = obj_elem.find(f"{{{ns}}}Name") or obj_elem.find("Name")
        type_elem = obj_elem.find(f"{{{ns}}}Type") or obj_elem.find("Type")
        bitsize_elem = obj_elem.find(f"{{{ns}}}BitSize") or obj_elem.find("BitSize")
        flags_elem = obj_elem.find(f"{{{ns}}}Flags") or obj_elem.find("Flags")
        info_elem = obj_elem.find(f"{{{ns}}}Info") or obj_elem.find("Info")

        if index_elem is None or not index_elem.text:
            return None

        # Parse index: "#x6078" → 0x6078
        index_str = index_elem.text.strip()
        index = int(index_str.replace("#x", ""), 16)

        name = name_elem.text.strip() if name_elem is not None and name_elem.text else ""
        type_name = type_elem.text.strip() if type_elem is not None and type_elem.text else "UNKNOWN"
        bit_size = int(bitsize_elem.text) if bitsize_elem is not None and bitsize_elem.text else 0

        # Parse flags
        access = "ro"
        pdo_mapping = ""
        if flags_elem is not None:
            acc = flags_elem.find(f"{{{ns}}}Access") or flags_elem.find("Access")
            pdo = flags_elem.find(f"{{{ns}}}PdoMapping") or flags_elem.find("PdoMapping")
            if acc is not None and acc.text:
                access = acc.text.strip()
            if pdo is not None and pdo.text:
                pdo_mapping = pdo.text.strip()

        # Parse default data
        default_data = None
        if info_elem is not None:
            dd = info_elem.find(f"{{{ns}}}DefaultData") or info_elem.find("DefaultData")
            if dd is not None and dd.text:
                default_data = dd.text.strip()

        # Get sub-items from DataType if complex
        sub_items = []
        if type_name.startswith("DT") and type_name in self.data_types:
            sub_items = self.data_types[type_name]

        # Categorize
        category = self._categorize(index)

        # Delta parameter inference
        delta_param, delta_group = self._infer_delta_param(index, name)

        return CoEObject(
            index=index,
            name=name,
            type_name=type_name,
            bit_size=bit_size,
            access=access,
            pdo_mapping=pdo_mapping,
            default_data=default_data,
            sub_items=sub_items,
            category=category,
            delta_param=delta_param,
            delta_group=delta_group,
        )

    def _categorize(self, index: int) -> str:
        if self.COMMUNICATION_RANGE[0] <= index <= self.COMMUNICATION_RANGE[1]:
            return "communication"
        elif self.CIA402_RANGE[0] <= index <= self.CIA402_RANGE[1]:
            return "cia402"
        elif self.MANUFACTURER_RANGE[0] <= index <= self.MANUFACTURER_RANGE[1]:
            return "delta_param"
        return "other"

    def _infer_delta_param(self, index: int, name: str) -> Tuple[Optional[str], Optional[str]]:
        """Infer Delta Px-xx parameter number from CoE index."""
        for group_id, base_addr in self.DELTA_PARAM_BASE.items():
            if base_addr <= index < base_addr + 0x100:
                offset = index - base_addr
                param = f"P{group_id}-{offset:02d}"
                return param, f"P{group_id}"
        # Try from name
        m = re.search(r"P(\d)-(\d+)", name)
        if m:
            return f"P{m.group(1)}-{int(m.group(2)):02d}", f"P{m.group(1)}"
        return None, None

    def _get_ns(self, root: ET.Element) -> str:
        """Extract XML namespace from root."""
        tag = root.tag
        if "}" in tag:
            return tag.split("}")[0].strip("{")
        return ""


# ============================================================================
# Report Generators
# ============================================================================


def generate_json(objects: List[CoEObject], output_dir: Path) -> dict:
    """Generate full JSON object dictionary."""
    all_objects = {obj.index_hex: obj.to_dict() for obj in objects}
    output_path = output_dir / "delta-a3-coe-objects.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_objects, f, indent=2, ensure_ascii=False)
    print(f"  [json] {output_path} ({len(all_objects)} objects)")
    return all_objects


def generate_pdo_map(objects: List[CoEObject], output_dir: Path):
    """Generate PDO-mappable objects JSON."""
    # RxPDO mappable (master → drive): position/velocity/torque commands
    rx_pdo = [obj.to_dict() for obj in objects
              if obj.is_pdo_mappable and ("R" in obj.pdo_mapping or "RT" in obj.pdo_mapping)]

    # TxPDO mappable (drive → master): actual position/velocity/current feedback
    tx_pdo = [obj.to_dict() for obj in objects
              if obj.is_pdo_mappable and ("T" in obj.pdo_mapping or "RT" in obj.pdo_mapping)]

    pdo_map = {
        "rx_pdo": rx_pdo,
        "tx_pdo": tx_pdo,
        "rx_pdo_count": len(rx_pdo),
        "tx_pdo_count": len(tx_pdo),
        "scope_signals": {
            "position": _find_scope_signal(tx_pdo, ["position actual", "position"]),
            "velocity": _find_scope_signal(tx_pdo, ["velocity actual", "velocity"]),
            "torque": _find_scope_signal(tx_pdo, ["torque actual", "torque"]),
            "current": _find_scope_signal(tx_pdo, ["current actual", "current"]),
            "following_error": _find_scope_signal(tx_pdo, ["following error"]),
            "digital_inputs": _find_scope_signal(tx_pdo, ["digital input"]),
        },
    }

    output_path = output_dir / "delta-a3-pdo-mapping.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pdo_map, f, indent=2, ensure_ascii=False)
    print(f"  [pdo]  {output_path} (RxPDO:{pdo_map['rx_pdo_count']}, TxPDO:{pdo_map['tx_pdo_count']})")
    return pdo_map


def _find_scope_signal(pdo_list: list, keywords: List[str]) -> Optional[dict]:
    """Find the most relevant PDO signal for oscilloscope channels."""
    for kw in keywords:
        for pdo in pdo_list:
            if kw.lower() in pdo["name"].lower():
                return {"index": pdo["index"], "name": pdo["name"], "type": pdo["type"]}
    return None


def generate_param_csv(objects: List[CoEObject], output_dir: Path):
    """Generate Delta A3 parameter CSV (human-readable, in 汇川-SV660 format style)."""
    output_path = output_dir / "delta-a3-params.csv"

    # Filter: only Delta P0-P9 parameters with clear names
    param_objects = [obj for obj in objects if obj.delta_param is not None]
    param_objects.sort(key=lambda o: (o.delta_group or "", o.index))

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "参数编号", "CoE Index", "参数名称", "类型", "位宽",
            "访问", "PDO映射", "默认值", "所属组", "示波器推荐通道",
        ])

        for obj in param_objects:
            # Suggest scope channel based on name
            scope_channel = _suggest_scope_channel(obj.name)

            writer.writerow([
                obj.delta_param,
                obj.index_hex,
                obj.name,
                obj.type_name,
                obj.bit_size,
                obj.access,
                obj.pdo_mapping or "-",
                obj.default_data or "-",
                obj.delta_group or "-",
                scope_channel,
            ])

    print(f"  [csv]  {output_path} ({len(param_objects)} Delta parameters)")


def _suggest_scope_channel(name: str) -> str:
    """Suggest oscilloscope channel based on parameter name."""
    name_lower = name.lower()
    suggestions = {
        "position": "CH1 (Position)",
        "velocity": "CH2 (Velocity)",
        "current": "CH3 (Current)",
        "torque": "CH4 (Torque)",
        "error": "CH5 (Error)",
        "speed": "CH2 (Velocity)",
        "acc": "CH6 (Acceleration)",
        "gain": "— (Tuning)",
        "filter": "— (Tuning)",
        "notch": "— (Tuning)",
        "limit": "— (Limits)",
        "control": "— (Control)",
        "status": "— (Status)",
        "mode": "— (Mode)",
        "input": "CH7 (Digital IO)",
        "output": "CH7 (Digital IO)",
    }
    for kw, ch in suggestions.items():
        if kw in name_lower:
            return ch
    return "—"


def generate_quickref(objects: List[CoEObject], output_dir: Path):
    """Generate quick-reference JSON for the most important objects."""
    scope_objects = []
    for obj in objects:
        if obj.index in ESIParser.SCOPE_OBJECTS:
            d = obj.to_dict()
            d["scope_label"] = ESIParser.SCOPE_OBJECTS[obj.index]
            scope_objects.append(d)

    # Also add critical Delta parameters for tuning
    tuning_params = [
        obj.to_dict() for obj in objects
        if obj.delta_param and any(kw in obj.name.lower() for kw in [
            "gain", "filter", "notch", "rigidity", "inertia",
            "auto", "bandwidth", "resonance", "friction", "backlash",
            "feedforward", "integral", "proportional",
        ])
    ]

    quickref = {
        "cia402_scope_objects": sorted(scope_objects, key=lambda o: o["index"]),
        "tuning_parameters": sorted(tuning_params, key=lambda o: o["index"]),
        "cia402_count": len(scope_objects),
        "tuning_count": len(tuning_params),
    }

    output_path = output_dir / "delta-a3-quickref.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(quickref, f, indent=2, ensure_ascii=False)
    print(f"  [ref]  {output_path} ({quickref['cia402_count']} scope + {quickref['tuning_count']} tuning)")


def generate_scope_config(objects: List[CoEObject], output_dir: Path):
    """Generate oscilloscope channel configuration file.

    Maps EtherCAT PDO signals to oscilloscope channels — this is the
    bridge between the EtherCAT master and the oscilloscope UI.
    """
    scope_config = {
        "channels": [
            {
                "id": "CH1",
                "label": "Position",
                "unit": "pulses / user units",
                "sources": [],
            },
            {
                "id": "CH2",
                "label": "Velocity",
                "unit": "rpm / user units",
                "sources": [],
            },
            {
                "id": "CH3",
                "label": "Current",
                "unit": "% rated / A",
                "sources": [],
            },
            {
                "id": "CH4",
                "label": "Torque",
                "unit": "% rated / Nm",
                "sources": [],
            },
            {
                "id": "CH5",
                "label": "Following Error",
                "unit": "pulses",
                "sources": [],
            },
            {
                "id": "CH6",
                "label": "Digital IO",
                "unit": "bitfield",
                "sources": [],
            },
            {
                "id": "CH7",
                "label": "User Analog / Custom",
                "unit": "V / user units",
                "sources": [],
            },
            {
                "id": "CH8",
                "label": "Profile / Status",
                "unit": "—",
                "sources": [],
            },
        ],
        "trigger_sources": [],
        "sample_rate_max_hz": 10000,
        "dc_cycle_us": 1000,
    }

    # Map: object name keyword → channel
    channel_map = {
        "CH1": ["position actual value", "position actual internal", "position demand"],
        "CH2": ["velocity actual value", "velocity", "speed"],
        "CH3": ["current actual value", "current"],
        "CH4": ["torque actual value", "torque"],
        "CH5": ["following error", "position window"],
        "CH6": ["digital input", "digital output", "physical output"],
        "CH8": ["status word", "control word", "modes of operation"],
    }

    for obj in objects:
        if not obj.is_pdo_mappable:
            continue
        name_lower = obj.name.lower()
        for ch_id, keywords in channel_map.items():
            if any(kw in name_lower for kw in keywords):
                # Find the channel
                for ch in scope_config["channels"]:
                    if ch["id"] == ch_id:
                        ch["sources"].append({
                            "index": obj.index_hex,
                            "name": obj.name,
                            "type": obj.type_name,
                            "bit_size": obj.bit_size,
                            "pdo_dir": obj.pdo_mapping,
                        })
                        break

    # Trigger sources: objects that change state
    trigger_keywords = ["status", "error", "limit", "following error", "digital input"]
    for obj in objects:
        name_lower = obj.name.lower()
        if any(kw in name_lower for kw in trigger_keywords):
            scope_config["trigger_sources"].append({
                "index": obj.index_hex,
                "name": obj.name,
                "access": obj.access,
            })

    output_path = output_dir / "delta-a3-scope-config.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scope_config, f, indent=2, ensure_ascii=False)

    total_sources = sum(len(ch["sources"]) for ch in scope_config["channels"])
    print(f"  [scope] {output_path} ({total_sources} signal sources, "
          f"{len(scope_config['trigger_sources'])} trigger sources)")


# ============================================================================
# Summary
# ============================================================================


def print_summary(objects: List[CoEObject]):
    """Print extraction summary."""
    categories = defaultdict(int)
    pdo_count = 0
    delta_params = 0
    cia402_count = 0

    for obj in objects:
        categories[obj.category] += 1
        if obj.is_pdo_mappable:
            pdo_count += 1
        if obj.delta_param:
            delta_params += 1
        if obj.category == "cia402":
            cia402_count += 1

    print(f"\n{'='*60}")
    print(f"  Delta A3 CoE Object Dictionary — Extraction Summary")
    print(f"{'='*60}")
    print(f"  Total objects:      {len(objects)}")
    print(f"  Communication:      {categories['communication']}")
    print(f"  Delta parameters:   {categories['delta_param']} ({delta_params} with Px-xx notation)")
    print(f"  CiA 402 profile:    {categories['cia402']}")
    print(f"  Other:              {categories['other']}")
    print(f"  PDO-mappable:       {pdo_count}")
    print(f"  Read-only:          {sum(1 for o in objects if o.access == 'ro')}")
    print(f"  Read-write:         {sum(1 for o in objects if 'rw' in o.access)}")
    print(f"{'='*60}")


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Delta A3 EtherCAT CoE Object Dictionary Extractor"
    )
    parser.add_argument(
        "--xml",
        default=None,
        help="Path to Delta ASDA-x3-E ESI XML file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: current directory)",
    )
    args = parser.parse_args()

    # Auto-detect ESI XML
    if args.xml:
        xml_path = args.xml
    else:
        # Search common locations
        candidates = [
            Path(r"D:\Solution Pack\C#\DELTA_IA-IPC_EtherCAT-X64_SW_TSE_20220816\program files\Delta Industrial Automation\EtherCAT\EtherCAT\ESI\Delta ASDA-x3-E rev0.05.xml"),
            Path(r"D:\Solution Pack\C#\DELTA_IA-IPC_EtherCAT-X64_SW_TSE_20220816\program files\Delta Industrial Automation\EtherCAT\EtherCAT\ESI\Delta ASDA-x3-E rev0.02.xml"),
        ]
        xml_path = None
        for c in candidates:
            if c.exists():
                xml_path = str(c)
                break
        if not xml_path:
            print("[error] ESI XML not found. Use --xml to specify path.")
            return 1

    output_dir = Path(args.output) if args.output else Path.cwd()

    print("=" * 60)
    print("  Delta A3 EtherCAT CoE Object Dictionary Extractor")
    print(f"  Source: {xml_path}")
    print(f"  Output: {output_dir}")
    print("=" * 60)

    # Parse
    parser_obj = ESIParser(xml_path)
    objects = parser_obj.parse()

    if not objects:
        print("[error] No objects extracted!")
        return 1

    # Generate outputs
    print("\n[export] Generating output files...")
    generate_json(objects, output_dir)
    generate_pdo_map(objects, output_dir)
    generate_param_csv(objects, output_dir)
    generate_quickref(objects, output_dir)
    generate_scope_config(objects, output_dir)

    # Summary
    print_summary(objects)

    return 0


if __name__ == "__main__":
    sys.exit(main())

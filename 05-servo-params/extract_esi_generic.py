"""
Generalized EtherCAT ESI XML → CoE Object Dictionary Parser.

Handles both formats:
  A) Delta A3 custom XML (<CoE> → <Group> → <Object>)
  B) Standard ETG.2000 XML (<Profile> → <Dictionary> → <Objects> → <Object>)

Usage:
    python extract_esi_generic.py --xml path/to/esi.xml --brand panasonic-a6
    python extract_esi_generic.py --xml path/to/esi.xml --brand yaskawa-sigma5
    python extract_esi_generic.py --all   # scan all ESI files in subdirectories
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

# ── Data Models ─────────────────────────────────────────────


@dataclass
class CoEObject:
    """A single CoE object dictionary entry."""
    index: int
    name: str
    type_name: str = ""
    bit_size: int = 0
    access: str = "ro"
    pdo_mapping: str = ""  # "R", "T", "RT", or ""
    default_data: Optional[str] = None
    category: str = ""  # "cia402", "manufacturer", "communication"

    @property
    def index_hex(self) -> str:
        return f"0x{self.index:04X}"

    @property
    def is_pdo_mappable(self) -> bool:
        return bool(self.pdo_mapping)

    def to_dict(self) -> dict:
        return {
            "index": self.index_hex,
            "name": self.name,
            "type": self.type_name,
            "bit_size": self.bit_size,
            "access": self.access,
            "pdo_mapping": self.pdo_mapping,
            "default": self.default_data,
            "category": self.category,
        }


@dataclass
class PdoMapping:
    """PDO mapping entry."""
    index: int  # 0x1600 (RxPDO) or 0x1A00 (TxPDO)
    name: str
    direction: str  # "Rx" or "Tx"
    entries: List[dict] = field(default_factory=list)
    sm: int = 0

    def to_dict(self) -> dict:
        return {
            "index": f"0x{self.index:04X}",
            "name": self.name,
            "direction": self.direction,
            "sm": self.sm,
            "entries": self.entries,
        }


# ── Parser ──────────────────────────────────────────────────


class ESIParser:
    """Parse EtherCAT ESI XML and extract CoE object dictionary."""

    # CiA 402 standard object ranges
    CIA402_RANGES = [
        (0x1000, 0x1FFF, "communication"),
        (0x2000, 0x2FFF, "manufacturer"),
        (0x3000, 0x3FFF, "manufacturer"),
        (0x4000, 0x5FFF, "manufacturer"),
        (0x6000, 0x6FFF, "cia402"),
        (0x7000, 0x7FFF, "manufacturer"),
    ]

    def __init__(self, xml_path: Path):
        self.xml_path = Path(xml_path)
        self.tree = ET.parse(str(self.xml_path))
        self.root = self.tree.getroot()
        self.ns = self._detect_namespace()

    def _detect_namespace(self) -> str:
        """Extract XML namespace if present."""
        tag = self.root.tag
        if "}" in tag:
            return tag.split("}")[0].lstrip("{")
        return ""

    def _findall(self, element, tag: str):
        """Search with or without namespace."""
        if self.ns:
            return element.findall(f"{{{self.ns}}}{tag}")
        return element.findall(tag)

    def _find(self, element, tag: str):
        """Find first with or without namespace."""
        if self.ns:
            return element.find(f"{{{self.ns}}}{tag}")
        return element.find(tag)

    def _parse_hex(self, text: str) -> int:
        """Parse hex string like '#x6064' or '0x6064' or '24676'."""
        text = text.strip()
        if text.startswith("#x") or text.startswith("0x"):
            return int(text.replace("#x", "").replace("0x", ""), 16)
        try:
            return int(text)
        except ValueError:
            return 0

    def _classify(self, index: int) -> str:
        for lo, hi, cat in self.CIA402_RANGES:
            if lo <= index <= hi:
                return cat
        return "unknown"

    def extract_vendor_info(self) -> dict:
        """Extract vendor ID and name."""
        vendor = self._find(self.root, "Vendor")
        if vendor is None:
            return {"id": "unknown", "name": "unknown"}
        vid = self._find(vendor, "Id")
        vname = self._find(vendor, "Name")
        return {
            "id": vid.text.strip() if vid is not None and vid.text else "unknown",
            "name": vname.text.strip() if vname is not None and vname.text else "unknown",
        }

    def extract_device_info(self) -> dict:
        """Extract device type and product code."""
        for device in self.root.iter("Device"):
            dev_type = self._find(device, "Type")
            product_code = dev_type.get("ProductCode", "") if dev_type is not None else ""
            name = self._find(device, "Name")
            return {
                "type": dev_type.text.strip() if dev_type is not None and dev_type.text else "",
                "product_code": product_code,
                "name": name.text.strip() if name is not None and name.text else "",
            }
        return {}

    # ── Format A: Delta A3-style ──────────────────────────

    def _parse_delta_a3(self) -> List[CoEObject]:
        """Parse Delta A3 custom CoE format."""
        objects = []
        for coe in self.root.iter("CoE"):
            for group in coe:
                for obj_elem in group:
                    idx = self._parse_hex(obj_elem.get("Index", "0"))
                    if idx == 0:
                        continue
                    coe_obj = CoEObject(
                        index=idx,
                        name=obj_elem.get("Name", ""),
                        type_name=obj_elem.get("DataType", ""),
                        bit_size=int(obj_elem.get("BitSize", 0)),
                        access=obj_elem.get("Access", "ro"),
                        pdo_mapping=obj_elem.get("PDOMapping", ""),
                        default_data=obj_elem.get("DefaultData"),
                        category=self._classify(idx),
                    )
                    objects.append(coe_obj)
        return objects

    # ── Format B: ETG.2000 standard ───────────────────────

    def _parse_etg2000_dict(self) -> List[CoEObject]:
        """Parse standard ETG.2000 Dictionary → Objects format (Yaskawa-style)."""
        objects = []
        for profile in self.root.iter("Profile"):
            dictionary = self._find(profile, "Dictionary")
            if dictionary is None:
                continue
            data_types = self._parse_data_types(dictionary)
            objects_elem = self._find(dictionary, "Objects")
            if objects_elem is None:
                continue

            for obj_elem in objects_elem:
                obj = self._parse_etg2000_object(obj_elem, data_types)
                if obj:
                    objects.append(obj)
        return objects

    def _parse_data_types(self, dictionary) -> Dict[int, str]:
        """Parse DataTypes section to map type indices to names."""
        types = {}
        data_types_elem = self._find(dictionary, "DataTypes")
        if data_types_elem is None:
            return types
        for dt in data_types_elem:
            idx = self._parse_hex(dt.find("Index").text if dt.find("Index") is not None else "0")
            name = dt.find("Name").text if dt.find("Name") is not None else ""
            bit_size_elem = dt.find("BitSize")
            bit_size = int(bit_size_elem.text) if bit_size_elem is not None else 0
            types[idx] = f"{name}:{bit_size}" if name else f"DT{idx}"
        return types

    def _parse_etg2000_object(self, obj_elem, data_types: Dict[int, str]) -> Optional[CoEObject]:
        """Parse a single Object element in ETG.2000 format."""
        idx_elem = obj_elem.find("Index")
        if idx_elem is None:
            return None

        idx_text = idx_elem.text or ""
        # Handle hex like '#x6064'
        index = self._parse_hex(idx_text)

        name_elem = obj_elem.find("Name")
        name = name_elem.text.strip() if name_elem is not None and name_elem.text else f"Object 0x{index:04X}"

        type_elem = obj_elem.find("Type")
        type_name = type_elem.text.strip() if type_elem is not None and type_elem.text else ""
        # Resolve data type reference
        if type_name and type_name.isdigit():
            dt_idx = int(type_name)
            type_name = data_types.get(dt_idx, f"DT{dt_idx}")

        bit_size = 0
        bit_size_elem = obj_elem.find("BitSize")
        if bit_size_elem is not None and bit_size_elem.text:
            bit_size = int(bit_size_elem.text)

        access = "ro"
        flags_elem = obj_elem.find("Flags")
        if flags_elem is not None:
            access_elem = flags_elem.find("Access")
            if access_elem is not None and access_elem.text:
                access = access_elem.text.lower()

        # Check PDO mapping
        pdo_mapping = ""
        info_elem = obj_elem.find("Info")
        if info_elem is not None:
            pdo_elem = info_elem.find("Pdo")
            if pdo_elem is not None:
                pdo_mapping = "T"  # at least TxPDO
            # Check sub-items
            for sub in info_elem:
                sub_pdo = sub.find("Pdo")
                if sub_pdo is not None and sub_pdo.text:
                    pdo_mapping = "T"

        default = None
        default_elem = obj_elem.find("DefaultData")
        if default_elem is not None and default_elem.text:
            default = default_elem.text

        # Also check <Info> → <DefaultData>
        if info_elem is not None:
            dd = info_elem.find("DefaultData")
            if dd is not None and dd.text:
                default = dd.text

        return CoEObject(
            index=index,
            name=name,
            type_name=type_name,
            bit_size=bit_size,
            access=access,
            pdo_mapping=pdo_mapping,
            default_data=default,
            category=self._classify(index),
        )

    # ── PDO mapping extraction ────────────────────────────

    def extract_pdo_mappings(self) -> List[PdoMapping]:
        """Extract RxPDO and TxPDO mappings."""
        mappings = []

        for device in self.root.iter("Device"):
            # RxPDO
            for rx in device.findall("RxPdo"):
                sm = int(rx.get("Sm", "0"))
                idx = self._parse_hex(rx.find("Index").text) if rx.find("Index") is not None else 0
                name = rx.find("Name").text if rx.find("Name") is not None else "RxPDO"
                entries = []
                for entry in rx.findall("Entry"):
                    e_idx = self._parse_hex(entry.find("Index").text) if entry.find("Index") is not None else 0
                    e_name = entry.find("Name").text if entry.find("Name") is not None else ""
                    e_type = entry.find("DataType").text if entry.find("DataType") is not None else ""
                    e_bits = int(entry.find("BitLen").text) if entry.find("BitLen") is not None else 0
                    entries.append({
                        "index": f"0x{e_idx:04X}", "name": e_name,
                        "type": e_type, "bit_size": e_bits,
                    })
                mappings.append(PdoMapping(
                    index=idx or 0x1600, name=name, direction="Rx",
                    entries=entries, sm=sm,
                ))

            # TxPDO
            for tx in device.findall("TxPdo"):
                sm = int(tx.get("Sm", "0"))
                idx = self._parse_hex(tx.find("Index").text) if tx.find("Index") is not None else 0
                name = tx.find("Name").text if tx.find("Name") is not None else "TxPDO"
                entries = []
                for entry in tx.findall("Entry"):
                    e_idx = self._parse_hex(entry.find("Index").text) if entry.find("Index") is not None else 0
                    e_name = entry.find("Name").text if entry.find("Name") is not None else ""
                    e_type = entry.find("DataType").text if entry.find("DataType") is not None else ""
                    e_bits = int(entry.find("BitLen").text) if entry.find("BitLen") is not None else 0
                    entries.append({
                        "index": f"0x{e_idx:04X}", "name": e_name,
                        "type": e_type, "bit_size": e_bits,
                    })
                mappings.append(PdoMapping(
                    index=idx or 0x1A00, name=name, direction="Tx",
                    entries=entries, sm=sm,
                ))

        return mappings

    # ── Format C: PDO-embedded (Panasonic-style) ──────────

    def _parse_pdo_objects(self) -> List[CoEObject]:
        """Extract CoE objects from PDO entries (Panasonic format — no Dictionary)."""
        objects = {}
        for pdo in self.root.iter("RxPdo"):
            for entry in pdo.findall("Entry"):
                self._add_pdo_entry(entry, "R", objects)
        for pdo in self.root.iter("TxPdo"):
            for entry in pdo.findall("Entry"):
                self._add_pdo_entry(entry, "T", objects)
        return sorted(objects.values(), key=lambda o: o.index)

    def _add_pdo_entry(self, entry, direction: str, objects: Dict[int, CoEObject]):
        """Add or update object from PDO entry."""
        idx_elem = entry.find("Index")
        if idx_elem is None or not idx_elem.text:
            return
        index = self._parse_hex(idx_elem.text)
        if index == 0:
            return

        name = entry.find("Name").text if entry.find("Name") is not None else ""
        data_type = entry.find("DataType").text if entry.find("DataType") is not None else ""
        bit_len = int(entry.find("BitLen").text) if entry.find("BitLen") is not None and entry.find("BitLen").text else 0

        if index in objects:
            # Update PDO mapping direction
            existing = objects[index]
            if direction == "R" and existing.pdo_mapping != "T":
                existing.pdo_mapping = "R"
            elif direction == "T" and existing.pdo_mapping != "R":
                existing.pdo_mapping = "T"
            else:
                existing.pdo_mapping = "RT"
        else:
            objects[index] = CoEObject(
                index=index,
                name=name,
                type_name=data_type,
                bit_size=bit_len,
                access="rw" if direction == "R" else "ro",
                pdo_mapping=direction,
                category=self._classify(index),
            )

    # ── Dispatch ───────────────────────────────────────────

    def extract_objects(self) -> List[CoEObject]:
        """Auto-detect format and extract CoE objects."""
        objects = []

        # Try ETG.2000 format first (has <Profile> → <Dictionary>)
        profiles = list(self.root.iter("Profile"))
        if profiles:
            objects = self._parse_etg2000_dict()

        # Try Delta A3 format (has <CoE>)
        coe_elems = list(self.root.iter("CoE"))
        if coe_elems:
            delta_objs = self._parse_delta_a3()
            existing = {o.index for o in objects}
            for obj in delta_objs:
                if obj.index not in existing:
                    objects.append(obj)
                    existing.add(obj.index)

        # Always merge PDO-embedded objects (many brands put CiA 402 objects
        # like 0x6064/0x6078 only in PDO entries, not in Dictionary)
        pdo_objs = self._parse_pdo_objects()
        existing = {o.index for o in objects}
        for obj in pdo_objs:
            if obj.index not in existing:
                objects.append(obj)
                existing.add(obj.index)
            else:
                # Update PDO mapping on existing object
                existing_obj = objects[[o.index for o in objects].index(obj.index)]
                if obj.pdo_mapping and not existing_obj.pdo_mapping:
                    existing_obj.pdo_mapping = obj.pdo_mapping

        # Deduplicate by index
        seen = {}
        for obj in objects:
            if obj.index not in seen:
                seen[obj.index] = obj
        return sorted(seen.values(), key=lambda o: o.index)


# ── CLI ─────────────────────────────────────────────────────


def parse_file(xml_path: Path, brand: str, output_dir: Path) -> dict:
    """Parse one ESI file and save outputs."""
    parser = ESIParser(xml_path)

    vendor = parser.extract_vendor_info()
    device = parser.extract_device_info()
    objects = parser.extract_objects()
    pdos = parser.extract_pdo_mappings()

    print(f"  {brand}: {len(objects)} CoE objects, {len(pdos)} PDO mappings")
    print(f"    Vendor: {vendor['name'][:60]}")
    print(f"    Device: {device.get('name', 'unknown')[:60]}")
    print(f"    CiA 402 objects: {sum(1 for o in objects if o.category == 'cia402')}")
    print(f"    PDO-mappable: {sum(1 for o in objects if o.is_pdo_mappable)}")

    # Save
    brand_dir = output_dir / brand
    brand_dir.mkdir(parents=True, exist_ok=True)

    # CoE objects
    coe_file = brand_dir / f"{brand}-coe-objects.json"
    with open(coe_file, "w", encoding="utf-8") as f:
        json.dump({
            "vendor": vendor,
            "device": device,
            "source_file": str(xml_path.name),
            "count": len(objects),
            "objects": [o.to_dict() for o in objects],
        }, f, indent=2, ensure_ascii=False)
    print(f"    -> {coe_file}")

    # PDO mapping
    pdo_file = brand_dir / f"{brand}-pdo-mapping.json"
    with open(pdo_file, "w", encoding="utf-8") as f:
        json.dump({
            "vendor": vendor,
            "count": len(pdos),
            "mappings": [p.to_dict() for p in pdos],
        }, f, indent=2, ensure_ascii=False)
    print(f"    -> {pdo_file}")

    # Quick reference (CiA 402 key objects)
    cia402_objs = [o for o in objects if o.category == "cia402"]
    quickref_file = brand_dir / f"{brand}-quickref.json"
    with open(quickref_file, "w", encoding="utf-8") as f:
        json.dump({
            "brand": brand,
            "vendor": vendor["name"],
            "cia402_objects": {o.index_hex: o.name for o in cia402_objs},
            "pdo_mappable": {o.index_hex: o.name for o in objects if o.is_pdo_mappable},
        }, f, indent=2, ensure_ascii=False)
    print(f"    -> {quickref_file}")

    return {"brand": brand, "objects": len(objects), "pdos": len(pdos)}


def main():
    parser = argparse.ArgumentParser(description="Generalized EtherCAT ESI Parser")
    parser.add_argument("--xml", help="Path to ESI XML file")
    parser.add_argument("--brand", help="Brand/device name (e.g. panasonic-a6, yaskawa-sigma5)")
    parser.add_argument("--all", action="store_true", help="Parse all ESI files in subdirectories")
    parser.add_argument("--output", default=".", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output != "." else Path(__file__).resolve().parent

    if args.all:
        results = []
        base = output_dir
        for xml_file in sorted(base.rglob("*.xml")):
            if "delta-a3" in str(xml_file.parent):
                continue  # skip, already parsed
            brand = xml_file.parent.name
            print(f"\nParsing: {xml_file.name}")
            try:
                r = parse_file(xml_file, brand, output_dir)
                results.append(r)
            except Exception as e:
                print(f"  ERROR: {e}")

        print(f"\n{'='*50}")
        print("Summary:")
        for r in results:
            print(f"  {r['brand']:20s}: {r['objects']:>4d} objects, {r['pdos']:>2d} PDOs")

    elif args.xml and args.brand:
        xml_path = Path(args.xml)
        if not xml_path.exists():
            print(f"File not found: {xml_path}")
            sys.exit(1)
        parse_file(xml_path, args.brand, output_dir)

    else:
        print("Usage:")
        print("  python extract_esi_generic.py --xml <file> --brand <name>")
        print("  python extract_esi_generic.py --all")
        print("\nFound ESI files:")
        for xml_file in sorted(output_dir.rglob("*.xml")):
            brand = xml_file.parent.name
            size_kb = xml_file.stat().st_size / 1024
            print(f"  {brand:20s}  {xml_file.name:40s}  {size_kb:6.0f} KB")


if __name__ == "__main__":
    main()

"""
Auto-generate scope config files for all brands.

Maps CiA 402 standard objects to the 8-channel oscilloscope layout.
All brands using CiA 402 share the same key objects — this script
reads each brand's extracted CoE dictionary and generates a compatible
scope config with available channels marked.

Usage:
    python generate_scope_configs.py
    python generate_scope_configs.py --brand delta-a3
"""

import json
from pathlib import Path

# ── Standard 8-channel template (CiA 402) ──────────────────
# These objects are common to ALL CiA 402 servo drives.
# If a brand's dictionary contains the object, the channel is available.

STANDARD_CHANNELS = [
    {
        "id": "CH1", "label": "Position", "unit": "pulses",
        "cia402_objects": [
            {"index": "0x6064", "name": "Position actual value", "role": "primary"},
            {"index": "0x6063", "name": "Position actual internal value", "role": "fallback"},
            {"index": "0x6062", "name": "Position demand value", "role": "reference"},
        ]
    },
    {
        "id": "CH2", "label": "Velocity", "unit": "rpm",
        "cia402_objects": [
            {"index": "0x606C", "name": "Velocity actual value", "role": "primary"},
            {"index": "0x606B", "name": "Velocity demand value", "role": "reference"},
        ]
    },
    {
        "id": "CH3", "label": "Current", "unit": "%",
        "cia402_objects": [
            {"index": "0x6078", "name": "Current actual value", "role": "primary"},
        ]
    },
    {
        "id": "CH4", "label": "Torque", "unit": "%",
        "cia402_objects": [
            {"index": "0x6077", "name": "Torque actual value", "role": "primary"},
            {"index": "0x6074", "name": "Torque demand value", "role": "reference"},
        ]
    },
    {
        "id": "CH5", "label": "Following Error", "unit": "pulses",
        "cia402_objects": [
            {"index": "0x60F4", "name": "Following error actual value", "role": "primary"},
            {"index": "0x6065", "name": "Following error window", "role": "reference"},
        ]
    },
    {
        "id": "CH6", "label": "Digital IO", "unit": "bitfield",
        "cia402_objects": [
            {"index": "0x60FD", "name": "Digital inputs", "role": "primary"},
        ]
    },
    {
        "id": "CH7", "label": "Status / Custom", "unit": "hex",
        "cia402_objects": [
            {"index": "0x6041", "name": "Statusword", "role": "primary"},
            {"index": "0x603F", "name": "Error code", "role": "fallback"},
        ]
    },
    {
        "id": "CH8", "label": "Op Mode / Profile", "unit": "code",
        "cia402_objects": [
            {"index": "0x6061", "name": "Modes of operation display", "role": "primary"},
            {"index": "0x6060", "name": "Modes of operation", "role": "reference"},
            {"index": "0x60FF", "name": "Target velocity", "role": "profile"},
        ]
    },
]


def generate_scope_config(brand_dir: Path, brand_key: str) -> dict:
    """Generate a scope config for one brand based on its CoE dictionary."""
    coe_file = brand_dir / f"{brand_key}-coe-objects.json"
    if not coe_file.exists():
        print(f"  SKIP: no CoE objects file for {brand_key}")
        return None

    with open(coe_file, encoding="utf-8") as f:
        coe_data = json.load(f)

    # Build index → name lookup
    obj_map = {}
    for obj in coe_data.get("objects", []):
        obj_map[obj["index"]] = obj

    channels = []
    available_count = 0
    for ch_template in STANDARD_CHANNELS:
        sources = []
        has_primary = False
        for ref in ch_template["cia402_objects"]:
            if ref["index"] in obj_map:
                obj = obj_map[ref["index"]]
                sources.append({
                    "index": ref["index"],
                    "name": ref["name"],
                    "type": obj.get("type", ""),
                    "bit_size": obj.get("bit_size", 0),
                    "pdo_dir": obj.get("pdo_mapping", ""),
                    "role": ref["role"],
                })
                if ref["role"] == "primary":
                    has_primary = True

        channel = {
            "id": ch_template["id"],
            "label": ch_template["label"],
            "unit": ch_template["unit"],
            "available": has_primary,
            "sources": sources,
        }
        channels.append(channel)
        if has_primary:
            available_count += 1

    # Trigger sources
    trigger_sources = []
    for idx in ["0x1001", "0x603F", "0x6041", "0x60F4", "0x60FD"]:
        if idx in obj_map:
            trigger_sources.append({
                "index": idx,
                "name": obj_map[idx]["name"],
                "access": obj_map[idx].get("access", "ro"),
            })

    config = {
        "brand": brand_key,
        "vendor": coe_data.get("vendor", {}).get("name", ""),
        "device": coe_data.get("device", {}).get("name", ""),
        "channels": channels,
        "available_channels": available_count,
        "trigger_sources": trigger_sources,
        "sample_rate_max_hz": 10000,
        "dc_cycle_us": 1000,
    }

    return config


def main():
    base = Path(__file__).resolve().parent

    # Load brand registry
    with open(base / "brands.json", encoding="utf-8") as f:
        registry = json.load(f)

    print("Generating scope configs for all brands...\n")

    for brand_key, brand_info in registry["brands"].items():
        brand_dir = base / brand_key
        if not brand_dir.exists():
            continue

        config = generate_scope_config(brand_dir, brand_key)
        if config is None:
            continue

        # Save
        config_path = brand_dir / f"{brand_key}-scope-config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        n_ch = config["available_channels"]
        print(f"  {brand_key:20s}: {n_ch}/8 channels available  -> {config_path.name}")


if __name__ == "__main__":
    main()

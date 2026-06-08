"""
EtherCAT Slave Discovery + ESI Matching + Axis Auto-Naming.

Reads SII EEPROM data from each slave on the bus (vendor ID, product code,
revision, name), matches against the ESI/parameter library to identify the
drive brand/model, and auto-suggests axis names based on position and type.

Usage:
    from discover import discover_slaves, match_esi, auto_name_axes, load_axis_config

    # Discover slaves on the bus
    slaves = discover_slaves(master)  # works with SOEM, IgH, or Sim

    # Match against ESI library
    for s in slaves:
        s["brand"] = match_esi(s["vendor_id"], s["product_code"])

    # Auto-name axes or load from config
    axes_cfg = auto_name_axes(slaves)
    # → [{"id":"X","slave_position":0,"brand":"delta-a3","sii_name":"ASDA-A3-E",...}, ...]

    # Save for next run
    save_axis_config(axes_cfg)

    # Next run: load saved config
    axes_cfg = load_axis_config() or auto_name_axes(slaves)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── ESI/Vendor database ──────────────────────────────────────────────

# Well-known EtherCAT vendor IDs
VENDOR_NAMES: Dict[int, str] = {
    0x00000001: "EtherCAT Technology Group",
    0x00000002: "Beckhoff Automation",
    0x000000DD: "Delta Electronics",     # seen in some ESI
    0x000001DD: "Delta Electronics",
    0x0000011A: "Delta Electronics (alt)",
    0x00000083: "Yaskawa Electric",
    0x0000066F: "Yaskawa Electric (Omron)",
    0x0000006A: "Panasonic",
    0x00000634: "Panasonic (A6)",
    0x00000539: "Elmo Motion Control",
    0x00000911: "Elmo (Gold)",
    0x0000009A: "Servotronix",
    0x000004B: "INVT",
    0x00000168: "Estun",
    0x0000060A: "Leadshine",
    0x000008B6: "Leadshine (DM3E)",
    0x000001B9: "Lenze",
    0x00000021: "CKD",
    0x00000588: "SMC",
    0x00000319: "Oriental Motor",
    0x000002E1: "Parker Hannifin",
    0x000002BE: "Kollmorgen",
    0x00004321: "Syn-Tek",
    0x000001A05: "Delta (alt)",
    0x00000114: "Nikki Denso",
    0x0000556: "Balluff",
    0x0000994: "Omron",
    0x00006B5: "RISE",
    0x0000816: "NTI LinMot",
    0x0000871: "RFT",
    0x0000C44: "VMMORE",
    0x00009555: "ZeroErr",
    0x0000AAAA: "Generic",
    0x0048554B: "PBA",
    0x010000E8: "SW",
    0x5A65726F: "ZeroErr (alt)",
    0xA0000000: "TEST",
}

# Vendor ID → brand key (matching 05-servo-params/ directory names)
VENDOR_TO_BRAND: Dict[int, str] = {
    0x000001DD: "delta-a3",
    0x0000011A: "delta-a3",
    0x00001A05: "delta-a3",
    0x00000539: "elmo-gold",
    0x00000168: "estun-pronet",
    0x0000060A: "leadshine-cl3",
    0x000008B6: "leadshine-dm3e",
    0x000001B9: "lenze-i700",
    0x00000634: "panasonic-a6",
    0x0000006A: "panasonic-a6",
    0x0000009A: "servotronix-cdhd",
    0x00000083: "yaskawa-sigma7",
    0x0000066F: "yaskawa-sigma7",
    0x0000004B: "invt-da200",
    0x00000911: "elmo-gold",
}

# Product code → sub-model
PRODUCT_NAMES: Dict[int, str] = {
    0x00006010: "ASDA-A3-E",
    0x00006012: "ASDA-A3-E (1kW)",
    0x00006022: "ASDA-A3-E (2kW)",
    0x00006032: "ASDA-A3-E (3kW)",
    0x00005621: "ASDA-A2-E",
    0x00007062: "ASDA-B3-E",
    0x00008124: "ASDA-B3-E (1.5kW)",
    0x00009144: "ASDA-B3-E (2kW)",
    0x10305070: "ASDA-x3-E (multi)",
    0x00005500: "ASDA-A2 (generic)",
    0x02200001: "Elmo Gold",
    0x00010420: "Servotronix CDHD",
    0x00030924: "Servotronix CDHD2",
    0x00029252: "Elmo Gold (mini)",
    0x00040003: "Panasonic A6B",
    0x511050A1: "Yaskawa Sigma-7",
    0x51507451: "Yaskawa Sigma-7 (400W)",
    0x60380000: "Yaskawa Sigma-7 (multi)",
    0x613C0000: "Yaskawa Sigma-5",
    0x60540000: "Yaskawa Sigma-7 (1kW)",
    0x044c2c52: "Beckhoff EK1100",
    0x07d43052: "Beckhoff EL2004",
    0x0c503052: "Beckhoff EL3152",
    0x10063052: "Beckhoff EL4102",
}


# ── NIC Auto-Detection ────────────────────────────────────────────────


def detect_ethercat_adapter() -> Optional[str]:
    """Auto-detect an available EtherCAT-compatible NIC.

    Windows: Uses SOEM's ec_find_adapters() to list pcap devices,
             filters for Ethernet + link-up.
    Linux:   Scans /sys/class/net for interfaces with carrier=1.

    Returns:
        Adapter name string (e.g. "\\Device\\NPF_{GUID}" on Windows,
        "eth0" on Linux), or None if no suitable NIC found.
    """
    if sys.platform == "win32":
        return _detect_adapter_windows()
    else:
        return _detect_adapter_linux()


def _detect_adapter_windows() -> Optional[str]:
    """Windows: use SOEM ec_find_adapters() to find pcap devices."""
    # Check if libsoem.dll is available before importing bindings
    # (avoids CRT mismatch crash when DLL is missing or built with different compiler)
    try:
        from . import soem_bindings
        if not soem_bindings.is_available():
            return None
        soem = soem_bindings.get_soem()
        if soem is None:
            return None
        adapters = soem.ec_find_adapters()
        if not adapters:
            return None
        for ad in adapters:
            # Prefer Ethernet adapters with link up
            is_eth = getattr(ad, 'is_ethernet', True)
            link_up = getattr(ad, 'link_up', True)
            if is_eth and link_up:
                return ad.name
        # Fallback: first available adapter
        return adapters[0].name if adapters else None
    except (ImportError, OSError, AttributeError, ValueError):
        return None
    except Exception:
        return None


def _detect_adapter_linux() -> Optional[str]:
    """Linux: scan /sys/class/net for Ethernet interfaces with carrier."""
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return None
    for iface in sorted(net_dir.iterdir()):
        if not iface.is_dir():
            continue
        # Skip loopback and virtual
        if iface.name == "lo" or iface.name.startswith("docker") or \
           iface.name.startswith("veth") or iface.name.startswith("br-"):
            continue
        carrier = iface / "carrier"
        if carrier.exists():
            try:
                if carrier.read_text().strip() == "1":
                    return iface.name
            except Exception:
                pass
    return None


def match_esi(vendor_id: int, product_code: int) -> dict:
    """Match vendor+product against the ESI/parameter library.

    Returns:
        {"brand": "delta-a3", "vendor_name": "Delta Electronics",
         "product_name": "ASDA-A3-E", "is_servo_drive": True}
        Empty dict if no match.
    """
    result = {
        "vendor_name": VENDOR_NAMES.get(vendor_id, f"Vendor 0x{vendor_id:08X}"),
        "product_name": PRODUCT_NAMES.get(product_code, f"Product 0x{product_code:08X}"),
        "brand": VENDOR_TO_BRAND.get(vendor_id, ""),
        "is_servo_drive": vendor_id in VENDOR_TO_BRAND,
    }
    return result


# ── Default axis naming patterns ────────────────────────────────────

# Standard machine axis naming conventions
PRIMARY_LINEAR_AXES = ["X", "Y", "Z"]
SECONDARY_LINEAR_AXES = ["U", "V", "W"]
ROTARY_AXES = ["A", "B", "C"]
SPINDLE_NAMES = ["S", "S0", "S1"]
AUX_NAMES = ["T0", "T1", "T2"]


def auto_name_axes(discovered_slaves: List[dict]) -> List[dict]:
    """Auto-assign axis IDs based on discovered slave types and positions.

    Rules:
      - First 3 servo drives (CiA 402) → X, Y, Z
      - Next 3 servo drives → A, B, C (rotary)
      - Next 3 servo drives → U, V, W
      - Non-servo slaves keep their SII name
      - Assign colors and phase offsets
    """
    axes_cfg = []
    servo_count = 0
    non_servo_count = 0

    colors = ["#44FF44", "#FF8800", "#44AAFF", "#FF44FF", "#FFCC00",
              "#00FFCC", "#FF6644", "#66FF66", "#6688FF", "#FF66CC"]

    for slave in discovered_slaves:
        esi = slave.get("esi_match", {})
        is_servo = esi.get("is_servo_drive", False)

        if is_servo:
            if servo_count < 3:
                aid = PRIMARY_LINEAR_AXES[servo_count]
            elif servo_count < 6:
                aid = ROTARY_AXES[servo_count - 3]
            elif servo_count < 9:
                aid = SECONDARY_LINEAR_AXES[servo_count - 6]
            else:
                aid = f"S{servo_count - 9}" if servo_count < 12 else f"D{servo_count - 12}"
            servo_count += 1
        else:
            # Non-servo: use SII name or generic name
            sii_name = slave.get("sii_name", "")
            aid = sii_name.replace(" ", "_") if sii_name else f"IO{non_servo_count}"
            non_servo_count += 1

        cfg = {
            "id": aid,
            "slave_position": slave["position"],
            "vendor_id": f"0x{slave['vendor_id']:08X}",
            "product_code": f"0x{slave['product_code']:08X}",
            "revision": slave.get("revision", 0),
            "sii_name": slave.get("sii_name", ""),
            "brand": esi.get("brand", ""),
            "vendor_name": esi.get("vendor_name", ""),
            "product_name": esi.get("product_name", ""),
            "is_servo_drive": is_servo,
            "name": f"{aid} Axis",
            "color": colors[slave["position"] % len(colors)],
            "offset": slave["position"] * 0.8,  # phase offset for demo
        }
        axes_cfg.append(cfg)

    return axes_cfg


# ── Config persistence ──────────────────────────────────────────────

def _config_path() -> Path:
    """Path to the axis mapping config file."""
    return Path(__file__).resolve().parent.parent.parent / "scope_axes.json"


def save_axis_config(axes_cfg: List[dict], filepath: str = None):
    """Save axis configuration to JSON for next session."""
    path = Path(filepath) if filepath else _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"axes": axes_cfg, "discovered_at": ""}, f, indent=2, ensure_ascii=False)
    print(f"[discover] Axis config saved: {path}")


def load_axis_config(filepath: str = None) -> Optional[List[dict]]:
    """Load previously saved axis configuration.

    Returns None if no config exists (first run).
    """
    path = Path(filepath) if filepath else _config_path()
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("axes", [])
    except (json.JSONDecodeError, OSError):
        return None


# ── Slave Discovery ──────────────────────────────────────────────────

def discover_slaves(master) -> List[dict]:
    """Discover all slaves on the EtherCAT bus.

    Reads SII EEPROM data (vendor ID, product code, name, revision)
    from each slave. Works with SOEM, IgH, and Simulated backends.

    Args:
        master: EcMaster instance (must have called scan() first).

    Returns:
        List of slave dicts with keys:
          position, vendor_id, product_code, revision, sii_name, state,
          esi_match (if matched against library)
    """
    slaves = []

    if getattr(master, '_is_igh', False):
        # IgH backend — use ecrt_master_get_slave
        slaves = _discover_igh(master)
    elif getattr(master, '_is_sim', False):
        # Simulated backend
        slaves = _discover_sim(master)
    else:
        # SOEM backend (RealEtherCAT)
        slaves = _discover_soem(master)

    # Match each slave against ESI library
    for s in slaves:
        s["esi_match"] = match_esi(s["vendor_id"], s["product_code"])

    return slaves


def _discover_soem(master) -> List[dict]:
    """Discover slaves via SOEM DLL — reads ec_slave array."""
    backend = getattr(master, '_backend', None)
    if backend is None:
        return []

    soem = getattr(backend, '_soem', None)
    if soem is None or not soem.available:
        return []

    slaves = []
    count = soem.slavecount

    for pos in range(1, count + 1):  # SOEM: slaves are 1-based
        sl = soem.get_slave(pos)
        if sl is None:
            continue

        name = sl.name.decode("utf-8", errors="replace").strip("\x00").strip() if sl.name else ""
        slaves.append({
            "position": pos - 1,  # convert to 0-based
            "vendor_id": sl.eep_man,
            "product_code": sl.eep_id,
            "revision": sl.eep_rev,
            "sii_name": name or f"Slave {pos}",
            "state": sl.state,
            "has_dc": bool(sl.hasdc),
        })

    return slaves


def _discover_igh(master) -> List[dict]:
    """Discover slaves via IgH API — uses ecrt_master_get_slave()."""
    backend = getattr(master, '_backend', None)
    if backend is None:
        return []

    igh = getattr(backend, '_igh', None)
    if igh is None or not igh.available:
        return []

    lib = igh._lib
    slaves = []

    # Get master info for slave count
    from .ec_master import ec_master_info_t
    from ctypes import byref
    info = ec_master_info_t()
    ret = lib.ecrt_master(backend._master, byref(info))
    if ret < 0:
        return []

    from .igh_bindings import ec_slave_info_t

    for pos in range(info.slave_count):
        slave_info = ec_slave_info_t()
        ret = lib.ecrt_master_get_slave(backend._master, pos, byref(slave_info))
        if ret < 0:
            continue

        name = slave_info.name.decode("utf-8", errors="replace").strip("\x00").strip() if slave_info.name else ""

        slaves.append({
            "position": pos,
            "vendor_id": slave_info.vendor_id,
            "product_code": slave_info.product_code,
            "revision": slave_info.revision_number,
            "sii_name": name or f"Slave {pos}",
            "state": slave_info.al_state,
            "has_dc": True,
        })

    return slaves


def _discover_sim(master) -> List[dict]:
    """Discover slaves from simulated backend."""
    slaves = []
    for s in getattr(master, 'slaves', []):
        slaves.append({
            "position": s.position - 1,  # sim uses 1-based
            "vendor_id": s.manufacturer_id,
            "product_code": s.product_id,
            "revision": s.revision,
            "sii_name": s.name,
            "state": s.state,
            "has_dc": s.has_dc,
        })
    return slaves


# ── Print helpers ────────────────────────────────────────────────────

def print_discovery(slaves: List[dict]):
    """Print a formatted discovery report."""
    print(f"\n{'='*65}")
    print(f"  EtherCAT Bus Scan — {len(slaves)} slave(s) discovered")
    print(f"{'='*65}")
    print(f"  {'Pos':<4} {'Vendor ID':<12} {'Product':<12} {'Name':<25} {'Axis':<6}")
    print(f"  {'-'*4} {'-'*12} {'-'*12} {'-'*25} {'-'*6}")

    for s in slaves:
        esi = s.get("esi_match", {})
        vendor_name = esi.get("vendor_name", f"0x{s['vendor_id']:08X}")
        if len(vendor_name) > 12:
            vendor_name = vendor_name[:11] + "…"
        product_name = esi.get("product_name", f"0x{s['product_code']:08X}")
        if len(product_name) > 12:
            product_name = product_name[:11] + "…"
        sii_name = s.get("sii_name", "")[:25]
        axis_id = s.get("id", "?")
        print(f"  {s['position']:<4} {vendor_name:<12} {product_name:<12} {sii_name:<25} {axis_id:<6}")

    servo_count = sum(1 for s in slaves if s.get("esi_match", {}).get("is_servo_drive"))
    print(f"  {'-'*65}")
    print(f"  Servo drives: {servo_count}   I/O / other: {len(slaves) - servo_count}")
    print(f"{'='*65}\n")

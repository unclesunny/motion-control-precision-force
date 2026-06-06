"""
EtherCAT Master — High-level Python API with dual-mode support.

Real Mode:    Uses libsoem.dll via soem_bindings.py — actual EtherCAT hardware.
Sim Mode:     Uses Delta A3 parameter library to simulate SDO/PDO operations.
              Allows full API testing without hardware.

Lifecycle:
  1. master = EcMaster()
  2. master.scan()              → discover slaves
  3. master.sdo_read(idx, sub)  → read object dictionary
  4. master.go_operational()    → enter cyclic data exchange
  5. master.exchange()          → send + receive PDOs (call in loop)
  6. master.close()             → shutdown

Usage:
  from ec_master import EcMaster
  master = EcMaster(adapter="eth0")  # or adapter="sim" for simulation
"""

import ctypes
import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Try to load real SOEM bindings
try:
    from . import soem_bindings
    _SOEM = soem_bindings.get_soem()
except (ImportError, SystemError):
    _SOEM = None


# ============================================================================
# EtherCAT constants
# ============================================================================

EC_STATE_NONE = 0x00
EC_STATE_INIT = 0x01
EC_STATE_PRE_OP = 0x02
EC_STATE_BOOT = 0x03
EC_STATE_SAFE_OP = 0x04
EC_STATE_OPERATIONAL = 0x08

STATE_NAMES = {
    0x00: "NONE",
    0x01: "INIT",
    0x02: "PRE-OP",
    0x03: "BOOT",
    0x04: "SAFE-OP",
    0x08: "OP",
}

# CiA 402 key objects (from our parameter library)
CIA402_KEY_OBJECTS = {
    0x1000: "Device type",
    0x1008: "Device name",
    0x1009: "Hardware version",
    0x100A: "Software version",
    0x1018: "Identity object",
    0x1600: "RxPDO Mapping 1",
    0x1A00: "TxPDO Mapping 1",
    0x1C12: "RxPDO assign",
    0x1C13: "TxPDO assign",
    0x6040: "Control word",
    0x6041: "Status word",
    0x6060: "Modes of operation",
    0x6061: "Modes of operation display",
    0x6064: "Position actual value",
    0x606C: "Velocity actual value",
    0x6071: "Target torque",
    0x6077: "Torque actual value",
    0x6078: "Current actual value",
    0x607A: "Target position",
    0x60FF: "Target velocity",
    0x60FD: "Digital inputs",
    0x60F4: "Following error actual value",
    0x60B1: "Velocity offset",
    0x60B2: "Torque offset",
    0x6081: "Profile velocity",
    0x6083: "Profile acceleration",
    0x6084: "Profile deceleration",
}


# ============================================================================
# Data types for SDO parsing
# ============================================================================

def _soem_type_to_struct_fmt(type_name: str, bit_size: int) -> str:
    """Map SOEM/CoE data type to Python struct format."""
    mapping = {
        "BOOL": "?", "BIT1": "?", "BIT2": "B",
        "SINT": "b", "USINT": "B",
        "INT": "h", "UINT": "H",
        "DINT": "i", "UDINT": "I",
        "REAL": "f", "LREAL": "d",
    }
    if type_name in mapping:
        return mapping[type_name]
    # Fallback: use bit_size
    if bit_size <= 8:
        return "B"
    elif bit_size <= 16:
        return "H"
    elif bit_size <= 32:
        return "I"
    return "Q"


def _parse_sdo_data(data: bytes, type_name: str, bit_size: int) -> Any:
    """Parse raw SDO bytes into Python value."""
    fmt = _soem_type_to_struct_fmt(type_name, bit_size)
    try:
        val = struct.unpack(fmt, data[:struct.calcsize(fmt)])[0]
        return val
    except Exception:
        return data.hex()


def _pack_sdo_data(value: Any, type_name: str, bit_size: int) -> bytes:
    """Pack Python value into SDO byte buffer."""
    fmt = _soem_type_to_struct_fmt(type_name, bit_size)
    try:
        return struct.pack(fmt, value)
    except Exception:
        return bytes(value)


# ============================================================================
# Slave data model
# ============================================================================


@dataclass
class EcSlave:
    """Discovered EtherCAT slave."""
    position: int           # bus position (1-based, 0 = master)
    name: str               # from SII EEPROM
    manufacturer_id: int    # 0x000001DD = Delta
    product_id: int
    revision: int
    state: int = 0
    rx_pdo_size: int = 0
    tx_pdo_size: int = 0
    has_dc: bool = False

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state & 0x0F, f"0x{self.state:04X}")

    @property
    def is_delta_a3(self) -> bool:
        """Check if this is a Delta ASDA-A3-E drive (vendor=0x1DD)."""
        return self.manufacturer_id == 0x000001DD


# ============================================================================
# Simulated EtherCAT Master
# ============================================================================


class SimulatedEtherCAT:
    """Simulates EtherCAT communication using the Delta A3 parameter library.

    Provides full SDO read/write simulation backed by our extracted ESI+CHM
    parameter library. This allows developing and testing the oscilloscope,
    AI analyzer, and parameter tools without physical hardware.
    """

    def __init__(self, param_lib_path: Optional[str] = None):
        self.slaves: List[EcSlave] = []
        self._state: int = EC_STATE_INIT
        self._io_map: bytearray = bytearray(4096)
        self._sdo_store: Dict[Tuple[int, int, int], bytes] = {}
        self._param_db: Dict[str, dict] = {}

        # Load parameter library
        if param_lib_path is None:
            param_lib_path = str(
                Path(__file__).resolve().parent.parent.parent
                / "05-servo-params" / "delta-a3" / "delta-a3-merged.json"
            )
        self._load_param_lib(param_lib_path)

        # Simulate a Delta A3 on the bus
        self._init_slave()

    def _load_param_lib(self, path: str):
        """Load Delta A3 parameter library for SDO simulation."""
        try:
            with open(path, encoding="utf-8") as f:
                objects = json.load(f)
        except FileNotFoundError:
            print(f"[sim] Parameter library not found: {path}")
            return

        for obj in objects:
            index_str = obj.get("index", "")
            if index_str.startswith("0x"):
                index = int(index_str, 16)
                self._param_db[f"{index}:0"] = obj
                # Also store sub-items
                for si in obj.get("sub_items", []):
                    key = f"{index}:{si['sub_idx']}"
                    self._param_db[key] = si

        print(f"[sim] Loaded {len(self._param_db)} parameter entries from library")

    def _init_slave(self):
        """Create a simulated Delta ASDA-A3-E slave at position 1."""
        # Delta vendor ID from ESI XML: #x1DD = 0x1DD = 477
        # Product code: #x00006010 = 0x00006010
        slave = EcSlave(
            position=1,
            name="Delta ASDA-A3-E CoE Drive",
            manufacturer_id=0x000001DD,
            product_id=0x00006010,
            revision=0x00030000,
            state=EC_STATE_INIT,
            rx_pdo_size=64,
            tx_pdo_size=64,
            has_dc=True,
        )
        self.slaves = [slave]

        # Initialize default SDO values from parameter library
        for key, obj in self._param_db.items():
            if ":" in key:
                parts = key.split(":")
                idx = int(parts[0])
                sub = int(parts[1])
                default = obj.get("default_data") or obj.get("default_value_chm") or ""
                if default and default not in ("—", "-", ""):
                    try:
                        type_name = obj.get("type", "UINT")
                        bit_size = obj.get("bit_size", 16)
                        # Try to parse default value
                        val_str = str(default).strip()
                        if val_str.startswith("0x"):
                            val = int(val_str, 16)
                        else:
                            try:
                                val = int(val_str)
                            except ValueError:
                                val = 0
                        data = _pack_sdo_data(val, type_name, bit_size)
                        self._sdo_store[(1, idx, sub)] = data
                    except Exception:
                        pass

    # ==================================================================
    # Simulated API (mirrors SOEM lifecycle)
    # ==================================================================

    def init(self, adapter: str = "sim") -> bool:
        print(f"[sim] EtherCAT master initialized on {adapter}")
        return True

    def config_init(self) -> int:
        self._state = EC_STATE_PRE_OP
        self.slaves[0].state = EC_STATE_PRE_OP
        print(f"[sim] Bus scan complete. Found {len(self.slaves)} slave(s).")
        return len(self.slaves)

    def config_map(self) -> bool:
        print(f"[sim] PDO mapped. RxPDO={self.slaves[0].rx_pdo_size}B, "
              f"TxPDO={self.slaves[0].tx_pdo_size}B")
        return True

    def statecheck(self, req_state: int, timeout: int = 20000) -> bool:
        self.slaves[0].state = req_state
        self._state = req_state
        print(f"[sim] State → {STATE_NAMES.get(req_state, hex(req_state))}")
        return True

    def go_operational(self) -> bool:
        """Full sequence: PRE-OP → SAFE-OP → OP."""
        self.statecheck(EC_STATE_SAFE_OP)
        time.sleep(0.01)
        self.statecheck(EC_STATE_OPERATIONAL)
        return True

    def sdo_read(self, index: int, subindex: int = 0) -> Tuple[bool, Any]:
        """Simulated SDO read from parameter library."""
        key = (1, index, subindex)

        # Check our SDO store first
        if key in self._sdo_store:
            obj_key = f"{index}:{subindex}"
            obj = self._param_db.get(obj_key, {})
            type_name = obj.get("type", "UINT")
            bit_size = obj.get("bit_size", 16)
            val = _parse_sdo_data(self._sdo_store[key], type_name, bit_size)
            return True, val

        # Check parameter library
        obj_key = f"{index}:{subindex}"
        if obj_key in self._param_db:
            obj = self._param_db[obj_key]
            default = obj.get("default_data") or obj.get("default_value_chm", "")
            if default and default not in ("—", "-", ""):
                return True, default
            # Return type-appropriate zero
            type_name = obj.get("type", "UINT")
            return True, 0

        return False, None

    def sdo_write(self, index: int, subindex: int, value: Any) -> bool:
        """Simulated SDO write. Stores value in local SDO store."""
        obj_key = f"{index}:{subindex}"
        obj = self._param_db.get(obj_key, {})
        type_name = obj.get("type", "UINT")
        bit_size = obj.get("bit_size", 16)

        data = _pack_sdo_data(value, type_name, bit_size)
        self._sdo_store[(1, index, subindex)] = data
        return True

    def exchange(self) -> int:
        """Simulated PDO exchange. Returns WorkCounter (simulated)."""
        # In sim mode, we just return WKC=1 (OK)
        return 1

    def read_pdo(self, index: int, subindex: int = 0) -> Any:
        """Read from simulated TxPDO buffer."""
        return self.sdo_read(index, subindex)[1]

    def write_pdo(self, index: int, subindex: int, value: Any):
        """Write to simulated RxPDO buffer."""
        self.sdo_write(index, subindex, value)

    def close(self):
        print("[sim] EtherCAT master closed.")

    @property
    def slavecount(self) -> int:
        return len(self.slaves)


# ============================================================================
# Real EtherCAT Master (SOEM-backed)
# ============================================================================


class RealEtherCAT:
    """Real EtherCAT master using libsoem.dll."""

    def __init__(self, adapter: str = "eth0"):
        self.adapter = adapter
        self.slaves: List[EcSlave] = []
        self._io_map: Optional[ctypes.Array] = None
        self._soem = _SOEM

        if self._soem is None or not self._soem.available:
            raise RuntimeError(
                "SOEM library not available. Build libsoem.dll from "
                "src/SOEM/ or use EcMaster in simulation mode (adapter='sim')."
            )

    def init(self) -> bool:
        ret = self._soem.ec_init(self.adapter)
        if ret != 0:
            raise RuntimeError(f"ec_init failed on {self.adapter}: ret={ret}")
        print(f"[ecat] Initialized on {self.adapter}")
        return True

    def config_init(self) -> int:
        count = self._soem.ec_config_init(False)
        if count <= 0:
            raise RuntimeError("No EtherCAT slaves found")
        print(f"[ecat] Found {count} slave(s)")

        # Read slave info
        self.slaves = []
        # ec_slave[0] is virtual "sum" slave; real slaves start at index 1
        # We need to read the global ec_slave array from the DLL
        # This requires ctypes to access the exported symbol
        # For now, build slaves from the slavecount
        for i in range(1, count + 1):
            self.slaves.append(EcSlave(
                position=i,
                name=f"Slave {i}",
                manufacturer_id=0,
                product_id=0,
                revision=0,
                state=EC_STATE_PRE_OP,
            ))
        return count

    def config_map(self) -> bool:
        io_map = ctypes.create_string_buffer(4096)
        ret = self._soem.ec_config_map(ctypes.cast(io_map, c_void_p))
        self._io_map = io_map
        return ret > 0

    def statecheck(self, req_state: int, timeout: int = 20000) -> bool:
        state = self._soem.ec_statecheck(0, req_state, timeout)
        return (state & req_state) == req_state

    def go_operational(self) -> bool:
        if not self.statecheck(EC_STATE_SAFE_OP):
            return False
        self._soem.ec_send_processdata()
        self._soem.ec_receive_processdata(2000)
        self._soem.ec_writestate(0)
        return self.statecheck(EC_STATE_OPERATIONAL)

    def sdo_read(self, slave: int, index: int, subindex: int = 0) -> Tuple[bool, Any]:
        ok, data = self._soem.ec_SDOread(slave, index, subindex)
        return ok, data

    def sdo_write(self, slave: int, index: int, subindex: int, value: Any,
                  type_name: str = "UDINT") -> bool:
        bit_size = {"UINT": 16, "UDINT": 32, "INT": 16, "DINT": 32}.get(type_name, 32)
        data = _pack_sdo_data(value, type_name, bit_size)
        return self._soem.ec_SDOwrite(slave, index, subindex, data)

    def exchange(self) -> int:
        self._soem.ec_send_processdata()
        return self._soem.ec_receive_processdata(2000)

    @property
    def slavecount(self) -> int:
        return len(self.slaves)

    def close(self):
        if self._soem:
            self._soem.ec_close()
        print("[ecat] Closed.")


# ============================================================================
# Unified EcMaster — auto-selects real or sim
# ============================================================================


class EcMaster:
    """Unified EtherCAT master API — auto-detects real vs simulation mode.

    Usage:
        master = EcMaster()                  # auto-detect
        master = EcMaster(adapter="sim")     # force simulation
        master = EcMaster(adapter="eth0")    # force real on eth0

        master.scan()
        print(f"Found: {master.slavecount} slave(s)")
        for slave in master.slaves:
            print(f"  [{slave.position}] {slave.name}")

        # Read CoE objects
        ok, val = master.sdo_read(0x6078, 0)  # Current actual value
        master.sdo_write(0x6040, 0, 0x0006)   # Shutdown command

        # Cyclic exchange
        master.go_operational()
        for _ in range(100):
            master.exchange()
            pos = master.read_pdo(0x6064)  # Position actual value
            print(f"Position: {pos}")
            time.sleep(0.001)

        master.close()
    """

    def __init__(self, adapter: str = "auto"):
        self.adapter = adapter
        self._backend = None
        self._is_sim = False

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def scan(self) -> int:
        """Initialize and scan the EtherCAT bus. Returns slave count."""
        if self.adapter == "sim" or (self.adapter == "auto" and not self._real_available()):
            self._backend = SimulatedEtherCAT()
            self._is_sim = True
        else:
            self._backend = RealEtherCAT(self.adapter)
            self._is_sim = False

        self._backend.init(self.adapter)
        count = self._backend.config_init()
        self._backend.config_map()
        return count

    def _real_available(self) -> bool:
        if _SOEM is None:
            return False
        return _SOEM.available

    @property
    def slaves(self) -> List[EcSlave]:
        return self._backend.slaves if self._backend else []

    @property
    def slavecount(self) -> int:
        return self._backend.slavecount if self._backend else 0

    @property
    def is_simulation(self) -> bool:
        return self._is_sim

    # ==================================================================
    # State machine
    # ==================================================================

    def go_operational(self) -> bool:
        return self._backend.go_operational()

    def statecheck(self, req_state: int, timeout: int = 20000) -> bool:
        return self._backend.statecheck(req_state, timeout)

    # ==================================================================
    # SDO access (CoE object dictionary)
    # ==================================================================

    def sdo_read(self, index: int, subindex: int = 0, slave: int = 1) -> Tuple[bool, Any]:
        """Read a CoE object via SDO.

        Args:
            index: CoE object index (e.g. 0x6078 for Current Actual Value)
            subindex: sub-index (default 0)
            slave: slave position (default 1 for first slave)

        Returns:
            (success, value) tuple
        """
        return self._backend.sdo_read(index, subindex)

    def sdo_write(self, index: int, subindex: int, value: Any,
                  slave: int = 1) -> bool:
        """Write a CoE object via SDO."""
        return self._backend.sdo_write(index, subindex, value)

    def read_object_name(self, index: int) -> str:
        """Get human-readable name for a CoE object."""
        return CIA402_KEY_OBJECTS.get(index, f"0x{index:04X}")

    # ==================================================================
    # PDO exchange
    # ==================================================================

    def exchange(self) -> int:
        """Send + receive process data. Call in a loop for cyclic operation.

        Returns:
            WorkCounter (WKC) — should equal expected WKC for healthy bus
        """
        return self._backend.exchange()

    def read_pdo(self, index: int, subindex: int = 0) -> Any:
        """Read a PDO-mapped object from the process data image."""
        result = self._backend.read_pdo(index, subindex)
        if isinstance(result, tuple):
            return result[1] if result[0] else None
        return result

    def write_pdo(self, index: int, subindex: int, value: Any):
        """Write a PDO-mapped object to the process data image."""
        self._backend.write_pdo(index, subindex, value)

    # ==================================================================
    # Convenience: scope data acquisition
    # ==================================================================

    def read_scope_channels(self, channels: List[int]) -> Dict[int, Any]:
        """Read multiple scope channels from the process data image."""
        self.exchange()
        result = {}
        for ch in channels:
            val = self.read_pdo(ch, 0)
            if val is not None or self._is_sim:
                result[ch] = val
        return result

    # ==================================================================
    # Cleanup
    # ==================================================================

    def close(self):
        if self._backend:
            self._backend.close()
            self._backend = None

    def __enter__(self):
        self.scan()
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================================
# Demo / Test
# ============================================================================


def demo():
    """Demonstrate the EcMaster in simulation mode."""
    print("=" * 60)
    print("  EtherCAT Master — Simulation Demo")
    print("=" * 60)

    with EcMaster(adapter="sim") as master:
        print(f"\n  Bus scan: {master.slavecount} slave(s) found")
        for s in master.slaves:
            print(f"  [{s.position}] {s.name} (0x{s.manufacturer_id:08X}:0x{s.product_id:08X})")

        # Read key CiA 402 objects
        print(f"\n  --- CiA 402 Drive Profile Objects ---")
        for idx in [0x1000, 0x6040, 0x6041, 0x6060, 0x6064, 0x606C, 0x6078, 0x607A]:
            ok, val = master.sdo_read(idx, 0)
            name = master.read_object_name(idx)
            print(f"  0x{idx:04X} {name:<30s} = {val}")

        # Write control word sequence: Shutdown → Switch On → Enable
        print(f"\n  --- Control Word Sequence ---")
        for cmd_name, cmd_val in [("Shutdown", 0x0006), ("Switch On", 0x0007),
                                   ("Enable Op", 0x000F)]:
            ok = master.sdo_write(0x6040, 0, cmd_val)
            ok2, status = master.sdo_read(0x6041, 0)
            print(f"  {cmd_name:12s} (0x6040=0x{cmd_val:04X}) → Status=0x{status or 0:04X}")

        # Read scope channels
        print(f"\n  --- Scope Channels (one exchange) ---")
        scope_channels = [0x6064, 0x606C, 0x6078, 0x6077, 0x60F4]
        values = master.read_scope_channels(scope_channels)
        for idx, val in values.items():
            name = master.read_object_name(idx)
            print(f"  0x{idx:04X} {name:<30s} = {val}")

    print(f"\n  ✓ Demo complete.")


if __name__ == "__main__":
    demo()

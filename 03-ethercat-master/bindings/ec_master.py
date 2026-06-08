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

    def __init__(self, param_lib_path: Optional[str] = None,
                 num_axes: int = 1,
                 axis_names: Optional[List[str]] = None):
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

        # Simulate N Delta A3 drives on the bus
        names = axis_names or [f"Axis{i}" for i in range(num_axes)]
        for pos in range(num_axes):
            self._init_slave(position=pos + 1, name=names[pos] if pos < len(names) else f"Axis{pos}")

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

    def _init_slave(self, position: int = 1, name: str = "Delta ASDA-A3-E CoE Drive"):
        """Create a simulated Delta ASDA-A3-E slave at the given position.

        Args:
            position: EtherCAT bus position (1-based).
            name: Human-readable slave name.
        """
        slave = EcSlave(
            position=position,
            name=name,
            manufacturer_id=0x000001DD,
            product_id=0x00006010,
            revision=0x00030000,
            state=EC_STATE_INIT,
            rx_pdo_size=64,
            tx_pdo_size=64,
            has_dc=True,
        )
        self.slaves.append(slave)

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
                        val_str = str(default).strip()
                        if val_str.startswith("0x"):
                            val = int(val_str, 16)
                        else:
                            try:
                                val = int(val_str)
                            except ValueError:
                                val = 0
                        data = _pack_sdo_data(val, type_name, bit_size)
                        self._sdo_store[(position, idx, sub)] = data
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

    def sdo_read(self, index: int, subindex: int = 0, slave: int = 1) -> Tuple[bool, Any]:
        """Simulated SDO read from parameter library.

        Args:
            index: CoE object index.
            subindex: Sub-index.
            slave: Slave position (1-based). Default 1 for backwards compat.
        """
        key = (slave, index, subindex)

        # Check our SDO store first
        if key in self._sdo_store:
            obj_key = f"{index}:{subindex}"
            obj = self._param_db.get(obj_key, {})
            type_name = obj.get("type", "UINT")
            bit_size = obj.get("bit_size", 16)
            val = _parse_sdo_data(self._sdo_store[key], type_name, bit_size)
            return True, val

        # Check parameter library (shared across slaves)
        obj_key = f"{index}:{subindex}"
        if obj_key in self._param_db:
            obj = self._param_db[obj_key]
            default = obj.get("default_data") or obj.get("default_value_chm", "")
            if default and default not in ("—", "-", ""):
                return True, default
            type_name = obj.get("type", "UINT")
            return True, 0

        return False, None

    def sdo_write(self, index: int, subindex: int, value: Any, slave: int = 1) -> bool:
        """Simulated SDO write. Stores value in local SDO store."""
        obj_key = f"{index}:{subindex}"
        obj = self._param_db.get(obj_key, {})
        type_name = obj.get("type", "UINT")
        bit_size = obj.get("bit_size", 16)

        data = _pack_sdo_data(value, type_name, bit_size)
        self._sdo_store[(slave, index, subindex)] = data
        return True

    def exchange(self) -> int:
        """Simulated PDO exchange. Returns WorkCounter (simulated)."""
        return 1

    def read_pdo(self, index: int, subindex: int = 0, slave: int = 1) -> Any:
        """Read from simulated TxPDO buffer."""
        return self.sdo_read(index, subindex, slave)[1]

    def write_pdo(self, index: int, subindex: int, value: Any, slave: int = 1):
        """Write to simulated RxPDO buffer."""
        self.sdo_write(index, subindex, value, slave)

    def close(self):
        print("[sim] EtherCAT master closed.")

    @property
    def slavecount(self) -> int:
        return len(self.slaves)


# ============================================================================
# IgH EtherCAT Master (Linux production)
# ============================================================================


class IgHEtherCAT:
    """EtherCAT master backed by IgH libethercat.so (Linux kernel module).

    DECLARATIVE model — all PDO entries MUST be registered BEFORE activate().
    After activation, the domain data buffer is updated in each exchange()
    cycle and read via byte offsets (no per-object read_pdo calls).

    Multi-axis support is NATIVE: each slave's scope channels are registered
    into one domain. After exchange(), domain_data[offset_axisX_pos] gives
    Axis X position, domain_data[offset_axisY_pos] gives Axis Y position, etc.

    Usage:
        master = IgHEtherCAT()
        master.scan()                # discover slaves + read SII
        master.configure_scope()     # register PDO entries for all axes
        master.activate()            # enter OPERATIONAL

        while running:
            master.receive()         # fetch new process data
            data = master.read_scope("X")  # read Axis X channels
            master.queue_and_send()  # prepare for next cycle
        master.close()
    """

    # ── CiA 402 scope channels (8-channel layout) ──
    SCOPE_PDO_ENTRIES = [
        (0x6064, 0, "DINT"),   # Position actual value
        (0x606C, 0, "DINT"),   # Velocity actual value
        (0x6078, 0, "INT"),    # Current actual value
        (0x6077, 0, "INT"),    # Torque actual value
        (0x60F4, 0, "DINT"),   # Following error actual value
        (0x60FD, 0, "UDINT"),  # Digital inputs
        (0x6041, 0, "UINT"),   # Statusword
        (0x6061, 0, "SINT"),   # Modes of operation display
    ]

    SCOPE_CHANNEL_NAMES = [
        "Position", "Velocity", "Current", "Torque",
        "Foll.Err", "DIO", "Status", "OpMode",
    ]

    def __init__(self, master_index: int = 0):
        self._master_index = master_index
        self._master = None      # ec_master_t*
        self._domain = None      # ec_domain_t*
        self._domain_ptr = 0     # uint8_t* from ecrt_domain_data()
        self.slaves: List[EcSlave] = []
        self._slave_configs: Dict[int, c_void_p] = {}  # {position: ec_slave_config_t*}

        # Per-axis PDO offset table: {axis_id: {index: (byte_offset, data_type)}}
        self._offsets: Dict[str, Dict[int, Tuple[int, str]]] = {}
        self._axis_map: Dict[int, str] = {}  # {position: axis_id}

        # Pre-allocated offset pointers (must survive until domain_reg_pdo_entry_list)
        self._offset_ptrs: List[ctypes.POINTER(ctypes.c_uint32)] = []

        # Try to load IgH library
        try:
            from . import igh_bindings
            self._igh = igh_bindings.get_igh()
        except (ImportError, SystemError):
            self._igh = None

    @property
    def available(self) -> bool:
        return self._igh is not None and self._igh.available

    # ── Lifecycle: Scan ──────────────────────────────────────────

    def scan(self, axis_names: Optional[List[str]] = None) -> int:
        """Initialize and scan the EtherCAT bus.

        IgH scans the bus during ecrt_request_master + ecrt_master().
        Creates the process data domain for scope data exchange.

        Args:
            axis_names: Optional list of axis names (e.g. ["X","Y","Z"]).
                       If None, uses ["Axis0", "Axis1", ...].

        Returns:
            Number of slaves found.
        """
        if not self.available:
            raise RuntimeError(
                "IgH libethercat.so not available. Is the IgH kernel module loaded?\n"
                "  sudo modprobe ec_master\n"
                "  sudo /etc/init.d/ethercat start"
            )

        lib = self._igh._lib

        # 1. Request master
        self._master = lib.ecrt_request_master(self._master_index)
        if not self._master:
            raise RuntimeError(
                f"Failed to request IgH master {self._master_index}. "
                f"Is the kernel module loaded?"
            )

        # 2. Get master info (slave count, link status)
        info = ec_master_info_t()
        ret = lib.ecrt_master(self._master, byref(info))
        if ret < 0:
            raise RuntimeError(f"ecrt_master() failed: {ret}")

        slave_count = info.slave_count
        print(f"[igh] Master {self._master_index}: {slave_count} slave(s), "
              f"link={'UP' if info.link_up else 'DOWN'}")

        # 3. Create process data domain
        self._domain = lib.ecrt_master_create_domain(self._master)
        if not self._domain:
            raise RuntimeError("ecrt_master_create_domain() failed")
        print(f"[igh] Domain created for scope data exchange")

        # 4. Discover slaves (read SII EEPROM via sysfs or ecrt_master)
        #    In IgH, slave info comes from /sys/ethercat/ or ecrt_master_slave_config
        #    For now, create EcSlave entries from slave_count
        self.slaves = []
        names = axis_names or [f"Axis{i}" for i in range(slave_count)]

        for pos in range(slave_count):
            name = names[pos] if pos < len(names) else f"Axis{pos}"
            self.slaves.append(EcSlave(
                position=pos,
                name=name,
                manufacturer_id=0,
                product_id=0,
                revision=0,
                state=EC_STATE_PRE_OP,
                has_dc=True,
            ))
            self._axis_map[pos] = name
            print(f"  [igh] Slave {pos}: {name} → axis_id='{name}'")

        return slave_count

    # ── Lifecycle: Configure PDO entries ─────────────────────────

    def configure_scope(self, channel_entries: Optional[List[Tuple[int, int, str]]] = None):
        """Register scope PDO entries for all slaves in the domain.

        This is the KEY multi-axis configuration step. Each slave's 8 CiA 402
        scope channels are registered as PDO entries. The IgH API writes back
        the byte offset within the domain buffer for each entry.

        After this call, self._offsets[axis_id][index] = (byte_offset, data_type)
        for every axis × channel combination.

        Args:
            channel_entries: Optional custom channel list as [(index, sub, type), ...].
                            If None, uses SCOPE_PDO_ENTRIES (8 standard channels).
        """
        if not self._domain:
            raise RuntimeError("No domain. Call scan() first.")

        entries = channel_entries or self.SCOPE_PDO_ENTRIES
        lib = self._igh._lib

        self._offset_ptrs = []

        for slave in self.slaves:
            pos = slave.position
            axis_id = self._axis_map.get(pos, f"Axis{pos}")

            # Get or create slave config
            slave_cfg = lib.ecrt_master_slave_config(
                self._master,
                0,                      # alias (0 = use position)
                pos,
                slave.manufacturer_id,
                slave.product_id,
            )
            if not slave_cfg:
                print(f"  [igh] WARNING: Failed to get slave config for position {pos}")
                continue
            self._slave_configs[pos] = slave_cfg

            # Register PDO entries and capture byte offsets
            self._offsets[axis_id] = {}
            print(f"  [igh] Configuring {axis_id} (slave {pos}):")

            for index, subindex, data_type in entries:
                offset_ptr = ctypes.POINTER(c_uint32)(ctypes.c_uint32(0))
                ret = lib.ecrt_slave_config_reg_pdo_entry(
                    slave_cfg,
                    c_uint16(index),
                    c_uint8(subindex),
                    self._domain,
                    offset_ptr,
                )
                if ret < 0:
                    print(f"    WARNING: Failed to register 0x{index:04X}:{subindex} "
                          f"for {axis_id} (ret={ret})")
                    continue

                self._offset_ptrs.append(offset_ptr)
                byte_offset = offset_ptr.contents.value // 8  # bits → bytes
                self._offsets[axis_id][index] = (byte_offset, data_type)
                print(f"    0x{index:04X}:{subindex} → offset={byte_offset}B ({data_type})")

        n_entries = sum(len(o) for o in self._offsets.values())
        print(f"  [igh] Total: {n_entries} PDO entries across {len(self._offsets)} axes")

    # ── Lifecycle: Activate ──────────────────────────────────────

    def activate(self) -> bool:
        """Activate the master — transitions all slaves to OPERATIONAL.

        After this call, cyclic data exchange begins. The domain data buffer
        is now valid and updated on each receive().
        """
        if not self._master:
            raise RuntimeError("No master. Call scan() first.")

        lib = self._igh._lib
        ret = lib.ecrt_master_activate(self._master)
        if ret != 0:
            print(f"[igh] Activate failed: {ret}")
            return False

        # Get domain data pointer (unchanging after activation)
        self._domain_ptr = lib.ecrt_domain_data(self._domain)
        if not self._domain_ptr:
            print("[igh] WARNING: domain_data() returned NULL")
            return False

        print(f"[igh] Activated. Domain data at 0x{self._domain_ptr:X}")
        return True

    # ── Cyclic Exchange ──────────────────────────────────────────
    #
    # Verified against: ethercat-1.5.2/examples/user/main.c:256-301
    #
    # Correct IgH cyclic pattern:
    #   ecrt_master_receive(master)    — fetch frames from last cycle
    #   ecrt_domain_process(domain)    — evaluate working counters
    #   ... read/write domain_data ...
    #   ecrt_domain_queue(domain)      — queue datagrams for next cycle
    #   ecrt_master_send(master)       — send frames

    def receive(self):
        """Fetch new process data from slaves → domain buffer.

        Calls ecrt_master_receive() + ecrt_domain_process().
        After this returns, domain_data() is valid for reading.
        """
        if self._igh and self._master and self._domain:
            lib = self._igh._lib
            lib.ecrt_master_receive(self._master)
            lib.ecrt_domain_process(self._domain)

    def queue_and_send(self):
        """Queue domain data for next cycle and send to slaves.

        Calls ecrt_domain_queue() + ecrt_master_send().
        """
        if self._igh and self._master and self._domain:
            lib = self._igh._lib
            lib.ecrt_domain_queue(self._domain)
            lib.ecrt_master_send(self._master)

    def exchange(self) -> int:
        """Single receive + process + queue + send cycle (SOEM-compatible API).

        Returns:
            WorkCounter — IgH doesn't expose WKC directly; returns 1 if
            domain data pointer is valid.
        """
        self.receive()
        self.queue_and_send()
        return 1 if self._domain_ptr else 0

    # ── Scope Data Access ────────────────────────────────────────

    def read_scope(self, axis_id: str) -> Dict[str, float]:
        """Read all 8 scope channels for one axis from the domain buffer.

        This is the MAIN read path for the oscilloscope. Each call reads
        from the pre-computed byte offsets within the domain data buffer.

        Args:
            axis_id: Axis name (e.g. "X", "Y", "Z").

        Returns:
            {"Position": 1000.0, "Velocity": 500.0, ...} (8 channels)
        """
        if not self._domain_ptr:
            return {}

        offsets = self._offsets.get(axis_id, {})
        result = {}

        for i, (index, subindex, data_type) in enumerate(self.SCOPE_PDO_ENTRIES):
            entry = offsets.get(index)
            if entry is None:
                result[self.SCOPE_CHANNEL_NAMES[i]] = 0.0
                continue

            byte_offset, dt = entry
            addr = self._domain_ptr + byte_offset

            # Data type → struct format
            fmt_map = {
                "SINT": ("b", 1), "USINT": ("B", 1),
                "INT": ("h", 2), "UINT": ("H", 2),
                "DINT": ("i", 4), "UDINT": ("I", 4),
                "REAL": ("f", 4), "LREAL": ("d", 8),
            }
            s_fmt, n_bytes = fmt_map.get(dt, ("i", 4))

            try:
                buf = ctypes.string_at(addr, n_bytes)
                val = struct.unpack(s_fmt, buf)[0]
                result[self.SCOPE_CHANNEL_NAMES[i]] = float(val)
            except Exception:
                result[self.SCOPE_CHANNEL_NAMES[i]] = 0.0

        return result

    def read_scope_all_axes(self) -> Dict[str, Dict[str, float]]:
        """Read scope channels for ALL axes in one exchange.

        Returns:
            {"X": {"Position": ..., "Velocity": ...}, "Y": {...}, ...}
        """
        self.receive()
        result = {}
        for axis_id in self._offsets:
            result[axis_id] = self.read_scope(axis_id)
        self.queue_and_send()
        return result

    @property
    def axis_ids(self) -> List[str]:
        """List of configured axis IDs."""
        return list(self._offsets.keys())

    # ── SDO Access (CoE object dictionary, non-cyclic) ───────────

    def sdo_read(self, slave: int, index: int, subindex: int = 0) -> Tuple[bool, Any]:
        """Read a CoE object via SDO (mailbox, not cyclic).

        IgH doesn't have a simple ecrt_sdo_read() in cyclic mode.
        SDO access is typically done via the kernel character device
        (/dev/ethercat) or command-line tool (ethercat upload).
        For now, this returns a placeholder.
        """
        print(f"[igh] SDO read not implemented in cyclic mode. "
              f"Use: ethercat upload {slave} 0x{index:04X} {subindex}")
        return False, None

    def sdo_write(self, slave: int, index: int, subindex: int, value: Any,
                  type_name: str = "UDINT") -> bool:
        """Write a CoE object via SDO (mailbox, not cyclic)."""
        print(f"[igh] SDO write not implemented in cyclic mode. "
              f"Use: ethercat download {slave} 0x{index:04X} {subindex} {value}")
        return False

    # ── Slave States ─────────────────────────────────────────────

    def statecheck(self, req_state: int, timeout: int = 20000) -> bool:
        """Check if all slaves reached requested state.

        IgH handles state transitions automatically during activate().
        Individual slave states are accessible via ecrt_slave_config_state().
        """
        # IgH activates all slaves atomically; statecheck is less granular
        return True

    def go_operational(self) -> bool:
        """Full sequence: configure scope → activate."""
        if not self._offsets:
            self.configure_scope()
        return self.activate()

    # ── Properties ───────────────────────────────────────────────

    @property
    def slavecount(self) -> int:
        return len(self.slaves)

    def close(self):
        """Deactivate master and release resources."""
        if self._igh and self._master:
            lib = self._igh._lib
            lib.ecrt_master_deactivate(self._master)
            lib.ecrt_release_master(self._master)
            self._master = None
            self._domain = None
            self._domain_ptr = 0
            print("[igh] Master released.")



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

    def read_pdo(self, index: int, subindex: int = 0, slave: int = 1) -> Any:
        """Read a PDO-mapped object from the process data image.

        SOEM maps PDO data to the IOMap buffer. The ec_slave struct has
        'inputs' (c_void_p) pointing to its TxPDO region. This method
        does a best-effort read: for SDO-mapped objects, falls back to
        ec_SDOread. For true PDO objects, the IOMap offset must be known.

        Currently delegates to SDO read (functional but not real PDO speed).
        Full PDO access requires tracking IOMap byte offsets per slave.
        """
        # Fallback to SDO read for now (works for all objects, but slower)
        ok, val = self._soem.ec_SDOread(slave, index, subindex)
        return val if ok else None

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

    Three backends:
      - IgHEtherCAT:     Linux production, libethercat.so + kernel module
      - RealEtherCAT:    SOEM on Windows/lab, libsoem.dll
      - SimulatedEtherCAT: No hardware, dev/test

    Usage:
        master = EcMaster()                  # auto-detect
        master = EcMaster(adapter="sim")     # force simulation
        master = EcMaster(adapter="eth0")    # force real on eth0
        master = EcMaster(adapter="igh")     # force IgH on Linux

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
        self._is_igh = False

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def scan(self, axis_names: Optional[List[str]] = None) -> int:
        """Initialize and scan the EtherCAT bus. Returns slave count."""
        # ── IgH mode (Linux production) ──
        if self.adapter == "igh" or (self.adapter == "auto" and self._igh_available()):
            self._backend = IgHEtherCAT()
            self._is_igh = True
            self._is_sim = False
            count = self._backend.scan(axis_names=axis_names)
            return count

        # ── Simulation mode ──
        if self.adapter == "sim" or (self.adapter == "auto" and not self._real_available()):
            self._backend = SimulatedEtherCAT()
            self._is_sim = True
            self._is_igh = False
        else:
            # ── SOEM mode (Windows/lab) ──
            self._backend = RealEtherCAT(self.adapter)
            self._is_sim = False
            self._is_igh = False

        self._backend.init(self.adapter)
        count = self._backend.config_init()
        self._backend.config_map()
        return count

    def _real_available(self) -> bool:
        if _SOEM is None:
            return False
        return _SOEM.available

    def _igh_available(self) -> bool:
        """Check if IgH is available (Linux kernel module loaded)."""
        import platform
        if platform.system() != "Linux":
            return False
        try:
            from . import igh_bindings
            igh = igh_bindings.get_igh()
            return igh.available
        except Exception:
            return False

    @property
    def slaves(self) -> List[EcSlave]:
        return self._backend.slaves if self._backend else []

    @property
    def slavecount(self) -> int:
        return self._backend.slavecount if self._backend else 0

    @property
    def is_simulation(self) -> bool:
        return self._is_sim

    @property
    def is_igh(self) -> bool:
        """True if using IgH EtherCAT Master (Linux production)."""
        return self._is_igh

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
        return self._backend.sdo_read(index, subindex, slave)

    def sdo_write(self, index: int, subindex: int, value: Any,
                  slave: int = 1) -> bool:
        """Write a CoE object via SDO."""
        return self._backend.sdo_write(index, subindex, value, slave)

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

    def read_pdo(self, index: int, subindex: int = 0, slave: int = 1) -> Any:
        """Read a PDO-mapped object from the process data image.

        Args:
            index: CoE object index.
            subindex: Sub-index.
            slave: Slave position (1-based).
        """
        result = self._backend.read_pdo(index, subindex, slave)
        if isinstance(result, tuple):
            return result[1] if result[0] else None
        return result

    def write_pdo(self, index: int, subindex: int, value: Any, slave: int = 1):
        """Write a PDO-mapped object to the process data image."""
        self._backend.write_pdo(index, subindex, value, slave)

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

    def read_scope(self, axis_id: str = "Axis0") -> Dict[str, float]:
        """Read all 8 scope channels for one axis.

        IgH backend: reads from domain data buffer at pre-configured offsets.
        SOEM/sim backend: calls read_pdo for each channel.

        Returns:
            {"Position": 1000.0, "Velocity": 500.0, ...}
        """
        if self._is_igh:
            return self._backend.read_scope(axis_id)

        # SOEM/sim fallback: per-object PDO read
        self.exchange()
        channel_map = [
            (0x6064, "Position"), (0x606C, "Velocity"),
            (0x6078, "Current"), (0x6077, "Torque"),
            (0x60F4, "Foll.Err"), (0x60FD, "DIO"),
            (0x6041, "Status"), (0x6061, "OpMode"),
        ]
        result = {}
        for idx, name in channel_map:
            val = self.read_pdo(idx, 0)
            result[name] = float(val) if val is not None else 0.0
        return result

    def read_scope_all_axes(self) -> Dict[str, Dict[str, float]]:
        """Read scope channels for all configured axes.

        IgH: single domain buffer access, all axes in one call.
        SOEM/sim: iterates read_scope per axis.

        Returns:
            {"X": {"Position": ..., "Velocity": ...}, "Y": {...}, ...}
        """
        if self._is_igh:
            return self._backend.read_scope_all_axes()

        # SOEM/sim: one at a time (all slaves share the same exchange)
        result = {}
        self.exchange()
        for slave in self.slaves:
            axis_id = getattr(slave, 'name', f"Axis{slave.position}")
            channel_map = [
                (0x6064, "Position"), (0x606C, "Velocity"),
                (0x6078, "Current"), (0x6077, "Torque"),
                (0x60F4, "Foll.Err"), (0x60FD, "DIO"),
                (0x6041, "Status"), (0x6061, "OpMode"),
            ]
            axis_data = {}
            for idx, name in channel_map:
                val = self.read_pdo(idx, 0)
                axis_data[name] = float(val) if val is not None else 0.0
            result[axis_id] = axis_data
        return result

    def discover(self) -> List[dict]:
        """Discover all slaves on the bus and match against ESI library.

        Reads SII EEPROM data from each slave (vendor, product, name, revision)
        via the active backend (SOEM/IgH/Sim). Auto-matches against the ESI
        library to identify brand and model.

        Returns:
            List of slave dicts with position, vendor_id, product_code, revision,
            sii_name, state, has_dc, and esi_match fields.
        """
        from .discover import discover_slaves
        return discover_slaves(self)

    @property
    def axis_ids(self) -> List[str]:
        """List of configured axis IDs."""
        if self._is_igh:
            return self._backend.axis_ids
        return [getattr(s, 'name', f"Axis{s.position}") for s in self.slaves]

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

"""
IgH EtherCAT Master — ctypes bindings for libethercat.so.

The IgH EtherCAT Master is the industry-standard open-source EtherCAT stack
for Linux. It runs as a kernel module (ec_master.ko) with a userspace library
(libethercat.so) for configuration and cyclic data exchange.

Unlike SOEM (imperative: read_pdo anytime), IgH is DECLARATIVE:
  1. Configure domains + PDO entries upfront (no data yet)
  2. ecrt_master_activate() → enters OPERATIONAL
  3. Cyclic: receive → read domain buffer → queue → send

This module provides ctypes wrappers for the full userspace API.

References:
  - IgH EtherCAT Master 1.6 (etherlab.org)
  - Documentation: https://etherlab.org/en/ethercat/
  - Source: https://gitlab.com/etherlab.org/etherlabmaster

Usage:
    from igh_bindings import IgHMaster, PdoEntryReg

    master = IgHMaster()
    master.request(0)
    master.create_domain("scope_domain")

    # Register PDO entries for each slave
    for slave_pos in [0, 1, 2]:
        slave_cfg = master.get_slave_config(slave_pos, vendor_id, product_code)
        for ch in scope_channels:
            master.reg_pdo_entry(slave_cfg, ch.index, 0, offset_ptr)

    master.activate()
    while running:
        master.receive()
        data = master.domain_data()
        # Read per-axis values from data at known offsets
        master.queue()
        master.send()
    master.deactivate()
"""

import ctypes
import os
import struct
from ctypes import (
    POINTER, Structure, byref, c_char_p, c_int, c_int32, c_uint8, c_uint16,
    c_uint32, c_uint64, c_void_p,
)
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================================
# IgH Type Definitions
# ============================================================================

# Opaque pointers (we never dereference — just pass back to API)
ec_master_t = c_void_p
ec_domain_t = c_void_p
ec_slave_config_t = c_void_p
ec_slave_config_state_t = c_void_p


class ec_pdo_entry_reg_t(Structure):
    """PDO entry registration — matches IgH 1.5.2 ecrt.h exactly.

    Verified against: ethercat-1.5.2/include/ecrt.h:495-508

    Each entry registers one CoE object into a domain. The API writes back
    the byte offset (via *offset) and optionally the bit position (via
    *bit_position, which can be NULL if byte-aligned).

    The list is terminated by an all-zero entry (IgH sentinel).

    Reference IgH user example:
        const static ec_pdo_entry_reg_t domain1_regs[] = {
            {AnaInSlavePos, Beckhoff_EL3102, 0x3101, 1, &off_ana_in_status},
            {AnaInSlavePos, Beckhoff_EL3102, 0x3101, 2, &off_ana_in_value},
            {}
        };

    Fields:
        alias:        Slave alias (0 = use position)
        position:     Slave ring position (0-based)
        vendor_id:    Expected vendor ID (e.g. 0x00000002 for Beckhoff)
        product_code: Expected product code
        index:        CoE object index (e.g. 0x6064 for Position)
        subindex:     Sub-index (0 for single-value objects)
        offset:       OUTPUT — pointer to byte offset within domain data
        bit_position: OUTPUT — pointer to bit position (0-7), can be NULL
    """
    _fields_ = [
        ("alias", c_uint16),
        ("position", c_uint16),
        ("vendor_id", c_uint32),
        ("product_code", c_uint32),
        ("index", c_uint16),
        ("subindex", c_uint8),
        # ctypes auto-pads here for pointer alignment (5 bytes on 64-bit, 1 on 32-bit)
        ("offset", POINTER(c_uint32)),       # unsigned int *offset
        ("bit_position", POINTER(c_uint32)),  # unsigned int *bit_position (can be NULL)
    ]


class ec_master_info_t(Structure):
    """Master information struct."""
    _fields_ = [
        ("slave_count", c_uint32),
        ("link_up", c_uint32),
        ("scan_busy", c_uint32),
        ("app_time", c_uint64),
        ("_reserved", c_uint8 * 32),
    ]


class ec_slave_info_t(Structure):
    """Slave information struct (simplified — key fields only)."""
    _fields_ = [
        ("position", c_uint16),
        ("alias", c_uint16),
        ("vendor_id", c_uint32),
        ("product_code", c_uint32),
        ("revision_number", c_uint32),
        ("serial_number", c_uint32),
        ("name", c_char_p),
        ("state", c_uint16),
    ]


# ============================================================================
# IgH DLL Loader
# ============================================================================


class IgHLibrary:
    """Load and wrap libethercat.so."""

    def __init__(self, lib_path: Optional[str] = None):
        self._lib = None
        self._available = False
        self._load_error: str = ""

        search_paths = []
        if lib_path:
            search_paths.append(Path(lib_path))
        search_paths.extend([
            Path("/usr/lib/libethercat.so"),
            Path("/usr/local/lib/libethercat.so"),
            Path("/opt/etherlab/lib/libethercat.so"),
            Path("libethercat.so"),  # LD_LIBRARY_PATH
        ])

        for p in search_paths:
            if p.exists() or not p.is_absolute():
                try:
                    self._lib = ctypes.CDLL(str(p))
                    self._available = True
                    break
                except OSError as e:
                    self._load_error = str(e)

        if self._available:
            self._bind_functions()

    def _bind_functions(self):
        """Define ctypes function signatures for libethercat.so."""
        lib = self._lib

        # ── Master lifecycle ──
        lib.ecrt_request_master.argtypes = [c_uint32]
        lib.ecrt_request_master.restype = ec_master_t

        lib.ecrt_release_master.argtypes = [ec_master_t]
        lib.ecrt_release_master.restype = None

        # ── Domain management ──
        lib.ecrt_master_create_domain.argtypes = [ec_master_t]
        lib.ecrt_master_create_domain.restype = ec_domain_t

        # ── Slave configuration ──
        lib.ecrt_master_slave_config.argtypes = [
            ec_master_t, c_uint16, c_uint16,
            c_uint32, c_uint32,
        ]
        lib.ecrt_master_slave_config.restype = ec_slave_config_t

        # ── PDO entry registration ──
        lib.ecrt_slave_config_reg_pdo_entry.argtypes = [
            ec_slave_config_t, c_uint16, c_uint8,
            ec_domain_t, POINTER(c_uint32),
        ]
        lib.ecrt_slave_config_reg_pdo_entry.restype = c_int

        # ── PDO entry list (batch register, terminated by empty entry) ──
        lib.ecrt_domain_reg_pdo_entry_list.argtypes = [
            ec_domain_t, POINTER(ec_pdo_entry_reg_t),
        ]
        lib.ecrt_domain_reg_pdo_entry_list.restype = c_int

        # ── Master activation ──
        lib.ecrt_master_activate.argtypes = [ec_master_t]
        lib.ecrt_master_activate.restype = c_int

        lib.ecrt_master_deactivate.argtypes = [ec_master_t]
        lib.ecrt_master_deactivate.restype = None

        # ── Cyclic data exchange ──
        lib.ecrt_master_receive.argtypes = [ec_master_t]
        lib.ecrt_master_receive.restype = None

        lib.ecrt_master_send.argtypes = [ec_master_t]
        lib.ecrt_master_send.restype = None

        lib.ecrt_domain_queue.argtypes = [ec_domain_t]
        lib.ecrt_domain_queue.restype = None

        lib.ecrt_domain_data.argtypes = [ec_domain_t]
        lib.ecrt_domain_data.restype = c_void_p

        lib.ecrt_domain_process.argtypes = [ec_domain_t]
        lib.ecrt_domain_process.restype = None

        # ── Slave state ──
        lib.ecrt_slave_config_state.argtypes = [ec_slave_config_t]
        lib.ecrt_slave_config_state.restype = ec_slave_config_state_t

        # ── Master info ──
        lib.ecrt_master.argtypes = [ec_master_t, POINTER(ec_master_info_t)]
        lib.ecrt_master.restype = c_int

        # ── SDO configuration (during setup, not cyclic) ──
        lib.ecrt_slave_config_sdo8.argtypes = [
            ec_slave_config_t, c_uint16, c_uint8, c_uint8,
        ]
        lib.ecrt_slave_config_sdo8.restype = c_int

        lib.ecrt_slave_config_sdo16.argtypes = [
            ec_slave_config_t, c_uint16, c_uint8, c_uint16,
        ]
        lib.ecrt_slave_config_sdo16.restype = c_int

        lib.ecrt_slave_config_sdo32.argtypes = [
            ec_slave_config_t, c_uint16, c_uint8, c_uint32,
        ]
        lib.ecrt_slave_config_sdo32.restype = c_int

        # ── Distributed Clocks ──
        lib.ecrt_slave_config_dc.argtypes = [
            ec_slave_config_t, c_uint16, c_uint32, c_int32, c_int32, c_int32, c_int32,
        ]
        lib.ecrt_slave_config_dc.restype = c_int

        # ── Watchdog ──
        lib.ecrt_slave_config_watchdog.argtypes = [
            ec_slave_config_t, c_uint16, c_uint16,
        ]
        lib.ecrt_slave_config_watchdog.restype = c_int

    @property
    def available(self) -> bool:
        return self._available

    @property
    def load_error(self) -> str:
        return self._load_error


# Singleton
_igh: Optional[IgHLibrary] = None


def get_igh() -> IgHLibrary:
    """Get or create the IgH library singleton."""
    global _igh
    if _igh is None:
        _igh = IgHLibrary()
    return _igh


# ============================================================================
# Data Access Helpers
# ============================================================================


class DomainAccessor:
    """Read typed data from an IgH domain buffer at known byte offsets.

    IgH returns a raw uint8_t* from ecrt_domain_data(). This class wraps
    that pointer with typed accessors for CiA 402 objects.

    Usage:
        accessor = DomainAccessor(domain_data_ptr, self._offsets)
        pos = accessor.read_int32("X", 0x6064)  # Axis X position
        cur = accessor.read_uint16("Y", 0x6078) # Axis Y current
    """

    def __init__(self, domain_data_ptr: int,
                 offsets: Dict[str, Dict[int, Tuple[int, str]]]):
        """Args:
            domain_data_ptr: Raw pointer from ecrt_domain_data().
            offsets: {axis_id: {index: (byte_offset, data_type)}}
                e.g. {"X": {0x6064: (0, "DINT"), 0x6078: (4, "INT")}}
        """
        self._ptr = domain_data_ptr
        self._offsets = offsets

    def _read(self, axis_id: str, index: int) -> Optional[int]:
        axis_offsets = self._offsets.get(axis_id, {})
        entry = axis_offsets.get(index)
        if entry is None:
            return None
        byte_offset, data_type = entry
        addr = self._ptr + byte_offset

        fmt = {
            "SINT": "b", "USINT": "B",
            "INT": "h", "UINT": "H",
            "DINT": "i", "UDINT": "I",
            "REAL": "f", "LREAL": "d",
        }
        size = {
            "SINT": 1, "USINT": 1,
            "INT": 2, "UINT": 2,
            "DINT": 4, "UDINT": 4,
            "REAL": 4, "LREAL": 8,
        }
        s_fmt = fmt.get(data_type, "I")
        n_bytes = size.get(data_type, 4)

        buf = ctypes.string_at(addr, n_bytes)
        try:
            return struct.unpack(s_fmt, buf)[0]
        except Exception:
            return None

    def read_int32(self, axis_id: str, index: int) -> int:
        val = self._read(axis_id, index)
        return int(val) if val is not None else 0

    def read_uint32(self, axis_id: str, index: int) -> int:
        val = self._read(axis_id, index)
        return int(val) if val is not None else 0

    def read_uint16(self, axis_id: str, index: int) -> int:
        val = self._read(axis_id, index)
        return int(val) if val is not None else 0

    def read_all_scope(self, axis_id: str,
                       channel_indices: List[int]) -> Dict[int, int]:
        """Read all scope channels for one axis. Returns {index: value}."""
        return {idx: self.read_int32(axis_id, idx) for idx in channel_indices}


# ============================================================================
# PDO Entry Registration Builder
# ============================================================================


def build_pdo_entry_list(
    slave_position: int,
    vendor_id: int,
    product_code: int,
    entries: List[Tuple[int, int]],  # [(index, subindex), ...]
    offset_ptrs: List[ctypes.POINTER(c_uint32)],
) -> ctypes.Array:
    """Build an ec_pdo_entry_reg_t array for ecrt_domain_reg_pdo_entry_list().

    The array is terminated with an all-zero entry (IgH sentinel).

    Verfified against: ethercat-1.5.2/examples/user/main.c:92-98

    Args:
        slave_position: EtherCAT ring position (0-based).
        vendor_id: Vendor ID (e.g. 0x000001DD for Delta).
        product_code: Product code (e.g. 0x00006010 for ASDA-A3-E).
        entries: List of (index, subindex) tuples to register.
        offset_ptrs: Pre-allocated c_uint32 pointers (one per entry).
                     The API writes byte offsets back into these.

    Returns:
        ctypes array of ec_pdo_entry_reg_t, terminated with a zero entry.
    """
    n = len(entries)
    regs = (ec_pdo_entry_reg_t * (n + 1))()

    for i, ((idx, sub), offset_ptr) in enumerate(zip(entries, offset_ptrs)):
        regs[i].alias = 0
        regs[i].position = slave_position
        regs[i].vendor_id = vendor_id
        regs[i].product_code = product_code
        regs[i].index = idx
        regs[i].subindex = sub
        regs[i].offset = offset_ptr
        regs[i].bit_position = None  # NULL → require byte-aligned entries

    # Sentinel: all zeros
    regs[n].alias = 0
    regs[n].position = 0
    regs[n].vendor_id = 0
    regs[n].product_code = 0
    regs[n].index = 0
    regs[n].subindex = 0
    regs[n].offset = None
    regs[n].bit_position = None

    return regs

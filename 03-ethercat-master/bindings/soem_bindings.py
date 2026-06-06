"""
SOEM ctypes bindings — Windows DLL wrapper for Simple Open EtherCAT Master.

Loads libsoem.dll (built from src/SOEM) and exposes all key EtherCAT functions
as Python ctypes wrappers.

If the DLL is not available, falls back gracefully — the EcMasterSimulator
in ec_master.py provides a full simulation alternative.
"""

import ctypes
import os
import platform
from ctypes import (
    POINTER, Structure, byref, c_bool, c_char, c_char_p, c_int, c_int16,
    c_int32, c_int64, c_uint8, c_uint16, c_uint32, c_void_p,
)
from pathlib import Path
from typing import Optional


# ============================================================================
# Type definitions (matching SOEM ethercattype.h)
# ============================================================================

# boolean → c_uint8
c_boolean = c_uint8

# EC_MAXSLAVE = 200, EC_MAXNAME = 40
EC_MAXSLAVE = 200
EC_MAXNAME = 40
EC_MAXSM = 8
EC_MAXFMMU = 8


class ec_fmmut(Structure):
    """FMMU configuration struct."""
    _fields_ = [
        ("LogStart", c_uint32),
        ("LogLength", c_uint16),
        ("LogStartbit", c_uint8),
        ("LogEndbit", c_uint8),
        ("PhysStart", c_uint16),
        ("PhysStartBit", c_uint8),
        ("FMMUtype", c_uint8),
        ("FMMUactive", c_uint8),
        ("_pad", c_uint8),
    ]


class ec_smt(Structure):
    """SyncManager configuration struct."""
    _fields_ = [
        ("StartAddr", c_uint16),
        ("SMlength", c_uint16),
        ("SMflags", c_uint32),
    ]


class ec_slavet(Structure):
    """Complete slave info struct (simplified for ctypes).

    The full struct is ~400 bytes. We keep the fields needed for Python
    bindings. For production, a full mapping would be in a .pyi stub.
    """
    _fields_ = [
        ("state", c_uint16),
        ("ALstatuscode", c_uint16),
        ("configadr", c_uint16),
        ("aliasadr", c_uint16),
        ("eep_man", c_uint32),
        ("eep_id", c_uint32),
        ("eep_rev", c_uint32),
        ("Obits", c_uint16),
        ("Obytes", c_uint32),
        ("outputs", c_void_p),
        ("Ibits", c_uint16),
        ("Ibytes", c_uint32),
        ("inputs", c_void_p),
        ("hasdc", c_boolean),
        ("pdelay", c_int32),
        ("DCcycle", c_int32),
        ("DCshift", c_int32),
        ("DCactive", c_uint8),
        ("_pad1", c_uint8 * 3),
        ("name", c_char * (EC_MAXNAME + 1)),
    ]


class ec_groupt(Structure):
    """Slave group struct."""
    _fields_ = [
        ("logstartaddr", c_uint32),
        ("Obytes", c_uint32),
        ("Ibytes", c_uint32),
        ("outputs", c_void_p),
        ("inputs", c_void_p),
        ("hasdc", c_boolean),
        ("_pad", c_uint8 * 3),
        ("outputsWKC", c_uint16),
        ("inputsWKC", c_uint16),
    ]


class ec_adaptert(Structure):
    """Network adapter info."""
    pass  # Forward reference for linked list


ec_adaptert._fields_ = [
    ("name", c_char * 128),
    ("desc", c_char * 128),
    ("next", POINTER(ec_adaptert)),
]

# Error type (simplified)
class ec_errort(Structure):
    _pack_ = 1
    _fields_ = [
        ("Time", c_int64),
        ("Signal", c_int32),
        ("Slave", c_uint16),
        ("Index", c_uint16),
        ("SubIdx", c_uint8),
        ("AbortCode", c_int32),
        ("Eoe", c_int16),
        ("SoeIndex", c_int16),
    ]


# ============================================================================
# DLL loader
# ============================================================================


class SOEMLibrary:
    """Load and wrap the SOEM shared library."""

    def __init__(self, dll_path: Optional[str] = None):
        self._dll = None
        self._available = False
        self._load_error: str = ""

        # Find DLL
        if dll_path:
            paths = [Path(dll_path)]
        else:
            paths = [
                Path(__file__).resolve().parent.parent / "src" / "SOEM" / "lib" / "win32" / "libsoem.lib",
                Path("libsoem.dll"),
                Path("./libsoem.dll"),
            ]

        for p in paths:
            if p.exists() and p.suffix in (".dll", ".lib"):
                try:
                    self._dll = ctypes.CDLL(str(p))
                    self._available = True
                    break
                except OSError as e:
                    self._load_error = str(e)

        if self._available:
            self._bind_functions()
        else:
            self._load_error = self._load_error or (
                "libsoem.dll not found. Build SOEM from src/SOEM/ using "
                "make_libsoem_lib.bat, or use EcMasterSimulator."
            )

    def _bind_functions(self):
        """Define all ctypes function signatures."""
        dll = self._dll

        # --- Init / Close ---
        dll.ec_init.argtypes = [c_char_p]
        dll.ec_init.restype = c_int

        dll.ec_close.argtypes = []
        dll.ec_close.restype = None

        # --- Config ---
        dll.ec_config_init.argtypes = [c_uint8]
        dll.ec_config_init.restype = c_int

        dll.ec_config_map.argtypes = [c_void_p]
        dll.ec_config_map.restype = c_int

        # --- State ---
        dll.ec_readstate.argtypes = []
        dll.ec_readstate.restype = c_int

        dll.ec_writestate.argtypes = [c_uint16]
        dll.ec_writestate.restype = c_int

        dll.ec_statecheck.argtypes = [c_uint16, c_uint16, c_int]
        dll.ec_statecheck.restype = c_uint16

        # --- Process data ---
        dll.ec_send_processdata.argtypes = []
        dll.ec_send_processdata.restype = c_int

        dll.ec_receive_processdata.argtypes = [c_int]
        dll.ec_receive_processdata.restype = c_int

        # --- CoE SDO ---
        dll.ec_SDOread.argtypes = [
            c_uint16, c_uint16, c_uint8, c_boolean,
            POINTER(c_int), c_void_p, c_int,
        ]
        dll.ec_SDOread.restype = c_int

        dll.ec_SDOwrite.argtypes = [
            c_uint16, c_uint16, c_uint8, c_boolean,
            c_int, c_void_p, c_int,
        ]
        dll.ec_SDOwrite.restype = c_int

        # --- Adapter ---
        dll.ec_find_adapters.argtypes = []
        dll.ec_find_adapters.restype = POINTER(ec_adaptert)

        dll.ec_free_adapters.argtypes = [POINTER(ec_adaptert)]
        dll.ec_free_adapters.restype = None

        # --- Globals ---
        # ec_slavecount is an exported int
        try:
            self._ec_slavecount = ctypes.c_int.in_dll(dll, "ec_slavecount")
        except Exception:
            self._ec_slavecount = None

    # ==================================================================
    # Wrapped API methods
    # ==================================================================

    @property
    def available(self) -> bool:
        return self._available

    @property
    def load_error(self) -> str:
        return self._load_error

    def ec_init(self, ifname: str) -> int:
        """Initialize SOEM, bind to network interface. Returns 0 on success."""
        if not self._available:
            return -1
        return self._dll.ec_init(ifname.encode("utf-8"))

    def ec_close(self):
        if self._available:
            self._dll.ec_close()

    def ec_config_init(self, usetable: bool = False) -> int:
        """Scan and auto-configure slaves. Returns slave count."""
        if not self._available:
            return -1
        return self._dll.ec_config_init(c_uint8(1 if usetable else 0))

    def ec_config_map(self, io_map: c_void_p) -> int:
        """Map PDOs to IOmap buffer. Returns WKC."""
        if not self._available:
            return -1
        return self._dll.ec_config_map(io_map)

    def ec_readstate(self) -> int:
        if not self._available:
            return -1
        return self._dll.ec_readstate()

    def ec_writestate(self, slave: int) -> int:
        """Write state to slave (0 = all slaves)."""
        if not self._available:
            return -1
        return self._dll.ec_writestate(c_uint16(slave))

    def ec_statecheck(self, slave: int, reqstate: int, timeout: int) -> int:
        """Wait for slave to reach requested state. Returns state."""
        if not self._available:
            return 0
        return self._dll.ec_statecheck(c_uint16(slave), c_uint16(reqstate), timeout)

    def ec_send_processdata(self) -> int:
        if not self._available:
            return -1
        return self._dll.ec_send_processdata()

    def ec_receive_processdata(self, timeout: int) -> int:
        """Returns WorkCounter."""
        if not self._available:
            return -1
        return self._dll.ec_receive_processdata(timeout)

    def ec_SDOread(self, slave: int, index: int, subindex: int,
                   complete_access: bool = False) -> tuple:
        """Read SDO object. Returns (success_bool, data_bytes)."""
        if not self._available:
            return False, b""
        buf_size = c_int(1024)
        buf = ctypes.create_string_buffer(1024)
        ret = self._dll.ec_SDOread(
            c_uint16(slave), c_uint16(index), c_uint8(subindex),
            c_boolean(1 if complete_access else 0),
            byref(buf_size), buf, 2000,  # EC_TIMEOUTRXM
        )
        if ret > 0:
            return True, buf.raw[:buf_size.value]
        return False, b""

    def ec_SDOwrite(self, slave: int, index: int, subindex: int,
                    data: bytes, complete_access: bool = False) -> bool:
        """Write SDO object. Returns success."""
        if not self._available:
            return False
        ret = self._dll.ec_SDOwrite(
            c_uint16(slave), c_uint16(index), c_uint8(subindex),
            c_boolean(1 if complete_access else 0),
            len(data), ctypes.c_char_p(data), 2000,
        )
        return ret > 0

    def ec_find_adapters(self) -> list:
        """List available network adapters. Returns [(name, desc), ...]."""
        if not self._available:
            return []
        adapters = []
        head = self._dll.ec_find_adapters()
        current = head
        while current:
            adapters.append((
                current.contents.name.decode("utf-8", errors="replace"),
                current.contents.desc.decode("utf-8", errors="replace"),
            ))
            current = current.contents.next
        self._dll.ec_free_adapters(head)
        return adapters

    @property
    def slavecount(self) -> int:
        if self._available and self._ec_slavecount is not None:
            return self._ec_slavecount.value
        return 0


# Singleton
_soem: Optional[SOEMLibrary] = None


def get_soem() -> SOEMLibrary:
    global _soem
    if _soem is None:
        _soem = SOEMLibrary()
    return _soem

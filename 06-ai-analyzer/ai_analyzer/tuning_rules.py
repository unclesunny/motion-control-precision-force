"""
Tuning Rules — Free shell (CiA 402 standard reference only).

Pro license required for:
  - 148 brand-specific tuning aliases (12 brands)
  - 56 parameter descriptions with tuning guidance
  - LPF/S-Curve auto-calculation rules
  - Brand capability notes and recommended values

This Free version contains only CiA 402 standard object names (public IEC standard).
"""

# ── CiA 402 standard object names (public IEC 61800-7 standard) ──
CIA402_STANDARD_NAMES = {
    0x1000: "Device type",
    0x1008: "Device name",
    0x1009: "Hardware version",
    0x100A: "Software version",
    0x1018: "Identity object",
    0x6040: "Controlword",
    0x6041: "Statusword",
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
    0x6081: "Profile velocity",
    0x6083: "Profile acceleration",
    0x6084: "Profile deceleration",
    0x60B1: "Velocity offset",
    0x60B2: "Torque offset",
}

# ── Parameter descriptions (CiA 402 standard only) ──
PARAM_DESCRIPTIONS: dict = {
    0x6040: "Controlword — state machine commands per CiA 402",
    0x6041: "Statusword — drive state per CiA 402",
    0x6060: "Modes of operation — profile position/velocity/torque",
    0x6061: "Modes of operation display — current operating mode",
    0x6064: "Position actual value (pulses)",
    0x606C: "Velocity actual value (rpm)",
    0x6071: "Target torque (0.1% rated)",
    0x6077: "Torque actual value (0.1% rated)",
    0x6078: "Current actual value (0.1% rated)",
    0x607A: "Target position (pulses)",
    0x60FF: "Target velocity (rpm)",
    0x60FD: "Digital inputs (bit-mapped)",
    0x60F4: "Following error actual value (pulses)",
    0x6081: "Profile velocity (rpm)",
    0x6083: "Profile acceleration (rpm/s)",
    0x6084: "Profile deceleration (rpm/s)",
    0x60B1: "Velocity offset (rpm)",
    0x60B2: "Torque offset (0.1% rated)",
}

# ── Brand aliases (Free: brand names are public knowledge) ──
BRAND_ALIASES: dict = {
    "default": "default",
    "delta-a3": "Delta A3",
    "yaskawa-sigma7": "Yaskawa Σ-7",
    "panasonic-a6": "Panasonic A6",
    "invt-da200": "INVT DA200",
    "estun-pronet": "Estun ProNet",
    "leadshine-dm3e": "Leadshine DM3E",
    "leadshine-cl3": "Leadshine CL3",
    "elmo-gold": "Elmo Gold",
    "servotronix-cdhd": "Servotronix CDHD",
    "lenze-i700": "Lenze i700",
}

# ── Brand capability notes (empty in Free) ──
BRAND_CAPABILITY_NOTES: dict = {}

# ── LPF / S-Curve aliases (empty in Free) ──
LPF_ALIASES: dict = {}
SCURVE_ALIASES: dict = {}

# ── Pro license notice ──
_PRO_LICENSE_REQUIRED = (
    "Pro license required for 148 brand-specific tuning aliases (12 brands), "
    "56 parameter descriptions with tuning guidance, LPF/S-Curve auto-calculation "
    "rules, and brand capability notes. Contact your vendor for licensing."
)

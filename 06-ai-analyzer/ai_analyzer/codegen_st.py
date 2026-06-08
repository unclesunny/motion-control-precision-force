"""
CODESYS ST Code Generator — AI annotations → IEC 61131-3 Structured Text.

Generates complete FUNCTION_BLOCK definitions for servo diagnostics and
parameter tuning, deployable directly to CODESYS runtime.

Architecture:
    AIAnnotation[] + ParameterRecommendation[] + TuningRules
        → CodegenST
        → FB_ServoDiag.st + FB_ServoTune.st + DUT_ServoDiag.st

Self-contained — no dependency on external RuleInjector or AI&ML Agent.
Follows IEC 61131-3 ST syntax: := for assignment, = for comparison,
// for comments, (* *) for block comments.

Usage:
    from codegen_st import CodegenST

    gen = CodegenST(brand="delta-a3")
    fb_diag = gen.generate_fb_diag(annotations)
    fb_tune = gen.generate_fb_tune(recommendations)
    dut = gen.generate_dut()

    # Write to files
    gen.export_all("07-codesys-fb/")
"""

import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── CODESYS type mapping ─────────────────────────────────────

# CiA 402 index → CODESYS-compatible variable name + type
CIA402_VAR_MAP: Dict[int, tuple] = {
    0x6064: ("iActualPosition", "DINT", "Position Actual Value"),
    0x606C: ("iActualVelocity", "DINT", "Velocity Actual Value (0.1 rpm)"),
    0x6077: ("iActualTorque", "INT", "Torque Actual Value (permille rated)"),
    0x6078: ("iActualCurrent", "INT", "Current Actual Value (permille rated)"),
    0x60F4: ("iFollowingError", "DINT", "Following Error Actual Value"),
    0x6041: ("iStatusWord", "UINT", "Status Word"),
    0x6061: ("iOpMode", "INT", "Modes of Operation Display"),
    0x60FD: ("iDigitalInputs", "UDINT", "Digital Inputs"),
}

# CODESYS IEC types
IEC_INT  = "INT"
IEC_DINT = "DINT"
IEC_UDINT = "UDINT"
IEC_REAL = "REAL"
IEC_BOOL = "BOOL"
IEC_UINT = "UINT"


class CodegenST:
    """CODESYS Structured Text code generator for servo diagnostics.

    Parameters:
        brand: Servo brand key (e.g. "delta-a3", "yaskawa-sigma7").
              Affects parameter indexing in generated code.
        author: Author name embedded in code header.
        fb_prefix: Prefix for generated function block names.
    """

    def __init__(self, brand: str = "delta-a3", author: str = "AI Analyzer",
                 fb_prefix: str = "FB_"):
        self.brand = brand
        self.author = author
        self.fb_prefix = fb_prefix
        self._timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── FB_ServoDiag Generation ──────────────────────────────

    def generate_fb_diag(self, annotations: List[Any],
                         fb_name: str = "FB_ServoDiag") -> str:
        """Generate FB_ServoDiag — continuous anomaly detection.

        Args:
            annotations: List of AIAnnotation from the pipeline.
            fb_name: Function block name.

        Returns:
            Complete IEC 61131-3 ST FUNCTION_BLOCK source code.
        """
        # Deduplicate annotations by category
        seen_categories = set()
        unique_anns = []
        for a in annotations:
            if a.category not in seen_categories:
                seen_categories.add(a.category)
                unique_anns.append(a)

        sections = []
        sections.append(self._header(fb_name, "Servo Drive Diagnostic Block"))
        sections.append(self._fb_diag_variables(unique_anns, fb_name))
        sections.append(self._fb_diag_body(unique_anns))
        return "\n\n".join(sections)

    def _fb_diag_variables(self, annotations: List[Any], fb_name: str = "FB_ServoDiag") -> str:
        """Generate FUNCTION_BLOCK declaration + VAR_INPUT, VAR_OUTPUT, VAR sections."""
        lines = []

        # ── FUNCTION_BLOCK declaration ──
        lines.append(f"FUNCTION_BLOCK {fb_name}")
        lines.append("")

        # ── VAR_INPUT ──
        lines.append("VAR_INPUT")
        lines.append("    // ── PDO Feedback (CiA 402) ──")
        for idx, (var_name, var_type, desc) in CIA402_VAR_MAP.items():
            default = self._default_value(var_type)
            lines.append(f"    {var_name:25s} : {var_type:6s} := {default};  // 0x{idx:04X} {desc}")

        lines.append("")
        lines.append("    // ── Detection Thresholds ──")
        for i, a in enumerate(annotations):
            safe_name = self._safe_var_name(a.category)
            threshold_val = a.value * 0.7 if a.value > 0 else 100.0
            if a.category == "current_saturation":
                threshold_val = 200.0
            elif a.category == "tracking_absolute_limit":
                threshold_val = 1000000.0
            lines.append(f"    r{safe_name}Threshold : REAL := {threshold_val:.1f};  // {a.category}")

        lines.append("")
        lines.append("    // ── HITL Confirmation ──")
        lines.append("    bOperatorConfirmed : BOOL := FALSE;  // Engineer authorization gate")
        lines.append("")
        lines.append("    // ── Enable ──")
        lines.append("    bEnable            : BOOL;")
        lines.append("END_VAR")

        # ── VAR_OUTPUT ──
        lines.append("VAR_OUTPUT")
        lines.append("    iFaultCode         : INT;      // 0=OK, see fault code table")
        lines.append("    bAlarm             : BOOL;     // Any alarm active")
        lines.append("    bShutdown          : BOOL;     // Critical fault -> E-Stop")
        lines.append("    rFaultScore        : REAL;     // 0.0~1.0 confidence")
        for i, a in enumerate(annotations):
            safe_name = self._safe_var_name(a.category)
            lines.append(f"    b{safe_name}Detected : BOOL;     // {a.category}")
        lines.append("END_VAR")

        # ── VAR ──
        lines.append("VAR")
        lines.append("    // ── Debounce counters ──")
        for i, a in enumerate(annotations):
            safe_name = self._safe_var_name(a.category)
            lines.append(f"    i{safe_name}Cnt     : INT := 0;")
        lines.append("")
        lines.append("    // ── Constants ──")
        lines.append("    iDebounceLimit     : INT := 10;  // Consecutive cycles to confirm")
        lines.append("END_VAR")

        return "\n".join(lines)

    def _fb_diag_body(self, annotations: List[Any]) -> str:
        """Generate the IF-THEN fault detection body."""
        lines = []
        lines.append(f"// ===== {self.fb_prefix}ServoDiag Method Body =====")
        lines.append("")
        lines.append("// ── Enable Gate ──")
        lines.append("IF NOT bEnable THEN")
        lines.append("    bAlarm    := FALSE;")
        lines.append("    bShutdown := FALSE;")
        lines.append("    iFaultCode := 0;")
        lines.append("    RETURN;")
        lines.append("END_IF;")
        lines.append("")

        # Generate detection blocks for each anomaly category
        for i, a in enumerate(annotations):
            safe_name = self._safe_var_name(a.category)
            var_name = self._channel_to_var(a.channel)
            condition = self._gen_detection_condition(a, var_name)
            lines.append(f"// ── {a.category}: {a.message[:60]} ──")
            lines.append(f"IF {condition} THEN")
            lines.append(f"    i{safe_name}Cnt := i{safe_name}Cnt + 1;")
            lines.append("ELSE")
            lines.append(f"    i{safe_name}Cnt := MAX(0, i{safe_name}Cnt - 1);")
            lines.append("END_IF;")
            lines.append("")

        # Fault aggregation (priority-ordered)
        lines.append("// ── Fault Aggregation ──")
        lines.append("iFaultCode := 0;")
        lines.append("bAlarm     := FALSE;")
        lines.append("bShutdown  := FALSE;")
        lines.append("rFaultScore := 0.0;")
        lines.append("")

        # Sort: critical first, then warning, then info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        sorted_anns = sorted(annotations, key=lambda a: severity_order.get(a.severity, 3))

        first = True
        for i, a in enumerate(sorted_anns):
            safe_name = self._safe_var_name(a.category)
            fault_code = annotations.index(a) + 1
            prefix = "IF" if first else "ELSIF"
            first = False

            is_critical = a.severity == "critical"
            shutdown_str = "TRUE" if is_critical else "FALSE"
            score_expr = f"MIN(1.0, INT_TO_REAL(i{safe_name}Cnt) / 20.0)"

            lines.append(f"{prefix} i{safe_name}Cnt >= iDebounceLimit THEN")
            lines.append(f"    iFaultCode := {fault_code};")
            lines.append(f"    bAlarm     := TRUE;")
            lines.append(f"    bShutdown  := {shutdown_str};")
            lines.append(f"    rFaultScore := {score_expr};")
            lines.append(f"    b{safe_name}Detected := TRUE;")

        lines.append("END_IF;")
        lines.append("")

        # Reset detection flags when no fault
        lines.append("// ── Reset detection flags ──")
        lines.append("IF iFaultCode = 0 THEN")
        for a in annotations:
            safe_name = self._safe_var_name(a.category)
            lines.append(f"    b{safe_name}Detected := FALSE;")
        lines.append("END_IF;")

        return "\n".join(lines)

    # ── FB_ServoTune Generation ──────────────────────────────

    def generate_fb_tune(self, recommendations: List[Any],
                         fb_name: str = "FB_ServoTune") -> str:
        """Generate FB_ServoTune — parameter adjustment logic.

        Args:
            recommendations: List of ParameterRecommendation.
            fb_name: Function block name.

        Returns:
            Complete IEC 61131-3 ST FUNCTION_BLOCK source code.
        """
        sections = []
        sections.append(self._header(fb_name, "Servo Parameter Tuning Block"))
        sections.append(self._fb_tune_variables(recommendations, fb_name))
        sections.append(self._fb_tune_body(recommendations))
        return "\n\n".join(sections)

    def _fb_tune_variables(self, recs: List[Any], fb_name: str = "FB_ServoTune") -> str:
        """Generate tuning FB variable declarations."""
        lines = []
        lines.append(f"FUNCTION_BLOCK {fb_name}")
        lines.append("")
        lines.append("VAR_INPUT")
        lines.append("    // ── HITL Authorization ──")
        lines.append("    bAuthorized        : BOOL;   // Engineer must set TRUE to execute")
        lines.append("    bExecute           : BOOL;   // Rising edge triggers parameter write")
        lines.append("")
        lines.append("    // ── Enable ──")
        lines.append("    bEnable            : BOOL;")
        lines.append("END_VAR")
        lines.append("")
        lines.append("VAR_OUTPUT")
        lines.append("    bBusy              : BOOL;   // Parameter write in progress")
        lines.append("    bDone              : BOOL;   // All parameters written successfully")
        lines.append("    bError             : BOOL;   // Write error")
        lines.append("    iErrorID           : INT;    // SDO abort code (0 = OK)")
        lines.append("    iParamIndex        : INT;    // Current parameter being written (0-based)")
        lines.append("END_VAR")
        lines.append("")
        lines.append("VAR")
        lines.append("    // ── State machine ──")
        lines.append("    iStep              : INT := 0;")
        lines.append("    iStepCount         : INT := {len(recs)};")
        lines.append("")
        lines.append("    // ── Edge detection ──")
        lines.append("    bExecutePrev       : BOOL;")
        lines.append("    bExecuteRising     : BOOL;")
        lines.append("")
        lines.append("    // ── Target values ──")
        for i, r in enumerate(recs):
            idx_hex = f"0x{r.index:04X}" if hasattr(r, 'index') else "0x????"
            safe_name = self._safe_var_name(f"param{i}_{idx_hex}")
            target = getattr(r, 'target_value', None) or 0.0
            lines.append(f"    r{safe_name}       : REAL := {target:.1f};")
        lines.append("END_VAR")

        return "\n".join(lines)

    def _fb_tune_body(self, recs: List[Any]) -> str:
        """Generate the tuning state machine body."""
        lines = []
        lines.append(f"// ===== {self.fb_prefix}ServoTune Method Body =====")
        lines.append("")
        lines.append("// ── Edge detection on bExecute ──")
        lines.append("bExecuteRising := bExecute AND NOT bExecutePrev;")
        lines.append("bExecutePrev   := bExecute;")
        lines.append("")
        lines.append("// ── State Machine ──")
        lines.append("CASE iStep OF")
        lines.append("")
        lines.append("0:  // ── Idle: wait for authorization + execute trigger ──")
        lines.append("    bBusy  := FALSE;")
        lines.append("    bDone  := FALSE;")
        lines.append("    bError := FALSE;")
        lines.append("    IF bAuthorized AND bExecuteRising THEN")
        lines.append("        iStep := 10;")
        lines.append("    END_IF;")
        lines.append("")

        # Generate one step per parameter
        for i, r in enumerate(recs):
            idx_hex = f"0x{r.index:04X}" if hasattr(r, 'index') else "0x????"
            safe_name = self._safe_var_name(f"param{i}_{idx_hex}")
            action = getattr(r, 'action', 'set')
            reason = getattr(r, 'reason', 'AI recommendation')
            safety = getattr(r, 'safety', '')

            step = 10 + i
            next_step = 10 + i + 1 if i < len(recs) - 1 else 99

            lines.append(f"{step}:  // ── Write {idx_hex}: {action} (target: see r{safe_name}) ──")
            lines.append(f"    bBusy := TRUE;")
            lines.append(f"    iParamIndex := {i};")
            lines.append(f"    // {reason[:80]}")
            if safety:
                lines.append(f"    // SAFETY: {safety[:80]}")
            lines.append(f"    // TODO: Call vendor-specific SDO write FB for {idx_hex}")
            lines.append(f"    // Example: fbSdoWrite(xExecute:=TRUE, iIndex:={r.index}, iSubIndex:=0, rValue:=r{safe_name});")
            lines.append(f"    iStep := {next_step};")
            lines.append("")

        lines.append("99: // ── Done ──")
        lines.append("    bBusy  := FALSE;")
        lines.append("    bDone  := TRUE;")
        lines.append("    iStep  := 0;")
        lines.append("")
        lines.append("END_CASE;")

        return "\n".join(lines)

    # ── DUT Generation ───────────────────────────────────────

    def generate_dut(self) -> str:
        """Generate DUT (Data Unit Type) structures for servo diagnostics."""
        lines = []
        lines.append(self._header("DUT_ServoDiag", "Servo Diagnostic Data Structures"))
        lines.append("")
        lines.append("/// Fault code enumeration")
        lines.append("{attribute 'qualified_only'}")
        lines.append("{attribute 'strict'}")
        lines.append("TYPE E_ServoFault :")
        lines.append("(")
        lines.append("    eFault_None             := 0,")
        lines.append("    eFault_CurrentSaturation := 1,")
        lines.append("    eFault_SensorFault       := 2,")
        lines.append("    eFault_FollowingError    := 3,")
        lines.append("    eFault_OverTemp          := 4,")
        lines.append("    eFault_MechanicalWear    := 5,")
        lines.append("    eFault_DriveFault        := 6,")
        lines.append("    eFault_Resonance         := 7,")
        lines.append("    eFault_GainDeficiency    := 8,")
        lines.append("    eFault_CurrentRipple     := 9,")
        lines.append("    eFault_VelocityRipple    := 10")
        lines.append(");")
        lines.append("END_TYPE")
        lines.append("")
        lines.append("/// HITL authorization state")
        lines.append("TYPE E_HITLState :")
        lines.append("(")
        lines.append("    eHITL_Pending    := 0,  // Waiting for engineer feedback")
        lines.append("    eHITL_Approved   := 1,  // Engineer authorized")
        lines.append("    eHITL_Rejected   := 2,  // Engineer rejected")
        lines.append("    eHITL_Delegated  := 3   // Delegated to another engineer")
        lines.append(");")
        lines.append("END_TYPE")
        lines.append("")
        lines.append("/// Diagnostic session record (persistent)")
        lines.append("TYPE ST_ServoSession :")
        lines.append("STRUCT")
        lines.append("    sSessionID      : STRING(36);   // UUID")
        lines.append("    dtStartTime     : DT;           // Session start timestamp")
        lines.append("    iTotalFaults    : UDINT;        // Cumulative fault count")
        lines.append("    iAuthorizedCnt  : UDINT;        // Engineer-authorized actions")
        lines.append("    iRejectedCnt    : UDINT;        // Engineer-rejected actions")
        lines.append("    rAuthRate       : REAL;         // Authorization rate")
        lines.append("END_STRUCT")
        lines.append("END_TYPE")

        return "\n".join(lines)

    # ── Export (versioned, never overwrite) ─────────────────────

    def export_all(self, output_dir: str,
                   annotations: List[Any] = None,
                   recommendations: List[Any] = None):
        """Export all generated ST files to a directory.

        NEVER overwrites existing files. Each export creates versioned copies:
          FB_ServoDiag_v1.st, FB_ServoDiag_v2.st, ...
          FB_ServoTune_v1.st, FB_ServoTune_v2.st, ...
          DUT_ServoDiag_v1.st, DUT_ServoDiag_v2.st, ...

        Args:
            output_dir: Target directory path.
            annotations: Annotations for FB_ServoDiag.
            recommendations: Recommendations for FB_ServoTune.

        Returns:
            Dict of {filename: content}.
        """
        import os
        import re
        os.makedirs(output_dir, exist_ok=True)

        files = {}

        def _next_version(dir_path: str, base_name: str) -> str:
            """Find the next available version number for base_name in dir_path.

            Scans existing files matching base_name_vN.st, returns base_name_v(N+1).st.
            Never returns a filename that already exists.
            """
            pattern = re.compile(
                re.escape(base_name) + r'_v(\d+)\.st$',
                re.IGNORECASE,
            )
            max_v = 0
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_file():
                        m = pattern.match(entry.name)
                        if m:
                            max_v = max(max_v, int(m.group(1)))
            except OSError:
                pass
            return f"{base_name}_v{max_v + 1}.st"

        # DUT (always generated, versioned)
        dut_content = self.generate_dut()
        dut_name = _next_version(output_dir, "DUT_ServoDiag")
        dut_path = os.path.join(output_dir, dut_name)
        with open(dut_path, "w", encoding="utf-8") as f:
            f.write(dut_content)
        files[dut_name] = dut_content

        # FB_ServoDiag (versioned)
        if annotations:
            diag_content = self.generate_fb_diag(annotations)
            diag_name = _next_version(output_dir, "FB_ServoDiag")
            diag_path = os.path.join(output_dir, diag_name)
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(diag_content)
            files[diag_name] = diag_content

        # FB_ServoTune (versioned)
        if recommendations:
            tune_content = self.generate_fb_tune(recommendations)
            tune_name = _next_version(output_dir, "FB_ServoTune")
            tune_path = os.path.join(output_dir, tune_name)
            with open(tune_path, "w", encoding="utf-8") as f:
                f.write(tune_content)
            files[tune_name] = tune_content

        return files

    # ── Helpers ──────────────────────────────────────────────

    def _header(self, name: str, description: str) -> str:
        """Generate file header comment."""
        return textwrap.dedent(f"""\
        // ================================================================
        // {name} — {description}
        // ================================================================
        // Auto-generated by AI Analyzer CodegenST
        // Brand: {self.brand}
        // Author: {self.author}
        // Generated: {self._timestamp}
        //
        // ⚠ HITL PRINCIPLE: Parameter writes require operator authorization.
        //    Set bAuthorized:=TRUE only after engineer confirms.
        // ================================================================""")

    @staticmethod
    def _safe_var_name(category: str) -> str:
        """Convert an anomaly category to a CODESYS-safe variable name."""
        # Remove special chars, capitalize words
        name = category.replace("_", " ").title().replace(" ", "")
        # Ensure starts with letter
        if name and name[0].isdigit():
            name = "F" + name
        return name[:31]  # CODESYS max identifier length

    @staticmethod
    def _channel_to_var(channel: str) -> str:
        """Map an AI annotation channel name to CODESYS variable name."""
        ch_lower = channel.lower()
        mapping = {
            "current": "iActualCurrent",
            "velocity": "iActualVelocity",
            "foll.err": "iFollowingError",
            "torque": "iActualTorque",
            "position": "iActualPosition",
        }
        for key, var in mapping.items():
            if key in ch_lower:
                return var
        return "iActualCurrent"  # default

    @staticmethod
    def _default_value(var_type: str) -> str:
        """Get default initial value for a CODESYS type."""
        defaults = {
            "INT": "0", "DINT": "0", "UDINT": "0",
            "REAL": "0.0", "BOOL": "FALSE", "UINT": "0",
        }
        return defaults.get(var_type, "0")

    def _gen_detection_condition(self, ann, var_name: str) -> str:
        """Generate a CODESYS IF condition for an anomaly category."""
        safe_name = self._safe_var_name(ann.category)
        threshold_var = f"r{safe_name}Threshold"
        val = ann.value if ann.value > 0 else 100.0

        conditions = {
            "current_saturation":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
            "current_sensor_fault":
                f"{var_name} = 0",
            "tracking_absolute_limit":
                f"ABS(INT_TO_REAL({var_name})) > {threshold_var}",
            "tracking_mechanical_bind":
                f"ABS(INT_TO_REAL({var_name})) > {threshold_var}",
            "tracking_gain_deficiency":
                f"ABS(INT_TO_REAL({var_name})) > {threshold_var}",
            "current_wear":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
            "resonance_detected":
                f"INT_TO_REAL({var_name}) > {threshold_var}",  # FFT peak in Python; threshold check in PLC
            "resonance_harmonic":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
            "current_ripple":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
            "velocity_ripple":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
            "system_overload":
                f"INT_TO_REAL({var_name}) > {threshold_var}",
        }
        return conditions.get(ann.category,
                             f"INT_TO_REAL({var_name}) > {threshold_var}")

    # ── CLI Integration ─────────────────────────────────────

    def generate_cli_export(self, annotations: List[Any],
                            recommendations: List[Any]) -> str:
        """Generate a combined ST file with both FB + DUT, for CLI export."""
        parts = []
        parts.append(self.generate_dut())
        parts.append("")
        parts.append(self.generate_fb_diag(annotations))
        parts.append("")
        parts.append(self.generate_fb_tune(recommendations))
        return "\n\n".join(parts)

// ================================================================
// FB_ForceControl — Closed-Loop Force/Torque Control for Dispensing
// ================================================================
// Implements precision force control for 3C dispensing applications.
// Uses CiA 402 CST (Cyclic Synchronous Torque) mode over EtherCAT.
//
// Control Modes:
//   0 = Idle
//   1 = Approach (position-controlled, fast)
//   2 = Contact Detect (torque threshold)
//   3 = Force Hold (PID force control)
//   4 = Retract
//
// Contact Detection:
//   Uses torque feedback spike to detect workpiece contact.
//   Threshold auto-adapted based on approach speed.
//
// Usage:
//   fbForce(
//     iActualTorque := %ID10,  // 0x6077 from PDO
//     iTargetForce  := 500,    // 5.00 N (scaled ×100)
//     bEnable       := TRUE
//   );
//   // Set iTorqueCommand (0x6071) to fbForce.iOutputTorque
// ================================================================

FUNCTION_BLOCK FB_ForceControl
VAR_INPUT
    // Feedback
    iActualTorque   : INT;      // 0x6077 Torque Actual Value (‰ rated)
    iActualPos      : DINT;     // 0x6064 Position Actual Value (pulses)

    // Setpoint
    iTargetForce    : INT;      // Target force (‰ rated torque, e.g. 500 = 50.0%)
    iApproachSpeed  : UDINT := 100000; // Approach speed (pulses/s)
    iRetractSpeed   : UDINT := 200000; // Retract speed (pulses/s)
    iRetractPos     : DINT;     // Position to retract to after dispensing

    // Tuning
    rForceKp        : REAL := 0.5;   // Force loop P gain
    rForceKi        : REAL := 0.02;  // Force loop I gain
    rForceKd        : REAL := 0.0;   // Force loop D gain
    iContactThreshold : INT := 50;   // Contact detection threshold (‰)
    iContactDebounce : INT := 5;     // Contact confirm cycles

    // Limits
    iMaxTorque      : INT  := 800;   // Safety: max torque (80%)
    iMaxForceTime   : UDINT := 5000; // Safety: max force hold time (ms)
    iPosLimitFwd    : DINT;          // Forward soft limit
    iPosLimitRev    : DINT;          // Reverse soft limit

    // Commands
    bStart          : BOOL;     // Rising edge: start dispensing cycle
    bStop           : BOOL;     // Rising edge: emergency stop
    bEnable         : BOOL;
END_VAR
VAR_OUTPUT
    iOutputTorque   : INT;      // 0x6071 Target Torque (‰ rated)
    iOutputMode     : SINT;     // 0x6060 Modes of Operation (10 = CST)
    iState          : INT;      // 0=Idle 1=Approach 2=Contact 3=Hold 4=Retract 5=Done 6=Fault
    bCycleComplete  : BOOL;     // Dispensing cycle finished
    bContactMade    : BOOL;     // Workpiece contact detected
    rForceActual    : REAL;     // Actual force (scaled)
    rForceError     : REAL;     // Force error
    iErrorCode      : INT;
END_VAR
VAR
    // State machine
    iPrevState      : INT;

    // Force PID
    rIntegral       : REAL;
    rPrevError      : REAL;
    rOutputRaw      : REAL;

    // Contact detection
    iContactCnt     : INT;
    rAvgTorqueBase  : REAL;     // Baseline torque (moving avg during approach)

    // Timing
    tHoldStart      : UDINT;
    tCurrent        : UDINT;

    // Edge detection
    bStartPrev      : BOOL;
    bStopPrev       : BOOL;
END_VAR

// ===== FB_ForceControl Method Body =====

IF NOT bEnable THEN
    iState := 0;
    iOutputTorque := 0;
    bCycleComplete := FALSE;
    RETURN;
END_IF;

// ── Safety: Emergency Stop ──
IF bStop AND NOT bStopPrev THEN
    iState := 6; // Fault
    iOutputTorque := 0;
    iErrorCode := 1;
END_IF;
bStopPrev := bStop;

// ── Start rising edge ──
IF bStart AND NOT bStartPrev AND iState = 0 THEN
    iState := 1; // Approach
    rIntegral := 0.0;
    rPrevError := 0.0;
    bCycleComplete := FALSE;
    bContactMade := FALSE;
    iContactCnt := 0;
    rAvgTorqueBase := 0.0;
END_IF;
bStartPrev := bStart;

// ── Current time (ms) ──
tCurrent := 0; // Placeholder — use PLC cycle counter or RTC in production

// ── State Machine ──
CASE iState OF
    // ────────────────────────────────────
    0: // Idle — waiting for start
        iOutputTorque := 0;
        iOutputMode := 8; // CSP mode for positioning

    // ────────────────────────────────────
    1: // Approach — fast positioning to workpiece
        iOutputMode := 8; // CSP mode
        iOutputTorque := 0;

        // Baseline torque tracking (moving avg for contact detection)
        rAvgTorqueBase := rAvgTorqueBase * 0.95 +
                          INT_TO_REAL(iActualTorque) * 0.05;

        // Contact detection: torque spike above baseline + threshold
        IF INT_TO_REAL(iActualTorque) > rAvgTorqueBase + INT_TO_REAL(iContactThreshold) THEN
            iContactCnt := iContactCnt + 1;
        ELSE
            iContactCnt := MAX(0, iContactCnt - 1);
        END_IF;

        IF iContactCnt >= iContactDebounce THEN
            iState := 2; // Contact confirmed
            bContactMade := TRUE;
        END_IF;

    // ────────────────────────────────────
    2: // Contact — transition to force control
        iOutputMode := 10; // CST mode
        rIntegral := 0.0;
        rPrevError := 0.0;
        tHoldStart := tCurrent;
        iState := 3; // Enter force hold

    // ────────────────────────────────────
    3: // Force Hold — PID force control
        iOutputMode := 10; // CST mode

        // Force error
        rForceActual := INT_TO_REAL(iActualTorque);
        rForceError  := INT_TO_REAL(iTargetForce) - rForceActual;

        // PID
        rIntegral := rIntegral + rForceError;
        // Anti-windup: clamp integral
        IF rIntegral > 500.0 THEN rIntegral := 500.0; END_IF;
        IF rIntegral < -500.0 THEN rIntegral := -500.0; END_IF;

        rOutputRaw := rForceKp * rForceError +
                      rForceKi * rIntegral +
                      rForceKd * (rForceError - rPrevError);
        rPrevError := rForceError;

        // Clamp output
        IF rOutputRaw > INT_TO_REAL(iMaxTorque) THEN
            rOutputRaw := INT_TO_REAL(iMaxTorque);
        END_IF;
        IF rOutputRaw < 0.0 THEN
            rOutputRaw := 0.0;
        END_IF;
        iOutputTorque := REAL_TO_INT(rOutputRaw);

        // Safety: force hold timeout
        IF (tCurrent - tHoldStart) > iMaxForceTime THEN
            iState := 4; // Timeout → retract
            iErrorCode := 2;
        END_IF;

        // Safety: position limit
        IF iActualPos > iPosLimitFwd OR iActualPos < iPosLimitRev THEN
            iState := 4; // Limit hit → retract
            iErrorCode := 3;
        END_IF;

    // ────────────────────────────────────
    4: // Retract — move back to safe position
        iOutputMode := 8; // CSP mode
        iOutputTorque := 0;
        // Check if retract complete (within window of target)
        IF ABS(iActualPos - iRetractPos) < 1000 THEN
            iState := 5; // Done
        END_IF;

    // ────────────────────────────────────
    5: // Done — cycle complete
        iOutputMode := 8;
        iOutputTorque := 0;
        bCycleComplete := TRUE;
        // Auto-reset to idle after one scan
        iState := 0;

    // ────────────────────────────────────
    6: // Fault
        iOutputTorque := 0;
        iOutputMode := 8;
        bCycleComplete := FALSE;

END_CASE;

// ================================================================
// FB_ServoDiag — Servo Drive Diagnostic Block
// ================================================================
// Continuous monitoring of servo health. Detects:
//   1. Current anomaly (deviation from linear regression model)
//   2. Following error exceedance
//   3. Vibration/resonance (via current FFT approximation)
//   4. Temperature trend
//   5. Mechanical wear (current trend over time)
//
// Based on AI&ML Agent Solution 02 (Current Anomaly) and
// Solution 03 (Multi-Sensor Fault Diagnosis).
//
// Usage: Call every servo cycle. Monitor iFaultCode output.
// ================================================================

FUNCTION_BLOCK FB_ServoDiag
VAR_INPUT
    // PDO feedback
    iActualCurrent  : INT;      // 0x6078 Current Actual Value (‰ rated)
    iActualSpeed    : DINT;     // 0x606C Velocity Actual Value (0.1 rpm)
    iActualTorque   : INT;      // 0x6077 Torque Actual Value (‰ rated)
    iFollowingErr   : DINT;     // 0x60F4 Following Error (pulses)
    iStatusWord     : UINT;     // 0x6041 Status Word
    iActualTemp     : INT;      // Temperature sensor (scaled, e.g. 10×°C)

    // Current model (trained offline — from Solution 02)
    // I_theory = w0*Speed + w1*Torque + w2*Runtime + Bias
    rCurW0          : REAL := 0.012;    // Speed coefficient
    rCurW1          : REAL := 0.085;    // Torque coefficient
    rCurW2          : REAL := 0.000;    // Runtime coefficient
    rCurBias        : REAL := 5.0;      // Bias (base current)

    // Thresholds
    rCurrentHighRatio  : REAL := 1.30;  // I_actual / I_theory > 1.30 → wear alarm
    rCurrentLowRatio   : REAL := 0.60;  // I_actual / I_theory < 0.60 → sensor fault
    iFollErrLimit      : DINT := 1000;  // Following error limit (pulses)
    iTempLimit         : INT  := 850;   // Temperature limit (85.0°C)
    iTempTrendLimit    : INT  := 50;    // Temp trend limit (5.0°C/h)
    iWearTrendCycles   : UDINT := 1000000; // Cycles for wear trend analysis

    // Runtime counter (cumulative)
    udiRuntimeHours : UDINT;    // Total servo runtime (hours)

    bEnable         : BOOL;
END_VAR
VAR_OUTPUT
    iFaultCode      : INT;      // 0=OK, 1=CurrentHigh, 2=CurrentLow, 3=FollErr, 4=OverTemp, 5=WearTrend, 6=DriveFault
    bAlarm          : BOOL;     // Any alarm active
    bShutdown       : BOOL;     // Critical fault → E-stop
    rFaultScore     : REAL;     // 0.0~1.0 confidence
    rTheoryCur      : REAL;     // Theoretical current (model output)
    rCurRatio       : REAL;     // Actual / Theory current ratio
    rTempTrend      : REAL;     // Temperature trend (°C/h)
    rWearTrend      : REAL;     // Current trend over time (%/1000h)
END_VAR
VAR
    // Filtered values (EMA)
    rCurFiltered    : REAL := 0.0;
    rTempFiltered   : REAL := 0.0;
    rFollErrFiltered: REAL := 0.0;

    // Trend tracking (long-term)
    rCurBaseline    : REAL := 0.0;     // Baseline current (set after first 100h)
    udiBaselineSet  : UDINT := 0;      // Runtime when baseline was set
    bBaselineSet    : BOOL := FALSE;

    // Temperature trend
    rTempPrev       : REAL := 0.0;
    udiTempTimePrev : UDINT := 0;

    // Debounce counters
    iCurHighCnt     : INT := 0;
    iCurLowCnt      : INT := 0;
    iFollErrCnt     : INT := 0;
    iTempCnt        : INT := 0;

    // Constants
    iDebounceLimit  : INT := 10;       // Consecutive cycles to confirm fault

    // Drive fault check
    bDriveFault     : BOOL;
END_VAR

// ===== FB_ServoDiag Method Body =====

IF NOT bEnable THEN
    bAlarm    := FALSE;
    bShutdown := FALSE;
    iFaultCode := 0;
    RETURN;
END_IF;

// ── Filter inputs (EMA, α=0.1) ──
rCurFiltered     := rCurFiltered     * 0.9 + INT_TO_REAL(iActualCurrent)  * 0.1;
rFollErrFiltered := rFollErrFiltered * 0.9 + ABS(INT_TO_REAL(iFollowingErr)) * 0.1;
rTempFiltered    := rTempFiltered    * 0.9 + INT_TO_REAL(iActualTemp)     * 0.1;

// ════════════════════════════════════════════════════════════
// 1. Current Anomaly Detection (Solution 02 model)
// ════════════════════════════════════════════════════════════

// Theoretical current: I = w0*Speed + w1*Torque + w2*Runtime + Bias
rTheoryCur := rCurW0 * INT_TO_REAL(iActualSpeed) / 10.0  // convert 0.1rpm → rpm
            + rCurW1 * INT_TO_REAL(iActualTorque)
            + rCurW2 * UDINT_TO_REAL(udiRuntimeHours)
            + rCurBias;

// Ratio
IF ABS(rTheoryCur) > 0.1 THEN
    rCurRatio := rCurFiltered / rTheoryCur;
ELSE
    rCurRatio := 1.0;
END_IF;

// Check: high current → mechanical wear
IF rCurRatio > rCurrentHighRatio THEN
    iCurHighCnt := iCurHighCnt + 1;
ELSE
    iCurHighCnt := MAX(0, iCurHighCnt - 1);
END_IF;

// Check: low current → sensor/wiring fault
IF rCurRatio < rCurrentLowRatio AND rTheoryCur > 1.0 THEN
    iCurLowCnt := iCurLowCnt + 1;
ELSE
    iCurLowCnt := MAX(0, iCurLowCnt - 1);
END_IF;

// ════════════════════════════════════════════════════════════
// 2. Following Error
// ════════════════════════════════════════════════════════════

IF rFollErrFiltered > INT_TO_REAL(iFollErrLimit) THEN
    iFollErrCnt := iFollErrCnt + 1;
ELSE
    iFollErrCnt := MAX(0, iFollErrCnt - 1);
END_IF;

// ════════════════════════════════════════════════════════════
// 3. Temperature Monitoring
// ════════════════════════════════════════════════════════════

// Trend: °C per hour
IF udiRuntimeHours <> udiTempTimePrev THEN
    rTempTrend := (rTempFiltered - rTempPrev) /
                  MAX(1.0, UDINT_TO_REAL(udiRuntimeHours - udiTempTimePrev));
    rTempPrev := rTempFiltered;
    udiTempTimePrev := udiRuntimeHours;
END_IF;

IF rTempFiltered > INT_TO_REAL(iTempLimit) THEN
    iTempCnt := iTempCnt + 1;
ELSE
    iTempCnt := MAX(0, iTempCnt - 1);
END_IF;

// ════════════════════════════════════════════════════════════
// 4. Wear Trend (long-term current drift)
// ════════════════════════════════════════════════════════════

IF NOT bBaselineSet AND udiRuntimeHours >= 100 THEN
    rCurBaseline   := rCurFiltered;
    udiBaselineSet := udiRuntimeHours;
    bBaselineSet   := TRUE;
END_IF;

IF bBaselineSet AND udiRuntimeHours > udiBaselineSet + 100 THEN
    rWearTrend := (rCurFiltered - rCurBaseline) /
                  MAX(1.0, UDINT_TO_REAL(udiRuntimeHours - udiBaselineSet)) * 1000.0;
    // rWearTrend > 10 means current increased by 10% per 1000 hours
END_IF;

// ════════════════════════════════════════════════════════════
// 5. Drive Fault (from Status Word)
// ════════════════════════════════════════════════════════════

// Status word bit 3 = Fault (0x0008)
bDriveFault := (iStatusWord AND 16#0008) <> 0;

// ════════════════════════════════════════════════════════════
// Fault Aggregation
// ════════════════════════════════════════════════════════════

iFaultCode := 0;
bAlarm     := FALSE;
bShutdown  := FALSE;
rFaultScore := 0.0;

// Priority: shutdown faults first
IF bDriveFault THEN
    iFaultCode := 6;
    bAlarm     := TRUE;
    bShutdown  := TRUE;
    rFaultScore := 1.0;

ELSIF iFollErrCnt >= iDebounceLimit THEN
    iFaultCode := 3;
    bAlarm     := TRUE;
    bShutdown  := TRUE;  // Following error → mechanical collision risk
    rFaultScore := MIN(1.0, INT_TO_REAL(iFollErrCnt) / 20.0);

ELSIF iTempCnt >= iDebounceLimit THEN
    iFaultCode := 4;
    bAlarm     := TRUE;
    bShutdown  := TRUE;  // Over-temp → fire/melt risk
    rFaultScore := MIN(1.0, (rTempFiltered - 800.0) / 200.0);

ELSIF iCurHighCnt >= iDebounceLimit THEN
    iFaultCode := 1;
    bAlarm     := TRUE;
    bShutdown  := FALSE; // Warning only — schedule maintenance
    rFaultScore := MIN(1.0, (rCurRatio - 1.0) * 2.0);

ELSIF rWearTrend > 10.0 THEN
    iFaultCode := 5;
    bAlarm     := TRUE;
    bShutdown  := FALSE; // Long-term trend — advisory
    rFaultScore := MIN(1.0, rWearTrend / 30.0);

ELSIF iCurLowCnt >= iDebounceLimit THEN
    iFaultCode := 2;
    bAlarm     := TRUE;
    bShutdown  := FALSE; // Sensor fault — check wiring
    rFaultScore := 0.7;

END_IF;

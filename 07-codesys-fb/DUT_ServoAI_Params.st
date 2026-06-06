// ================================================================
// DUT_ServoAI_Params — AI Servo Parameter Structure
// ================================================================
// Central parameter struct for all servo AI function blocks.
// Parameters are trained offline (PPO/LightGBM/linear regression)
// and written to this struct via Modbus TCP or CODESYS recipe.
//
// To update: edge IPC trains new model → writes to PLC holding
// registers → CODESYS copies to this struct → FB uses new params.
// ================================================================

TYPE DUT_ServoAI_Params :
STRUCT
    // ============================================================
    // FB_ForceControl — Force control parameters
    // ============================================================
    rForce_Kp         : REAL := 0.5;
    rForce_Ki         : REAL := 0.02;
    rForce_Kd         : REAL := 0.0;
    iForce_ContactThr : INT  := 50;    // Contact threshold (‰)
    iForce_MaxTorque  : INT  := 800;   // Safety max (‰)
    iForce_MaxTime    : UDINT := 5000; // Max hold time (ms)

    // ============================================================
    // FB_GainScheduler — Gain scheduling tables (4 zones)
    // ============================================================
    rGain_Z1_KpVel    : REAL := 40.0;
    rGain_Z1_KiVel    : REAL := 20.0;
    rGain_Z1_KpPos    : REAL := 30.0;
    rGain_Z1_Kff      : REAL := 0.0;

    rGain_Z2_KpVel    : REAL := 60.0;
    rGain_Z2_KiVel    : REAL := 30.0;
    rGain_Z2_KpPos    : REAL := 45.0;
    rGain_Z2_Kff      : REAL := 30.0;

    rGain_Z3_KpVel    : REAL := 80.0;
    rGain_Z3_KiVel    : REAL := 40.0;
    rGain_Z3_KpPos    : REAL := 60.0;
    rGain_Z3_Kff      : REAL := 50.0;

    rGain_Z4_KpVel    : REAL := 35.0;
    rGain_Z4_KiVel    : REAL := 15.0;
    rGain_Z4_KpPos    : REAL := 25.0;
    rGain_Z4_Kff      : REAL := 60.0;

    rGain_SmoothFactor: REAL := 0.1;   // EMA smoothing

    // ============================================================
    // FB_ServoDiag — Diagnostic thresholds
    // ============================================================
    rDiag_CurW0       : REAL := 0.012;
    rDiag_CurW1       : REAL := 0.085;
    rDiag_CurBias     : REAL := 5.0;
    rDiag_CurRatioHi  : REAL := 1.30;
    rDiag_CurRatioLo  : REAL := 0.60;
    iDiag_FollErrLim  : DINT := 1000;
    iDiag_TempLim     : INT  := 850;
    iDiag_TempTrendLim: INT  := 50;

    // ============================================================
    // FB_ServoScope — Scope configuration
    // ============================================================
    iScope_TrigChannel : INT  := 1;
    rScope_TrigLevel   : REAL := 0.0;
    iScope_PreSamples  : INT  := 200;
    iScope_PostSamples : INT  := 800;

    // ============================================================
    // Meta
    // ============================================================
    sModelVersion     : STRING := 'v1.0.0';
    sModelDate        : STRING := '2026-06-04';
END_STRUCT
END_TYPE

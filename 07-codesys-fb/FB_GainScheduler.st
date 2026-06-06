// ================================================================
// FB_GainScheduler — Adaptive Servo Gain Scheduling
// ================================================================
// Automatically adjusts servo loop gains based on operating
// conditions (load, speed, position). Uses linear interpolation
// between pre-defined operating points.
//
// Operating Points (pre-configured — tuned offline with PPO/RL):
//   Low Load  (< 30% rated):  Conservative gains
//   Mid Load  (30-70%):       Standard gains
//   High Load (> 70% rated):  Aggressive gains
//   High Speed (> 80% max):   Reduced gains (stability)
//
// Outputs (to Delta A3 via SDO or PDO):
//   Velocity Loop Gain     (P1-04,  CoE 0x2104)
//   Velocity Loop Integral (P1-05,  CoE 0x2105)
//   Position Loop Gain     (P1-06,  CoE 0x2106)
//   Speed Feedforward      (P1-07,  CoE 0x2107)
//   Torque Filter          (P1-08,  CoE 0x2108)
//
// Usage: Call every servo cycle. Gains auto-adjust based on
// current load and speed feedback.
// ================================================================

FUNCTION_BLOCK FB_GainScheduler
VAR_INPUT
    // Feedback (from PDO)
    iActualCurrent  : INT;      // 0x6078 Current Actual Value (‰ rated)
    iActualSpeed    : DINT;     // 0x606C Velocity Actual Value (0.1 rpm)
    iActualPos      : DINT;     // 0x6064 Position Actual Value

    // Motor specs (for normalization)
    iRatedCurrent   : INT  := 1000;   // Rated current (‰, e.g. 1000 = 100%)
    iMaxSpeed       : DINT := 300000; // Max speed (0.1 rpm, e.g. 300000 = 3000 rpm)

    // ── Pre-configured operating point tables ──
    // Entries: [Load%, Speed%] → {Kp_vel, Ki_vel, Kp_pos, Kff, TorqFilt}

    // Zone 1: Low Load, Low Speed (< 30%, < 50%)
    rZ1_KpVel       : REAL := 40.0;
    rZ1_KiVel       : REAL := 20.0;
    rZ1_KpPos       : REAL := 30.0;
    rZ1_Kff         : REAL := 0.0;
    rZ1_TorqFilt    : REAL := 1.0;

    // Zone 2: Mid Load, Mid Speed (30-70%, 50-80%)
    rZ2_KpVel       : REAL := 60.0;
    rZ2_KiVel       : REAL := 30.0;
    rZ2_KpPos       : REAL := 45.0;
    rZ2_Kff         : REAL := 30.0;
    rZ2_TorqFilt    : REAL := 0.5;

    // Zone 3: High Load, Low-Mid Speed (> 70%, < 80%)
    rZ3_KpVel       : REAL := 80.0;
    rZ3_KiVel       : REAL := 40.0;
    rZ3_KpPos       : REAL := 60.0;
    rZ3_Kff         : REAL := 50.0;
    rZ3_TorqFilt    : REAL := 0.3;

    // Zone 4: High Speed, Any Load (> 80%)
    rZ4_KpVel       : REAL := 35.0;
    rZ4_KiVel       : REAL := 15.0;
    rZ4_KpPos       : REAL := 25.0;
    rZ4_Kff         : REAL := 60.0;
    rZ4_TorqFilt    : REAL := 0.2;

    // Interpolation config
    rSmoothFactor   : REAL := 0.1;  // 0.0=instant, 0.5=slow transition (EMA)
    iUpdateRate     : INT  := 10;   // Update every N cycles

    bEnable         : BOOL;
END_VAR
VAR_OUTPUT
    // Computed gains (write to Delta A3 parameters)
    rOutKpVel       : REAL;     // → P1-04 (0x2104)
    rOutKiVel       : REAL;     // → P1-05 (0x2105)
    rOutKpPos       : REAL;     // → P1-06 (0x2106)
    rOutKff         : REAL;     // → P1-07 (0x2107)
    rOutTorqFilt    : REAL;     // → P1-08 (0x2108)

    // Status
    rLoadPct        : REAL;     // Current load percentage
    rSpeedPct       : REAL;     // Current speed percentage
    iActiveZone     : INT;      // Active operating zone (1-4)
    bInTransition   : BOOL;     // TRUE during gain transition
END_VAR
VAR
    iCycleCnt       : INT;
    rLoadPrev       : REAL;
    rSpeedPrev      : REAL;
    // EMA-smoothed outputs
    rKpVel_ema      : REAL := 40.0;
    rKiVel_ema      : REAL := 20.0;
    rKpPos_ema      : REAL := 30.0;
    rKff_ema        : REAL := 0.0;
    rTfilt_ema      : REAL := 1.0;
END_VAR

// ===== FB_GainScheduler Method Body =====

IF NOT bEnable THEN
    RETURN;
END_IF;

// ── Cycle counter: don't update every scan ──
iCycleCnt := iCycleCnt + 1;
IF iCycleCnt < iUpdateRate THEN
    RETURN;
END_IF;
iCycleCnt := 0;

// ── Normalize load and speed to 0-100% ──
rLoadPct  := ABS(INT_TO_REAL(iActualCurrent)) / INT_TO_REAL(iRatedCurrent) * 100.0;
rSpeedPct := ABS(INT_TO_REAL(iActualSpeed))  / INT_TO_REAL(iMaxSpeed)    * 100.0;

// Clamp
IF rLoadPct  > 100.0 THEN rLoadPct  := 100.0; END_IF;
IF rSpeedPct > 100.0 THEN rSpeedPct := 100.0; END_IF;

// ── Determine operating zone ──
IF rSpeedPct > 80.0 THEN
    // Zone 4: High speed — stability priority
    iActiveZone := 4;
    rOutKpVel    := rZ4_KpVel;
    rOutKiVel    := rZ4_KiVel;
    rOutKpPos    := rZ4_KpPos;
    rOutKff      := rZ4_Kff;
    rOutTorqFilt := rZ4_TorqFilt;

ELSIF rLoadPct > 70.0 THEN
    // Zone 3: High load
    iActiveZone := 3;
    rOutKpVel    := rZ3_KpVel;
    rOutKiVel    := rZ3_KiVel;
    rOutKpPos    := rZ3_KpPos;
    rOutKff      := rZ3_Kff;
    rOutTorqFilt := rZ3_TorqFilt;

ELSIF rLoadPct > 30.0 THEN
    // Zone 2: Mid load
    iActiveZone := 2;
    rOutKpVel    := rZ2_KpVel;
    rOutKiVel    := rZ2_KiVel;
    rOutKpPos    := rZ2_KpPos;
    rOutKff      := rZ2_Kff;
    rOutTorqFilt := rZ2_TorqFilt;

ELSE
    // Zone 1: Low load
    iActiveZone := 1;
    rOutKpVel    := rZ1_KpVel;
    rOutKiVel    := rZ1_KiVel;
    rOutKpPos    := rZ1_KpPos;
    rOutKff      := rZ1_Kff;
    rOutTorqFilt := rZ1_TorqFilt;

END_IF;

// ── EMA smoothing — prevents gain jumps ──
rKpVel_ema  := rKpVel_ema  * (1.0 - rSmoothFactor) + rOutKpVel    * rSmoothFactor;
rKiVel_ema  := rKiVel_ema  * (1.0 - rSmoothFactor) + rOutKiVel    * rSmoothFactor;
rKpPos_ema  := rKpPos_ema  * (1.0 - rSmoothFactor) + rOutKpPos    * rSmoothFactor;
rKff_ema    := rKff_ema    * (1.0 - rSmoothFactor) + rOutKff      * rSmoothFactor;
rTfilt_ema  := rTfilt_ema  * (1.0 - rSmoothFactor) + rOutTorqFilt * rSmoothFactor;

rOutKpVel    := rKpVel_ema;
rOutKiVel    := rKiVel_ema;
rOutKpPos    := rKpPos_ema;
rOutKff      := rKff_ema;
rOutTorqFilt := rTfilt_ema;

bInTransition := ABS(rLoadPct - rLoadPrev) > 5.0 OR ABS(rSpeedPct - rSpeedPrev) > 5.0;
rLoadPrev  := rLoadPct;
rSpeedPrev := rSpeedPct;

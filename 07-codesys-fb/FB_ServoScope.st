// ================================================================
// FB_ServoScope — EtherCAT PDO Data Capture for Oscilloscope
// ================================================================
// Captures Cyclic PDO data from EtherCAT slaves into a PLC ring
// buffer array. Designed to feed an external oscilloscope (HMI,
// SCADA, or edge IPC via Modbus TCP).
//
// Captured Signals (from CiA 402 + Delta A3 CoE objects):
//   CH1: Position Actual Value   (0x6064)    — INT32
//   CH2: Velocity Actual Value   (0x606C)    — INT32
//   CH3: Current Actual Value    (0x6078)    — INT16
//   CH4: Torque Actual Value     (0x6077)    — INT16
//   CH5: Following Error         (0x60F4)    — INT32
//   CH6: Status Word             (0x6041)    — UINT16
//   CH7: Digital Inputs          (0x60FD)    — UINT32
//   CH8: Modes of Operation      (0x6061)    — INT8
//
// Buffer: 1000 samples × 8 channels, ring buffer (FIFO)
// Trigger: level trigger on any channel, rising/falling edge
//
// Usage:
//   fbScope(
//     iPosActual := %ID0,   // from PDO image
//     iVelActual := %ID4,
//     iCurActual  := %ID8,
//     ...
//     bEnable := TRUE
//   );
//   // Read captured data from fbScope.arBuffer
// ================================================================

FUNCTION_BLOCK FB_ServoScope
VAR_INPUT
    // PDO Inputs (mapped from EtherCAT I/O image)
    iPosActual      : DINT;     // 0x6064 Position Actual Value
    iVelActual      : DINT;     // 0x606C Velocity Actual Value
    iCurActual      : INT;      // 0x6078 Current Actual Value
    iTrqActual      : INT;      // 0x6077 Torque Actual Value
    iFollErr        : DINT;     // 0x60F4 Following Error Actual Value
    iStatusWord     : UINT;     // 0x6041 Status Word
    iDigInputs      : UDINT;    // 0x60FD Digital Inputs
    iOpMode         : SINT;     // 0x6061 Modes of Operation Display

    bEnable         : BOOL;     // Enable capture

    // Trigger config
    bTrigEnable     : BOOL;     // Enable trigger mode
    iTrigChannel    : INT  := 1; // Trigger source channel (1-8)
    rTrigLevel      : REAL := 0.0; // Trigger level
    bTrigEdge       : BOOL := TRUE; // TRUE=Rising, FALSE=Falling
    iTrigPreSamples : INT  := 200;  // Pre-trigger samples to retain
    iTrigPostSamples: INT  := 800;  // Post-trigger samples
END_VAR
VAR_OUTPUT
    // Ring buffer (exposed for HMI/SCADA readout)
    arBuffer        : ARRAY[0..7, 0..999] OF REAL;  // 8ch × 1000 samples
    iBufHead        : INT;      // Current write position (0..999)
    iBufCount       : UDINT;    // Total samples captured
    iBufSamples     : INT;      // Valid samples in buffer (0..1000)
    bBufFull        : BOOL;     // Buffer full (1000 samples)
    bTriggered      : BOOL;     // Trigger fired
    iTrigPosition   : INT;      // Buffer index of trigger point (-1 = none)

    // Status
    bActive         : BOOL;
    iErrorCode      : INT;
END_VAR
VAR
    bInit           : BOOL := TRUE;
    bArming         : BOOL;
    iPreCounter     : INT;
    iPostCounter    : INT;
    rPrevTrigVal    : REAL;
    arrChValues     : ARRAY[0..7] OF REAL;
    bTrigEdgePrev   : BOOL;
END_VAR

// ===== FB_ServoScope Method Body =====

IF NOT bEnable THEN
    bActive := FALSE;
    RETURN;
END_IF;

// ── Initialize buffer on first cycle ──
IF bInit THEN
    FOR i: INT := 0 TO 7 DO
        FOR j: INT := 0 TO 999 DO
            arBuffer[i, j] := 0.0;
        END_FOR;
    END_FOR;
    iBufHead    := 0;
    iBufCount   := 0;
    iBufSamples := 0;
    bBufFull    := FALSE;
    bTriggered  := FALSE;
    iTrigPosition := -1;
    bInit       := FALSE;
    bArming     := bTrigEnable;
    iPreCounter := iTrigPreSamples;
    iPostCounter:= 0;
END_IF;

bActive := TRUE;

// ── Assemble channel values ──
arrChValues[0] := INT_TO_REAL(iPosActual);
arrChValues[1] := INT_TO_REAL(iVelActual);
arrChValues[2] := INT_TO_REAL(iCurActual);
arrChValues[3] := INT_TO_REAL(iTrqActual);
arrChValues[4] := INT_TO_REAL(iFollErr);
arrChValues[5] := UINT_TO_REAL(iStatusWord);
arrChValues[6] := UDINT_TO_REAL(iDigInputs);
arrChValues[7] := SINT_TO_REAL(iOpMode);

// ── Trigger logic ──
IF bTrigEnable THEN
    IF iTrigChannel >= 1 AND iTrigChannel <= 8 THEN
        IF bArming THEN
            // Pre-trigger: fill buffer without marking trigger
            IF iPreCounter > 0 THEN
                iPreCounter := iPreCounter - 1;
            ELSE
                bArming := FALSE;
            END_IF;
        ELSE
            // Check trigger condition
            IF iTrigChannel >= 1 AND iTrigChannel <= 8 THEN
                rPrevTrigVal := arrChValues[iTrigChannel - 1];
                IF bTrigEdge THEN
                    // Rising edge
                    IF rPrevTrigVal < rTrigLevel AND
                       arrChValues[iTrigChannel - 1] >= rTrigLevel THEN
                        bTriggered := TRUE;
                        iTrigPosition := iBufHead;
                        iPostCounter := iTrigPostSamples;
                    END_IF;
                ELSE
                    // Falling edge
                    IF rPrevTrigVal > rTrigLevel AND
                       arrChValues[iTrigChannel - 1] <= rTrigLevel THEN
                        bTriggered := TRUE;
                        iTrigPosition := iBufHead;
                        iPostCounter := iTrigPostSamples;
                    END_IF;
                END_IF;
            END_IF;

            // Post-trigger countdown
            IF bTriggered AND iPostCounter > 0 THEN
                iPostCounter := iPostCounter - 1;
                IF iPostCounter = 0 THEN
                    bTrigEnable := FALSE; // Single-shot: disarm after capture
                END_IF;
            END_IF;
        END_IF;
    END_IF;
END_IF;

// ── Write to ring buffer ──
FOR i: INT := 0 TO 7 DO
    arBuffer[i, iBufHead] := arrChValues[i];
END_FOR;

iBufHead  := (iBufHead + 1) MOD 1000;
iBufCount := iBufCount + 1;

IF iBufSamples < 1000 THEN
    iBufSamples := iBufSamples + 1;
END_IF;
IF iBufHead = 0 THEN
    bBufFull := TRUE;
END_IF;

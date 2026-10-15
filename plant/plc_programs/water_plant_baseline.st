(* ==================================================================
   PROGRAM WaterPlant  (baseline, approved version)
   SYNTHETIC DEMO PROGRAM - not for use on a real plant.
   Small water treatment plant: raw tank, intake pump, chlorine dosing,
   treated tank, distribution pump.
   ================================================================== *)
PROGRAM WaterPlant

VAR_INPUT
    LT_101 : REAL;          (* Raw water tank level, % *)
    FT_101 : REAL;          (* Intake flow, m3/h *)
    AT_201 : REAL;          (* Chlorine residual, ppm *)
    LT_301 : REAL;          (* Treated water tank level, % *)
    PT_301 : REAL;          (* Distribution discharge pressure, bar *)
    P_201_HMI_CMD : BOOL;   (* SCADA/HMI command bit, chlorine dosing pump *)
    P_301_HMI_CMD : BOOL;   (* SCADA/HMI command bit, distribution pump *)
END_VAR

VAR_OUTPUT
    P_101_RUN : BOOL;       (* Intake pump run *)
    P_201_RUN : BOOL;       (* Chlorine dosing pump run *)
    P_301_RUN : BOOL;       (* Distribution pump run *)
END_VAR

VAR
    P_101_AUTO : BOOL := TRUE;
    P_201_AUTO : BOOL := FALSE;
    P_301_AUTO : BOOL := TRUE;
    P_101_CMD : BOOL;
    P_201_CMD : BOOL;
    P_301_CMD : BOOL;
    IL_01 : BOOL;
    IL_02 : BOOL;
    IL_03 : BOOL;
    IL_04 : BOOL;
    IL_05 : BOOL;
    IL_06 : BOOL;
    AL_01 : BOOL;
    AL_02 : BOOL;
    AL_03 : BOOL;
END_VAR

(* ---------- Intake pump P-101: automatic control (hysteresis) ---------- *)
IF LT_101 >= 50.0 AND LT_301 < 85.0 THEN
    P_101_AUTO := TRUE;
END_IF;
IF LT_101 < 30.0 OR LT_301 > 90.0 THEN
    P_101_AUTO := FALSE;
END_IF;
P_101_CMD := P_101_AUTO;

(* IL-01: trip intake pump on raw tank low-low (dry-run protection) *)
IL_01 := LT_101 < 15.0;
(* IL-02: trip intake pump on treated tank high-high (overflow protection) *)
IL_02 := LT_301 > 95.0;
P_101_RUN := P_101_CMD AND NOT (IL_01 OR IL_02);

(* ---------- Chlorine dosing pump P-201: automatic control ---------- *)
IF P_101_RUN AND AT_201 < 1.2 THEN
    P_201_AUTO := TRUE;
END_IF;
IF NOT P_101_RUN OR AT_201 > 1.8 THEN
    P_201_AUTO := FALSE;
END_IF;
P_201_CMD := P_201_AUTO OR P_201_HMI_CMD;

(* IL-03: trip chlorine dosing when there is no intake flow *)
IL_03 := NOT P_101_RUN;
(* IL-04: trip chlorine dosing on chlorine overdose *)
IL_04 := AT_201 > 4.0;
P_201_RUN := P_201_CMD AND NOT (IL_03 OR IL_04);

(* ---------- Distribution pump P-301: automatic control ---------- *)
IF LT_301 >= 30.0 THEN
    P_301_AUTO := TRUE;
END_IF;
IF LT_301 < 20.0 THEN
    P_301_AUTO := FALSE;
END_IF;
P_301_CMD := P_301_AUTO OR P_301_HMI_CMD;

(* IL-05: trip distribution pump on treated tank low-low *)
IL_05 := LT_301 < 15.0;
(* IL-06: trip distribution pump on overpressure *)
IL_06 := PT_301 > 6.0;
P_301_RUN := P_301_CMD AND NOT (IL_05 OR IL_06);

(* ---------- Alarms ---------- *)
AL_01 := LT_101 < 25.0;
AL_02 := AT_201 < 0.2;
AL_03 := PT_301 > 5.0;

END_PROGRAM

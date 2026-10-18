# PlantMind - Functional Requirements

Priority: M = Must, S = Should, C = Could.
Owner: A = Plant & Knowledge workstream, B = Agent & Experience workstream, S = shared.

## 0. Reference Plant Definition (single source of truth for both workstreams)

A small water treatment plant. All IDs below are fixed and must be used
identically in the PLC programs, simulator, knowledge map, and UI.

Tags:
| Tag    | Meaning                         | Unit |
|--------|---------------------------------|------|
| LT-101 | Raw water tank level            | %    |
| FT-101 | Intake flow                     | m3/h |
| P-101  | Intake pump (run status)        | bool |
| AT-201 | Chlorine residual               | ppm  |
| P-201  | Chlorine dosing pump            | bool |
| LT-301 | Treated water tank level        | %    |
| PT-301 | Distribution discharge pressure | bar  |
| P-301  | Distribution pump               | bool |

Interlocks:
| ID    | Rule                                   | Purpose            |
|-------|----------------------------------------|--------------------|
| IL-01 | P-101 trips if LT-101 < 15             | dry-run protection |
| IL-02 | P-101 trips if LT-301 > 95             | overflow           |
| IL-03 | P-201 trips if P-101 is not running    | no dosing w/o flow |
| IL-04 | P-201 trips if AT-201 > 4.0            | chlorine overdose  |
| IL-05 | P-301 trips if LT-301 < 15             | dry-run protection |
| IL-06 | P-301 trips if PT-301 > 6.0            | overpressure       |

Alarms: AL-01 LT-101 < 25, AL-02 AT-201 < 0.2, AL-03 PT-301 > 5.0.

## 1. Plant Simulator [A]
- FR-SIM-01 (M) Simulate the plant above with plausible dynamics (levels move
  with pump state, chlorine follows dosing, pressure follows distribution).
- FR-SIM-02 (M) Emit telemetry every TELEMETRY_INTERVAL_S seconds in the
  schema defined in core/contracts.py.
- FR-SIM-03 (M) The simulator mirrors the logic of the .st baseline file.
  The .st file is analyzed statically and is not executed. Every interlock
  keeps the same ID in both places.
- FR-SIM-04 (M) Scenario injection (synthetic, defensive testing only):
  normal, sensor_fault (frozen LT-101), spoofed_reading (reported value
  differs from physical reality), logic_tamper (IL-04 bypassed in the
  tampered program), abnormal_command (unexpected pump command).
- FR-SIM-05 (S) Scenarios can be started and stopped at runtime by API.
- FR-SIM-06 (M) Provide water_plant_baseline.st and water_plant_tampered.st
  (IEC 61131-3 Structured Text) matching section 0.

## 2. Knowledge Map [A]
- FR-KM-01 (M) Parse a defined subset of Structured Text (variables, IF/THEN/
  ELSE, boolean and comparison expressions, assignments, comments).
- FR-KM-02 (M) Build knowledge_map.json: equipment, tags, interlocks with
  machine-evaluable conditions and actions, and expected relations.
- FR-KM-03 (S) LLM enrichment adds a plain-language description per
  interlock. Output is validated against the parser; any tag not found in the
  parsed program is rejected (no invented tags).
- FR-KM-04 (M) The map is the contract between workstreams (see contracts).

## 3. Plant Documentation (Function 1) [A]
- FR-DOC-01 (M) Generate a plain-language plant document from the map.
- FR-DOC-02 (M) Generate an interlock table (ID, condition, action, purpose).
- FR-DOC-03 (S) Grounded Q&A, e.g. "why did P-201 stop?"; answers cite
  interlock IDs from the map.
- FR-DOC-04 (S) Export Markdown and HTML.

## 4. Change Guard (Function 2) [A]
- FR-GRD-01 (M) Accept a baseline and a candidate .st program.
- FR-GRD-02 (M) Interlock-level structural diff: added, removed, or modified
  conditions and actions.
- FR-GRD-03 (M) Deterministic rule check, independent of the LLM: any removed
  or weakened interlock is flagged. The LLM never lowers a severity set by
  the rules.
- FR-GRD-04 (M) LLM safety-impact assessment per change: severity
  (info/low/medium/high/critical), affected equipment, hazardous scenario in
  plain language, recommended review step.
- FR-GRD-05 (M) Map each finding to a technique in data/mitre_ics_subset.json
  (IDs verified against the official ATT&CK for ICS matrix).
- FR-GRD-06 (M) Human decision recorded: approve, reject, or needs review.

## 5. Smart Detection (Function 3) [B]
- FR-DET-01 (M) Ingest telemetry stream and keep a rolling window.
- FR-DET-02 (M) Expected-behavior engine: evaluate each interlock condition
  from the knowledge map against live state and report violations
  (condition true but expected action not observed).
- FR-DET-03 (M) Physical consistency checks (for example tank level trend
  versus pump state and flow) to expose spoofed or frozen readings.
- FR-DET-04 (M) Fast triage with the small model (Nano): classify and
  decide whether to escalate. Deterministic evidence is gathered first.
- FR-DET-05 (M) Deep analysis with the large model (Super/Ultra) on escalated
  events: ranked hypotheses (sensor fault, process upset, spoofing, logic
  tampering, command abuse), evidence IDs, confidence, first things to check.
- FR-DET-06 (M) LLM output must reference evidence IDs produced by the
  deterministic layer; unreferenced claims are discarded.
- FR-DET-07 (S) De-duplicate and rate-limit alerts to control token usage.

## 6. Operator Assistant and Reports (Function 4) [B]
- FR-OPS-01 (M) Explain any alert in plain language for a control-room
  operator.
- FR-OPS-02 (M) Recommended actions with human approval; approve, reject, or
  defer is logged. The system never actuates equipment.
- FR-OPS-03 (S) Chat about the plant, grounded in the knowledge map and live
  state.
- FR-OPS-04 (M) Incident report generator: timeline, evidence, hypotheses,
  actions taken, ATT&CK mapping.
- FR-OPS-05 (M) Export report as Markdown and HTML.
- FR-OPS-06 (M) Tavily runtime call: search recent ICS advisories relevant to
  the event type and attach references to the report.
- FR-OPS-07 (C) English/Arabic output toggle.

## 7. API and Dashboard [B, with A routers for sections 3 and 4]
- FR-WEB-01 (M) Live trends and plant status view.
- FR-WEB-02 (M) Alerts feed with explanation and approval buttons.
- FR-WEB-03 (M) Change Guard page: upload or select baseline and candidate,
  view diff and assessment.
- FR-WEB-04 (M) Documentation page (generated doc and interlock table).
- FR-WEB-05 (M) Reports page.
- FR-WEB-06 (M) Demo control panel to start and stop scenarios.
- FR-API-01 (M) REST endpoints per module; OpenAPI docs enabled.

## 8. LLM Platform [S]
- FR-LLM-01 (M) Single client over Nebius Token Factory with model tiers
  (nano, super, ultra) configured by environment variables.
- FR-LLM-02 (M) Structured JSON output with schema validation and retry.
- FR-LLM-03 (M) MOCK_LLM mode returning canned responses so both workstreams can
  develop and test without credits.
- FR-LLM-04 (S) Response caching and a per-run token budget.

## 9. Submission Artifacts [S]
- FR-SUB-01 (M) README: setup, run, where Nemotron is used, where Token
  Factory accelerates the workflow.
- FR-SUB-02 (M) MIT license visible on the repository page.
- FR-SUB-03 (M) Demo script for a video under 3 minutes.
- FR-SUB-04 (M) Feedback section text for the Nebius/NVIDIA feedback prize.

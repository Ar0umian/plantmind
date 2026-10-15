# PlantMind - Work Split Between Two Workstreams

Two separate Claude accounts (A and B) work like two independent
contributors on one repository. Aram is the integrator and the only person who
moves files between them. Repository location: ~/plantmind on Aram's Mac.

## 1. Working Rules
1. Each workstream writes ONLY inside its own folders (section 2).
2. core/, fixtures/, data/, docs/ are shared and frozen after Phase 0.
   A change request goes through Aram to both workstreams and bumps
   CONTRACT_VERSION in core/contracts.py.
3. Code is delivered as copy-paste Terminal commands (cat heredocs), split
   across several messages, working directory ~/plantmind.
4. B develops against fixtures and MOCK_LLM until A delivers real outputs.
   A develops against MOCK_LLM until credits are available.
5. Every delivery ends with the tests that prove it works.

## 2. Ownership

| Area | Owner |
|------|-------|
| plant/ (simulator, scenarios, .st programs) | A |
| knowledge/ (parser, map, docs, change guard, Q&A) | A |
| api/routers/knowledge.py, api/routers/guard.py | A |
| agent/ (detection, triage, reasoner, assistant, reports, Tavily) | B |
| web/ (dashboard) | B |
| api/main.py, api/routers/{telemetry,alerts,assistant,reports,scenarios}.py | B |
| core/, fixtures/, data/, docs/, scripts/ | Shared |

## 3. Interfaces Between Workstreams (defined in core/contracts.py)

| Contract | Produced by | Consumed by |
|----------|-------------|-------------|
| TelemetryFrame | A (simulator) | B (detection) |
| KnowledgeMap and Interlock | A (map builder) | B (detection, assistant), A (docs) |
| ChangeReport | A (change guard) | B (UI, reports) |
| PlantRunner interface: start_scenario, stop_scenario, get_state | A | B (scenarios router) |
| Alert, Hypothesis, IncidentReport | B | B (UI) |
| LLMClient.generate_json(tier, system, user, schema) | Shared | A and B |

## 4. Phases and Dates (Saudi time)

Deadline: 30 Oct 2026, 10:00 PT = 20:00 Saudi time. Target: submit by 29 Oct.

### Phase 0 - Shared Foundation (15-16 Oct)
- A (this chat) delivers core/contracts.py, core/config.py, core/llm_client.py
  with MOCK mode, and the sample fixtures.
- Aram runs scripts/make_briefing.sh B and uploads out/briefing_B.txt to
  Account B as the first message. B replies with its task summary.
- Exit check: both accounts can import core and run the mock LLM.

### Phase 1 - Parallel Work (17-23 Oct)

Account A tasks, in order:
- A1 Plant simulator and water_plant_baseline.st (FR-SIM)
- A2 ST parser and knowledge_map.json builder (FR-KM)   -> Checkpoint C1
- A3 Change guard: structural diff, rules, LLM assessment, MITRE mapping,
  water_plant_tampered.st (FR-GRD)                       -> Checkpoint C2
- A4 Documentation generator and Q&A (FR-DOC)
- A5 Routers knowledge.py and guard.py, tests

Account B tasks, in order:
- B1 Telemetry store, expected-behavior engine, physical checks (FR-DET-01..03)
- B2 Triage and reasoner (FR-DET-04..07)
- B3 Operator assistant, report generator, Tavily client (FR-OPS)
- B4 API main and routers (FR-API)
- B5 Dashboard (FR-WEB)

Checkpoints:
- C1 (by 19 Oct): A replaces fixtures/knowledge_map.sample.json with the
  real output and provides real telemetry. B switches from samples to real.
- C2 (by 22 Oct): A provides a real ChangeReport. B wires the Change Guard page.

### Phase 2 - Integration (24-26 Oct)
Aram merges everything in ~/plantmind and runs the acceptance matrix:

| Scenario | Expected result |
|----------|-----------------|
| normal | no alerts |
| sensor_fault | alert; top hypothesis is sensor fault |
| spoofed_reading | alert; spoofing among the top two hypotheses |
| logic_tamper | Change Guard flags IL-04 as critical with ATT&CK mapping; detection flags the overdose condition |
| abnormal_command | alert; hypothesis is command abuse |

Fix list: each failure goes to the owner of the folder where it occurs.
End of phase: freeze features.

### Phase 3 - Polish and Submission (27-29 Oct)
- README with setup, Nemotron usage, Token Factory usage
- Demo video (under 3 minutes) and Devpost form
- Feedback section for the feedback prize
- Verify a fresh clone runs with the documented commands
- Keep 29 Oct as buffer; submit before the deadline

## 5. Definition of Done (per task)
- Code lives in the owner's folders and runs with MOCK_LLM=1
- Tests for the task pass (pytest)
- Output matches the contract schema
- Short note added to docs/CHANGELOG.md (one line per delivery)

## 6. If Time Runs Short (cut order)
1. Arabic output toggle (FR-OPS-07)
2. Grounded Q&A (FR-DOC-03) and chat (FR-OPS-03)
3. HTML export (keep Markdown)
The Must items in the functional requirements stay.

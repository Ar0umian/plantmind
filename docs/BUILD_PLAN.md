# PlantMind - Build Plan (single workstream)

All work is done in one chat with Claude, delivered as copy-paste Terminal
commands in several messages, working directory ~/plantmind. The module tags
[A] and [B] in FUNCTIONAL_REQUIREMENTS.md remain as logical groupings:
[A] = plant and knowledge, [B] = agent and experience.

## Principles
1. Thin end-to-end slice first, then deepen. A working demo exists by step 4.
2. Every step ends with passing tests (pytest) and a git commit
   "step N: ..." plus one line in docs/CHANGELOG.md.
3. MOCK_LLM=1 keeps everything runnable offline; real Nebius calls are
   switched on once credentials are in .env.
4. core/contracts.py changes only with a CONTRACT_VERSION bump.
5. Sample fixtures are generated from real outputs (scripts), not hand-written.

## Steps and Dates (Saudi time)
Deadline: 30 Oct 2026, 10:00 PT = 20:00 Saudi time. Target: submit by 29 Oct.

| Step | Content | Requirements | Target |
|------|---------|--------------|--------|
| 0 | Structure, docs, core contracts, LLM client (done) | - | 15 Oct |
| 1 | Plant simulator, scenarios, water_plant_baseline.st | FR-SIM | 17 Oct |
| 2 | ST parser and knowledge_map.json builder | FR-KM | 18 Oct |
| 3 | Detection core: telemetry store, expected-behavior engine, physical checks | FR-DET-01..03 | 19 Oct |
| 4 | API skeleton and minimal dashboard (live trends, alerts) - first end-to-end demo | FR-API, FR-WEB-01..02 | 20 Oct |
| 5 | Triage and reasoner with the LLM (needs Nebius key) | FR-DET-04..07 | 21 Oct |
| 6 | Change Guard, water_plant_tampered.st, MITRE mapping | FR-GRD | 22 Oct |
| 7 | Operator assistant, incident reports, Tavily | FR-OPS | 23 Oct |
| 8 | Documentation generator and Q&A | FR-DOC | 24 Oct |
| 9 | Dashboard completion (Change Guard, docs, reports, demo panel) | FR-WEB | 25 Oct |
| 10 | Integration, acceptance matrix, fixes | all | 26 Oct |
| 11 | README, demo video, Devpost form, feedback section | FR-SUB | 27-29 Oct |

## Acceptance Matrix (step 10)
| Scenario | Expected result |
|----------|-----------------|
| normal | no alerts |
| sensor_fault | alert; top hypothesis is sensor fault |
| spoofed_reading | alert; spoofing among the top two hypotheses |
| logic_tamper | Change Guard flags IL-04 as critical with ATT&CK mapping; detection flags the overdose condition |
| abnormal_command | alert; hypothesis is command abuse |

## Credentials Needed
- Nebius Token Factory key and model IDs: needed by step 5 (21 Oct).
  Join the Nebius Builder program early to get credits.
- Tavily API key: needed by step 7 (23 Oct).

## Resume Protocol (if the chat becomes long or slow)
Run scripts/make_briefing.sh, upload out/briefing.txt to a new chat and say
which step you are on. The repository holds the full state.

## If Time Runs Short (cut order)
1. Arabic output toggle (FR-OPS-07)
2. Grounded Q&A (FR-DOC-03) and chat (FR-OPS-03)
3. HTML export (keep Markdown)
Must items in the functional requirements stay.

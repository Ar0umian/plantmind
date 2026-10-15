# PlantMind - Non-Functional Requirements

Priority: M = Must, S = Should, C = Could.

## 1. Safety and Responsible Use
- NFR-SAF-01 (M) Advisory only: the system never sends commands to any
  real or simulated actuator. Every action is a recommendation that a human
  approves or rejects.
- NFR-SAF-02 (M) Human-in-the-loop: all approvals and rejections are logged
  with timestamp and decision.
- NFR-SAF-03 (M) Defensive scope: tamper and attack scenarios exist only as
  synthetic data inside the simulator. No exploit code, no tooling that
  touches real PLCs or networks.
- NFR-SAF-04 (M) The LLM explains and ranks; deterministic rules set the
  safety floor (rule-based severity can never be lowered by the LLM).

## 2. Reliability and Graceful Degradation
- NFR-REL-01 (M) If the LLM is unavailable or returns invalid output, the
  system still returns the deterministic result (violations, diff, rule-based
  severity) and marks the explanation as unavailable.
- NFR-REL-02 (M) MOCK_LLM mode makes the full demo flow run offline.
- NFR-REL-03 (S) Retries with backoff for LLM and Tavily calls; a failed
  Tavily call must not block report generation.

## 3. Performance (targets)
- NFR-PRF-01 (S) Telemetry to dashboard update: under 2 seconds.
- NFR-PRF-02 (S) Triage (small model) result: under 3 seconds.
- NFR-PRF-03 (S) Deep analysis and change assessment: under 30 seconds.
- NFR-PRF-04 (M) Deterministic checks run locally and do not depend on any
  network call.

## 4. Cost and Token Efficiency
- NFR-CST-01 (M) Route by tier: Nano for triage and routine calls, Super or
  Ultra only for escalated analysis.
- NFR-CST-02 (S) Send compact summaries of telemetry windows, not raw streams.
- NFR-CST-03 (S) Log token usage per call and per run.

## 5. Security
- NFR-SEC-01 (M) No secrets in the repository; configuration through .env.
- NFR-SEC-02 (M) Uploaded .st files are parsed as text only, never executed.
- NFR-SEC-03 (M) Validate all API inputs (size limits, schema validation).
- NFR-SEC-04 (M) Dashboard binds to localhost by default.

## 6. Privacy and Data
- NFR-PRV-01 (M) Only synthetic plant data is used and sent to external
  services.
- NFR-PRV-02 (S) Prompts contain plant descriptions and telemetry summaries
  only; no personal data.

## 7. Explainability and Trust
- NFR-EXP-01 (M) Every alert and finding references evidence IDs.
- NFR-EXP-02 (M) LLM JSON outputs are schema-validated; invalid or
  unreferenced claims are discarded.
- NFR-EXP-03 (S) The UI shows which findings are rule-based and which are
  model-generated.

## 8. Usability
- NFR-USE-01 (M) Operator-facing text is plain language, short, and actionable.
- NFR-USE-02 (S) The main demo flow needs no more than three clicks per step.
- NFR-USE-03 (C) Arabic output option.

## 9. Maintainability and Testability
- NFR-MNT-01 (M) All cross-workstream data uses typed pydantic models in
  core/contracts.py with a CONTRACT_VERSION.
- NFR-MNT-02 (M) Modules are built in the order of docs/BUILD_PLAN.md; shared contracts change only with a CONTRACT_VERSION bump.
- NFR-MNT-03 (M) Unit tests for the ST parser, the interlock evaluator, and
  the change-guard rules; integration test per scenario.
- NFR-MNT-04 (S) Structured logging, one line per event.

## 10. Portability and Reproducibility
- NFR-POR-01 (M) Python 3.10 or newer; runs on macOS and Linux.
- NFR-POR-02 (M) Setup in at most five commands documented in the README.
- NFR-POR-03 (M) One command starts the full demo (scripts/run_dev.sh).

## 11. Compliance with Hackathon Rules
- NFR-CMP-01 (M) Public repository with a visible open-source license (MIT).
- NFR-CMP-02 (M) All submission materials in English.
- NFR-CMP-03 (M) Demo video under 3 minutes, public on YouTube, without
  copyrighted music or third-party branding.
- NFR-CMP-04 (M) Third-party libraries and APIs used within their license
  terms.

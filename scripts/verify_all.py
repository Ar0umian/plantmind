#!/usr/bin/env python3
"""End-to-end verification of the PlantMind project, steps 0 to 8.

Run from the project root:   python scripts/verify_all.py
Options:                     --skip-pytest   (skip the unit-test run)

It checks, in order:
  A. every project file exists, is complete (size and end-of-file markers) -> finds incomplete pastes
  B. every module imports
  C. the whole pytest suite passes (and its test count matches the test files)
  D. the acceptance matrix: the five scenarios end to end, in offline (mock) mode
  E. the API answers correctly (needs fastapi + httpx)
  F. safety and publishing checks (no secrets tracked by git, license, .env ignored)
Everything runs offline: no model or search service is called.
"""
import importlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["MOCK_LLM"] = "1"          # never call a real service from this script
os.environ["MOCK_TAVILY"] = "1"

# path: (minimum lines, markers that must appear, step). Markers sit near the END of each
# file, so a truncated paste is detected.
MANIFEST = {
    "core/contracts.py": (150, ["class PlantRunner", "def recent_frames", "class IncidentReport"], 0),
    "core/config.py": (38, ["mock_tavily", "def get_settings"], 0),
    "core/llm_client.py": (100, ["def generate_json", "Invalid JSON from model after retries"], 0),
    "data/mitre_ics_subset.json": (20, ['"abnormal_command"', '"T0889"'], 0),
    "docs/FUNCTIONAL_REQUIREMENTS.md": (100, ["FR-SUB-04"], 0),
    "docs/NON_FUNCTIONAL_REQUIREMENTS.md": (50, ["NFR-CMP-04"], 0),
    "docs/BUILD_PLAN.md": (40, ["Resume Protocol"], 0),
    "tests/test_core_smoke.py": (20, ["test_llm_mock_json"], 0),
    "LICENSE": (15, ["MIT"], 0),
    "plant/simulator/plant_model.py": (125, ["def truth", "def step"], 1),
    "plant/simulator/interlocks.py": (54, ["def tripping", "UNWIRED"], 1),
    "plant/simulator/runner.py": (88, ["def _main", "__main__"], 1),
    "plant/scenarios/scenarios.py": (90, ["def deactivate", "abnormal_command"], 1),
    "plant/plc_programs/water_plant_baseline.st": (80, ["END_PROGRAM", "AT_201 > 1.8"], 1),
    "plant/plc_programs/water_plant_tampered.st": (80, ["END_PROGRAM", "AT_201 > 99.0"], 1),
    "tests/test_simulator.py": (100, ["test_runner_implements_interface_and_switches_scenarios"], 1),
    "knowledge/st_parser.py": (190, ["interlock.target = targets[0]", "def parse_st"], 2),
    "knowledge/map_builder.py": (106, ["def build_knowledge_map", "__main__"], 2),
    "tests/test_knowledge_map.py": (80, ["test_map_serializes_to_json"], 2),
    "fixtures/knowledge_map.json": (50, ["IL-04"], 2),
    "agent/signals.py": (9, ["class Signal"], 3),
    "agent/telemetry_store.py": (35, ["def slope"], 3),
    "agent/expected_behavior.py": (72, ["def check_commands"], 3),
    "agent/physical_checks.py": (86, ["def all_checks"], 3),
    "agent/detector.py": (80, ["class Detector", "__main__"], 3),
    "tests/test_detection.py": (94, ["test_store_window_and_slope"], 3),
    "agent/alerts.py": (80, ["class AlertManager", "def decide"], 4),
    "agent/engine.py": (240, ["def llm_info", "def plant_document", "def incident_report_bundle",
                              "_guard_context", "def guard_running"], 4),
    "api/main.py": (46, ["plant_docs.router", "reports.router", "guard.router"], 4),
    "api/routers/telemetry.py": (30, ['"llm"'], 4),
    "api/routers/alerts.py": (35, ["decisions"], 4),
    "api/routers/scenarios.py": (30, ["reset_demo"], 4),
    "web/index.html": (80, ['id="ai"', 'id="guard-panel"', 'id="assistant-panel"', 'id="docs-panel"'], 4),
    "web/static/app.js": (340, ["renderAnalysis", "renderReportLinks", "renderLlm", "setInterval(refresh, POLL_MS)"], 4),
    "web/static/style.css": (140, [".analysis {", "#guard-text {", ".chat-log {", ".docs-frame {"], 4),
    "tests/test_engine.py": (138, ["test_background_analysis_thread_fills_in_the_alert"], 4),
    "tests/test_api.py": (160, ["test_plant_document_endpoints", "test_assistant_endpoint_answers_blocks_and_validates",
                                "test_guard_running_program_follows_the_scenario"], 4),
    "scripts/run_dev.sh": (4, ["uvicorn"], 4),
    "agent/context.py": (38, ["def format_evidence"], 5),
    "agent/triage.py": (47, ["def run_triage"], 5),
    "agent/reasoner.py": (146, ["def run_reasoner", "differs from the approved program"], 5),
    "agent/analysis.py": (87, ["def apply_result"], 5),
    "tests/test_analysis.py": (136, ["test_model_failure_leaves_the_rule_based_alert_intact"], 5),
    "knowledge/change_guard.py": (345, ["class GuardService", "def reset"], 6),
    "api/routers/guard.py": (44, ["report not found"], 6),
    "web/static/guard.js": (155, ["setInterval(refreshRunning"], 6),
    "tests/test_change_guard.py": (175, ["test_mock_reasoner_uses_guard_context"], 6),
    "agent/tavily_client.py": (72, ["self._cache[query] = links"], 7),
    "agent/report_generator.py": (195, ["def render_html", "advisory only: it never sends commands"], 7),
    "agent/assistant.py": (200, ['mode="mock" if self.llm.is_mock', "what stops"], 7),
    "api/routers/reports.py": (31, ["report.html"], 7),
    "api/routers/assistant.py": (24, ["def ask"], 7),
    "web/static/assistant.js": (75, ['addMessage("assistant", "Ask about the current alert'], 7),
    "tests/test_reports_assistant.py": (174, ["test_history_is_limited_to_the_last_turns"], 7),
    "knowledge/doc_generator.py": (178, ["def generate_plant_document"], 8),
    "api/routers/plant_docs.py": (24, ["plant-operating-document.html"], 8),
    "tests/test_docs.py": (84, ["I find nothing"], 8),
}

MODULES = [
    "core.contracts", "core.config", "core.llm_client",
    "plant.simulator.plant_model", "plant.simulator.interlocks", "plant.simulator.runner", "plant.scenarios.scenarios",
    "knowledge.st_parser", "knowledge.map_builder",
    "agent.telemetry_store", "agent.expected_behavior", "agent.physical_checks", "agent.detector",
    "agent.alerts", "agent.context", "agent.triage", "agent.reasoner", "agent.analysis",
    "knowledge.change_guard", "agent.tavily_client", "agent.report_generator", "agent.assistant",
    "knowledge.doc_generator", "agent.engine",
]

results = []        # (section, name, status, detail)


def record(section, name, ok, detail="", skip=False):
    status = "SKIP" if skip else ("OK" if ok else "FAIL")
    results.append((section, name, status, detail))
    mark = {"OK": "[ OK ]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[status]
    print(f"  {mark} {name}" + (f"  -> {detail}" if detail and status != "OK" else ""))


# ------------------------------------------------------------------ A. files
def check_files():
    print("\nA. Files complete (a truncated or missing paste is reported here)")
    broken = {}
    for path, (min_lines, markers, step) in MANIFEST.items():
        file = ROOT / path
        if not file.exists():
            broken.setdefault(step, []).append(f"{path} is MISSING")
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        lines = text.count("\n") + 1
        problems = []
        if lines < min_lines:
            problems.append(f"only {lines} lines (expected at least {min_lines})")
        missing = [m for m in markers if m not in text]
        if missing:
            problems.append("missing text: " + ", ".join(repr(m) for m in missing))
        if problems:
            broken.setdefault(step, []).append(f"{path}: " + "; ".join(problems))
    for step in range(0, 9):
        issues = broken.get(step, [])
        total = sum(1 for v in MANIFEST.values() if v[2] == step)
        record("files", f"step {step}: {total} files complete", not issues, "; ".join(issues))
    if broken:
        print("\n  Fix: re-paste the batch that creates each file above (one file at a time), "
              "then check it with:  wc -l <file>")


# ---------------------------------------------------------------- B. imports
def check_imports():
    print("\nB. Modules import")
    failed = []
    for module in MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:               # report, never crash the verifier
            failed.append(f"{module}: {type(exc).__name__}: {exc}")
    record("imports", f"{len(MODULES) - len(failed)}/{len(MODULES)} modules import", not failed, "; ".join(failed))


# ----------------------------------------------------------------- C. pytest
def expected_test_count() -> int:
    total = 0
    for file in (ROOT / "tests").glob("test_*.py"):
        total += len(re.findall(r"^def test_", file.read_text(encoding="utf-8"), flags=re.M))
    return total


def check_pytest():
    print("\nC. Unit tests (pytest)")
    expected = expected_test_count()
    started = time.time()
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout + proc.stderr
    passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", out) or [0, 0])[1])
    errors = int((re.search(r"(\d+) error", out) or [0, 0])[1])
    ok = proc.returncode == 0 and failed == 0 and errors == 0
    detail = "" if ok else "see the pytest output below"
    record("pytest", f"{passed} passed, {failed} failed, {errors} errors ({time.time() - started:.0f}s)", ok, detail)
    record("pytest", f"test count matches the test files ({expected} expected)", passed == expected,
           f"pytest ran {passed} but the test files define {expected}; a test file may be incomplete")
    if not ok:
        print("\n" + "\n".join("    " + line for line in out.strip().splitlines()[-40:]))


# ------------------------------------------------------ D. acceptance matrix
def run_engine(scenario, ticks):
    from agent.engine import Engine
    engine = Engine(interval_s=0.0)
    if scenario != "normal":
        engine.start_scenario(scenario)
    for _ in range(ticks):
        engine.step()
    return engine


def check_matrix():
    print("\nD. Acceptance matrix (five scenarios, offline mode)")
    try:
        engine = run_engine("normal", 300)
        record("matrix", "normal: no alerts after 300 frames", not engine.alerts() and not engine.history(),
               f"{len(engine.alerts())} alert(s) appeared")

        engine = run_engine("sensor_fault", 60)
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else None
        record("matrix", "sensor_fault: alert, top cause = sensor_fault, no ATT&CK mapping",
               top == "sensor_fault" and engine.incident_report(alerts[0].id).mitre == [], f"top cause = {top}")

        engine = run_engine("spoofed_reading", 140)
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else None
        ids = {m.technique_id for m in engine.incident_report(alerts[0].id).mitre} if alerts else set()
        record("matrix", "spoofed_reading: alert, top cause = spoofing, report maps T0856",
               top == "spoofing" and "T0856" in ids, f"top cause = {top}, techniques = {sorted(ids)}")

        engine = run_engine("logic_tamper", 120)
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else None
        guard = engine.guard_running()
        guard_ok = guard is not None and guard.report.overall_severity.value == "critical"
        record("matrix", "logic_tamper: IL-04 alert + top cause logic_tampering + Change Guard CRITICAL",
               bool(alerts) and "IL-04" in alerts[0].title and top == "logic_tampering" and guard_ok,
               f"title = {alerts[0].title if alerts else None}, top = {top}, guard ok = {guard_ok}")

        engine = run_engine("abnormal_command", 20)
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else None
        record("matrix", "abnormal_command: alert, top cause = command_abuse",
               bool(alerts) and top == "command_abuse", f"top cause = {top}")

        reply = engine.ask("stop P-201")
        record("matrix", "assistant refuses commands to equipment", reply.mode == "blocked", f"mode = {reply.mode}")
        reply = run_engine("normal", 5).ask("Why does P-201 stop?")
        record("matrix", "assistant explains what stops P-201 from the approved program (IL-03, IL-04)",
               "IL-03" in reply.answer and "IL-04" in reply.answer, reply.answer[:100])
        doc = engine.plant_document()
        from agent.engine import load_approved_map
        missing = [i.id for i in load_approved_map().interlocks if i.id not in doc.markdown]
        record("matrix", "plant document lists all six interlocks", not missing, f"missing {missing}")
    except Exception as exc:
        record("matrix", "acceptance matrix ran without errors", False, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- E. API
def check_api():
    print("\nE. API")
    try:
        from fastapi.testclient import TestClient
        from agent.engine import Engine
        from api.main import create_app
    except Exception as exc:
        record("api", "FastAPI test client available", False, f"{type(exc).__name__}: {exc}", skip=True)
        return
    try:
        engine = Engine(interval_s=0.0)
        client = TestClient(create_app(autostart=False, engine=engine))
        checks = []
        checks.append(("health", client.get("/api/health").json().get("status") == "ok"))
        names = [s["name"] for s in client.get("/api/scenarios").json()]
        checks.append(("five scenarios listed", len(names) == 5))
        client.post("/api/scenarios/logic_tamper/start")
        for _ in range(120):
            engine.step()
        alerts = client.get("/api/alerts").json()
        checks.append(("tamper alert via API", bool(alerts) and "IL-04" in alerts[0]["title"]))
        alert_id = alerts[0]["id"] if alerts else "A-0001"
        page = client.get(f"/api/alerts/{alert_id}/report.html")
        checks.append(("incident report html", page.status_code == 200 and "Incident report" in page.text))
        checks.append(("decision saved", client.post(f"/api/alerts/{alert_id}/decision",
                                                    json={"decision": "approved"}).status_code == 200))
        sample = client.get("/api/guard/samples").json()
        guard = client.post("/api/guard/check", json={"candidate": sample["tampered"]}).json()
        checks.append(("change guard flags critical", guard["report"]["overall_severity"] == "critical"))
        checks.append(("running program differs", client.get("/api/guard/running").json()["matches_approved"] is False))
        checks.append(("assistant answers", client.post("/api/assistant/ask",
                                                        json={"question": "What is happening?"}).json()["mode"] == "mock"))
        checks.append(("assistant refuses commands", client.post("/api/assistant/ask",
                                                                 json={"question": "start P-201"}).json()["mode"] == "blocked"))
        checks.append(("plant document served", "Protective interlocks" in client.get("/api/docs/plant.md").text))
        checks.append(("oversized input rejected", client.post("/api/guard/check",
                                                               json={"candidate": "x" * 200_001}).status_code == 422))
        checks.append(("dashboard page served", client.get("/").status_code == 200))
        bad = [name for name, ok in checks if not ok]
        record("api", f"{len(checks) - len(bad)}/{len(checks)} API checks pass", not bad, "failed: " + ", ".join(bad))
    except Exception as exc:
        record("api", "API checks ran without errors", False, f"{type(exc).__name__}: {exc}")


# ------------------------------------------------------- F. safety / publishing
def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
    except OSError:
        return None


def check_safety():
    print("\nF. Safety and publishing checks")
    ignore = (ROOT / ".gitignore")
    record("safety", ".env is listed in .gitignore", ignore.exists() and ".env" in ignore.read_text().splitlines())
    repo = git("rev-parse", "--is-inside-work-tree")
    if repo is None or repo.returncode != 0:
        record("safety", "git repository present", False, "run: git init", skip=True)
        return
    tracked = git("ls-files").stdout.splitlines()
    record("safety", ".env is NOT tracked by git", ".env" not in tracked, ".env is tracked: run git rm --cached .env")
    patterns = [re.compile(r"tvly-[A-Za-z0-9_\-]{12,}"),
                re.compile(r"(?m)^[ \t]*(NEBIUS_API_KEY|TAVILY_API_KEY)[ \t]*=[ \t]*[^\s#]{8,}"),
                re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}")]
    leaks = []
    for path in tracked:
        file = ROOT / path
        if not file.is_file() or file.suffix in (".png", ".jpg", ".pyc"):
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(p.search(text) for p in patterns):
            leaks.append(path)
    record("safety", "no API keys inside files tracked by git", not leaks, "possible key in: " + ", ".join(leaks))
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8") if (ROOT / "LICENSE").exists() else ""
    record("safety", "MIT license file present", "MIT License" in license_text)
    readme = ROOT / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    record("safety", "README.md written", len(readme_text) > 400, "README.md is empty or missing")
    todo = readme_text.count("TODO(live)")
    record("safety", "README has no unfinished TODO(live) markers (fill them after the live run)", todo == 0,
           f"{todo} TODO(live) marker(s) left", skip=todo > 0)
    from core.config import get_settings
    settings = get_settings()
    print(f"\n  Current mode (from .env): MOCK_LLM={'1' if settings.mock_llm else '0'}, "
          f"MOCK_TAVILY={'1' if settings.mock_tavily else '0'}  "
          "(this script forces both to 1 while it runs)")


def main():
    started = time.time()
    skip_pytest = "--skip-pytest" in sys.argv
    print("PlantMind verification (steps 0 to 8)")
    check_files()
    check_imports()
    if skip_pytest:
        print("\nC. Unit tests (pytest)")
        record("pytest", "pytest run", True, "skipped by --skip-pytest", skip=True)
    else:
        check_pytest()
    check_matrix()
    check_api()
    check_safety()

    ok = sum(1 for r in results if r[2] == "OK")
    fail = [r for r in results if r[2] == "FAIL"]
    skip = sum(1 for r in results if r[2] == "SKIP")
    print("\n" + "=" * 70)
    print(f"RESULT: {ok} ok, {len(fail)} failed, {skip} skipped  ({time.time() - started:.0f}s)")
    if fail:
        print("\nFAILED CHECKS:")
        for section, name, _, detail in fail:
            print(f" - [{section}] {name}\n     {detail}")
        print("\nSend me this whole output and I will tell you exactly which file to fix.")
        sys.exit(1)
    print("All checks passed." + (" (Some were skipped; see [SKIP] lines above.)" if skip else ""))


if __name__ == "__main__":
    main()

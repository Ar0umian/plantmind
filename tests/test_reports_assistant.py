import os

os.environ["MOCK_LLM"] = "1"

from agent.assistant import (BLOCK_MESSAGE, AssistantAnswer, AssistantContext, OperatorAssistant,
                             is_command_request)
from agent.engine import Engine, load_approved_map
from agent.report_generator import NO_MITRE_NOTE, build_incident_report, render_html
from agent.tavily_client import TavilyClient
from core.contracts import Alert, Evidence, ReferenceLink, Severity
from core.llm_client import LLMClient, LLMError


def _engine_with(scenario, ticks):
    engine = Engine(interval_s=0.0)
    engine.start_scenario(scenario)
    for _ in range(ticks):
        engine.step()
    return engine


# ----------------------------------------------------------------- reports
def test_tamper_report_has_every_section_and_correct_mapping():
    engine = _engine_with("logic_tamper", 120)
    alert_id = engine.alerts()[0].id
    bundle = engine.incident_report_bundle(alert_id)
    report, md = bundle.report, bundle.report.markdown
    for heading in ("# Incident report R-A-0001", "## Summary", "## What happened", "## Most likely causes",
                    "## Program integrity", "## Timeline", "## Actions and decisions",
                    "## ATT&CK for ICS mapping", "## References", "## Appendix: telemetry summary"):
        assert heading in md, heading
    assert "MOCK MODEL" in md and "DIFFERS from the approved baseline" in md
    assert {"T0889", "T0837"} <= {m.technique_id for m in report.mitre}
    assert report.references and all(r.title.startswith("[offline example]") or len(r.title) > 0 for r in report.references)
    assert any(a.startswith("Suggested check:") for a in report.actions)
    stamps = [line[:19] for line in report.timeline]
    assert stamps == sorted(stamps) and len(report.timeline) >= 3
    engine.decide(alert_id, "approved")
    again = engine.incident_report(alert_id)
    assert any(a.startswith("Decision: approved") for a in again.actions)
    assert any("Human decision" in line for line in again.timeline)


def test_sensor_fault_has_no_attack_mapping_but_spoofing_does():
    sensor = _engine_with("sensor_fault", 60)
    bundle = sensor.incident_report_bundle(sensor.alerts()[0].id)
    assert bundle.report.mitre == [] and NO_MITRE_NOTE in bundle.report.markdown
    spoof = _engine_with("spoofed_reading", 140)
    ids = {m.technique_id for m in spoof.incident_report(spoof.alerts()[0].id).mitre}
    assert "T0856" in ids


def test_unknown_alert_has_no_report():
    assert Engine(interval_s=0.0).incident_report("A-9999") is None


def _manual_alert(summary="<script>alert(1)</script>"):
    ev = Evidence(id="EV-0001", kind="stale_value", summary=summary, tags=["AT-201"], ts=1.0)
    return Alert(id="A-0001", ts=1.0, severity=Severity.medium, title="t <b>x</b>", evidence=[ev],
                 operator_explanation="explain <img src=x>")


def test_html_report_escapes_everything_dynamic():
    bundle = build_incident_report(_manual_alert(), [], [], None, TavilyClient(mock=True), llm_mock=True)
    page = render_html(bundle)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<img src=x>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page
    assert page.startswith("<!doctype html>") and "advisory only" in page


class _EvilTavily:
    def references_for(self, label, max_results=3):
        return [ReferenceLink(title="bad", url="javascript:alert(1)"),
                ReferenceLink(title="good", url="https://example.com/a")]


def test_html_report_never_emits_non_http_links():
    bundle = build_incident_report(_manual_alert("plain"), [], [], None, _EvilTavily(), llm_mock=True)
    page = render_html(bundle)
    assert "javascript:" not in page and "https://example.com/a" in page


# ------------------------------------------------------------------ tavily
def test_tavily_offline_mode_is_labelled_and_attack_only():
    client = TavilyClient(mock=True)
    assert client.references_for("sensor_fault") == []
    links = client.references_for("command_abuse")
    assert links and all(l.url.startswith("https://attack.mitre.org/techniques/") for l in links)
    assert client.stats["live_searches"] == 0


def test_tavily_live_mode_filters_caches_and_limits():
    calls = []

    def fake(query, max_results):
        calls.append(query)
        return [{"title": " Good   advisory ", "url": "https://example.org/a", "score": 0.9},
                {"title": "low score", "url": "https://example.org/b", "score": 0.05},
                {"title": "bad url", "url": "ftp://example.org/c", "score": 0.9},
                {"title": "", "url": "https://example.org/d", "score": 0.9}]

    client = TavilyClient(search_fn=fake, mock=False, max_live_searches=2)
    first = client.references_for("spoofing")
    assert [(l.title, l.url) for l in first] == [("Good advisory", "https://example.org/a")]
    assert client.references_for("spoofing") == first and len(calls) == 1
    assert client.stats["cache_hits"] == 1
    client.references_for("logic_tampering")
    assert client.references_for("command_abuse") == [] and len(calls) == 2    # budget reached


def test_tavily_failures_never_raise():
    def broken(query, max_results):
        raise RuntimeError("network down")

    client = TavilyClient(search_fn=broken, mock=False)
    assert client.references_for("spoofing") == [] and client.stats["failures"] == 1
    keyless = TavilyClient(mock=False)
    keyless._api_key = ""
    assert keyless.references_for("spoofing") == [] and keyless.stats["failures"] == 1


# --------------------------------------------------------------- assistant
def test_command_requests_are_recognized_but_questions_are_not():
    for text in ("start P-201", "Please shut down the intake pump", "could you turn off P-101",
                 "override the interlock", "bypass IL-04", "Reset the alarm"):
        assert is_command_request(text), text
    for text in ("why did P-201 stop?", "what should I check first?", "what does IL-04 do",
                 "is the program running the approved one?", "how is the chlorine level"):
        assert not is_command_request(text), text


class _CountingLLM:
    is_mock = False

    def __init__(self, answer=None, error=False):
        self.calls, self.prompts, self.answer, self.error = 0, [], answer, error

    def generate_json(self, tier, system, user, schema, mock=None, **kwargs):
        self.calls += 1
        self.prompts.append(user)
        if self.error:
            raise LLMError("down")
        return self.answer


def _context(engine):
    return AssistantContext(frame=engine.latest_frame(), alerts=engine.alerts(),
                            evidence=engine.active_evidence(), guard=engine.guard_running())


def test_command_requests_are_refused_without_calling_the_model():
    llm = _CountingLLM(AssistantAnswer(answer="x"))
    assistant = OperatorAssistant(llm, load_approved_map())
    reply = assistant.ask("Please start P-201", AssistantContext(frame=None))
    assert reply.mode == "blocked" and reply.answer == BLOCK_MESSAGE and llm.calls == 0
    assert assistant.ask("   ", AssistantContext(frame=None)).mode == "blocked" and llm.calls == 0


def test_mock_assistant_answers_from_the_live_state():
    engine = _engine_with("logic_tamper", 120)
    alert_id = engine.alerts()[0].id
    what = engine.ask("What is happening?")
    assert what.mode == "mock" and alert_id in what.sources and "IL-04" in what.answer
    il = engine.ask("What does IL-04 do?")
    assert il.sources == ["IL-04"] and "chlorine overdose" in il.answer.lower()
    program = engine.ask("Is the program running the approved one?")
    assert "DIFFERS" in program.answer and program.sources
    level = engine.ask("What is the chlorine level?")
    assert "AT-201 =" in level.answer and "ppm" in level.answer and level.sources == ["AT-201"]
    checks = engine.ask("What should I check first?")
    assert "suggested checks" in checks.answer.lower() and alert_id in checks.sources
    assert engine.ask("start P-201").mode == "blocked"


def test_quiet_plant_gets_a_calm_answer():
    engine = Engine(interval_s=0.0)
    for _ in range(20):
        engine.step()
    assert "No alerts" in engine.ask("what is going on?").answer
    assert "matches the approved baseline" in engine.ask("is the plc program modified?").answer


def test_model_answer_is_cleaned_and_sources_are_validated():
    engine = _engine_with("logic_tamper", 120)
    llm = _CountingLLM(AssistantAnswer(answer="  Spaced   answer ", sources=["EV-9999", "IL-04", "IL-04"]))
    assistant = OperatorAssistant(llm, engine.kmap)
    reply = assistant.ask("explain it", _context(engine))
    assert reply.mode == "live" and reply.answer == "Spaced answer" and reply.sources == ["IL-04"]


def test_model_failure_is_reported_not_raised():
    engine = Engine(interval_s=0.0)
    assistant = OperatorAssistant(_CountingLLM(error=True), engine.kmap)
    reply = assistant.ask("what is happening?", _context(engine))
    assert reply.mode == "unavailable" and "unavailable" in reply.answer


def test_history_is_limited_to_the_last_turns():
    engine = Engine(interval_s=0.0)
    llm = _CountingLLM(AssistantAnswer(answer="ok"))
    assistant = OperatorAssistant(llm, engine.kmap)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"turn number {i}"} for i in range(10)]
    assistant.ask("and now?", _context(engine), history)
    prompt = llm.prompts[0]
    assert "turn number 9" in prompt and "turn number 4" in prompt and "turn number 3" not in prompt

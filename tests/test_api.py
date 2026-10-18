import os

os.environ["MOCK_LLM"] = "1"

from fastapi.testclient import TestClient

from agent.engine import Engine
from api.main import create_app


def _client():
    engine = Engine(interval_s=0.0)
    app = create_app(autostart=False, engine=engine)
    return TestClient(app), engine


def test_health_and_empty_state():
    client, _ = _client()
    assert client.get("/api/health").json()["status"] == "ok"
    body = client.get("/api/state").json()
    assert body["latest"] is None and body["demo_scenario"] == "normal"


def test_telemetry_endpoint_returns_recent_frames():
    client, engine = _client()
    for _ in range(30):
        engine.step()
    frames = client.get("/api/telemetry?n=10").json()
    assert len(frames) == 10
    assert set(frames[-1]["values"]) == {"LT-101", "FT-101", "AT-201", "LT-301", "PT-301"}
    assert client.get("/api/telemetry?n=0").status_code == 422


def test_scenarios_list_and_start_and_unknown():
    client, _ = _client()
    names = [s["name"] for s in client.get("/api/scenarios").json()]
    assert "logic_tamper" in names
    assert client.post("/api/scenarios/logic_tamper/start").json() == {"scenario": "logic_tamper"}
    assert client.get("/api/state").json()["demo_scenario"] == "logic_tamper"
    assert client.post("/api/scenarios/nope/start").status_code == 404
    client.post("/api/scenarios/stop")
    assert client.get("/api/state").json()["demo_scenario"] == "normal"


def test_alert_flow_end_to_end():
    client, engine = _client()
    client.post("/api/scenarios/logic_tamper/start")
    for _ in range(120):
        engine.step()
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1 and alerts[0]["severity"] == "high"
    assert "IL-04" in alerts[0]["title"]
    alert_id = alerts[0]["id"]
    assert client.get(f"/api/alerts/{alert_id}").json()["status"] == "open"

    reply = client.post(f"/api/alerts/{alert_id}/decision", json={"decision": "approved"})
    assert reply.status_code == 200 and reply.json()["status"] == "approved"
    assert client.get("/api/decisions").json()[-1]["decision"] == "approved"
    assert client.post(f"/api/alerts/{alert_id}/decision", json={"decision": "maybe"}).status_code == 422
    assert client.post("/api/alerts/A-9999/decision", json={"decision": "approved"}).status_code == 404
    assert client.get("/api/alerts/A-9999").status_code == 404

    assert len(client.get("/api/evidence").json()) >= 1
    client.post("/api/demo/reset")
    assert client.get("/api/alerts").json() == []


def test_knowledge_map_endpoint():
    client, _ = _client()
    body = client.get("/api/knowledge-map").json()
    assert len(body["interlocks"]) == 6 and body["plant_name"] == "WaterPlant"


def test_dashboard_is_served():
    client, _ = _client()
    page = client.get("/")
    assert page.status_code == 200 and "PlantMind" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_alert_carries_model_analysis_and_state_reports_mock_mode():
    client, engine = _client()
    client.post("/api/scenarios/logic_tamper/start")
    for _ in range(120):
        engine.step()
    alert = client.get("/api/alerts").json()[0]
    assert alert["hypotheses"][0]["label"] == "logic_tampering"
    assert alert["operator_explanation"].startswith("[MOCK")
    assert client.get("/api/state").json()["llm"]["mock"] is True


def _program(name):
    from agent.engine import PROGRAMS
    return PROGRAMS[name].read_text(encoding="utf-8")


def test_guard_check_endpoint_reports_the_bypass():
    client, _ = _client()
    reply = client.post("/api/guard/check", json={"candidate": _program("tampered"), "label": "demo upload"})
    assert reply.status_code == 200
    body = reply.json()
    assert body["report"]["overall_severity"] == "critical" and len(body["report"]["findings"]) == 2
    assert body["mode"] == "mock" and body["source"] == "demo upload"
    assert body["report"]["findings"][0]["interlock_id"] == "IL-04"
    assert "+IF NOT P_101_RUN OR AT_201 > 99.0 THEN" in body["diff"]
    clean = client.post("/api/guard/check", json={"candidate": _program("baseline")}).json()
    assert clean["report"]["findings"] == [] and clean["mode"] == "none"


def test_guard_rejects_empty_and_oversized_input():
    client, _ = _client()
    assert client.post("/api/guard/check", json={"candidate": ""}).status_code == 422
    assert client.post("/api/guard/check", json={"candidate": "x" * 200_001}).status_code == 422


def test_guard_decisions_samples_and_listing():
    client, _ = _client()
    first = client.post("/api/guard/check", json={"candidate": _program("tampered")}).json()
    key = first["report"]["candidate_hash"]
    ok = client.post(f"/api/guard/{key}/decision", json={"decision": "needs_review"})
    assert ok.status_code == 200 and ok.json()["report"]["decision"] == "needs_review"
    assert client.post(f"/api/guard/{key}/decision", json={"decision": "maybe"}).status_code == 422
    assert client.post("/api/guard/deadbeef/decision", json={"decision": "approved"}).status_code == 404
    assert [r["report"]["candidate_hash"] for r in client.get("/api/guard/reports").json()] == [key]
    samples = client.get("/api/guard/samples").json()
    assert "PROGRAM WaterPlant" in samples["approved"] and "AT_201 > 99.0" in samples["tampered"]


def test_guard_running_program_follows_the_scenario():
    client, engine = _client()
    engine.step()
    assert client.get("/api/guard/running").json() == {"matches_approved": True, "result": None}
    client.post("/api/scenarios/logic_tamper/start")
    engine.step()
    body = client.get("/api/guard/running").json()
    assert body["matches_approved"] is False
    assert body["result"]["report"]["overall_severity"] == "critical"
    client.post("/api/scenarios/stop")
    engine.step()
    assert client.get("/api/guard/running").json()["matches_approved"] is True


def _tamper_alert(client, engine):
    client.post("/api/scenarios/logic_tamper/start")
    for _ in range(120):
        engine.step()
    return client.get("/api/alerts").json()[0]["id"]


def test_report_endpoints_return_json_markdown_and_html():
    client, engine = _client()
    alert_id = _tamper_alert(client, engine)
    body = client.get(f"/api/alerts/{alert_id}/report").json()
    assert body["id"] == f"R-{alert_id}" and body["evidence"] and body["markdown"].startswith("# Incident report")
    assert {m["technique_id"] for m in body["mitre"]} >= {"T0889", "T0837"}
    md = client.get(f"/api/alerts/{alert_id}/report.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "## Timeline" in md.text and "attachment" not in md.headers.get("content-disposition", "")
    dl = client.get(f"/api/alerts/{alert_id}/report.md?download=true")
    assert f'incident-{alert_id}.md' in dl.headers["content-disposition"]
    page = client.get(f"/api/alerts/{alert_id}/report.html")
    assert page.status_code == 200 and page.text.startswith("<!doctype html>") and "ATT&amp;CK" in page.text
    assert client.get("/api/alerts/A-9999/report").status_code == 404
    assert client.get("/api/alerts/A-9999/report.html").status_code == 404


def test_assistant_endpoint_answers_blocks_and_validates():
    client, engine = _client()
    _tamper_alert(client, engine)
    ok = client.post("/api/assistant/ask", json={"question": "What is happening?", "history": []})
    assert ok.status_code == 200
    body = ok.json()
    assert body["mode"] == "mock" and "IL-04" in body["answer"] and body["sources"]
    blocked = client.post("/api/assistant/ask", json={"question": "stop P-201"}).json()
    assert blocked["mode"] == "blocked" and "advisory" in blocked["answer"]
    assert client.post("/api/assistant/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/assistant/ask", json={"question": "x" * 501}).status_code == 422
    turns = [{"role": "user", "text": "hi"}] * 13
    assert client.post("/api/assistant/ask", json={"question": "hi", "history": turns}).status_code == 422


def test_plant_document_endpoints():
    client, _ = _client()
    doc = client.get("/api/docs/plant").json()
    assert doc["summary_mode"] == "mock" and doc["markdown"].startswith("# Plant operating document")
    md = client.get("/api/docs/plant.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "## Protective interlocks" in md.text
    dl = client.get("/api/docs/plant.html?download=true")
    assert "plant-operating-document.html" in dl.headers["content-disposition"]
    assert dl.text.startswith("<!doctype html>") and "IL-04" in dl.text

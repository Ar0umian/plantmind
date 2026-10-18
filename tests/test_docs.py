import os

os.environ["MOCK_LLM"] = "1"

from agent.assistant import AssistantContext, OperatorAssistant
from agent.engine import APPROVED_PROGRAM, PROGRAMS, Engine, load_approved_map
from core.llm_client import LLMClient, LLMError
from knowledge.doc_generator import DocSummary, PlantDocument, generate_plant_document
from knowledge.map_builder import build_knowledge_map


def _doc(llm=None, kmap=None):
    return generate_plant_document(kmap or load_approved_map(), llm)


def test_document_has_every_section_and_every_interlock():
    kmap = load_approved_map()
    doc = _doc(LLMClient(), kmap)
    assert isinstance(doc, PlantDocument) and doc.program_hash == kmap.program_hash
    for heading in ("## Overview", "## Equipment and instruments", "## Protective interlocks",
                    "## What stops each pump", "## Automatic control", "## Alarms",
                    "## External command paths", "## Limits of this document"):
        assert heading in doc.markdown, heading
    for il in kmap.interlocks:
        assert il.id in doc.markdown and il.id in doc.html
    for equipment in kmap.equipment:
        assert equipment.tag in doc.markdown
    assert "MOCK model" in doc.markdown and doc.summary_mode == "mock"


def test_document_uses_plain_language_and_explains_what_stops_each_pump():
    doc = _doc()
    assert " >= " not in doc.markdown and " < " not in doc.markdown
    assert "LT-101 is below 15.0" in doc.markdown
    stops = doc.markdown.split("## What stops each pump")[1].split("##")[0]
    assert "P-201 (Chlorine dosing pump) stops when" in stops and "IL-03" in stops and "IL-04" in stops
    assert "automatic control: P-201 auto-stops" in stops


def test_without_a_model_the_overview_is_deterministic():
    doc = _doc(None)
    assert doc.summary_mode == "deterministic" and "MOCK" not in doc.markdown
    assert "5 instruments and 3 pumps" in doc.markdown


def test_unwired_interlock_is_called_out():
    tampered, _ = build_knowledge_map(PROGRAMS["tampered"].read_text(encoding="utf-8"))
    doc = _doc(kmap=tampered)
    assert "nothing (not wired to any pump)" in doc.markdown
    assert "IL-04 is computed by the program but is not wired" in doc.markdown
    assert "Warning: IL-04 is defined but protects nothing" in doc.markdown


class _ScriptedLLM:
    def __init__(self, summary=None, error=False):
        self.summary, self.error, self.is_mock = summary, error, False

    def generate_json(self, tier, system, user, schema, mock=None, **kwargs):
        if self.error:
            raise LLMError("down")
        return DocSummary(summary=self.summary)


def test_model_overview_is_accepted_only_when_grounded():
    good = _doc(_ScriptedLLM("The plant has pumps P-101 and P-201 protected by IL-04."))
    assert good.summary_mode == "live" and "protected by IL-04" in good.markdown
    bad = _doc(_ScriptedLLM("Tank LT-999 is protected by IL-77."))
    assert bad.summary_mode == "deterministic" and "LT-999" not in bad.markdown
    empty = _doc(_ScriptedLLM("   "))
    assert empty.summary_mode == "deterministic"
    failed = _doc(_ScriptedLLM(error=True))
    assert failed.summary_mode == "deterministic" and "## Overview" in failed.markdown


def test_html_is_escaped_and_complete():
    kmap = load_approved_map()
    kmap.equipment[0].name = "<script>alert(1)</script>"
    doc = _doc(kmap=kmap)
    assert "<script>" not in doc.html and "&lt;script&gt;" in doc.html
    assert doc.html.startswith("<!doctype html>") and "<table>" in doc.html and doc.html.endswith("</html>")


def test_engine_caches_the_document():
    engine = Engine(interval_s=0.0)
    first = engine.plant_document()
    assert engine.plant_document() is first


def test_assistant_answers_what_stops_a_pump_from_the_approved_program():
    engine = Engine(interval_s=0.0)
    for _ in range(5):
        engine.step()
    reply = engine.ask("Why does P-201 stop?")
    assert reply.mode == "mock" and "IL-03" in reply.answer and "IL-04" in reply.answer
    assert "automatic control" in reply.answer and "IL-04" in reply.sources and "P-201" in reply.sources
    assert "I find nothing" not in engine.ask("what stops P-101?").answer
    assert engine.ask("stop P-201").mode == "blocked"
    status = engine.ask("what is the status of P-301?")
    assert "P-301" in status.answer and "stopped by" not in status.answer

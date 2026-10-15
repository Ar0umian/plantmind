import os

os.environ["MOCK_LLM"] = "1"

import pytest

from core.contracts import (Condition, Equipment, Finding, Interlock, KnowledgeMap,
                            Severity, TelemetryFrame, max_severity, sha256_text)
from core.llm_client import LLMClient, LLMError


def test_frame_roundtrip():
    frame = TelemetryFrame(ts=1.0, tick=1,
                           values={"LT-101": 60.0, "AT-201": 1.2},
                           status={"P-101": True, "P-201": True})
    again = TelemetryFrame.model_validate_json(frame.model_dump_json())
    assert again.values["LT-101"] == 60.0
    assert again.scenario == "normal"


def test_knowledge_map_roundtrip():
    il04 = Interlock(id="IL-04", target="P-201",
                     conditions=[Condition(tag="AT-201", op=">", value=4.0)])
    kmap = KnowledgeMap(plant_name="demo", program_hash=sha256_text("x"),
                        equipment=[Equipment(tag="P-201", name="Chlorine pump", kind="pump")],
                        interlocks=[il04])
    again = KnowledgeMap.model_validate_json(kmap.model_dump_json())
    assert again.interlocks[0].id == "IL-04"
    assert again.interlocks[0].conditions[0].value == 4.0


def test_boolean_condition_value_kept():
    cond = Condition(tag="P-101", op="==", value=False)
    assert cond.value is False


def test_model_cannot_lower_rule_severity():
    finding = Finding(id="F-001", kind="removed", interlock_id="IL-04",
                      summary="x", rule_severity=Severity.critical,
                      llm_severity=Severity.low)
    assert finding.final_severity() == Severity.critical
    assert max_severity(None, Severity.low) == Severity.low


def test_llm_mock_json():
    client = LLMClient()
    result = client.generate_json(
        "nano", "sys", "user", Finding,
        mock=lambda: Finding(id="F-9", kind="added", summary="mock",
                             rule_severity=Severity.info))
    assert result.id == "F-9"


def test_llm_mock_requires_factory():
    with pytest.raises(LLMError):
        LLMClient().generate_json("nano", "sys", "user", Finding)


def test_llm_mock_text():
    assert LLMClient().generate_text("nano", "s", "u", mock="hello") == "hello"

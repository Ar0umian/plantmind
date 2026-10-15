import os

os.environ["MOCK_LLM"] = "1"

from knowledge.map_builder import UNWIRED, build_knowledge_map
from knowledge.st_parser import parse_st
from plant.simulator.interlocks import INTERLOCKS

ST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plant", "plc_programs")


def _read(name):
    with open(os.path.join(ST_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def test_baseline_parses_without_warnings():
    program = parse_st(_read("water_plant_baseline.st"))
    assert program.program_name == "WaterPlant"
    assert program.warnings == []
    assert len(program.interlocks) == 6
    assert len(program.alarms) == 3


def test_parsed_interlocks_match_the_simulator_definitions():
    kmap, warnings = build_knowledge_map(_read("water_plant_baseline.st"))
    assert warnings == []
    by_id = {item.id: item for item in kmap.interlocks}
    for definition in INTERLOCKS:
        parsed = by_id[definition.id]
        assert parsed.target == definition.target, definition.id
        got = [(c.tag, c.op, c.value) for c in parsed.conditions]
        assert got == list(definition.conditions), definition.id


def test_equipment_extracted_with_names_and_units():
    kmap, _ = build_knowledge_map(_read("water_plant_baseline.st"))
    sensors = {e.tag: e for e in kmap.equipment if e.kind == "sensor"}
    pumps = {e.tag: e for e in kmap.equipment if e.kind == "pump"}
    assert set(sensors) == {"LT-101", "FT-101", "AT-201", "LT-301", "PT-301"}
    assert set(pumps) == {"P-101", "P-201", "P-301"}
    assert sensors["AT-201"].unit == "ppm"
    assert sensors["LT-101"].name == "Raw water tank level"
    assert pumps["P-201"].name == "Chlorine dosing pump"


def test_alarms_and_purposes():
    kmap, _ = build_knowledge_map(_read("water_plant_baseline.st"))
    alarms = {a.id: a for a in kmap.alarms}
    assert (alarms["AL-02"].tag, alarms["AL-02"].op, alarms["AL-02"].value) == ("AT-201", "<", 0.2)
    il04 = next(i for i in kmap.interlocks if i.id == "IL-04")
    assert "overdose" in il04.purpose.lower()
    assert il04.source_lines and il04.source_lines[0] > 0


def test_command_bits_become_relations():
    kmap, _ = build_knowledge_map(_read("water_plant_baseline.st"))
    external = [r for r in kmap.relations if r.source == "SCADA/HMI"]
    assert {r.target for r in external} == {"P-201", "P-301"}


def test_tampered_program_shows_unwired_interlock_and_new_setpoint():
    baseline, _ = build_knowledge_map(_read("water_plant_baseline.st"))
    tampered, warnings = build_knowledge_map(_read("water_plant_tampered.st"))
    assert warnings == []
    assert baseline.program_hash != tampered.program_hash
    il04 = next(i for i in tampered.interlocks if i.id == "IL-04")
    assert il04.target == UNWIRED
    assert next(i for i in baseline.interlocks if i.id == "IL-04").target == "P-201"
    others = [i for i in tampered.interlocks if i.id != "IL-04"]
    assert all(i.target != UNWIRED for i in others)


def test_control_rule_setpoint_difference():
    def stop_threshold(name):
        program = parse_st(_read(name))
        rule = next(r for r in program.control_rules
                    if r.var == "P_201_AUTO" and r.value is False)
        return next(t.value for t in rule.expr.terms if t.tag == "AT-201")
    assert stop_threshold("water_plant_baseline.st") == 1.8
    assert stop_threshold("water_plant_tampered.st") == 99.0


def test_unsupported_syntax_is_reported_not_crashing():
    program = parse_st("PROGRAM X\nVAR_INPUT\n  A_101 : REAL;\nEND_VAR\nFOO := (A_101 < 3) AND TRUE;\nEND_PROGRAM\n")
    assert program.warnings
    kmap, _ = build_knowledge_map("PROGRAM X\nEND_PROGRAM\n")
    assert kmap.interlocks == []


def test_map_serializes_to_json():
    kmap, _ = build_knowledge_map(_read("water_plant_baseline.st"))
    text = kmap.model_dump_json()
    assert "IL-04" in text and "P-201" in text

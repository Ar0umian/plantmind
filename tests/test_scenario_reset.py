import os

os.environ["MOCK_LLM"] = "1"

from agent.engine import Engine
from plant.scenarios.scenarios import activate, deactivate
from plant.simulator.plant_model import PlantSim


def test_starting_a_scenario_resets_the_plant_to_its_nominal_state():
    sim = PlantSim(seed=3)
    for _ in range(400):
        sim.step()
    assert (round(sim.raw), round(sim.treated)) != (60, 60)          # the plant has moved on
    activate(sim, "normal")
    assert (sim.raw, sim.treated, sim.chlorine) == (60.0, 60.0, 1.5)
    assert sim.status == {"P-101": True, "P-201": False, "P-301": True}
    assert sim.variant == "baseline" and sim.scenario_name == "normal" and sim.scenario_age == 0


def test_back_to_normal_does_not_reset_the_plant():
    sim = PlantSim(seed=3)
    activate(sim, "logic_tamper")
    for _ in range(80):
        sim.step()
    raw, chlorine = sim.raw, sim.chlorine
    deactivate(sim)
    assert sim.variant == "baseline" and sim.scenario_name == "normal"
    assert (sim.raw, sim.chlorine) == (raw, chlorine)


def test_every_start_of_a_scenario_reproduces_its_incident():
    engine = Engine(interval_s=0.0)
    for run in range(4):                                             # used to fail from the third run on
        engine.start_scenario("logic_tamper")
        for _ in range(120):
            engine.step()
        alerts = engine.alerts()
        assert len(alerts) == 1 and "IL-04" in alerts[0].title, f"run {run + 1}"
    for run in range(3):
        engine.start_scenario("spoofed_reading")
        for _ in range(140):
            engine.step()
        alerts = engine.alerts()
        assert alerts and any("LT-101" in e.tags for e in alerts[0].evidence), f"spoof run {run + 1}"

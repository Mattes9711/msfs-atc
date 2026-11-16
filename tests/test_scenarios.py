"""Full-flight scenario tests: YAML scripts in tests/scenarios/, compared against golden transcripts.

A script is what you would type in text mode (transmissions and /commands, see HELP in atc/runtime.py), plus:
    - {fly_until_call: [from_nm, to_nm]}  fly 1 nm at a time and tick, like the sim loop does every second,
                                          until ATC says something
    - {comment: text}                     copied into the transcript as "# text"
Transmissions may use {squawk}, {runway}, {arrival_runway} and {heading} (a radar vector waiting for its readback),
filled in from the controller at that moment.

The transcript looks like a text-mode session. When it changes on purpose, rewrite the golden files with
    pytest tests/test_scenarios.py --update-golden
and read the diff before committing: the golden files are the reviewed record of what ATC says.
"""
import difflib
import random
from pathlib import Path

import pytest
import yaml

from atc.airport.json_data import JsonAirportData
from atc.airspace.centers import CenterSectors, parse_sector
from atc.config import ROOT
from atc.controller.controller import Controller, Response
from atc.flightplan.model import FlightPlan
from atc.events import ConsoleSink
from atc.runtime import emit_responses, handle_command
from atc.sim.fake import FakeSim
from atc.units import parse_level
from atc.weather.metar import parse_metar

SCENARIOS = Path(__file__).parent / "scenarios"
SCENARIO_KEYS = {"description", "plan", "metar", "seed", "strict_freq", "centers", "steps"}
PLAN_KEYS = {"callsign", "departure", "destination", "cruise", "route", "aircraft"}


class Transcript:
    """Collects everything a text-mode session would print. Also the SpeechOutput for ATC transmissions."""

    def __init__(self):
        self.lines: list[str] = []

    def say(self, text: str, station: str | None = None, kind: str = "atc") -> None:
        self.lines.append(f"ATC:   {text}")

    def show(self, text: str) -> None:
        self.lines.append(text)

    def emit(self, responses: list[Response]) -> None:
        emit_responses(ConsoleSink(self, self.show), responses)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def build(spec: dict, name: str) -> tuple[Controller, FakeSim]:
    if unknown := set(spec) - SCENARIO_KEYS:
        raise ValueError(f"{name}: unknown key(s) {', '.join(sorted(unknown))}")
    if unknown := set(spec["plan"]) - PLAN_KEYS:
        raise ValueError(f"{name}: unknown plan key(s) {', '.join(sorted(unknown))}")
    p = spec["plan"]
    plan = FlightPlan(callsign=p["callsign"], departure=p["departure"], destination=p.get("destination"),
                      cruise_ft=parse_level(str(p["cruise"])) if "cruise" in p else None,
                      route=p.get("route", ""), aircraft=p.get("aircraft"))
    airports = JsonAirportData(ROOT / "data" / "airports")
    origin = airports.get(plan.departure)
    destination = airports.get(plan.destination) if plan.destination else None
    metars = {icao: parse_metar(raw) for icao, raw in spec.get("metar", {}).items()}
    centers = CenterSectors([parse_sector(s, f"{name} sector {i + 1}") for i, s in enumerate(spec.get("centers", []))],
                            source=name)
    controller = Controller(origin, plan, metars.get(plan.departure), strict_freq=spec.get("strict_freq", False),
                            destination=destination, destination_metar=metars.get(plan.destination),
                            rng=random.Random(spec.get("seed", 7)), centers=centers)
    return controller, FakeSim.parked_at(origin)


def run_scenario(path: Path) -> str:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    atc, sim = build(spec, path.name)
    out = Transcript()
    out.show(f"# {path.stem}: {' '.join(spec.get('description', '').split())}")
    for step in spec["steps"]:
        if isinstance(step, dict) and "comment" in step:
            out.show(f"# {step['comment']}")
        elif isinstance(step, dict) and "fly_until_call" in step:
            start, end = step["fly_until_call"]
            for nm in range(start, end + 1):
                sim.fly(atc.airport, atc.destination, nm, atc.plan.cruise_ft)
                if responses := atc.tick(sim.read()):
                    state = sim.read()
                    out.show(f"       (flew to {nm} nm, {state.alt_msl_ft:.0f} ft)")
                    out.emit(responses)
                    break
            else:
                out.show(f"       (flew to {end} nm: no call)")
        elif isinstance(step, str):
            heading = next((i.value for i in atc.pending if i.key == "heading"), "")  # the vector just given
            text = step.format(squawk=atc.squawk, runway=atc.runway, arrival_runway=atc.arrival_runway,
                               heading=heading)
            out.show(f"PILOT> {text}")
            if text.startswith("/"):
                handle_command(text, sim, atc, ConsoleSink(out, out.show))
            else:
                out.emit(atc.handle(text, sim.read()))
            out.emit(atc.tick(sim.read()))
        else:
            raise ValueError(f"{path.name}: unknown step {step!r}")
    return out.text()


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.yaml")), ids=lambda p: p.stem)
def test_scenario(path: Path, request):
    actual = run_scenario(path)
    golden = path.with_suffix(".golden.txt")
    if request.config.getoption("--update-golden"):
        golden.write_text(actual, encoding="utf-8")
        return
    if not golden.exists():
        golden.write_text(actual, encoding="utf-8")
        pytest.fail(f"new golden file {golden.name} written: read it, then run the tests again")
    expected = golden.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(difflib.unified_diff(expected.splitlines(keepends=True), actual.splitlines(keepends=True),
                                            golden.name, "actual"))
        pytest.fail(f"transcript differs from {golden.name} (if intended: --update-golden)\n{diff}", pytrace=False)


def test_every_scenario_has_a_golden_file():
    assert {p.stem for p in SCENARIOS.glob("*.yaml")} == {p.name.removesuffix(".golden.txt")
                                                          for p in SCENARIOS.glob("*.golden.txt")}

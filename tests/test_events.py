"""Events: what the app window will get. The console rendering of the same events is covered by the golden files."""
import pytest

from atc.airport.json_data import JsonAirportData
from atc.config import ROOT, Config
from atc.events import Collector, ConsoleSink, Event
from atc.flightplan.model import FlightPlan
from atc.runtime import describe_tuning, emit_responses, handle_command, transmit
from atc.session import PlanRequest, SessionOptions, SetupError, build_session
from atc.weather.source import StaticWeather
from tests.test_air_flow import cleared_for_takeoff
from tests.test_ground_flow import GROUND, TOWER, Session


def kinds(collector):
    return [(e.kind, e.station) for e in collector.events]


def test_unknown_event_kind_is_refused():
    with pytest.raises(ValueError):
        Event("shout", "hello")


def test_console_rendering():
    spoken, lines = [], []

    class Speech:
        def say(self, text, station=None, kind="atc"):
            spoken.append(text)

    sink = ConsoleSink(Speech(), lines.append)
    for e in (Event("atc", "Lufthansa four Alfa Bravo, roger", "Hamburg Ground"), Event("pilot", "request taxi"),
              Event("understood", "understood: request_taxi"), Event("atis", "Hamburg information Alfa", "ATIS")):
        sink.emit(e)
    assert spoken == ["Lufthansa four Alfa Bravo, roger", "Hamburg information Alfa"]
    assert lines == ["       (understood: request_taxi)"]  # the pilot's own line is already on screen


def test_a_transmission_and_its_readback_as_events(eddh):
    s, log = Session(eddh), Collector()
    s.sim.update(com1_khz=GROUND)
    transmit(log, s.sim, s.atc, "Hamburg Ground, Lufthansa 4AB, request clearance information alpha")
    assert kinds(log) == [("pilot", None), ("understood", None), ("atc", "Hamburg Ground")]
    log.events.clear()
    transmit(log, s.sim, s.atc, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert kinds(log) == [("pilot", None), ("understood", None), ("readback", None), ("atc", "Hamburg Ground")]


def test_a_call_on_another_frequency_says_who_called(eddh, eddm):
    s, log = cleared_for_takeoff(eddh, eddm), Collector()
    s.sim.update(com1_khz=GROUND)
    s.sim.fly(s.atc.airport, s.atc.destination, 2, 35000)
    emit_responses(log, s.atc.tick(s.sim.read()))
    [event] = log.events
    assert (event.kind, event.station) == ("missed_call", "Hamburg Tower")


def test_tuning_names_the_station_and_plays_the_atis(eddh):
    s, log = Session(eddh), Collector()
    describe_tuning(s.atc, TOWER, log)
    describe_tuning(s.atc, 124325, log)
    assert kinds(log) == [("tuning", "Hamburg Tower"), ("tuning", "ATIS"), ("atis", "ATIS")]


def test_command_output_is_info_or_position(eddh, eddm):
    s, log = Session(eddh, destination=eddm), Collector()
    handle_command("/taxi", s.sim, s.atc, log)
    handle_command("/goto holding", s.sim, s.atc, log)
    handle_command("/fly 5", s.sim, s.atc, log)
    assert [e.kind for e in log.events] == ["info", "info", "position", "position"]
    assert log.events[-1].text.startswith("position: ")


# --- session setup (shared by console and app) --------------------------------------------------------------

AIRPORTS = [JsonAirportData(ROOT / "data" / "airports")]
WEATHER = StaticWeather({"EDDH": "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"})


def test_build_session_without_a_sim():
    session = build_session(PlanRequest(callsign="dlh4ab", departure="eddh", destination="EDDM"),
                            SessionOptions(nosim=True), Config(), weather=WEATHER, airports=AIRPORTS)
    assert session.plan == FlightPlan("DLH4AB", "EDDH", "EDDM")
    assert session.controller.runway == "23" and session.destination.ident == "EDDM"
    assert session.banner()[0].startswith("DLH4AB parked at EDDH Hamburg")


@pytest.mark.parametrize("request_, options, message", [
    (PlanRequest(departure="EDDH"), SessionOptions(nosim=True), "--callsign is required"),
    (PlanRequest(callsign="X", departure="EDDH"), SessionOptions(nosim=True, weather="sim"), "--weather sim"),
    (PlanRequest(callsign="X", departure="ZZZZ"), SessionOptions(nosim=True), "no airport data for ZZZZ"),
    (PlanRequest(callsign="X"), SessionOptions(), "MSFS is not running"),
])
def test_setup_problems_are_setup_errors(request_, options, message):
    with pytest.raises(SetupError, match=message):
        build_session(request_, options, Config(), weather=WEATHER, airports=AIRPORTS)


def test_weather_refresh_comes_from_the_session():
    session = build_session(PlanRequest(callsign="X", departure="EDDH"), SessionOptions(nosim=True), Config(),
                            weather=WEATHER, airports=AIRPORTS)
    metar, dest = session.refresh_weather()
    assert metar.raw.startswith("METAR EDDH") and dest is None

"""P3: the Apron station where the MSFS data has one (EDDM), pushback "facing", and acknowledging instructions."""
import pytest

from atc.airport.model import Frequency
from atc.flightplan.model import FlightPlan
from atc.intent.parser import parse
from atc.phraseology import spoken
from tests.test_ground_flow import confirmed
from tests.test_ground_flow import EDDM_METAR, GROUND, Session

CS = "Lufthansa four Alfa Bravo"
DELIVERY, APRON, MUNICH_GROUND = 121730, 121710, 121750


def test_apron_frequencies_are_their_own_controller():
    apron, ground = Frequency("G", "Munichapron1", 121780), Frequency("G", "Munich", 121750)
    assert (apron.role, apron.station) == ("APRON", "Munich Apron")
    assert (ground.role, ground.station) == ("G", "Munich Ground")
    assert Frequency("G", "Ramp", 122000).station == "Ramp Apron"  # no airport name in it


@pytest.fixture
def munich(eddm, eddh):
    s = Session(eddm, plan=FlightPlan("DLH4AB", "EDDM", "EDDH", cruise_ft=35000), metar=EDDM_METAR, destination=eddh)
    s.say(DELIVERY, "Munich Delivery, Lufthansa 4AB, request IFR clearance to Hamburg, information alpha")
    return s


def test_delivery_hands_over_to_apron_and_apron_does_push_and_taxi(munich):
    s = munich
    out = s.say(DELIVERY, f"runway {s.atc.runway}, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert out[-1] == f"{CS}, readback correct, contact Munich Apron one two one decimal seven one zero"
    assert confirmed(s.say(DELIVERY, "contact Munich Apron 121.710, Lufthansa 4AB"))
    [push] = s.say(APRON, "Munich Apron, Lufthansa 4AB, request push and start")
    assert push.startswith(f"{CS}, push and start approved, facing ")
    [taxi] = s.say(APRON, "Munich Apron, Lufthansa 4AB, request taxi")
    assert taxi.startswith(f"{CS}, taxi to holding point ")


def test_apron_hands_over_to_ground_when_leaving_the_apron(munich):
    s = munich
    s.say(DELIVERY, f"runway {s.atc.runway}, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(DELIVERY, "contact Munich Apron 121.710, Lufthansa 4AB")
    s.say(APRON, "Munich Apron, Lufthansa 4AB, request taxi")
    s.atc.pending = ()  # the taxi readback is tested elsewhere
    nodes = [s.atc.route_out.edges[0].a] + [e.b for e in s.atc.route_out.edges]
    for node in nodes:  # taxi along the route until ATC calls
        s.sim.update(lat=s.atc.taxi.latlon[node][0], lon=s.atc.taxi.latlon[node][1], ground_speed_kt=15)
        if out := s.tick():
            break
    assert out == [f"{CS}, contact Munich Ground one two one decimal seven fife zero"]
    assert s.atc.status()["controller"] == "Munich Ground"
    assert confirmed(s.say(APRON, "contact Munich Ground 121.750, Lufthansa 4AB"))
    assert s.say(MUNICH_GROUND, "Munich Ground, Lufthansa 4AB, with you") == [
        f"{CS}, Munich Ground, continue taxi to holding point runway {spoken.runway(s.atc.runway)}"]


def test_without_an_apron_frequency_ground_does_it_all(eddh, eddm):
    s = Session(eddh, destination=eddm)
    assert s.atc.station("apron") is None and s.atc._ground_role() == "ground"


@pytest.mark.parametrize("text", ["push and start approved, facing east, Lufthansa 4AB", "pushing back, Lufthansa 4AB",
                                  "continue taxi, Lufthansa 4AB", "continue to stand G201, Lufthansa 4AB"])
def test_acknowledging_an_instruction_without_values_is_not_say_again(eddh, text):
    # Found while building P3: "push and start approved, Lufthansa 4AB" got "say again"
    assert parse(text, "DLH4AB").kind in ("acknowledge", "readback")  # a pushback readback carries its value
    s = Session(eddh)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.say(GROUND, text) == []


def test_arrival_ground_hands_over_to_apron_at_the_apron(eddh, eddm):
    from tests.test_air_flow import cleared_for_takeoff

    s = cleared_for_takeoff(eddh, eddm)
    s.atc.phase = "vacating"  # landed: skip the flight, but keep the landing clearance for the runway
    s.atc.cleared_runways.add(s.atc._runway_key(eddm, s.atc.arrival_runway))
    s.sim.landed(eddm, eddm.runway_end(s.atc.arrival_runway))
    [taxi] = s.say(MUNICH_GROUND, "Munich Ground, Lufthansa 4AB, request taxi to the gate")
    assert taxi.startswith(f"{CS}, taxi to stand")
    s.atc.pending = ()
    stand = s.atc.stand_in
    s.sim.update(lat=stand.lat, lon=stand.lon, ground_speed_kt=10)
    assert s.tick() == [f"{CS}, contact Munich Apron one two one decimal seven one zero"]
    s.say(MUNICH_GROUND, "contact Munich Apron 121.710, Lufthansa 4AB")
    assert s.say(APRON, "Munich Apron, Lufthansa 4AB, with you") == [
        f"{CS}, Munich Apron, continue to stand {spoken.spell(stand.name)}"]

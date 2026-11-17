"""From takeoff clearance to the gate: EDDH -> EDDM with the fake sim moved along the route."""
import pytest

from atc.airport.geo import distance_nm
from atc.flightplan.route import first_fix
from atc.phraseology import spoken
from atc.weather.metar import parse_metar
from tests.test_ground_flow import confirmed
from tests.test_ground_flow import GROUND, TOWER, Session

HAMBURG_APPROACH = 118205  # EDDH has no Departure frequency, so Approach handles departures
MUNICH_APPROACH, MUNICH_TOWER, MUNICH_GROUND = 118830, 118705, 121750


@pytest.fixture
def s(eddh, eddm):
    return cleared_for_takeoff(eddh, eddm)


def cleared_for_takeoff(eddh, eddm, centers=None) -> Session:
    s = Session(eddh, destination=eddm, centers=centers)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "holding point runway 23, Lufthansa 4AB")
    s.say(TOWER, "Lufthansa 4AB, ready for departure")
    s.say(TOWER, "runway 23, cleared for takeoff, Lufthansa 4AB")
    return s


def fly(s, nm):
    s.sim.fly(s.atc.airport, s.atc.destination, nm, s.atc.plan.cruise_ft)
    return s.tick()


def test_full_flight_to_the_gate(s, eddm):
    assert s.atc.arrival_runway in ("08L", "08R")
    rwy = {"08L": "zero eight left", "08R": "zero eight right"}[s.atc.arrival_runway]

    assert fly(s, 2) == ["Lufthansa four Alfa Bravo, contact Hamburg Approach one one eight decimal two zero fife"]
    assert s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 3000 climbing 5000") == [
        "Lufthansa four Alfa Bravo, Hamburg Approach, radar contact, climb flight level tree fife zero, "
        "proceed direct Amluh"]
    assert confirmed(s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB"))

    assert fly(s, 100) == []  # cruising
    assert fly(s, s_total(s) - 110) == []  # top of descent for FL350 is 105 nm out
    [descent] = fly(s, s_total(s) - 100)
    assert descent == "Lufthansa four Alfa Bravo, descend flight level one hundred, expect ILS approach runway zero eight right"
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Lufthansa 4AB"))

    assert fly(s, s_total(s) - 35) == [
        "Lufthansa four Alfa Bravo, contact Munich Approach one one eight decimal eight tree zero"]
    [approach] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    assert approach == ("Lufthansa four Alfa Bravo, Munich Approach, descend altitude four thousand fife hundred feet, "
                        "QNH one zero one niner, speed two two zero knots, fly heading one niner zero, "
                        f"vectors ILS approach runway {rwy}")
    assert confirmed(s.say(MUNICH_APPROACH, "descend 4500 feet, QNH 1019, speed 220 knots, heading 190, Lufthansa 4AB"))
    s.sim.on_final(eddm, eddm.runway_end(s.atc.arrival_runway), 10)  # practice mode's /final 10: on the centreline
    assert s.tick() == [f"Lufthansa four Alfa Bravo, cleared ILS approach runway {rwy}, speed one eight zero knots"]
    # Read back on a 10 nm final: inside 12 nm, so the handoff to Tower comes at once
    assert s.say(MUNICH_APPROACH, f"cleared ILS runway {s.atc.arrival_runway}, speed 180 knots, Lufthansa 4AB") \
        == ["(readback correct)", "Lufthansa four Alfa Bravo, readback correct",
            "Lufthansa four Alfa Bravo, contact Munich Tower one one eight decimal seven zero fife"]
    assert s.say(MUNICH_TOWER, f"Munich Tower, Lufthansa 4AB, established ILS {s.atc.arrival_runway}") == [
        f"Lufthansa four Alfa Bravo, wind zero eight zero degrees eight knots, runway {rwy}, cleared to land"]
    assert confirmed(s.say(MUNICH_TOWER, f"cleared to land runway {s.atc.arrival_runway}, Lufthansa 4AB"))

    s.sim.landed(eddm, eddm.runway_end(s.atc.arrival_runway))
    assert s.tick() == ["Lufthansa four Alfa Bravo, vacate runway, contact Munich Ground one two one decimal "
                        "seven fife zero"]
    [taxi_in] = s.say(MUNICH_GROUND, "Munich Ground, Lufthansa 4AB, request taxi to the gate")
    assert taxi_in.startswith("Lufthansa four Alfa Bravo, taxi to stand Golf two zero one")  # a Lufthansa gate
    assert s.atc.phase == "taxi_in"


def cleared_ils(s, eddm):
    """Check in with Munich Approach, read back the vectors, then on a 10 nm final the ILS clearance."""
    rwy = s.atc.arrival_runway
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    heading = s.atc.pending[-1].value
    assert confirmed(s.say(MUNICH_APPROACH,
                           f"descend 4500 feet, QNH 1019, speed 220 knots, heading {heading}, Lufthansa 4AB"))
    s.sim.on_final(eddm, eddm.runway_end(rwy), 10)
    assert s.tick() == [f"Lufthansa four Alfa Bravo, cleared ILS approach runway {spoken.runway(rwy)}, "
                        "speed one eight zero knots"]
    assert s.say(MUNICH_APPROACH, f"cleared ILS runway {rwy}, speed 180 knots, Lufthansa 4AB")[0] == "(readback correct)"


def s_total(s):
    a, d = s.atc.airport, s.atc.destination
    return distance_nm(a.lat, a.lon, d.lat, d.lon)


def test_atc_calls_on_another_frequency_are_only_a_hint(s):
    s.sim.update(com1_khz=GROUND)  # forgot to stay on Tower
    [hint] = fly(s, 2)
    assert hint.startswith("(Hamburg Tower is calling you on 121.280: Lufthansa four Alfa Bravo, contact Hamburg")


def test_calling_the_old_controller_repeats_the_handoff(s):
    fly(s, 2)  # Tower: contact Hamburg Approach
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, passing 3000 climbing 5000") == [
        "Lufthansa four Alfa Bravo, contact Hamburg Approach one one eight decimal two zero fife"]


def test_calling_the_wrong_controller_in_the_air(s):
    fly(s, 2)
    assert s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, with you") == [
        "Lufthansa four Alfa Bravo, contact Hamburg Approach one one eight decimal two zero fife"]


def test_pilot_can_request_descent_early(s):
    fly(s, 2)
    s.say(HAMBURG_APPROACH, "Lufthansa 4AB, with you")
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    fly(s, 150)
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request descent") == [
        "Lufthansa four Alfa Bravo, descend flight level one hundred, expect ILS approach runway zero eight right"]


def test_no_new_instruction_until_the_last_one_is_read_back(s):
    fly(s, 2)
    s.say(HAMBURG_APPROACH, "Lufthansa 4AB, with you")  # radar contact + climb, not read back yet
    assert fly(s, s_total(s) - 50) == []


def test_runway_vacated_call(s, eddm):
    s.atc.phase = "landing"
    s.atc._set_pending(())
    s.sim.update(com1_khz=MUNICH_TOWER)
    assert s.say(MUNICH_TOWER, "Lufthansa 4AB, runway vacated") == [
        "Lufthansa four Alfa Bravo, vacate runway, contact Munich Ground one two one decimal seven fife zero"]


@pytest.mark.parametrize("route, fix", [
    ("AMLU2G AMLUH M852 DENIX", "AMLUH"), ("DCT DENIX M852", "DENIX"), ("M852 T703", None), ("", None),
])
def test_first_fix(route, fix):
    assert first_fix(route) == fix


EAST_WIND_EDDH = "METAR EDDH 141550Z AUTO 05015KT 9999 SCT035 07/04 Q1016 NOSIG"
WEST_WIND_EDDM = "METAR EDDM 141550Z AUTO 26015KT CAVOK 06/00 Q1015 NOSIG"


def test_new_weather_before_the_clearance_can_change_the_runway(eddh, eddm):
    session = Session(eddh, destination=eddm)
    changes = session.atc.update_weather(parse_metar(EAST_WIND_EDDH), None)
    assert session.atc.runway == "05"
    assert changes == [f"EDDH weather: {EAST_WIND_EDDH}, ATIS information B"]
    assert session.atc.update_weather(parse_metar(EAST_WIND_EDDH), None) == []  # same METAR again: nothing


def test_after_takeoff_only_the_atis_changes_but_the_arrival_runway_can(s):
    s.atc.update_weather(parse_metar(EAST_WIND_EDDH), parse_metar(WEST_WIND_EDDM))
    assert s.atc.runway == "23"  # already cleared for takeoff on 23
    assert s.atc.arrival_runway in ("26L", "26R")
    assert s.atc.destination_metar.qnh_hpa == 1015


def test_arrival_runway_is_fixed_once_cleared_for_the_approach(s):
    s.atc.phase = "approach"
    before = s.atc.arrival_runway
    [change] = s.atc.update_weather(None, parse_metar(WEST_WIND_EDDM))
    assert s.atc.arrival_runway == before and change.endswith(f"landing runway {before}")

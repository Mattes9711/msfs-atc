"""A light aircraft on an IFR flight (2026-11-21): Approach leaves it at its own speed. A C172 flies 90 to 120 knots,
so "speed two two zero knots" on the vectors or "one eight zero" on the intercept are not for it, nor the STAR's
speed limits."""
from dataclasses import replace

import pytest

from atc.controller import vectors
from atc.phraseology import spoken
from tests.test_air_flow import MUNICH_APPROACH, cleared_for_takeoff, fly, s_total
from tests.test_enroute import CS
from tests.test_ground_flow import confirmed
from tests.test_transition import between, downwind, legs, magnetic, procedures, put, qnh, with_approach


def light(s, aircraft="C172"):
    s.atc.plan = replace(s.atc.plan, aircraft=aircraft)
    return s


@pytest.mark.parametrize("aircraft, given", [("C172", False), ("DA40", False), ("P28A", False), ("A320", True),
                                             ("B738", True), (None, True)])
def test_speeds_only_for_aircraft_that_fly_them(eddh, eddm, aircraft, given):
    assert light(cleared_for_takeoff(eddh, eddm), aircraft).atc._speeds_given() is given


def test_vectors_and_the_approach_clearance_without_a_speed(eddh, eddm):
    s = light(cleared_for_takeoff(eddh, eddm))
    rwy = s.atc.arrival_runway
    fly(s, s_total(s) - 35)
    s.atc.pending, s.atc.phase = [], "arrival"
    [approach] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    assert "speed" not in approach and ", fly heading " in approach
    heading = s.atc.pending[-1].value
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 4500 feet, QNH 1019, heading {heading}, Lufthansa 4AB"))
    s.sim.on_final(eddm, eddm.runway_end(rwy), 10)
    assert s.tick() == [f"Lufthansa four Alfa Bravo, cleared ILS approach runway {spoken.runway(rwy)}"]
    assert s.say(MUNICH_APPROACH, f"cleared ILS runway {rwy}, Lufthansa 4AB")[0] == "(readback correct)"


def test_the_transition_without_its_speed_limit_and_the_intercept_without_a_speed(eddh, eddm):
    s = light(with_approach(eddh, eddm, procedures(eddm)))
    fixes = legs(s)
    end = eddm.runway_end("08R")
    put(s, eddm, *between(fixes["LANDU"], fixes["DT001"]), 160, 10000)
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, flight level 100")
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 6000 feet, QNH {qnh(s).value}, Lufthansa 4AB"))
    put(s, eddm, *between(fixes["DT001"], fixes["DT002"], 0.3), 200, 8000)
    assert s.tick() == []  # DT002's 220 kt: nothing to say to a C172
    put(s, eddm, *between(fixes["DT002"], fixes["DT003"], 0.3), 260, 6000)
    assert s.tick() == [f"{CS}, descend altitude fife thousand feet"]
    assert confirmed(s.say(MUNICH_APPROACH, "descend 5000 feet, Lufthansa 4AB"))
    assert downwind(s, eddm, 4, 50) == [] and downwind(s, eddm, 9, 100) == []
    intercept = magnetic(eddm, end.heading_true + 30)
    assert downwind(s, eddm, vectors.BASE_ALONG_NM - vectors.BASE_TURN_LEAD_NM + 0.2, 150) == [
        f"{CS}, turn left heading {spoken.heading(intercept)}, maintain fife thousand feet until established, "
        "cleared ILS approach runway zero eight right"]

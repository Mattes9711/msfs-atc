"""Found by the flight emulator's runs against the checklist (2026-11-19), each with its test here.

A field without Approach (EDDW, EDDN): the Tower vectored the aircraft and then handed it to itself, the flight
waited for a check-in that never came and was sent around; after the go-around nobody vectored it again. A short
flight was told to "descend" to an altitude above it. Approach handed over to Tower 12 nm out while the aircraft was
still turning onto the final, and the vectors corrected the heading seconds before the base turn (the zigzag test is
in tests/test_vectors.py).
"""
from dataclasses import replace

from atc.controller.controller import Controller
from atc.controller.suggest import suggestion
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_TOWER, cleared_for_takeoff
from tests.test_emulator import fly
from tests.test_vectors import CS, arriving, at, check_in


def without_approach(eddm):
    return replace(eddm, frequencies=tuple(f for f in eddm.frequencies if f.role != "A"))


def read_back(s):
    s.atc.state = s.sim.read()
    offer = suggestion(s.atc)
    return s.say(offer["khz"], offer["text"])


def test_a_field_without_approach_gate_to_gate(eddh, eddm):
    report = fly(eddh, without_approach(eddm))
    assert report.finished, report.text()
    assert not report.findings, report.text()
    assert "go around" not in report.text()


def test_the_tower_without_approach_clears_to_land_instead_of_handing_to_itself(eddh, eddm):
    field = without_approach(eddm)
    s = cleared_for_takeoff(eddh, field)
    s.sim.fly(eddh, field, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Lufthansa 4AB, with you")
    s.say(HAMBURG_APPROACH, "climb flight level 350, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    end = field.runway_end(s.atc.arrival_runway)
    s.sim.on_final(field, end, 10)
    [cleared] = s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, descending flight level 100")
    assert "cleared ILS approach runway" in cleared
    after = read_back(s)
    assert not any("contact" in x for x in after)
    assert any(x.endswith("cleared to land") for x in after), after

    # The go-around: no "contact Approach", and the Tower vectors again by itself once 1500 ft above the field
    at(s, field, 0.5, 0, end.heading_true, alt=field.elevation_ft + 300)  # going around half a mile out
    [missed] = s.say(MUNICH_TOWER, "Going around, Lufthansa 4AB")
    assert "contact" not in missed and "climb altitude" in missed
    at(s, field, -3, 0, end.heading_true, alt=field.elevation_ft + 1000)  # past the far end, climbing
    assert read_back(s)[0] == "(readback correct)"
    assert s.tick() == []
    at(s, field, -4, 0, end.heading_true, alt=field.elevation_ft + 1600)
    [vectors] = s.tick()
    assert vectors.startswith(f"{CS}, Munich Tower, climb altitude ") and " heading " in vectors
    assert "vectors ILS approach" in vectors and s.atc.vectoring is not None
    assert s.tick() == []  # once


def test_climb_or_descend_by_where_the_aircraft_is(eddh):
    state = parked_state(eddh)
    assert Controller._verb(5000, replace(state, alt_msl_ft=3000)) == "climb"
    assert Controller._verb(5000, replace(state, alt_msl_ft=4900)) == "descend"  # at it: no climb for 100 ft
    assert Controller._verb(5000, replace(state, alt_msl_ft=12000)) == "descend"


def parked_state(airport):
    from atc.sim.fake import FakeSim
    return FakeSim.parked_at(airport).read()


def cleared_on_base(eddh, eddm):
    """Vectored, then cleared on the base leg 12 nm out, 2 nm beside the centreline, with an intercept heading."""
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 0, 8, (end.heading_true + 180) % 360)
    check_in(s, eddm)
    at(s, eddm, 12, 5, (end.heading_true + 180) % 360)
    s.tick(now=100)  # the base turn
    read_back(s)
    at(s, eddm, 12, 2, (end.heading_true + 90) % 360)
    [cleared] = s.tick(now=200)
    assert "cleared ILS approach runway" in cleared
    read_back(s)
    return s, end


def tower(texts):
    return [x for x in texts if "contact Munich Tower" in x]


def test_tower_only_once_established(eddh, eddm):
    s, end = cleared_on_base(eddh, eddm)
    at(s, eddm, 11, 1.2, end.heading_true + 30)  # 11 nm out, still turning onto the final
    assert tower(s.tick(now=230)) == []
    at(s, eddm, 10.5, 0.1, end.heading_true)  # on the centreline
    assert tower(s.tick(now=260)) != []


def test_tower_at_8_nm_at_the_latest(eddh, eddm):
    s, end = cleared_on_base(eddh, eddm)
    at(s, eddm, 7.5, 1, end.heading_true + 30)
    assert tower(s.tick(now=300)) != []


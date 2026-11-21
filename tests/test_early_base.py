"""The base turn on the transition's downwind as soon as it is due (emulator, 2026-11-21): Munich 08's LANDU
transition runs on its downwind to DM420, 23 nm out, and only there the vectors begin; the aircraft flew 6 minutes
at 5000 ft past the base turn. Approach turns it in at the base turn, later when it is still high."""
from atc.airport.procedures import Leg, Procedure, Procedures, Transition
from atc.controller import vectors
from atc.phraseology import spoken
from tests.test_air_flow import MUNICH_APPROACH
from tests.test_enroute import CS
from tests.test_ground_flow import confirmed
from tests.test_transition import LANDU, qnh, with_approach
from tests.test_vectors import at, magnetic

ACROSS = 6.5  # the downwind's distance beside the centreline, like Munich's


def long_downwind(eddm):
    """LANDU, DW001 abeam the field, DW002 23 nm out on the downwind, then on its course until vectored."""
    end = eddm.runway_end("08R")
    outbound = round((end.heading_true + 180 - eddm.mag_var) % 360)

    def fix(ident, along, across, path="TF", alt=None, alt_ft=None, course=None):
        return Leg(ident, *vectors.point(end, along, across), path, alt, alt_ft, course=course)

    landu = Leg("LANDU", LANDU.lat, LANDU.lon, "IF", "at_or_below", 10000, speed_kt=250)
    star = Procedure("LAND2A", "star", "08R", (landu,))
    transition = Transition("LANDU", (
        Leg("LANDU", LANDU.lat, LANDU.lon, "IF"), fix("DW001", 0, ACROSS, alt="at_or_above", alt_ft=5000),
        fix("DW002", 23, ACROSS, alt="at_or_above", alt_ft=5000),
        fix("DW002", 23, ACROSS, "FM", course=outbound)))
    ils = Procedure("I08R", "approach", "08R", (fix("FAFXX", 10, 0, "IF", "at", 5000),), (transition,), "ILS")
    return Procedures("EDDM", (star,), (ils,))


def on_the_downwind(eddh, eddm):
    s = with_approach(eddh, eddm, long_downwind(eddm))
    end = eddm.runway_end("08R")
    at(s, eddm, -3, ACROSS + 1, (end.heading_true + 160) % 360, alt=7000)  # nearly at DW001
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    assert s.atc.transition_legs and s.atc.vectoring is None
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 5000 feet, QNH {qnh(s).value}, Lufthansa 4AB"))
    return s, end


def test_the_base_turn_before_the_downwinds_last_fix(eddh, eddm):
    s, end = on_the_downwind(eddh, eddm)
    outbound = (end.heading_true + 180) % 360
    at(s, eddm, 1, ACROSS, outbound, alt=5000)
    assert s.tick(now=10) == [] and s.atc.transition_legs  # DW001 passed, on the downwind
    at(s, eddm, 8, ACROSS, outbound, alt=5000)
    assert s.tick(now=60) == []
    at(s, eddm, vectors.BASE_ALONG_NM - vectors.BASE_TURN_LEAD_NM + 0.2, ACROSS, outbound, alt=5000)
    base = magnetic(eddm, end.heading_true + 90)
    assert s.tick(now=120) == [f"{CS}, turn left heading {spoken.heading(base)}"]
    assert s.atc.transition_legs is None and s.atc.vector_leg == "base"
    assert confirmed(s.say(MUNICH_APPROACH, f"heading {base}, Lufthansa 4AB"))
    at(s, eddm, vectors.BASE_ALONG_NM, 2, (end.heading_true + 90) % 360, alt=5000)
    [cleared] = s.tick(now=200)
    assert "cleared ILS approach runway zero eight right" in cleared


def test_still_high_the_base_turn_later(eddh, eddm):
    """At 9000 ft (7500 ft above the field) the base leg and the final must be 3 x 7.5 + 4 = 26.5 nm: the base turn
    about 20 nm out, not 13."""
    s, end = on_the_downwind(eddh, eddm)
    outbound = (end.heading_true + 180) % 360
    at(s, eddm, 1, ACROSS, outbound, alt=9000)
    s.tick(now=10)
    at(s, eddm, vectors.BASE_ALONG_NM - vectors.BASE_TURN_LEAD_NM + 0.2, ACROSS, outbound, alt=9000)
    assert s.tick(now=60) == [] and s.atc.transition_legs
    height = 9000 - eddm.elevation_ft
    due = vectors.energy_along_nm(height, ACROSS) - vectors.BASE_TURN_LEAD_NM
    assert 18 < due < 21
    at(s, eddm, due + 0.2, ACROSS, outbound, alt=9000)
    [turn] = s.tick(now=70)
    assert turn.startswith(f"{CS}, turn left heading ")


def test_the_downwinds_last_fix_close_to_the_base_turn_flown(eddh, eddm):
    """Its last fix only a little farther out than the base turn: flown to it, the vectors from there."""
    s, end = on_the_downwind(eddh, eddm)
    outbound = (end.heading_true + 180) % 360
    at(s, eddm, 1, ACROSS, outbound, alt=12000)  # so high the base turn would be 25 nm out
    s.tick(now=10)
    at(s, eddm, 19, ACROSS, outbound, alt=12000)  # 4 nm before the fix: still on the transition
    assert s.tick(now=60) == [] and s.atc.transition_legs

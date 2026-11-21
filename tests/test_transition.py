"""Milestone 10 E: the approach transition flown by the pilot and followed by Approach, the vectors at its end.

Munich-like procedures built in code around runway 08R (made up, like Munich's ILS 26R, transition LANDU): from
LANDU to the left downwind, vectors from its last fix; the approach from DX002 (12 nm out) with the FAF at 5000 ft."""
from types import SimpleNamespace

from atc.airport.procedures import Leg, Procedure, Procedures, Transition
from atc.controller import readback as rb
from atc.controller import vectors
from atc.controller.arrival import plan_arrival
from atc.phraseology import spoken
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH
from tests.test_arrival import descending
from tests.test_enroute import CS, SIMBRIEF
from tests.test_ground_flow import confirmed
from tests.test_vectors import at, magnetic

LANDU = next(w for w in SIMBRIEF.waypoints if w.ident == "LANDU")


def procedures(eddm, vectors_transition=True):
    end = eddm.runway_end("08R")
    downwind = round((end.heading_true + 180 - eddm.mag_var) % 360)

    def fix(ident, along, across, path="TF", alt=None, alt_ft=None, speed=None, course=None):
        return Leg(ident, *vectors.point(end, along, across), path, alt, alt_ft, speed_kt=speed, course=course)

    landu = Leg("LANDU", LANDU.lat, LANDU.lon, "IF", "at_or_below", 10000, speed_kt=250)
    star = Procedure("LAND2A", "star", "08R", (landu, fix("OSCAR", 20, 8, alt="at_or_above", alt_ft=6000)))
    to_downwind = Transition("LANDU", (
        Leg("LANDU", LANDU.lat, LANDU.lon, "IF"), fix("DT001", -8, 9),
        fix("DT002", -3, 4, alt="at_or_above", alt_ft=6000, speed=220),
        fix("DT003", 2, 4, "FM", "at_or_above", 5000, course=downwind),
        fix("DX002", 12, 0, "CF", "at_or_above", 5000)))
    oscar = Transition("OSCAR", (fix("OSCAR", 20, 8, "IF"), fix("DX002", 12, 0, "TF", "at_or_above", 5000)))
    ils = Procedure("I08R", "approach", "08R", (fix("DX002", 12, 0, "IF"), fix("FAFXX", 10, 0, alt="at", alt_ft=5000)),
                    (to_downwind, oscar) if vectors_transition else (oscar,), "ILS")
    return Procedures("EDDM", (star,), (ils,))


def between(a, b, f=0.5):
    return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f


def put(s, eddm, lat, lon, heading_true, alt):
    s.sim.update(lat=lat, lon=lon, alt_msl_ft=alt, alt_agl_ft=alt - eddm.elevation_ft, on_ground=False,
                 ground_speed_kt=250, heading_mag=(heading_true - eddm.mag_var) % 360)


def with_approach(eddh, eddm, p):
    s, _ = descending(eddh, eddm, procedures=p)
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB"))
    s.atc.phase = "arrival"  # handed over to Approach
    return s


def legs(s):
    return {leg.ident: leg for leg in s.atc.arrival.transition.legs}


def qnh(s):
    return rb.qnh(s.atc.destination_metar.qnh_hpa)


def downwind(s, eddm, along, now):
    end = eddm.runway_end("08R")
    at(s, eddm, along, 4, (end.heading_true + 180) % 360, alt=5000)
    return s.tick(now=now)


def test_the_transition_with_vectors_is_chosen(eddm):
    a = plan_arrival(eddm, "08R", SIMBRIEF, procedures(eddm))
    assert a.transition.name == "LANDU"  # not OSCAR, the STAR's last fix: its transition has no vectors
    assert plan_arrival(eddm, "08R", SIMBRIEF, procedures(eddm, False)).transition.name == "OSCAR"


def test_fly_the_transition_with_altitudes_speeds_and_vectors_at_its_end(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    fixes = legs(s)
    end = eddm.runway_end("08R")
    put(s, eddm, *between(fixes["LANDU"], fixes["DT001"]), 160, 10000)
    assert s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, flight level 100") == [
        f"{CS}, Munich Approach, descend altitude six thousand feet, {qnh(s).phrase}, cleared transition Landu, "
        "expect ILS approach runway zero eight right"]
    assert s.atc.vectoring is None and s.atc.transition_legs
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 6000 feet, QNH {qnh(s).value}, Lufthansa 4AB"))
    # DT001 passed, DT002 with its 220 kt close ahead
    put(s, eddm, *between(fixes["DT001"], fixes["DT002"], 0.3), 200, 8000)
    assert s.tick() == [f"{CS}, reduce speed two two zero knots"]
    assert confirmed(s.say(MUNICH_APPROACH, "speed 220 knots, Lufthansa 4AB"))
    assert s.tick() == []
    # DT002 passed (at or above 6000): down to the FAF's 5000 ft for DT003
    put(s, eddm, *between(fixes["DT002"], fixes["DT003"], 0.3), 260, 6000)
    assert s.tick() == [f"{CS}, descend altitude fife thousand feet"]
    assert confirmed(s.say(MUNICH_APPROACH, "descend 5000 feet, Lufthansa 4AB"))
    # DT003 passed: the vectors from there, on the downwind no heading
    assert downwind(s, eddm, 4, 50) == [] and s.atc.vectoring is not None and s.atc.vector_leg == "downwind"
    assert downwind(s, eddm, 9, 100) == []
    # The transition's downwind is 4 nm beside the centreline: no base leg (gone in the turn, K9), the intercept
    # heading and the clearance at once
    intercept = magnetic(eddm, end.heading_true + 30)
    [cleared] = downwind(s, eddm, vectors.base_along_nm(s.atc._join_nm()) - vectors.BASE_TURN_LEAD_NM + 0.2, 150)
    assert cleared == (f"{CS}, turn left heading {spoken.heading(intercept)}, maintain fife thousand feet until "
                       "established, cleared ILS approach runway zero eight right, speed one eight zero knots")


def test_traffic_ahead_makes_the_downwind_longer(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    fixes = legs(s)
    put(s, eddm, *between(fixes["DT002"], fixes["DT003"], 0.5), 260, 5000)
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, 5000 feet")
    s.atc.pending = []
    assert downwind(s, eddm, 4, 50) == [] and s.atc.vector_leg == "downwind"
    ahead = SimpleNamespace(model="A320", title="", object_id=7, callsign="EWG12", airline="Eurowings")
    s.atc._ahead_in_sequence = lambda state: [(18.0, ahead, "final")]  # 18 track miles to go
    assert downwind(s, eddm, 15.2, 100) == []  # 3 nm behind it: base at 18 nm, not 14
    [cleared] = downwind(s, eddm, 17.2, 150)
    assert ", turn left heading " in cleared and "cleared ILS approach runway" in cleared


def test_far_off_the_transition_radar_vectors(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    end = eddm.runway_end("08R")
    at(s, eddm, 0, -15, (end.heading_true + 180) % 360, alt=8000)  # south of the field, the transition is north
    [call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, 8000 feet")
    assert "transition" not in call and ", vectors ILS approach runway zero eight right" in call
    assert s.atc.vectoring is not None


def test_leaving_the_transition_brings_vectors(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    fixes = legs(s)
    put(s, eddm, *between(fixes["LANDU"], fixes["DT001"]), 160, 10000)
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, flight level 100")
    s.atc.pending = []
    lat, lon = between(fixes["LANDU"], fixes["DT001"], 0.7)
    put(s, eddm, lat - 0.2, lon - 0.1, 200, 9000)  # 12 nm south-west of it
    [call] = s.tick()
    assert call.startswith(f"{CS}, turn ") and call.endswith(", vectors ILS approach runway zero eight right")
    assert s.atc.transition_legs is None and s.atc.vectoring is not None


def test_a_transition_without_vectors_ends_in_the_approach_clearance(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm, vectors_transition=False))
    oscar, dx002 = legs(s)["OSCAR"], legs(s)["DX002"]
    put(s, eddm, *between(oscar, dx002, 0.1), 240, 7000)  # OSCAR (at or above 6000) passed: down to the FAF's 5000
    [call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, 7000 feet")
    assert call == (f"{CS}, Munich Approach, descend altitude fife thousand feet, {qnh(s).phrase}, cleared transition "
                    "Oscar, expect ILS approach runway zero eight right")
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 5000 feet, QNH {qnh(s).value}, Lufthansa 4AB"))
    put(s, eddm, *between(oscar, dx002, 0.2), 240, 6000)
    assert s.tick() == []  # more than 8 nm before DX002
    put(s, eddm, *between(oscar, dx002, 0.7), 240, 5000)
    assert s.tick() == [f"{CS}, cleared ILS approach runway zero eight right"]
    assert s.atc.approach_cleared

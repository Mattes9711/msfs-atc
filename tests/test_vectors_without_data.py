"""Milestone 10 F: better radar vectors without procedure data, and only after the STAR's last fix.

The 2026-11-17 flight was turned in at 45 degrees from 20 NM beside the final and met the localizer near the
threshold. Now: a 30-degree intercept only when it meets the centreline 8 NM out or farther, else the base point
first (a downwind, or from far beside in front a long base). Without a transition the plan's STAR (SimBrief:
LANDU, MIQ) is followed to its last fix before the vectors."""
from atc.airport.geo import bearing_deg
from atc.controller import vectors
from tests.test_air_flow import MUNICH_APPROACH
from tests.test_enroute import CS, SIMBRIEF
from tests.test_ground_flow import confirmed
from tests.test_transition import between, put, qnh, with_approach
from tests.test_vectors import arriving, at, check_in, magnetic

MIQ = next(w for w in SIMBRIEF.waypoints if w.ident == "MIQ")
LANDU = next(w for w in SIMBRIEF.waypoints if w.ident == "LANDU")


def test_near_the_final_a_30_degree_intercept_and_no_turn_with_the_clearance(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 25, -6, end.heading_true)  # 25 nm out, 6 nm right: meets the centreline 14.6 nm out
    _, heading = check_in(s, eddm)
    assert s.atc.vector_leg == "base" and heading == magnetic(eddm, end.heading_true - 30)
    at(s, eddm, 17, -2, end.heading_true - 30)  # flying the intercept heading
    [cleared] = s.tick(now=100)
    assert "turn" not in cleared and cleared.startswith(f"{CS}, maintain ")
    assert "until established, cleared ILS approach runway" in cleared


def test_far_beside_in_front_the_base_point_first_not_45_degrees(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 25, 20, end.heading_true)  # 20 nm to the left: 45 degrees would meet the final near the threshold
    _, heading = check_in(s, eddm)
    base = vectors.point(end, vectors.BASE_ALONG_NM, vectors.DOWNWIND_NM)
    assert s.atc.vector_leg == "downwind" and heading != magnetic(eddm, end.heading_true + 45)
    lat, lon = vectors.point(end, 25, 20)
    assert heading == magnetic(eddm, bearing_deg(lat, lon, *base))
    track = (heading + eddm.mag_var) % 360
    at(s, eddm, 16, 9, track)  # on the way in: no base turn yet, though farther out than the base point
    assert s.tick(now=100) == []
    at(s, eddm, 12.5, 5.5, track)  # at the base point: base at right angles
    base_heading = magnetic(eddm, end.heading_true + 90)
    assert s.tick(now=200) == [f"{CS}, turn right heading " + spoken_heading(base_heading)]
    assert confirmed(s.say(MUNICH_APPROACH, f"right heading {base_heading:03d}, Lufthansa 4AB"))
    at(s, eddm, 12, 2, end.heading_true + 90)
    [cleared] = s.tick(now=260)
    assert "heading" in cleared and "cleared ILS approach runway" in cleared  # 30 degrees on, 8 nm out


def test_the_plans_star_is_followed_to_its_last_fix_then_vectors(eddh, eddm):
    s = with_approach(eddh, eddm, None)  # no procedure data: the plan's STAR points LANDU, MIQ
    put(s, eddm, *between(LANDU, MIQ, 0.4), 90, 10000)
    assert s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, flight level 100") == [
        f"{CS}, Munich Approach, descend altitude four thousand fife hundred feet, {qnh(s).phrase}, expect vectors "
        "ILS approach runway zero eight right"]
    assert s.atc.vectoring is None and s.atc.transition_star
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 4500 feet, QNH {qnh(s).value}, Lufthansa 4AB"))
    put(s, eddm, *between(LANDU, MIQ, 0.8), 90, 7000)
    assert s.tick() == []  # still on the STAR: no heading
    lat, lon = between(LANDU, MIQ, 1.05)  # MIQ passed, 14 nm beside the final abeam the threshold
    put(s, eddm, lat, lon, 90, 5000)
    [call] = s.tick()
    assert call.startswith(f"{CS}, turn ") and call.endswith(", reduce speed two two zero knots")
    assert s.atc.vectoring is not None and s.atc.vector_leg == "downwind"


def test_off_the_star_at_check_in_vectors_at_once(eddh, eddm):
    s = with_approach(eddh, eddm, None)
    at(s, eddm, 0, -15, eddm.runway_end("08R").heading_true, alt=8000)  # south of the field, the STAR is north
    [call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, 8000 feet")
    assert ", vectors ILS approach runway zero eight right" in call and "expect vectors" not in call


def spoken_heading(degrees):
    from atc.phraseology import spoken

    return spoken.heading(degrees)

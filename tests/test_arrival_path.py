"""The way in along the arrival's transition (the user's flight 2026-11-21 to Munich: the descent was planned on a
straight-in, Approach then gave heading 220 instead of the transition). The descent is measured along the transition
that will be flown; Approach takes the aircraft onto it while it still flies to the first fix."""
from atc.airport.geo import destination_point, distance_nm
from atc.controller import vectors
from atc.controller.transition import path_legs
from atc.flightplan.track import track_to_go_nm
from tests.test_air_flow import MUNICH_APPROACH
from tests.test_enroute import CS
from tests.test_no_direct import at
from tests.test_transition import LANDU, procedures, put, qnh, with_approach
from tests.test_arrival import cruising


def test_the_descent_is_planned_along_the_transition(eddh, eddm):
    """At VESIX before LANDU: the route to LANDU, the transition's legs, the vectors from its last fix."""
    s = cruising(eddh, eddm, "VESIX")
    s.atc.procedures, s.atc.arrival_runway = procedures(eddm), "08R"
    state = at(s, "VESIX")
    end = eddm.runway_end("08R")
    legs = path_legs(s.atc._expected_arrival())
    assert legs[0].ident == "LANDU" and legs[-1].vectors
    dest = (eddm.lat, eddm.lon)
    to_landu = (track_to_go_nm(s.atc.plan.waypoints, dest, state.lat, state.lon)
                - track_to_go_nm(s.atc.plan.waypoints, dest, LANDU.lat, LANDU.lon))
    along = sum(distance_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(legs, legs[1:]))
    expected = to_landu + along + vectors.path_nm(end, legs[-1].lat, legs[-1].lon, s.atc._join_nm())
    assert abs(s.atc._path_to_go_nm(state) - expected) < 0.1


def test_without_procedures_the_way_vectors_would_fly(eddh, eddm):
    s = cruising(eddh, eddm, "VESIX")
    s.atc.procedures, s.atc.arrival_runway = None, "08R"
    state = at(s, "VESIX")
    assert s.atc._path_to_go_nm(state) <= vectors.path_nm(eddm.runway_end("08R"), state.lat, state.lon)


def before_landu(s, eddm, nm, heading_off=0):
    """nm before LANDU on the way from VESIX, heading for it (heading_off degrees beside)."""
    vesix = next(w for w in s.atc.plan.waypoints if w.ident == "VESIX")
    from atc.airport.geo import bearing_deg
    inbound = bearing_deg(vesix.lat, vesix.lon, LANDU.lat, LANDU.lon)
    lat, lon = destination_point(LANDU.lat, LANDU.lon, (inbound + 180) % 360, nm)
    put(s, eddm, lat, lon, inbound + heading_off, 18000)


def test_handed_over_before_the_first_fix_and_flying_to_it(eddh, eddm):
    """The emulator's flight: 16 nm before LANDU at FL180, flying to it: the transition, not vectors."""
    s = with_approach(eddh, eddm, procedures(eddm))
    before_landu(s, eddm, 16)
    assert s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100") == [
        f"{CS}, Munich Approach, descend altitude six thousand feet, {qnh(s).phrase}, cleared transition Landu, "
        "expect ILS approach runway zero eight right"]
    assert s.atc.vectoring is None and s.atc.transition_legs


def test_before_the_first_fix_but_flying_away_from_it_vectors(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    before_landu(s, eddm, 16, heading_off=90)
    [call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    assert "cleared transition" not in call and ", fly heading " in call

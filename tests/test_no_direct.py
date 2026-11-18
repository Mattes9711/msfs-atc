"""Milestone 10 C: no direct-to off the arrival route. Center's shortcut only en route: before the descent, never
past the STAR's first fix, and only when the track left still reaches to the top of descent. The pilot's "request
direct" after the descent only to a fix ahead on the arrival cleared."""
from dataclasses import replace

from atc.airspace.centers import CenterSectors
from atc.flightplan.model import Waypoint
from tests.test_arrival import PROCEDURES, descending
from tests.test_enroute import CS, SIMBRIEF, with_departure
from tests.test_air_flow import HAMBURG_APPROACH
from tests.test_ground_flow import confirmed


def at(s, ident, plan=SIMBRIEF):
    w = next(w for w in plan.waypoints if w.ident == ident)
    s.sim.update(lat=w.lat, lon=w.lon, alt_msl_ft=35000, alt_agl_ft=33500, on_ground=False, ground_speed_kt=450)
    return s.sim.read()


def en_route(eddh, eddm, plan=SIMBRIEF):
    s = with_departure(eddh, eddm, plan=plan, sectors=CenterSectors())
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    return s


def test_no_shortcut_that_cuts_away_the_top_of_descent(eddh, eddm):
    """At ALOSO a direct to LANDU leaves 170 nm to fly: given while the descent starts later than that, not when it
    would have to start before (the test flight: "direct Landu" cut the top of descent away)."""
    s = en_route(eddh, eddm)
    state = at(s, "ALOSO")
    s.atc._top_of_descent_nm = lambda state: 165
    assert s.atc._shortcut(state) == "LANDU"
    s.atc.shortcuts = 0
    s.atc._top_of_descent_nm = lambda state: 175
    assert s.atc._shortcut(state) != "LANDU"


def test_no_shortcut_after_the_descent(eddh, eddm):
    s = en_route(eddh, eddm)
    state = at(s, "ALOSO")
    s.atc.descent_given = True
    assert s.atc._shortcut(state) is None


def test_no_shortcut_past_the_stars_first_fix(eddh, eddm):
    """A plan whose STAR points came in as route points: nothing after LANDU, where LAND2A starts."""
    points = [replace(w, leg="route") for w in SIMBRIEF.waypoints]
    plan = replace(SIMBRIEF, waypoints=tuple(points))
    s = en_route(eddh, eddm, plan)
    s.atc.procedures = PROCEDURES
    state = at(s, "ABERU", plan)
    ahead = [w.ident for w in s.atc._en_route_ahead(state)]
    assert ahead[-1] == "LANDU" and "MIQ" not in ahead
    assert s.atc._shortcut(state) != "MIQ"


def test_before_the_descent_direct_only_up_to_the_arrival(eddh, eddm):
    s = en_route(eddh, eddm)
    at(s, "ABERU")
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Miq") == [
        f"{CS}, unable direct Miq, not ahead on your route"]
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Landu") == [f"{CS}, proceed direct Landu"]


def test_on_the_arrival_direct_only_to_a_fix_ahead_on_it(eddh, eddm):
    """Cleared LAND2B for 26R: its fixes and the transition to the ILS, not the route points before it."""
    s, _ = descending(eddh, eddm, "26R")
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2B arrival, Lufthansa 4AB"))
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Vesix") == [
        f"{CS}, unable direct Vesix, not ahead on your arrival"]
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Miq") == [  # the filed STAR's, not the cleared
        f"{CS}, unable direct Miq, not ahead on your arrival"]
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Mikey") == [f"{CS}, proceed direct Mikey"]


def test_on_the_arrival_without_procedures_the_plans_star(eddh, eddm):
    s, _ = descending(eddh, eddm, procedures=None)
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB"))
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Miq") == [f"{CS}, proceed direct Miq"]
    assert confirmed(s.say(HAMBURG_APPROACH, "direct Miq, Lufthansa 4AB"))
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Vesix") == [
        f"{CS}, unable direct Vesix, not ahead on your arrival"]

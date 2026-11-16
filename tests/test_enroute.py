"""P5b: step climb (Departure up to FL240, Center the rest), Center's direct-to along the SimBrief route, and the
pilot's requests for a level or a direct-to."""
from dataclasses import replace

import pytest

from atc.config import ROOT
from atc.flightplan.simbrief import parse_simbrief
from atc.intent.parser import parse
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff
from tests.test_centers import NORTH, SECTORS, fly, next_call

CS = "Lufthansa four Alfa Bravo"
SIMBRIEF = replace(parse_simbrief((ROOT / "tests" / "fixtures" / "simbrief_sample.xml").read_bytes()),
                   callsign="DLH4AB")


def with_departure(eddh, eddm, plan=SIMBRIEF, sectors=SECTORS):
    s = cleared_for_takeoff(eddh, eddm, centers=sectors)
    s.atc.plan = plan
    fly(s, 2)
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    return s


def test_center_gives_the_rest_of_the_climb_and_a_shortcut_only_when_it_is_one(eddh, eddm):
    s = with_departure(eddh, eddm)
    assert s.atc.pending[0].value == 240  # Departure: FL240 at most
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    next_call(s, 3, 60)  # handed to North Radar
    [check_in] = s.say(NORTH, "North Radar, Lufthansa 4AB, with you, climbing flight level 240")
    # On the straight line to Munich (the fake sim flies it) a direct would save next to nothing (A2)
    assert check_in == f"{CS}, North Radar, identified, climb flight level tree fife zero"


def detour_plan():
    """The test flight's route with a long dogleg east before ZUCKA, so a direct to ZUCKA is a real shortcut."""
    from atc.flightplan.model import Waypoint

    points = list(SIMBRIEF.waypoints)
    i = next(i for i, w in enumerate(points) if w.ident == "ZUCKA")
    points.insert(i, Waypoint("DOGLG", 52.6, 12.5, "route"))
    return replace(SIMBRIEF, waypoints=tuple(points))


def test_a_real_shortcut_is_given_but_never_twice(eddh, eddm):
    s = with_departure(eddh, eddm, plan=detour_plan())
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    next_call(s, 3, 60)
    [check_in] = s.say(NORTH, "North Radar, Lufthansa 4AB, with you, climbing flight level 240")
    assert ", proceed direct " in check_in
    fix = s.atc.pending[-1].value
    assert fix in {w.ident for w in SIMBRIEF.route_points()} and fix != "DOGLG"
    assert confirmed(s.say(NORTH, f"climb flight level 350, direct {fix}, Lufthansa 4AB"))
    assert s.atc._shortcut(s.sim.read()) is None  # the same fix again: no


def test_at_most_two_shortcuts_a_flight(eddh, eddm):
    s = with_departure(eddh, eddm, plan=detour_plan())
    s.atc.shortcuts = 2
    assert s.atc._shortcut(s.sim.read()) is None


def test_the_descent_after_a_direct_to(eddh, eddm):
    """The test flight: Frankfurt cleared direct Landu, and the descent never came: the track miles still went via
    the points the direct skips (A1)."""
    from atc.airport.geo import bearing_deg, destination_point, distance_nm
    from atc.airspace.centers import CenterSectors
    from atc.flightplan.track import track_to_go_nm

    s = with_departure(eddh, eddm, sectors=CenterSectors())
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    landu = next(w for w in SIMBRIEF.waypoints if w.ident == "LANDU")
    aberu = next(w for w in SIMBRIEF.waypoints if w.ident == "ABERU")  # the route bends east via LULAR from here
    munich = (eddm.lat, eddm.lon)
    tod = s.atc._top_of_descent_nm(s.sim.read())
    # Direct from ABERU to LANDU, cutting the bend: where the direct way is 1 nm short of the top of descent
    after_landu = track_to_go_nm(SIMBRIEF.waypoints, munich, landu.lat, landu.lon)
    out = tod - 1 - after_landu
    lat, lon = destination_point(landu.lat, landu.lon, bearing_deg(landu.lat, landu.lon, aberu.lat, aberu.lon), out)
    s.sim.update(lat=lat, lon=lon, alt_msl_ft=35000, alt_agl_ft=33500, on_ground=False, ground_speed_kt=450)
    assert track_to_go_nm(SIMBRIEF.waypoints, munich, lat, lon) > tod  # the old way: still far from the TOD
    s.atc.direct_fix = "LANDU"
    assert s.tick()[0].startswith(f"{CS}, descend flight level one hundred")
    assert distance_nm(lat, lon, *munich) < out + after_landu


def test_no_instruction_before_the_check_in(eddh, eddm):
    """Right after a handoff the next controller waits for the check-in before it instructs (A3)."""
    s = with_departure(eddh, eddm)
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    next_call(s, 3, 60)  # "contact North Radar"
    s.say(HAMBURG_APPROACH, "contact North Radar 123.450, Lufthansa 4AB")
    assert s.atc.call_next is not None
    s.atc.descent_given = False
    s.atc._top_of_descent_nm = lambda state: 10_000  # as if far past the top of descent
    assert s.tick() == []  # nothing from North Radar until the pilot has called it


def test_a_missing_direct_to_in_the_readback_is_asked_for(eddh, eddm):
    s = with_departure(eddh, eddm)
    assert s.say(HAMBURG_APPROACH, "climb flight level 240, Lufthansa 4AB") == [f"{CS}, read back direct-to"]


@pytest.mark.parametrize("call, answer", [
    ("request higher", "climb flight level tree fife zero"),
    ("request flight level 370", "climb flight level tree seven zero"),
    ("request flight level 200", "descend flight level two hundred"),  # ICAO says hundreds as "hundred"
    ("request flight level 450", "unable flight level four fife zero, maximum flight level four one zero"),
])
def test_level_requests(eddh, eddm, call, answer):
    s = with_departure(eddh, eddm)
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    s.sim.fly(eddh, eddm, 40, 24000)
    s.sim.update(alt_msl_ft=24000)  # level at FL240
    assert parse(f"Lufthansa 4AB, {call}", "DLH4AB").kind == "request_level"
    assert s.say(HAMBURG_APPROACH, f"Hamburg Approach, Lufthansa 4AB, {call}")[0] == f"{CS}, {answer}"


def test_direct_to_a_waypoint_ahead_but_not_behind(eddh, eddm):
    s = with_departure(eddh, eddm)
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    s.sim.fly(eddh, eddm, 15, 24000)
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Lular") == [f"{CS}, proceed direct Lular"]
    assert confirmed(s.say(HAMBURG_APPROACH, "direct Lular, Lufthansa 4AB"))
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Paris") == [
        f"{CS}, unable direct Paris, not ahead on your route"]


def test_a_manual_plan_without_positions_accepts_fixes_written_in_the_route(eddh, eddm):
    from tests.test_ground_flow import PLAN
    s = with_departure(eddh, eddm, plan=PLAN)
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request direct Denix") == [f"{CS}, proceed direct Denix"]


def test_the_descent_brings_the_star(eddh, eddm):
    from atc.airspace.centers import CenterSectors
    from tests.test_air_flow import s_total
    s = with_departure(eddh, eddm, sectors=CenterSectors())  # no sectors: Departure keeps us to the top of descent
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    nm, calls = next_call(s, 3, int(s_total(s)))
    assert calls == [f"{CS}, descend flight level one hundred, cleared Landu two Alfa arrival"]
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB"))

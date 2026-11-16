"""The descent at the right point (2026-11-16): just before SimBrief's top of descent, measured along the route.

Before, it came at 105 nm in a straight line from Munich; the STAR leads around the field, so that was about
45 nm (6 to 7 minutes) too early."""
from dataclasses import replace

from atc.airport.geo import distance_nm
from atc.airspace.centers import CenterSectors
from atc.flightplan.model import Waypoint
from atc.flightplan.track import track_to_go_nm
from tests.test_air_flow import HAMBURG_APPROACH
from tests.test_enroute import CS, SIMBRIEF, with_departure

MUNICH = (48.353783, 11.786086)


def point(ident):
    return next(w for w in SIMBRIEF.waypoints if w.ident == ident)


def test_simbriefs_top_of_descent_is_read():
    assert SIMBRIEF.tod == (49.162465, 12.61392)


def test_track_miles_follow_the_route_not_the_straight_line():
    a, b, c = Waypoint("A", 50.0, 10.0, "route"), Waypoint("B", 50.0, 11.0, "route"), Waypoint("C", 49.0, 11.0, "star")
    dest = (49.0, 10.0)  # the route goes east, south, then back west: a U around the destination
    on_ab = track_to_go_nm((a, b, c), dest, 50.0, 10.5)
    assert 117 < on_ab < 121  # 19 nm to B, 60 down to C, 39 back west: not the 60 nm straight down
    assert track_to_go_nm((), dest, 50.0, 10.0) == distance_nm(50.0, 10.0, *dest)  # no route: straight there
    tod = track_to_go_nm(SIMBRIEF.waypoints, MUNICH, *SIMBRIEF.tod)
    assert 75 < tod < 82  # along the STAR; 59 nm in a straight line


def cruising(eddh, eddm, at, alt_ft=35000):
    s = with_departure(eddh, eddm, sectors=CenterSectors())  # Departure keeps us to the top of descent
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    w = point(at)
    s.sim.update(lat=w.lat, lon=w.lon, alt_msl_ft=alt_ft, alt_agl_ft=alt_ft - 1500, ground_speed_kt=450)
    return s


def test_no_descent_well_before_the_top_of_descent(eddh, eddm):
    s = cruising(eddh, eddm, "LULAR")  # 72 nm from Munich in a straight line, 13 nm before the TOD on the route
    assert not any("descend" in call for call in s.tick())


def test_the_descent_just_before_the_top_of_descent(eddh, eddm):
    s = cruising(eddh, eddm, "EXUSI")  # 4 nm before the TOD
    assert s.tick() == [f"{CS}, descend flight level one hundred, cleared Landu two Alfa arrival"]


def test_cruising_higher_than_planned_starts_down_earlier(eddh, eddm):
    s = cruising(eddh, eddm, "LULAR", alt_ft=39000)  # 4000 ft higher: 12 nm earlier
    assert s.tick()[0].startswith(f"{CS}, descend flight level one hundred")


def test_without_simbriefs_point_the_three_in_one_rule(eddh, eddm):
    s = cruising(eddh, eddm, "LULAR")
    s.atc.plan = replace(SIMBRIEF, tod=None)  # e.g. a plan from another source
    # 3 nm per 1000 ft from FL350 down to 5000 ft, plus 15 nm: 105 nm along the route; LULAR is 92 nm to go
    assert s.tick()[0].startswith(f"{CS}, descend flight level one hundred")

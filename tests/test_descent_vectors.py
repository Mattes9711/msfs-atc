"""The descent before a STAR that loops around the field (the user's flight to EDDH, 2026-11-18).

NOLG3P leads past Hamburg, about 30 nm north-east and back. SimBrief's top of descent, measured along it, came 48 nm
from the field in a straight line at FL320; Approach then vectored straight in and the aircraft was still at FL220
12 nm out. Now the descent is measured on the way Approach really leaves: at most VECTOR_ALLOWANCE_NM more than
straight to the field. Here the same in Munich: the route to LANDU, then a loop 45 nm north-east and back to MIQ,
with SimBrief's top of descent at LANDU (84 track miles out, 24 nm straight). And the co-pilot offers
"request descent" when the descent point is near, so the pilot is never left with "nothing to call".
"""
from dataclasses import replace

from atc.airport.geo import destination_point
from atc.controller.suggest import suggestion
from tests.test_descent import MUNICH, cruising, point
from tests.test_enroute import CS, SIMBRIEF

DESCENT = f"{CS}, descend flight level one hundred, cleared Landu two Alfa arrival, expect ILS approach runway zero eight right"


def looping_plan():
    waypoints = list(SIMBRIEF.waypoints)
    i = next(i for i, w in enumerate(waypoints) if w.ident == "LANDU")
    lat, lon = destination_point(*MUNICH, 60, 45)  # 45 nm north-east of the field
    loop = replace(waypoints[i], ident="LOOPX", lat=lat, lon=lon)
    landu = point("LANDU")
    return replace(SIMBRIEF, waypoints=(*waypoints[:i + 1], loop, *waypoints[i + 1:]), tod=(landu.lat, landu.lon))


def looping(eddh, eddm, at):
    s = cruising(eddh, eddm, at)
    s.atc.plan = looping_plan()
    return s


def test_the_descent_comes_before_the_loop_not_on_it(eddh, eddm):
    """LULAR: 72 nm straight, 134 track miles. Counted along the loop the descent came only near LANDU, 24 nm from
    the field at FL300."""
    s = looping(eddh, eddm, "LULAR")
    assert s.atc._track_to_go_nm(s.sim.read()) > s.atc._top_of_descent_nm(s.sim.read()) + 40  # the old way: far off
    assert s.tick() == [DESCENT]


def test_but_not_far_too_early(eddh, eddm):
    s = looping(eddh, eddm, "ARMUT")  # 85 nm straight
    assert s.tick() == []


def test_without_a_loop_the_track_miles_still_count(eddh, eddm):
    """The plain LAND2A goes almost straight in: its track miles are less than straight + the allowance at LULAR,
    so the descent still comes only shortly before SimBrief's top of descent (tests/test_descent.py)."""
    s = cruising(eddh, eddm, "LULAR")
    state = s.sim.read()
    assert s.atc._path_to_go_nm(state) < s.atc._track_to_go_nm(state)
    assert s.tick() == []


def test_the_co_pilot_offers_request_descent_when_the_point_is_near(eddh, eddm):
    s = looping(eddh, eddm, "ABERU")  # 30 nm before the descent point
    s.atc.state = s.sim.read()
    assert suggestion(s.atc) is None
    s = looping(eddh, eddm, "ARMUT")  # 11 nm before it
    s.atc.state = s.sim.read()
    offer = suggestion(s.atc)
    assert (offer["title"], offer["text"]) == ("Request descent", "Hamburg Approach, Lufthansa 4AB, request descent")
    assert s.say(offer["khz"], offer["text"]) == [DESCENT]
    s.atc.state = s.sim.read()
    assert suggestion(s.atc)["title"] == "Read back"

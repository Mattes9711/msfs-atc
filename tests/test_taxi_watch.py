"""Later version 27: Ground watches the taxiing aircraft: off the cleared route, too fast, progressive taxi. And B5's
last piece: the caution behind a heavier aircraft that has just landed on our runway."""
from dataclasses import replace

from atc.airport.model import Frequency
from atc.airport.taxi import TaxiGraph
from atc.controller import taxi_watch
from atc.flightplan.model import FlightPlan
from atc.intent.parser import parse
from atc.weather.metar import parse_metar
from tests.test_ground_flow import TOWER, Session, confirmed
from tests.test_runway_traffic import at_holding_point
from tests.test_safety import midpoint, rwy_05_23
from tests.test_taxi import ll, route_from_gate, simple_airport
from tests.test_tower import WIND
from tests.test_traffic_picture import on_final

CS = "Lufthansa four Alfa Bravo"
GROUND = 121900
CLEARANCE = "taxi to holding point Alfa fife runway two seven, via Alfa"


def taxi_airport():
    """Runway 09/27; the gate's lead-in joins A, which doglegs north of the straight B and C to A5 (tests/test_taxi)."""
    return replace(simple_airport(), frequencies=(Frequency("G", "Test", GROUND), Frequency("T", "Test", 118500)))


def cleared(progressive=False) -> Session:
    s = Session(taxi_airport(), plan=FlightPlan("DLH4AB", "TEST"), metar=parse_metar("TEST 141450Z 27010KT 9999 Q1013"))
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 27, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    request = "request progressive taxi" if progressive else "request taxi"
    assert s.say(GROUND, f"Lufthansa 4AB, {request}") == [f"{CS}, {CLEARANCE}"]
    assert confirmed(s.say(GROUND, "taxi to holding point alpha 5 runway 27 via alpha, Lufthansa 4AB"))
    return s


def at(s, x, y, gs=15.0):
    lat, lon = ll(x, y)
    s.sim.update(lat=lat, lon=lon, ground_speed_kt=gs)
    return s.tick()


def test_off_the_cleared_route_gets_where_it_is_and_a_new_route():
    s = cleared()
    assert at(s, 1100, 150) == []  # on A, where it starts its dogleg
    assert at(s, 1400, 150) == [f"{CS}, you appear to be on Bravo, new route, "
                                "taxi to holding point Alfa fife runway two seven, via Charlie"]
    assert confirmed(s.say(GROUND, "taxi to holding point alpha 5 runway 27 via charlie, Lufthansa 4AB"))
    assert s.atc.route_out.taxiways == ["C", "A5"]
    assert at(s, 1700, 150) == []  # on the new route


def test_leaving_the_stand_towards_the_route_is_not_off_it():
    s = cleared()
    s.atc.route_joined = False  # as right after the clearance, before the aircraft has reached its route
    s.atc.route_start_off_m = 70  # cleared 70 m beside it (pushed back elsewhere)
    assert at(s, 1100, 300) == []  # 100 m off it, but never on it yet and not much farther than at the start


def test_turning_away_before_ever_joining_the_route_is_off_it():
    """Milestone 8, C4: a wrong turn right after the pushback got no reaction: the watch began only once the
    aircraft had been on its route."""
    s = cleared()
    s.atc.route_joined, s.atc.route_start_off_m = False, None  # as right after a clearance given after the pushback
    assert at(s, 1000, 440, gs=0) == []  # pushed back 40 m beside the lead-in, not yet on the route
    [call] = at(s, 1000, 520)  # and now taxiing away from it
    assert call.startswith(f"{CS}, you are off your cleared route, new route, taxi to holding point")


def test_near_the_holding_point_and_on_the_runway_nobody_reroutes():
    s = cleared()
    at(s, 1100, 150)
    assert at(s, 2030, 110) == []  # beside the holding point
    assert "new route" not in " ".join(at(s, 1800, 0))  # on the runway: the incursion check's job


def test_too_fast_gets_reduce_taxi_speed_once_until_slower_again():
    s = cleared()
    assert at(s, 1100, 150, gs=35) == [f"{CS}, reduce taxi speed"]
    assert at(s, 1150, 160, gs=35) == []
    assert at(s, 1200, 170, gs=15) == []
    assert at(s, 1250, 180, gs=35) == [f"{CS}, reduce taxi speed"]


def test_progressive_taxi_calls_each_turn_before_it():
    s = cleared(progressive=True)
    assert at(s, 1000, 400) == []  # at the gate, the turn onto A 250 m ahead
    assert at(s, 1000, 250) == [f"{CS}, turn left onto Alfa"]
    assert at(s, 1000, 220) == []  # once
    assert at(s, 1600, 230) == []  # A5 still 400 m away
    assert at(s, 1900, 170) == [f"{CS}, turn right onto Alfa fife"]


def test_progressive_taxi_asked_for_while_taxiing():
    s = cleared()
    assert at(s, 1000, 250) == []
    assert s.say(GROUND, "Lufthansa 4AB, request progressive taxi") == [
        f"{CS}, roger, progressive taxi, I will call your turns", f"{CS}, turn left onto Alfa"]  # it is close


def test_without_progressive_taxi_no_turns():
    s = cleared()
    assert at(s, 1000, 250) == []


def test_the_request_is_understood():
    intent = parse("Test Ground, Lufthansa 4AB, request progressive taxi", "DLH4AB")
    assert intent.kind == "request_taxi" and intent.items.get("progressive")


def test_next_turn_and_its_direction():
    a = simple_airport()
    graph, route = TaxiGraph(a), route_from_gate(a, "27")
    index, name, direction = taxi_watch.next_turn(graph, route, *ll(1000, 400))
    assert (name, direction) == ("A", "left") and route.edges[index].name == "A"
    assert taxi_watch.next_turn(graph, route, *ll(1600, 230))[1:] == ("A5", "right")
    assert taxi_watch.taxiway_at(graph, *ll(1400, 150)) == "B"
    assert taxi_watch.taxiway_at(graph, *ll(1000, 300)) is None  # the gate's lead-in line


# --- B5: behind a heavier landing ---------------------------------------------------------------------------


def landed_heavy(s, eddh, now):
    arrival = replace(on_final(eddh, "23", 2, oid=9), model="B77W", atc_id="UAE4LK", airline="Emirates", flight_number="")
    s.atc.update_traffic([arrival], now=now)
    s.atc.update_traffic([replace(arrival, lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1],
                                  on_ground=True, ground_speed_kt=60)], now=now + 30)  # landed
    gate = eddh.default_parking()
    s.atc.update_traffic([replace(arrival, lat=gate.lat, lon=gate.lon, on_ground=True, ground_speed_kt=15)],
                         now=now + 60)  # vacated


def test_takeoff_behind_a_heavier_landing_gets_the_caution(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    landed_heavy(s, eddh, 0)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, caution wake turbulence from the landing Emirates Boeing, {WIND}, runway two tree, cleared for takeoff"]


def test_long_after_the_landing_no_caution(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    landed_heavy(s, eddh, 0)
    s.atc.update_traffic([], now=400)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def test_behind_a_medium_landing_no_caution(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    arrival = on_final(eddh, "23", 2)
    s.atc.update_traffic([arrival], now=0)
    s.atc.update_traffic([replace(arrival, lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1],
                                  on_ground=True, ground_speed_kt=60)], now=30)
    s.atc.update_traffic([replace(arrival, lat=0.0, lon=0.0)], now=60)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, {WIND}, runway two tree, cleared for takeoff"]

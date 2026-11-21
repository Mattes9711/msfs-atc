"""L4: while we taxi, ATC moves us around traffic on our route (LiveTraffic never gives way)."""
import math
from dataclasses import replace

from atc.airport.geo import M_PER_DEG_LAT
from atc.controller.give_way import path_ahead, route_points
from tests.test_ground_flow import GROUND, TOWER, Session
from tests.test_traffic_picture import plane

CS = "Lufthansa four Alfa Bravo"


def taxiing(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha")
    s.say(GROUND, f"cleared to Munich, Amluh 2G, runway 23, climb 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "taxi to holding point A3 runway 23, Lufthansa 4AB")
    assert s.atc.phase == "taxi" and s.atc.route_out is not None
    return s


def on_route(s, ahead_m, sideways_m, heading_offset):
    """An aircraft ahead_m along our route ahead, sideways_m to the right of it, heading our way of travel there
    plus heading_offset degrees."""
    graph, me = s.atc.taxi, s.sim.read()
    path = path_ahead(route_points(graph, s.atc.route_out), graph.proj.xy(me.lat, me.lon), ahead_m)
    (x1, y1), (x2, y2) = path[-2], path[-1]
    along = math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360
    right = math.radians(along + 90)
    x, y = x2 + sideways_m * math.sin(right), y2 + sideways_m * math.cos(right)
    lat = graph.proj.lat0 + y / M_PER_DEG_LAT
    lon = graph.proj.lon0 + x / graph.proj.m_per_deg_lon
    return plane(lat, lon, gs=15, hdg=(along + heading_offset) % 360)


def test_traffic_crossing_ahead_gets_a_give_way(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.atc.update_traffic([on_route(s, 150, 120, -90)])  # on our right, heading across to our left
    assert s.tick() == [f"{CS}, give way to the Lufthansa Airbus crossing right to left"]
    assert s.tick() == []  # said once
    assert s.say(GROUND, "giving way to the Airbus, Lufthansa 4AB") == []  # an acknowledgement


def test_traffic_ahead_going_our_way_is_followed(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.atc.update_traffic([on_route(s, 120, 0, 0)])
    assert s.tick() == [f"{CS}, follow the Lufthansa Airbus"]


def test_traffic_coming_towards_us_holds_us_until_it_is_clear(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.atc.update_traffic([on_route(s, 150, 0, 180)])
    assert s.tick() == [f"{CS}, hold position, the Lufthansa Airbus coming towards you"]
    s.atc.update_traffic([on_route(s, 100, 0, 180)])
    assert s.tick() == []  # still coming
    s.atc.update_traffic([replace(on_route(s, 100, 0, 180), lat=0.0, lon=0.0)])  # turned off and gone
    assert s.tick() == [f"{CS}, continue taxi"]
    assert s.tick() == []


def test_traffic_far_ahead_is_left_alone(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.atc.update_traffic([on_route(s, 290, 0, 0)])  # going our way, but far ahead
    assert s.tick() == []


def test_a_standing_aircraft_in_the_way_holds_us_until_it_is_gone(eddh, eddm):
    """B2: LiveTraffic stops where its real flight stopped, also on our taxiway."""
    s = taxiing(eddh, eddm)
    s.atc.update_traffic([replace(on_route(s, 150, 0, 180), ground_speed_kt=0)])
    assert s.tick() == [f"{CS}, hold position, the Lufthansa Airbus stopped ahead"]
    assert s.tick() == []  # still there
    s.atc.update_traffic([])
    assert s.tick() == [f"{CS}, continue taxi"]


def test_a_standing_aircraft_pointing_our_way_is_followed(eddh, eddm):
    s = taxiing(eddh, eddm)  # e.g. the queue at the holding point
    s.atc.update_traffic([replace(on_route(s, 120, 0, 0), ground_speed_kt=0)])
    assert s.tick() == [f"{CS}, follow the Lufthansa Airbus"]


def test_an_aircraft_at_a_stand_is_parked_not_in_the_way(eddh):
    from atc.controller.controller import Controller

    stand = eddh.default_parking()
    assert Controller._at_stand(eddh, plane(stand.lat, stand.lon))
    assert not Controller._at_stand(eddh, plane(stand.lat + 0.003, stand.lon))


def test_missed_on_another_frequency(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.sim.update(com1_khz=TOWER)
    s.atc.update_traffic([on_route(s, 150, 120, -90)])
    [missed] = s.tick()
    assert missed.startswith("(Hamburg Ground is calling you")

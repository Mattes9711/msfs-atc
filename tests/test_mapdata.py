"""A6: the data the app's map draws."""
import json

from atc.airspace.centers import CenterSectors
from tests.test_app import PLAN, get, post, server  # noqa: F401 (the server fixture)
from tests.test_centers import box
from tests.test_enroute import SIMBRIEF
from tests.test_ground_flow import Session
from tests.test_traffic_picture import plane
from atc.controller.mapdata import map_data, moving


def test_airports_route_and_only_the_sectors_near_it(eddh, eddm):
    near, far = box("Bremen Radar", "EDWW", 125100, 52, 55), box("Far Radar", "XXXX", 120000, 30, 31)
    s = Session(eddh, plan=SIMBRIEF, destination=eddm, centers=CenterSectors([near, far]))
    data = map_data(s.atc)
    assert [a["ident"] for a in data["airports"]] == ["EDDH", "EDDM"]
    runway = data["airports"][0]["runways"][0]
    assert len(data["airports"][0]["runways"]) == 2 and len(runway["ends"]) == 2 and runway["names"] == ["05", "23"]
    assert data["route"][0]["ident"] == "DH250" and data["route"][-1]["ident"] == "MIQ"
    assert [x["name"] for x in data["sectors"]] == ["Bremen Radar"] and data["sectors"][0]["khz"] == 125100
    json.dumps(data)  # the page gets it as JSON


def test_moving_parts_come_with_the_status(eddh):
    s = Session(eddh)
    s.tick()
    s.atc.update_traffic([plane(53.6, 10.0, oid=3)])
    m = s.atc.status()["map"]
    assert m["own"]["lat"] == s.sim.read().lat and 0 <= m["own"]["heading"] < 360
    assert m["traffic"] == [{"callsign": "Lufthansa 123", "lat": 53.6, "lon": 10.0, "heading": 0.0, "alt_ft": 60,
                             "on_ground": True, "gs": 0.0}]
    assert moving(Session(eddh).atc)["own"] is None  # before the first tick


def test_the_map_endpoint(server):  # noqa: F811
    app, base = server
    assert json.loads(get(base + "/api/map")[2]) is None  # no flight
    post(base + "/api/start", PLAN)
    data = json.loads(get(base + "/api/map")[2])
    assert data["airports"][0]["ident"] == "EDDH" and data["route"] == []  # a manual plan has no waypoints


def test_taxiways_carry_the_names_atc_uses(eddh):
    s = Session(eddh)
    ways = map_data(s.atc)["airports"][0]["taxiways"]
    named = {w[4] for w in ways if w[4]}
    raw_named = sum(1 for t in eddh.taxi_paths if t.name)
    assert len(ways) >= len(eddh.taxi_paths) - 5  # every segment once (a few short ones may merge)
    assert sum(1 for w in ways if w[4]) > raw_named  # names carried along the taxiways
    assert {"A1", "B1"} <= named and any(w[5] for w in ways)  # lead-ins to stands are marked


def test_the_taxi_route_is_shown_while_taxiing(eddh):
    from tests.test_ground_flow import GROUND
    s = Session(eddh)
    s.tick()
    assert moving(s.atc)["taxi_route"] == []
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    route = moving(s.atc)["taxi_route"]
    assert len(route) == len(s.atc.route_out.edges) + 1 and len(route[0]) == 2
    assert moving(s.atc)["own"]["on_ground"] is True

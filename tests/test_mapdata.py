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
                             "on_ground": True, "gs": 0.0, "type": "A320", "reg": "D-AIZA"}]
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


def test_the_band_lists_frequencies_as_a_chart_does():
    from atc.airport.model import Frequency
    from atc.controller.mapdata import band
    freqs = (Frequency("T", "Hamburg", 121280), Frequency("A", "Hamburg", 118205), Frequency("ATIS", "Hamburg", 124325),
             Frequency("G", "Hamburg", 121705), Frequency("G", "HAMBURGAPRON", 121755),
             Frequency("C", "Hamburg", 121805), Frequency("T", "Hamburg", 121280), Frequency("XX", "Odd", 130000))
    assert [(f["label"], f["khz"]) for f in band(freqs)] == [
        ("ATIS", 124325), ("DEL", 121805), ("APRON", 121755), ("GND", 121705), ("TWR", 121280), ("APP", 118205),
        ("XX", 130000)]  # in the order of use on departure, each once, unknown types last
    assert band(freqs)[4]["station"] == "Hamburg Tower" and band(freqs)[0]["station"] == "Hamburg"


def test_the_flights_airports_come_as_a_taxi_chart(eddh):
    s = Session(eddh)
    chart = map_data(s.atc)["airports"][0]
    assert chart["elevation_ft"] == round(eddh.elevation_ft) and chart["frequencies"][0]["label"] == "ATIS"
    assert chart["runways"][0]["length_ft"] > 0 and all(1 <= h <= 360 for h in chart["runways"][0]["headings_mag"])
    assert len(chart["surfaces"]) == len(eddh.taxi_paths) and all(w[4] > 5 for w in chart["surfaces"])
    assert chart["holds"] and all(0 <= h[2] < 360 for h in chart["holds"])  # a bar across the taxiway each
    assert chart["aprons"] == [[list(p) for p in a] for a in eddh.aprons]


def test_the_area_around_the_camera(tmp_path, eddh, eddm):
    from atc.airport.json_data import JsonAirportData
    from atc.controller.mapdata import area
    source = JsonAirportData(tmp_path)
    source.save(eddh)
    source.save(eddm)
    near = box("Bremen Radar", "EDWW", 125100, 52, 55)
    data = area([source], CenterSectors([near]), 53, 9, 54, 11)
    [hamburg] = data["airports"]  # Munich is outside the box
    assert hamburg["ident"] == "EDDH" and hamburg["controlled"] and hamburg["longest_ft"] > 10000
    assert {"TWR", "GND"} <= {f["label"] for f in hamburg["frequencies"]} and len(hamburg["runways"]) == 2
    assert [z["name"] for z in data["zones"]] == [eddh.control_zone.name]
    assert [s["name"] for s in data["sectors"]] == ["Bremen Radar"]
    wide = area([source], CenterSectors([near]), 40, 0, 60, 20)
    assert [a["ident"] for a in wide["airports"]] == ["EDDM", "EDDH"]  # the longest runway first
    assert wide["zones"] == []  # too wide a view for control zones
    json.dumps(data)


def test_the_area_and_chart_endpoints_work_without_a_flight(server):  # noqa: F811
    from tests.test_app import BROWSER
    import urllib.error
    import urllib.request
    app, base = server
    app.map_centers = CenterSectors()
    data = json.loads(get(base + "/api/map/area?s=53&w=9&n=54&e=11")[2])
    assert [a["ident"] for a in data["airports"]] == ["EDDH"]
    chart = json.loads(get(base + "/api/map/airport?ident=eddm")[2])
    assert chart["ident"] == "EDDM" and chart["taxiways"] and chart["holds"]
    assert json.loads(get(base + "/api/map/airport?ident=ZZZZ")[2]) is None
    try:
        urllib.request.urlopen(urllib.request.Request(base + "/api/map/area?s=53&w=9", headers=BROWSER), timeout=5)
        raise AssertionError("a box without north and east is refused")
    except urllib.error.HTTPError as e:
        assert e.code == 400

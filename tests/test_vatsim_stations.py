"""The real roles of the German airports' frequencies from the VATGER datahub (atc/airport/vatsim_stations.py).

The sim's EDDH has three Grounds and two Towers; with the datahub's roles 121.805 is Delivery ("Hamburg Ground"),
121.705 and 121.980 the Aprons East and West, 126.855 the Tower and 121.280 the VFR Tower.
"""
import json
from dataclasses import replace

import pytest

from atc.airport import vatsim_stations
from atc.airport.model import AirportSummary, Frequency
from atc.config import ROOT, Config
from atc.controller.common import frequency_list
from atc.flightplan.model import FlightPlan
from atc.session import airport_sources
from tests.test_ground_flow import PLAN, Session, confirmed

CS = "Lufthansa four Alfa Bravo"
DELIVERY, APRON_E, APRON_W, TOWER, VFR_TOWER = 121805, 121705, 121980, 126855, 121280
STATIONS = vatsim_stations.load(ROOT / "data" / "stations_vatsim.json")


@pytest.fixture
def hamburg(eddh):
    """EDDH as the app loads it: with the datahub's roles."""
    return replace(eddh, frequencies=vatsim_stations.apply(eddh.frequencies, STATIONS["EDDH"]))


def test_a_sim_frequency_gets_the_role_of_the_datahub_position_on_it():
    entries = {121805: {"khz": 121805, "role": "C", "word": "Ground", "qualifier": ""},
               121705: {"khz": 121705, "role": "APRON", "word": "Apron", "qualifier": "E"},
               121280: {"khz": 121280, "role": "T", "word": "Tower", "qualifier": "VFR"},
               124325: {"khz": 124325, "role": "T", "word": "Tower", "qualifier": ""}}
    frequencies = (Frequency("G", "Hamburg", 121805), Frequency("G", "Hamburg", 121705),
                   Frequency("T", "Hamburg", 121280), Frequency("ATIS", "Hamburg", 124325),
                   Frequency("G", "Hamburg", 121900))
    delivery, apron, vfr, atis, other = vatsim_stations.apply(frequencies, entries)
    assert (delivery.role, delivery.station) == ("C", "Hamburg Ground")
    assert (apron.role, apron.station, apron.qualifier) == ("APRON", "Hamburg Apron", "E")
    assert (vfr.role, vfr.station, vfr.qualifier) == ("T", "Hamburg Tower", "VFR")
    assert atis == frequencies[3] and other == frequencies[4]  # ATIS stays ATIS; one the datahub lacks stays as it is
    assert vatsim_stations.apply(frequencies, None) == frequencies  # outside Germany nothing changes


def test_the_sim_name_of_an_apron_gives_the_place():
    f = vatsim_stations.apply((Frequency("G", "MUNICHAPRON1", 121780),),
                              {121780: {"role": "APRON", "word": "Apron", "qualifier": "1"}})[0]
    assert f.station == "Munich Apron"


def test_a_missing_or_broken_file_means_the_sims_own_roles(tmp_path):
    assert vatsim_stations.load(tmp_path / "missing.json") == {}
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert vatsim_stations.load(tmp_path / "broken.json") == {}


class Source:
    name = "test"

    def __init__(self, airport):
        self.airport = airport

    def get(self, ident):
        return self.airport if ident == self.airport.ident else None

    def in_area(self, south, west, north, east, limit):
        return [AirportSummary.of(self.airport)]

    def procedures(self, ident):
        return "procedures"


def test_the_source_gives_airports_and_the_map_area_with_the_roles(eddh):
    source = vatsim_stations.WithStations(Source(eddh), STATIONS)
    assert source.name == "test" and source.procedures("EDDH") == "procedures"  # the rest is the source's own
    assert source.get("EDDH").frequency_at(DELIVERY).role == "C"
    assert source.in_area(53, 9, 54, 10, 10)[0].frequencies == source.get("EDDH").frequencies
    assert source.get("EDDM") is None


def test_the_app_loads_the_shipped_roles(tmp_path):
    sources = airport_sources(Config(littlenavmap_db=tmp_path / "none.sqlite", airports_dir=tmp_path))
    assert all(isinstance(s, vatsim_stations.WithStations) for s in sources)


def test_hamburg_delivery_apron_and_tower(hamburg, eddm):
    atc = Session(hamburg, destination=eddm).atc
    assert (atc.station("clearance").freq.khz, atc.station("clearance").name) == (DELIVERY, "Hamburg Ground")
    assert atc.station("apron").freq.khz == atc.station("ground").freq.khz == APRON_E  # no Ground: Apron taxis
    assert atc.station("tower").freq.khz == TOWER  # not the VFR Tower
    assert frequency_list(hamburg) == ("Hamburg Ground 121.805 | Hamburg Apron 121.705, 121.980 | "
                                       "Hamburg Tower (VFR) 121.280 | Hamburg Tower 126.855 | "
                                       "Hamburg Approach 118.205 | ATIS 124.325")


def test_a_vfr_flight_gets_the_vfr_tower(hamburg):
    plan = FlightPlan(callsign="DEABC", departure="EDDH", destination="EDHL", rules="VFR")
    atc = Session(hamburg, plan=plan).atc
    tower = atc.station("tower")
    assert tower.freq.khz == VFR_TOWER and tower.key != Session(hamburg).atc.station("tower").key


def test_delivery_hands_over_to_apron_and_apron_to_the_tower(hamburg, eddm):
    s = Session(hamburg, plan=replace(PLAN, route=""), destination=eddm)
    s.say(DELIVERY, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha")
    out = s.say(DELIVERY, f"runway {s.atc.runway}, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert out[-1] == f"{CS}, readback correct, contact Hamburg Apron one two one decimal seven zero fife"
    assert confirmed(s.say(DELIVERY, "contact Hamburg Apron 121.705, Lufthansa 4AB"))
    [taxi] = s.say(APRON_E, "Hamburg Apron, Lufthansa 4AB, request taxi")
    assert taxi.startswith(f"{CS}, taxi to holding point ")
    s.atc.pending = ()  # the taxi readback is tested elsewhere
    calls = []
    for edge in s.atc.route_out.edges:  # taxi along the route: no Apron -> Ground handoff, the Tower at the end
        s.sim.update(lat=s.atc.taxi.latlon[edge.b][0], lon=s.atc.taxi.latlon[edge.b][1], ground_speed_kt=15)
        calls += [c for c in s.tick() if "contact" in c]
        s.atc.pending = ()
    assert calls == [f"{CS}, contact Hamburg Tower one two six decimal eight fife fife"]


def test_the_shipped_file_has_no_frequency_twice_at_an_airport():
    data = json.loads((ROOT / "data" / "stations_vatsim.json").read_text(encoding="utf-8"))
    for ident, entries in data["airports"].items():
        assert len({e["khz"] for e in entries}) == len(entries), ident


def test_the_map_and_the_panel_name_the_part_of_the_field(hamburg, eddm):
    from atc.controller.mapdata import band
    from atc.controller.panel import airport_panel

    labels = [(f["label"], f["khz"]) for f in band(hamburg.frequencies)]
    assert labels[:6] == [("ATIS", 124325), ("DEL", DELIVERY), ("APRON E", APRON_E), ("APRON W", APRON_W),
                          ("TWR VFR", VFR_TOWER), ("TWR", TOWER)]
    panel = [(f["label"], f["khz"]) for f in airport_panel(Session(hamburg, destination=eddm).atc)["frequencies"]]
    assert panel == [("ATIS", 124325), ("DEL", DELIVERY), ("APRON E", APRON_E), ("TWR", TOWER), ("APP", 118205)]

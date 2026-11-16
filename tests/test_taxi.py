import math

from atc.airport.model import Airport, Parking, Runway, RunwayEnd, TaxiPath
from atc.airport.taxi import Edge, TaxiGraph, TaxiRoute, propagate_names
from atc.phraseology.taxi import holding_point, taxi_clearance

LAT0, LON0 = 50.0, 8.0


def ll(x: float, y: float) -> tuple[float, float]:
    """Metres east/north of the reference point -> lat/lon."""
    return LAT0 + y / 111_195, LON0 + x / (111_195 * math.cos(math.radians(LAT0)))


def runway(a: str, ax: float, ay: float, b: str, bx: float, by: float, heading: float) -> Runway:
    return Runway(2000, 45, (RunwayEnd(a, heading, *ll(ax, ay), 0, None),
                             RunwayEnd(b, (heading + 180) % 360, *ll(bx, by), 0, None)))


def path(p: tuple, q: tuple, name: str, type="PT", start="N", end="N") -> TaxiPath:
    return TaxiPath(*ll(*p), *ll(*q), name, type, start, end)


def airport(runways, paths, gate=None) -> Airport:
    parking = (Parking("G 1", "GM", *ll(*gate), 0, ()),) if gate else ()
    return Airport("TEST", "Test", LAT0, LON0, 0, 0, (), tuple(runways), parking, tuple(paths))


RWY_09_27 = runway("09", 0, 0, "27", 2000, 0, 90)


def simple_airport() -> Airport:
    """Runway 09/27 along y=0. Taxiway A at y=150, with a dogleg between x=1000 and 2000 that makes it
    20 m longer than the straight B+C alternative. Hold-short connectors A1 (09 end) and A5 (27 end)."""
    return airport([RWY_09_27], [
        path((1000, 400), (1000, 150), "", type="P", start="P"),
        path((0, 150), (1000, 150), "A"),
        path((1000, 150), (1500, 250), "A"),
        path((1500, 250), (2000, 150), "A"),
        path((1000, 150), (1500, 150), "B"),
        path((1500, 150), (2000, 150), "C"),
        path((0, 150), (0, 90), "A1", end="HSND"),
        path((2000, 150), (2000, 90), "A5", end="HSND"),
    ], gate=(1000, 400))


def route_from_gate(a: Airport, runway_end: str) -> TaxiRoute | None:
    graph = TaxiGraph(a)
    gate = a.default_parking()
    return graph.route_to_runway(graph.nearest_node(gate.lat, gate.lon), runway_end)


def test_routes_to_the_holding_point_at_the_departure_end():
    assert route_from_gate(simple_airport(), "27").taxiways == ["A", "A5"]
    assert route_from_gate(simple_airport(), "09").taxiways == ["A", "A1"]


def test_staying_on_one_taxiway_beats_a_slightly_shorter_route_with_more_names():
    route = route_from_gate(simple_airport(), "27")
    assert "B" not in route.taxiways  # B+C is 20 m shorter but needs two more name changes


def test_clearance_names_the_taxiways_and_the_holding_point():
    # ICAO: TAXI TO HOLDING POINT [name] RUNWAY [number] VIA …: the stub A5 is the holding point, not said twice
    assert taxi_clearance(route_from_gate(simple_airport(), "27"), "27") == \
        "taxi to holding point Alfa fife runway two seven, via Alfa"


def test_a_route_ending_on_a_whole_taxiway_has_no_holding_point_name():
    route = TaxiRoute((Edge(0, 1, "A", 300, False, ()), Edge(1, 2, "N", 200, False, ())), cost=0)
    assert holding_point(route) is None
    assert taxi_clearance(route, "26R") == "taxi to holding point runway two six right, via Alfa, November"


def test_runway_crossing_becomes_a_hold_short():
    # Runway 18/36 north of 09/27, crossed by taxiway A on the way to the 27 holding point
    a = airport([RWY_09_27, runway("18", 1000, 1200, "36", 1000, 200, 180)], [
        path((500, 800), (500, 600), "", type="P", start="P"),
        path((500, 600), (1500, 600), "A"),
        path((1500, 600), (1500, 90), "A5", end="HSND"),
    ], gate=(500, 800))
    route = route_from_gate(a, "27")
    assert route.crossings == ["18"]
    assert taxi_clearance(route, "27").endswith("via Alfa, hold short runway one eight")


def test_unknown_runway_or_missing_taxi_data_gives_no_route():
    assert route_from_gate(simple_airport(), "99") is None
    bare = airport([RWY_09_27], [])
    assert TaxiGraph(bare).nearest_node(LAT0, LON0) is None


def test_unnamed_pieces_are_left_out_but_the_names_are_said():
    route = TaxiRoute((Edge(0, 1, "", 800, False, ()), Edge(1, 2, "A", 200, False, ())), cost=0)
    assert route.unnamed_share == 0.8
    assert taxi_clearance(route, "23") == "taxi to holding point runway two tree, via Alfa"  # all names, always
    assert taxi_clearance(None, "23") == "taxi to holding point runway two tree"


def test_parking_lead_in_does_not_count_as_unnamed():
    route = TaxiRoute((Edge(0, 1, "", 500, True, ()), Edge(1, 2, "A", 200, False, ())), cost=0)
    assert route.unnamed_share == 0


def e(a, b, name):
    return Edge(a, b, name, 100, False, ())


def test_unnamed_chain_between_same_taxiway_gets_its_name():
    edges = propagate_names([e(0, 1, "A"), e(1, 2, ""), e(2, 3, ""), e(3, 4, "A")])
    assert [x.name for x in edges] == ["A", "A", "A", "A"]


def test_unnamed_chain_between_different_taxiways_stays_unnamed():
    assert [x.name for x in propagate_names([e(0, 1, "A"), e(1, 2, ""), e(2, 3, "B")])] == ["A", "", "B"]


def test_ambiguous_chain_end_stays_unnamed():
    # Node 1 joins both A and B, so the chain could belong to either
    edges = propagate_names([e(0, 1, "A"), e(5, 1, "B"), e(1, 2, ""), e(2, 3, "A")])
    assert edges[2].name == ""


def test_eddh_gate_has_a_route_to_runway_23(eddh):
    route = route_from_gate(eddh, "23")
    assert route is not None and route.length_m > 0
    assert taxi_clearance(route, "23").startswith("taxi to holding point Alfa tree runway two tree")


def test_departure_holding_point_is_an_entry_not_a_crossing():
    """Milestone 8, C5: G at EDDH is the hold-short of a crossing of 33 (to B3), not a holding point for it."""
    a = airport([RWY_09_27], [
        path((300, 400), (300, 150), "", type="P", start="P"),
        path((300, 150), (900, 150), "A"),
        path((300, 150), (300, 90), "G", end="HSND"),  # nearest to the 09 threshold, but it goes on across
        path((300, 90), (300, -90), "G", start="HSND", end="HSND"),
        path((300, -90), (300, -300), "G", start="HSND"),
        path((900, 150), (900, 90), "A2", end="HSND"),  # an entry: ends on the runway
    ], gate=(300, 400))
    graph = TaxiGraph(a)
    g = graph.nearest_node(*ll(300, 90))
    assert graph.leads_across(g, "09") and not graph.leads_across(graph.nearest_node(*ll(900, 90)), "09")
    assert route_from_gate(a, "09").taxiways == ["A", "A2"]


def test_eddh_33_holding_point_is_not_the_crossing_g(eddh):
    graph = TaxiGraph(eddh)
    route = route_from_gate(eddh, "33")
    assert route is not None and not graph.leads_across(route.edges[-1].b, "33")
    # The route reaches B1 on unnamed pieces; the holding point still has its name
    assert taxi_clearance(route, "33").startswith("taxi to holding point Bravo one runway tree tree")

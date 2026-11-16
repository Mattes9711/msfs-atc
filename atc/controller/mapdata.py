"""What the app's map shows (step A6), as plain data for the page.

map_data() is what stays the same for a flight: airports with their runways, the route, the Center sectors near
the route. It is fetched once. moving() is the aircraft and the traffic, sent with every status poll.
Positions are [lat, lon]; the page projects them itself, so nothing is downloaded (no map tiles, works offline).
"""
from atc.airport.model import Airport
from atc.airport.taxi import TaxiGraph

SECTOR_MARGIN_DEG = 2  # sectors whose box comes this close to the route's box are drawn


def _airport(a: Airport, graph: TaxiGraph) -> dict:
    return {"ident": a.ident, "name": a.name, "lat": a.lat, "lon": a.lon,
            "runways": [{"ends": [[e.lat, e.lon] for e in r.ends], "names": [e.name for e in r.ends],
                         "width_m": r.width_ft * 0.3048} for r in a.runways],
            "taxiways": taxiways(graph),
            "parking": [{"name": p.name, "lat": p.lat, "lon": p.lon} for p in a.parking]}


def taxiways(graph: TaxiGraph) -> list[list]:
    """Every taxi segment once, as [lat1, lon1, lat2, lon2, name, to a stand]. From the taxi graph, not the raw data:
    many MSFS segments have no name, and the graph has carried the names along each taxiway, the same names ATC
    uses in its taxi instructions (atc/airport/taxi.py, propagate_names)."""
    out, seen = [], set()
    for edges in graph.adjacent.values():
        for e in edges:
            if (e.b, e.a) in seen:
                continue
            seen.add((e.a, e.b))
            (la1, lo1), (la2, lo2) = graph.latlon[e.a], graph.latlon[e.b]
            out.append([round(la1, 6), round(lo1, 6), round(la2, 6), round(lo2, 6), e.name, e.to_parking])
    return out


def taxi_route(atc) -> list[list[float]]:
    """The taxi route ATC gave, as points, while it is being taxied: out to the runway, or in to the stand."""
    if atc.phase in ("taxi", "pushback", "cleared") and atc.route_out and atc.route_out.edges:
        route, graph = atc.route_out, atc.taxi
    elif atc.phase == "taxi_in" and atc.route_in and atc.route_in.edges:
        route, graph = atc.route_in, atc._arrival_graph()
    else:
        return []
    nodes = [route.edges[0].a] + [e.b for e in route.edges]
    return [list(graph.latlon[n]) for n in nodes]


def map_data(atc) -> dict:
    airports = [a for a in (atc.airport, atc.destination) if a is not None]
    route = [{"ident": w.ident, "lat": w.lat, "lon": w.lon} for w in atc.plan.waypoints]
    points = [(a.lat, a.lon) for a in airports] + [(w["lat"], w["lon"]) for w in route]
    south, north = min(p[0] for p in points) - SECTOR_MARGIN_DEG, max(p[0] for p in points) + SECTOR_MARGIN_DEG
    west, east = min(p[1] for p in points) - SECTOR_MARGIN_DEG, max(p[1] for p in points) + SECTOR_MARGIN_DEG
    sectors = []
    for s in atc.centers.sectors:
        s_south, s_north, s_west, s_east = s.bbox
        if s_north >= south and s_south <= north and s_east >= west and s_west <= east:
            sectors.append({"name": s.name, "khz": s.khz, "polygon": [list(p) for p in s.polygon]})
    graphs = [atc.taxi] + ([atc._arrival_graph()] if atc.destination is not None else [])
    return {"airports": [_airport(a, g) for a, g in zip(airports, graphs)], "route": route, "sectors": sectors}


def moving(atc) -> dict:
    """Our aircraft (true track for drawing) and the other aircraft."""
    state = atc.state
    own = None
    if state is not None:
        own = {"lat": state.lat, "lon": state.lon, "on_ground": state.on_ground,
               "heading": (state.heading_mag + atc.current_airport().mag_var) % 360}
    traffic = [{"callsign": t.callsign, "lat": t.lat, "lon": t.lon, "heading": t.heading_true,
                "alt_ft": round(t.alt_ft), "on_ground": t.on_ground, "gs": round(t.ground_speed_kt, 1)}
               for t in atc.picture.aircraft.values()]  # gs: the map moves them on between readings
    return {"own": own, "traffic": traffic, "taxi_route": taxi_route(atc)}

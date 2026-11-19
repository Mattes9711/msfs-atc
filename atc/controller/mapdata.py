"""What the app's map shows (step A6), as plain data for the page.

map_data() is what stays the same for a flight: airports with their runways, the route, the Center sectors near
the route. It is fetched once. moving() is the aircraft and the traffic, sent with every status poll. area() is
what lies around the map's camera wherever the pilot moves it: the airports with their frequencies, the control
zones and the Center sectors (Milestone 11 O4). airport_chart() is one airport in full, for the taxi chart.
Positions are [lat, lon]; the page projects them itself, so nothing is downloaded (no map tiles, works offline).
"""
import math

from atc.airport.model import Airport, AirportData, Frequency
from atc.airport.taxi import TaxiGraph
from atc.airspace.centers import CenterSectors
from atc.controller.common import labelled

SECTOR_MARGIN_DEG = 2  # sectors whose box comes this close to the route's box are drawn
AREA_AIRPORTS = 250  # airports in one map view at most: the controlled ones and the long runways first
ZONES_UP_TO_DEG = 4  # control zones only in a view this small (latitude span): wider, they are specks
# The frequency band of an airport chart, in the order they are used on departure (Jeppesen 10-9 style), with the
# chart's short labels. Little Navmap COM types; "APRON" is a Ground frequency named as an apron (model.Frequency).
BAND = (("ATIS", "ATIS"), ("RCD", "DEL"), ("CPT", "DEL"), ("C", "DEL"), ("APRON", "APRON"), ("G", "GND"),
        ("T", "TWR"), ("D", "DEP"), ("A", "APP"), ("CTR", "CENTER"), ("FSS", "INFO"), ("UC", "UNICOM"),
        ("MC", "MULTICOM"), ("AWOS", "AWOS"), ("ASOS", "ASOS"))
BAND_ORDER = {role: i for i, (role, _) in enumerate(BAND)}
BAND_LABEL = dict(BAND)


def band(frequencies: tuple[Frequency, ...]) -> list[dict]:
    """The frequencies as an airport chart lists them: ATIS, Delivery, Apron, Ground, Tower, ... each once."""
    seen, out = set(), []
    for f in sorted(frequencies, key=lambda f: (BAND_ORDER.get(f.role, len(BAND)), f.khz)):
        if f.khz in seen:
            continue
        seen.add(f.khz)
        out.append({"label": labelled(BAND_LABEL.get(f.role, f.type), f), "station": f.station or f.name,
                    "khz": f.khz})
    return out


def _airport(a: Airport, graph: TaxiGraph) -> dict:
    return {"ident": a.ident, "name": a.name, "lat": a.lat, "lon": a.lon, "elevation_ft": round(a.elevation_ft),
            "mag_var": round(a.mag_var, 1), "frequencies": band(a.frequencies),
            "runways": [{"ends": [[e.lat, e.lon] for e in r.ends], "names": [e.name for e in r.ends],
                         "headings_mag": [round((e.heading_true - a.mag_var) % 360) or 360 for e in r.ends],
                         "length_ft": round(r.length_ft), "width_m": r.width_ft * 0.3048} for r in a.runways],
            "taxiways": taxiways(graph), "surfaces": surfaces(a), "holds": holds(graph),
            "aprons": [[list(p) for p in apron] for apron in a.aprons],
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


def surfaces(a: Airport) -> list[list]:
    """The paved taxi surface as the data draws it: every taxi path with its width, [lat1, lon1, lat2, lon2,
    width_m, to a stand]. Without a width (old JSON files) a common one: 23 m (75 ft) taxiways, 15 m lead-ins."""
    return [[round(t.start_lat, 6), round(t.start_lon, 6), round(t.end_lat, 6), round(t.end_lon, 6),
             round((t.width_ft or (50 if t.to_parking else 75)) * 0.3048, 1), t.to_parking]
            for t in a.taxi_paths]


def holds(graph: TaxiGraph) -> list[list[float]]:
    """The runway holding positions, [lat, lon, true bearing of the taxiway there]: the chart draws a bar across."""
    out = []
    for n in sorted(graph.hold_short):
        if not graph.adjacent[n]:
            continue
        (la1, lo1), (la2, lo2) = graph.latlon[n], graph.latlon[graph.adjacent[n][0].b]
        bearing = math.degrees(math.atan2((lo2 - lo1) * math.cos(math.radians(la1)), la2 - la1)) % 360
        out.append([round(la1, 6), round(lo1, 6), round(bearing, 1)])
    return out


def airport_chart(a: Airport) -> dict:
    """One airport in full, as for the flight's own: runways, taxiways, aprons, stands, holding positions."""
    return _airport(a, TaxiGraph(a))


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


def _sectors(centers: CenterSectors, south: float, west: float, north: float, east: float) -> list[dict]:
    out = []
    for s in centers.sectors:
        s_south, s_north, s_west, s_east = s.bbox
        if s_north >= south and s_south <= north and s_east >= west and s_west <= east:
            out.append({"name": s.name, "khz": s.khz, "polygon": [list(p) for p in s.polygon]})
    return out


def area(sources: list[AirportData], centers: CenterSectors,
         south: float, west: float, north: float, east: float) -> dict:
    """What lies in the map's view: airports with their frequencies and runways, control zones, Center sectors.
    The first source that knows an airport wins, as for the flight (Little Navmap, then JSON)."""
    airports: dict[str, dict] = {}
    zones: dict[str, dict] = {}
    for source in sources:
        for a in source.in_area(south, west, north, east, AREA_AIRPORTS):
            if a.ident in airports or len(airports) >= AREA_AIRPORTS:
                continue
            airports[a.ident] = {"ident": a.ident, "name": a.name, "lat": a.lat, "lon": a.lon,
                                 "elevation_ft": round(a.elevation_ft), "longest_ft": round(a.longest_runway_ft),
                                 "controlled": a.controlled, "frequencies": band(a.frequencies),
                                 "runways": [[round(x, 6) for x in r] for r in a.runways]}
        if north - south <= ZONES_UP_TO_DEG:
            for z in source.control_zones(south, west, north, east):
                zones.setdefault(z.name, {"name": z.name, "ceiling_ft": round(z.ceiling_ft),
                                          "polygon": [list(p) for p in z.polygon]})
    return {"airports": list(airports.values()), "zones": list(zones.values()),
            "sectors": _sectors(centers, south, west, north, east)}


def map_data(atc) -> dict:
    airports = [a for a in (atc.airport, atc.destination) if a is not None]
    route = [{"ident": w.ident, "lat": w.lat, "lon": w.lon} for w in atc.plan.waypoints]
    points = [(a.lat, a.lon) for a in airports] + [(w["lat"], w["lon"]) for w in route]
    south, north = min(p[0] for p in points) - SECTOR_MARGIN_DEG, max(p[0] for p in points) + SECTOR_MARGIN_DEG
    west, east = min(p[1] for p in points) - SECTOR_MARGIN_DEG, max(p[1] for p in points) + SECTOR_MARGIN_DEG
    sectors = _sectors(atc.centers, south, west, north, east)
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

"""Ground watching the taxiing aircraft (later version 27): off the cleared route, too fast, and progressive taxi.

A Ground controller sees the aircraft on the ground radar. Leaving the cleared route gets "you appear to be on
Bravo" and a new route from where the aircraft is; taxiing much faster than the usual 15 to 25 knots gets "reduce
taxi speed"; on "request progressive taxi" Ground calls each turn onto the next named taxiway shortly before it.
Crossing a runway-holding position without a clearance is the runway incursion check (atc/controller/safety.py).

Flat geometry in the taxi graph's local metres (x east, y north), like atc/controller/give_way.py.
"""
import math

from atc.airport.geo import Point, distance, point_segment_distance
from atc.airport.taxi import TaxiGraph, TaxiRoute
from atc.controller.give_way import route_points
from atc.phraseology import spoken

ON_ROUTE_M = 30  # this close to the route the aircraft is on it (taxiways are ~23 m wide)
OFF_ROUTE_M = 50  # farther than this, after having been on it: off the cleared route
ROUTE_END_M = 60  # near the end (the holding point, the stand) the route no longer counts
TAXIWAY_AT_M = 30  # "you appear to be on Bravo": a named taxiway this close
TAXI_SPEED_MAX_KT = 30
TAXI_SPEED_OK_KT = 20  # below this again, a later "reduce taxi speed" may come
TURN_AHEAD_M = 120  # progressive taxi: the turn is called this far before it
TURN_LOOK_M = 40  # the direction before and after a turn: over this much of the route
STRAIGHT_DEG = 25


def off_route_m(graph: TaxiGraph, route: TaxiRoute, lat: float, lon: float) -> float:
    """How far the aircraft is from its cleared route."""
    points = route_points(graph, route)
    here = graph.proj.xy(lat, lon)
    if len(points) < 2:
        return 0.0
    return min(point_segment_distance(here, a, b) for a, b in zip(points, points[1:]))


def near_route_end(graph: TaxiGraph, route: TaxiRoute, lat: float, lon: float) -> bool:
    return bool(route.edges) and graph.distance_m(route.edges[-1].b, lat, lon) <= ROUTE_END_M


def taxiway_at(graph: TaxiGraph, lat: float, lon: float) -> str | None:
    """The named taxiway the aircraft is on, None on an unnamed piece or a stand's lead-in line."""
    here = graph.proj.xy(lat, lon)
    best = None
    for edges in graph.adjacent.values():
        for e in edges:
            if not e.name or e.to_parking:
                continue
            d = point_segment_distance(here, graph.nodes[e.a], graph.nodes[e.b])
            if d <= TAXIWAY_AT_M and (best is None or d < best[0]):
                best = (d, e.name)
    return best[1] if best else None


def next_turn(graph: TaxiGraph, route: TaxiRoute, lat: float, lon: float) -> tuple[int, str, str] | None:
    """The next place ahead where the route goes onto another named taxiway: (index of the first edge on it, its
    name, "left" | "right" | "straight"). An unnamed piece between two parts of the same taxiway is no turn."""
    points = route_points(graph, route)
    if len(points) < 2:
        return None
    here = graph.proj.xy(lat, lon)
    at = min(range(len(points) - 1), key=lambda i: point_segment_distance(here, points[i], points[i + 1]))
    named = next((e.name for e in reversed(route.edges[:at + 1]) if e.name), None)
    for j in range(at + 1, len(route.edges)):
        edge = route.edges[j]
        if not edge.name or edge.to_parking:
            continue
        if edge.name != named:
            return j, edge.name, _direction(points, j)
        named = edge.name
    return None


def turn_distance_m(graph: TaxiGraph, route: TaxiRoute, index: int, lat: float, lon: float) -> float:
    return graph.distance_m(route.edges[index].a, lat, lon)


def _direction(points: list[Point], j: int) -> str:
    """Left, right or straight at points[j], from the route's direction TURN_LOOK_M before and after it (taxiways
    curve over many short segments)."""
    before, after = _walk(points, j, -1), _walk(points, j, 1)
    turn = math.degrees(math.atan2(*after) - math.atan2(*before))
    turn = (turn + 540) % 360 - 180  # positive: clockwise (bearings), so right
    if abs(turn) < STRAIGHT_DEG:
        return "straight"
    return "right" if turn > 0 else "left"


def _walk(points: list[Point], j: int, step: int) -> Point:
    """The direction (dx, dy) from points[j] TURN_LOOK_M along the route forwards (step 1) or the travel direction
    arriving there (step -1)."""
    corner, k, left = points[j], j, TURN_LOOK_M
    while 0 <= k + step < len(points) and left > 0:
        left -= distance(points[k], points[k + step])
        k += step
    far = points[k]
    return (far[0] - corner[0], far[1] - corner[1]) if step > 0 else (corner[0] - far[0], corner[1] - far[1])


def turn_phrase(direction: str, name: str) -> str:
    """"turn left onto Bravo" / "continue straight ahead onto Alfa one"."""
    where = spoken.spell(name)
    return f"continue straight ahead onto {where}" if direction == "straight" else f"turn {direction} onto {where}"

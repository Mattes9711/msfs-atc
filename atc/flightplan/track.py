"""Track miles to go: how far the aircraft still flies along its planned route, not in a straight line.

Found 2026-11-16 (the user was always sent down too early): the descent came at a straight-line distance from the
airport, but a STAR often leads around the field. Hamburg → Munich: SimBrief's top of descent is 59 nm from
Munich in a straight line and 89 nm along the route, while the 3-in-1 rule on the straight line said 105 nm.

The aircraft is on the route leg it is nearest to; from there it flies to that leg's end and on along the route.
A flat projection around the aircraft is close enough to find the leg; the distances are great-circle.
"""
from atc.airport.geo import LocalProjection, distance_nm, point_segment_distance
from atc.flightplan.model import Waypoint


def to_go_from_each(points: list[tuple[float, float]]) -> list[float]:
    """For each point, the route from it to the last point (the destination), in nm."""
    rest = [0.0] * len(points)
    for i in range(len(points) - 2, -1, -1):
        rest[i] = rest[i + 1] + distance_nm(*points[i], *points[i + 1])
    return rest


def track_to_go_nm(waypoints: tuple[Waypoint, ...], destination: tuple[float, float], lat: float,
                   lon: float, direct: str | None = None) -> float:
    """Nautical miles still to fly from (lat, lon) along the route to the destination; straight there without a
    route. `direct`: a fix ATC cleared the aircraft direct to (Milestone 8, A1: after "proceed direct Landu" the
    route via the points it skips no longer counts, and the descent never came): straight to it, then the route
    from there. Whichever is shorter counts, so it also stays right once the fix is passed."""
    points = [(w.lat, w.lon) for w in waypoints] + [destination]
    if len(points) == 1:
        return distance_nm(lat, lon, *destination)
    rest = to_go_from_each(points)
    proj = LocalProjection(lat, lon)
    here, xy = proj.xy(lat, lon), [proj.xy(*p) for p in points]
    leg = min(range(len(points) - 1), key=lambda i: point_segment_distance(here, xy[i], xy[i + 1]))
    along = distance_nm(lat, lon, *points[leg + 1]) + rest[leg + 1]
    fix = next((i for i, w in enumerate(waypoints) if w.ident == direct), None)
    if fix is None:
        return along
    return min(along, distance_nm(lat, lon, *points[fix]) + rest[fix])

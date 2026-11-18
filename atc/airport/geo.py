"""Geometry. LocalProjection and friends: flat metres, good within an airport (a few km).
The *_nm functions: great circle on a sphere, for en-route distances."""
import math
from typing import Sequence

M_PER_DEG_LAT = 111_195
EARTH_RADIUS_NM = 3440.065


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial true course from point 1 to point 2."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def destination_point(lat: float, lon: float, bearing: float, nm: float) -> tuple[float, float]:
    p1, l1, b, d = math.radians(lat), math.radians(lon), math.radians(bearing), nm / EARTH_RADIUS_NM
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def along_route(lat1: float, lon1: float, lat2: float, lon2: float, nm: float) -> tuple[float, float]:
    """The point nm along the great circle from point 1 towards point 2."""
    return destination_point(lat1, lon1, bearing_deg(lat1, lon1, lat2, lon2), nm)

Point = tuple[float, float]


class LocalProjection:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0))

    def xy(self, lat: float, lon: float) -> Point:
        return ((lon - self.lon0) * self.m_per_deg_lon, (lat - self.lat0) * M_PER_DEG_LAT)


def distance(p: Point, q: Point) -> float:
    return math.hypot(q[0] - p[0], q[1] - p[1])


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    length2 = ab[0] ** 2 + ab[1] ** 2
    if length2 == 0:
        return distance(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / length2))
    return distance(p, (a[0] + t * ab[0], a[1] + t * ab[1]))


def segment_distance_nm(lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """How far (lat, lon) is from the line a-b, flat around the point: fine up to a few hundred nm."""
    proj = LocalProjection(lat, lon)
    return point_segment_distance((0.0, 0.0), proj.xy(*a), proj.xy(*b)) / 1852


def segments_cross(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True if the two segments intersect (touching counts)."""
    def side(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
    d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
    return d1 * d2 <= 0 and d3 * d4 <= 0 and (d1, d2, d3, d4) != (0, 0, 0, 0)


def point_in_polygon(lat: float, lon: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """Ray casting on (lat, lon) treated as flat coordinates: fine for sectors a few hundred nm wide that don't
    cross the antimeridian or a pole. Points exactly on an edge may fall either way."""
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        (lat_i, lon_i), (lat_j, lon_j) = polygon[i], polygon[j]
        if (lat_i > lat) != (lat_j > lat):
            lon_cross = lon_i + (lat - lat_i) * (lon_j - lon_i) / (lat_j - lat_i)
            if lon < lon_cross:
                inside = not inside
        j = i
    return inside

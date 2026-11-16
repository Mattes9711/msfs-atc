"""Other aircraft in the way of our taxi route (Milestone 6, L4).

LiveTraffic aircraft follow their real taxi routes and never listen to ATC, so ATC moves the pilot around them, the
way a real ground controller does: "give way to the Airfrans Airbus crossing left to right", "follow the Lufthansa
Airbus", or, for one coming the other way, "hold position" and later "continue taxi".

Everything here is flat geometry in the taxi graph's local metres (x east, y north), on the part of our cleared route
still ahead of us.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from atc.airport.geo import Point, distance
from atc.airport.taxi import TaxiGraph, TaxiRoute

ON_ROUTE_M = 30  # this close to our route an aircraft is on it (taxiways are ~23 m wide)
LOOK_S = 30  # where a taxiing aircraft will be: its heading and speed for this long
LOOK_MAX_M = 400
SAME_WAY_DEG, OPPOSITE_DEG = 45, 135
KT_TO_MS = 0.5144


@dataclass(frozen=True)
class Conflict:
    kind: str  # "crossing", "follow" (ahead, going our way), "opposite" (ahead, coming towards us),
    # "blocking" (standing on our route, not pointing our way: B2)
    distance_m: float  # along our route to where it is or will cross
    direction: str | None = None  # crossing: "left to right" or "right to left", as seen from us


def route_points(graph: TaxiGraph, route: TaxiRoute) -> list[Point]:
    if not route.edges:
        return []
    return [graph.nodes[e.a] for e in route.edges] + [graph.nodes[route.edges[-1].b]]


def path_ahead(points: list[Point], here: Point, ahead_m: float) -> list[Point]:
    """Our route from the point nearest to us onwards, ahead_m long (the part behind us is done)."""
    if len(points) < 2:
        return []
    best = min(range(len(points) - 1), key=lambda i: _segment_distance(here, points[i], points[i + 1])[0])
    start = _segment_distance(here, points[best], points[best + 1])[1]
    path, left = [start], ahead_m
    for p in points[best + 1:]:
        step = distance(path[-1], p)
        if step >= left:
            t = left / step if step else 0
            path.append((path[-1][0] + (p[0] - path[-1][0]) * t, path[-1][1] + (p[1] - path[-1][1]) * t))
            break
        path.append(p)
        left -= step
    return path


def conflict(path: list[Point], at: Point, heading_true: float, gs_kt: float) -> Conflict | None:
    """How an aircraft at `at`, taxiing on that heading, gets in the way of our path ahead, if it does."""
    if len(path) < 2:
        return None
    v = (math.sin(math.radians(heading_true)), math.cos(math.radians(heading_true)))
    along = 0.0
    nearest = None  # (distance off the path, along the path, our direction there)
    for a, b in zip(path, path[1:]):
        off, foot = _segment_distance(at, a, b)
        d = _unit(a, b)
        if nearest is None or off < nearest[0]:
            nearest = (off, along + distance(a, foot), d)
        along += distance(a, b)
    off, s, d = nearest
    if off <= ON_ROUTE_M:  # on our route ahead
        angle = math.degrees(math.acos(max(-1.0, min(1.0, d[0] * v[0] + d[1] * v[1]))))
        if angle <= SAME_WAY_DEG:
            return Conflict("follow", s)
        if angle >= OPPOSITE_DEG:
            return Conflict("opposite", s)
        return Conflict("crossing", s, _side(d, v))
    reach = min(gs_kt * KT_TO_MS * LOOK_S, LOOK_MAX_M)
    end = (at[0] + v[0] * reach, at[1] + v[1] * reach)
    along = 0.0
    for a, b in zip(path, path[1:]):
        if (hit := _intersection(a, b, at, end)) is not None:
            return Conflict("crossing", along + distance(a, hit), _side(_unit(a, b), v))
        along += distance(a, b)
    return None


def traffic_name(callsign: str, airline: str, model: str) -> str:
    """How a ground controller names it: "the Airfrans Airbus", "the Lufthansa Boeing", "the Skyhawk"."""
    from atc.phraseology.airlines import TELEPHONY

    code = re.match(r"([A-Z]{3})\d", callsign.upper())
    company = TELEPHONY.get(code[1]) if code else None
    company = company or (airline if airline and not re.search(r"\d|-", airline) else "")
    words = " ".join(w for w in (company, type_word(model)) if w)
    return f"the {words}" if words else "the traffic"


def type_word(model: str) -> str:
    m = model.upper().replace("-", "")
    if re.fullmatch(r"A\d{3}N?|A2\dN|BCS\d", m):
        return "Airbus"
    if re.fullmatch(r"B?7\d\w+|B3\dM", m):
        return "Boeing"
    if re.fullmatch(r"E\d{3}|E\d{2}|ERJ\w*|E\d\w*", m):
        return "Embraer"
    if re.fullmatch(r"[A-Z ]{3,}", m) and not re.fullmatch(r"[A-Z]{3,4}", m):  # "Skyhawk", "King Air", not "CRJ9"
        return model.title()
    return ""


def _side(ours: Point, theirs: Point) -> str:
    """Moving towards our left means it comes from our right."""
    left = (-ours[1], ours[0])
    return "right to left" if theirs[0] * left[0] + theirs[1] * left[1] > 0 else "left to right"


def _unit(a: Point, b: Point) -> Point:
    length = distance(a, b) or 1.0
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def _segment_distance(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    """Distance from p to the segment a-b, and the nearest point on it."""
    ab = (b[0] - a[0], b[1] - a[1])
    length2 = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / length2))
    foot = (a[0] + ab[0] * t, a[1] + ab[1] * t)
    return distance(p, foot), foot


def _intersection(p1: Point, p2: Point, q1: Point, q2: Point) -> Point | None:
    r, s = (p2[0] - p1[0], p2[1] - p1[1]), (q2[0] - q1[0], q2[1] - q1[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-9:
        return None
    t = ((q1[0] - p1[0]) * s[1] - (q1[1] - p1[1]) * s[0]) / denom
    u = ((q1[0] - p1[0]) * r[1] - (q1[1] - p1[1]) * r[0]) / denom
    return (p1[0] + r[0] * t, p1[1] + r[1] * t) if 0 <= t <= 1 and 0 <= u <= 1 else None

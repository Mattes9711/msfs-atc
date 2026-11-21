"""Taxiway graph built from Little Navmap taxi paths, and a router that prefers routes ATC can say simply."""
import heapq
import itertools
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass

from atc.airport.geo import LocalProjection, Point, distance, point_segment_distance, segments_cross
from atc.airport.model import Airport

NAME_CHANGE_PENALTY_M = 150  # so "via A, B" beats a slightly shorter "via A, A3, A, B2, B"
RUNWAY_CROSSING_PENALTY_M = 1500  # avoid crossings unless the detour is long
HOLD_SHORT_MAX_FROM_CENTERLINE_M = 200
HOLDING_POINT_SLACK_M = 300  # consider all holding points this close to the best one near the threshold
CROSSING_STEPS = 10  # how far a hold-short point's taxiway is followed to find the other side of a crossing
STRIP_MARGIN_M = 10  # … within its hold lines, give or take this
HOLD_LINE_MARGIN_M = 5  # an aircraft *at* the holding point is not on the runway
DEFAULT_CLEARANCE_M = 30  # beyond the runway edge, when the scenery has no hold-short points
LOCAL_HOLD_M = 250  # a hold-short point this close sets the strip's edge there (one taxiway's hold line nearer in)
FT_TO_M = 0.3048


@dataclass(frozen=True)
class Edge:
    a: int
    b: int
    name: str
    length_m: float
    to_parking: bool
    crosses: tuple[str, ...]  # runway designators this segment crosses


@dataclass(frozen=True)
class TaxiRoute:
    edges: tuple[Edge, ...]
    cost: float
    point: str = ""  # the holding point's name when the route reaches it on an unnamed piece (EDDH B1)

    @property
    def length_m(self) -> float:
        return sum(e.length_m for e in self.edges)

    @property
    def taxiways(self) -> list[str]:
        """Named taxiways in order, consecutive repeats collapsed."""
        names: list[str] = []
        for e in self.edges:
            if e.name and (not names or names[-1] != e.name):
                names.append(e.name)
        return names

    @property
    def crossings(self) -> list[str]:
        seen: list[str] = []
        for e in self.edges:
            seen.extend(r for r in e.crosses if r not in seen)
        return seen

    @property
    def unnamed_share(self) -> float:
        """Share of the taxiway length (parking lead-ins excluded) without a name."""
        taxi = [e for e in self.edges if not e.to_parking]
        total = sum(e.length_m for e in taxi)
        return sum(e.length_m for e in taxi if not e.name) / total if total else 0.0


class TaxiGraph:
    def __init__(self, airport: Airport):
        self.airport = airport
        self.proj = LocalProjection(airport.lat, airport.lon)
        self.nodes: list[Point] = []
        self.latlon: list[tuple[float, float]] = []
        self.hold_short: set[int] = set()
        self.adjacent: dict[int, list[Edge]] = defaultdict(list)
        # (designator used in "hold short runway X", both end names, centreline end points)
        self._runways = [
            (r.ends[0].name, {r.ends[0].name, r.ends[1].name},
             self.proj.xy(r.ends[0].lat, r.ends[0].lon), self.proj.xy(r.ends[1].lat, r.ends[1].lon))
            for r in airport.runways
        ]
        index: dict[tuple[float, float], int] = {}

        def node(lat: float, lon: float) -> int:
            key = (round(lat, 7), round(lon, 7))  # identical points in the data differ only in float noise
            if key not in index:
                index[key] = len(self.nodes)
                self.nodes.append(self.proj.xy(lat, lon))
                self.latlon.append((lat, lon))
            return index[key]

        edges = []
        for t in airport.taxi_paths:
            a, b = node(t.start_lat, t.start_lon), node(t.end_lat, t.end_lon)
            if a == b:
                continue
            if t.start_type == "HSND":
                self.hold_short.add(a)
            if t.end_type == "HSND":
                self.hold_short.add(b)
            pa, pb = self.nodes[a], self.nodes[b]
            crosses = tuple(name for name, _, r1, r2 in self._runways if segments_cross(pa, pb, r1, r2))
            edges.append(Edge(a, b, radio_name(t.name), distance(pa, pb), t.to_parking, crosses))
        for e in propagate_names(edges):
            self.adjacent[e.a].append(e)
            self.adjacent[e.b].append(Edge(e.b, e.a, e.name, e.length_m, e.to_parking, e.crosses))
        # How far from each centreline its hold lines are, from the scenery's own hold-short points (they differ
        # per runway: ~60 m for small runways, ~90 m or more for big ones), and the nodes inside them
        self.strip_limit_m: dict[str, float] = {}
        self._strip_holds: dict[str, list[tuple[tuple[float, float], float]]] = {}
        self.in_strip: dict[str, set[int]] = {}
        for rwy, (name, _, r1, r2) in zip(airport.runways, self._runways):
            holds = [(self.nodes[n], d) for n in self.hold_short
                     if (d := point_segment_distance(self.nodes[n], r1, r2)) <= HOLD_SHORT_MAX_FROM_CENTERLINE_M]
            self._strip_holds[name] = holds
            self.strip_limit_m[name] = (statistics.median(d for _, d in holds) - HOLD_LINE_MARGIN_M if holds
                                        else rwy.width_ft * FT_TO_M / 2 + DEFAULT_CLEARANCE_M)
            self.in_strip[name] = {n for n in self.adjacent if n not in self.hold_short
                                   and point_segment_distance(self.nodes[n], r1, r2) < self.strip_limit(name, n)}

    def strip_limit(self, runway: str, at: int | tuple[float, float]) -> float:
        """How far from the centreline the runway's strip ends at a node or a point (x, y): at the nearest
        hold-short point's line, if one is close, else at the median of them all. EDHL, the emulator, 2026-11-19:
        runway 07's hold lines are 166-171 m out, the one on taxiway C 98 m; with the median for all of them, an
        aircraft that had vacated via C and passed its hold line was still "on the runway": stop immediately."""
        p = self.nodes[at] if isinstance(at, int) else at
        near = [(distance(p, xy), d) for xy, d in self._strip_holds[runway]]
        nearest = min(near, default=None)
        if nearest is None or nearest[0] > LOCAL_HOLD_M:
            return self.strip_limit_m[runway]
        return nearest[1] - HOLD_LINE_MARGIN_M

    def distance_m(self, node: int, lat: float, lon: float) -> float:
        return distance(self.nodes[node], self.proj.xy(lat, lon))

    def nearest_node(self, lat: float, lon: float) -> int | None:
        if not self.adjacent:
            return None
        p = self.proj.xy(lat, lon)
        return min(self.adjacent, key=lambda n: distance(p, self.nodes[n]))

    def holding_points(self, runway_end: str) -> list[int]:
        """Hold-short nodes beside this runway, nearest to its threshold first."""
        end = self.airport.runway_end(runway_end)
        if end is None:
            return []
        _, _, r1, r2 = next(r for r in self._runways if runway_end in r[1])
        threshold = self.proj.xy(end.lat, end.lon)
        beside = [n for n in self.hold_short
                  if point_segment_distance(self.nodes[n], r1, r2) <= HOLD_SHORT_MAX_FROM_CENTERLINE_M]
        return sorted(beside, key=lambda n: distance(self.nodes[n], threshold))

    def leads_across(self, node: int, runway_end: str) -> bool:
        """A hold-short point of a runway crossing, not of an entry: within the runway's strip its taxiway leads to
        another hold-short point on the other side (Milestone 8, C5: at EDDH the departure "holding point" for 33
        was G, which crosses 33 to B3; the user stood at a holding point that didn't exist for a departure). There
        are no runway segments in the data, so an entry's way ends on the runway."""
        _, _, r1, r2 = next(r for r in self._runways if runway_end in r[1])

        def side(n: int) -> float:
            (x, y) = self.nodes[n]
            return (r2[0] - r1[0]) * (y - r1[1]) - (r2[1] - r1[1]) * (x - r1[0])

        start, seen, frontier = side(node), {node}, [node]
        # Only the strip between the hold lines: a parallel taxiway is farther out than the hold-short point
        strip = point_segment_distance(self.nodes[node], r1, r2) + STRIP_MARGIN_M
        for _ in range(CROSSING_STEPS):
            following = []
            for n in frontier:
                for e in self.adjacent[n]:
                    if e.b in seen or point_segment_distance(self.nodes[e.b], r1, r2) > strip:
                        continue
                    seen.add(e.b)
                    following.append(e.b)
                    if e.b in self.hold_short and side(e.b) * start < 0:
                        return True
            frontier = following
        return False

    def route_to_runway(self, start: int, runway_end: str) -> TaxiRoute | None:
        """Cheapest route to a holding point near the departure threshold: one that leads onto the runway, not
        across it (only if the runway has no other, any)."""
        candidates = self.holding_points(runway_end)
        candidates = [n for n in candidates if not self.leads_across(n, runway_end)] or candidates
        if not candidates:
            return None
        end = self.airport.runway_end(runway_end)
        threshold = self.proj.xy(end.lat, end.lon)
        best = distance(self.nodes[candidates[0]], threshold)
        near = [n for n in candidates if distance(self.nodes[n], threshold) <= best + HOLDING_POINT_SLACK_M]
        routes = [r for r in (self.route(start, goal) for goal in near) if r is not None]
        best = min(routes, key=lambda r: r.cost, default=None)
        if best is not None and best.edges and not best.edges[-1].name:
            beyond = {e.name for e in self.adjacent[best.edges[-1].b] if e.name}
            if len(beyond) == 1:
                best = TaxiRoute(best.edges, best.cost, beyond.pop())
        return best

    def _runway_penalty(self, e: Edge, start_inside: set[str]) -> float:
        """Each way onto a runway's strip costs as much as a crossing: past its hold line (EDDB, the emulator,
        2026-11-19: from M5, just vacated 06R, the shortest way to the stand turned back to the M5/M4 junction
        inside the hold lines, crossed no centreline, so no hold short, and the safety check stopped the aircraft),
        or across it on one segment. Inside the strip a crossing is paid already, unless the route starts there."""
        penalty = 0.0
        for name, inside in self.in_strip.items():
            if e.a not in inside:
                if e.b in inside or name in e.crosses:
                    penalty += RUNWAY_CROSSING_PENALTY_M
            elif name in e.crosses and name in start_inside:
                penalty += RUNWAY_CROSSING_PENALTY_M
        return penalty

    def route(self, start: int, goal: int) -> TaxiRoute | None:
        # State includes the taxiway we arrived on, because changing names costs extra
        start_inside = {name for name, inside in self.in_strip.items() if start in inside}
        counter = itertools.count()
        queue = [(0.0, next(counter), start, None, ())]
        settled: set[tuple[int, str | None]] = set()
        while queue:
            cost, _, n, arrived_on, path = heapq.heappop(queue)
            if n == goal:
                return TaxiRoute(path, cost)
            if (n, arrived_on) in settled:
                continue
            settled.add((n, arrived_on))
            for e in self.adjacent[n]:
                step = e.length_m + self._runway_penalty(e, start_inside)
                if arrived_on is not None and e.name != arrived_on:
                    step += NAME_CHANGE_PENALTY_M
                if (e.b, e.name) not in settled:
                    heapq.heappush(queue, (cost + step, next(counter), e.b, e.name, path + (e,)))
        return None


DESIGNATOR = re.compile(r"[A-Z](?:\d{1,2}[A-Z]?)?")  # "N", "N5", "B12W": what ATC says and the pilot reads back
_SUFFIXED = (re.compile(r"([A-Z])-(\d{1,2})"),  # "T-2" is T2
             re.compile(r"([A-Z]\d{1,2})(?:[A-Z]{2,}|[-. ].*)"),  # "E3BLUE", "D2SSS", "Z3.1": a piece of E3
             re.compile(r"([A-Z])[-. ].*"))  # "N-SOUTH": a piece of N


def radio_name(name: str) -> str:
    """A scenery taxiway name as ATC says it. Some sceneries split a taxiway into pieces ("N-South" at EDDF): ATC
    said "November Sierra Oscar Uniform Tango Hotel" and refused the co-pilot's "N-South" five times (the emulator,
    2026-11-19). Names that are no designator at all ("LINK 4", "SWINGOVR", "PARKING") count as unnamed."""
    name = name.strip().upper()
    if DESIGNATOR.fullmatch(name):
        return name
    for pattern in _SUFFIXED:
        if m := pattern.fullmatch(name):
            return "".join(m.groups())
    return ""


def propagate_names(edges: list[Edge]) -> list[Edge]:
    """Give a chain of unnamed segments a name when both of its ends join the same single taxiway.
    MSFS scenery often names only the connectors, so this recovers names without guessing."""
    by_node: dict[int, list[int]] = defaultdict(list)
    for i, e in enumerate(edges):
        by_node[e.a].append(i)
        by_node[e.b].append(i)

    def names_at(n: int, exclude: set[int]) -> set[str]:
        return {edges[i].name for i in by_node[n] if i not in exclude and edges[i].name and not edges[i].to_parking}

    result = list(edges)
    done: set[int] = set()
    for i, e in enumerate(edges):
        if e.name or e.to_parking or i in done:
            continue
        chain, ends = _unnamed_chain(i, edges, by_node)
        done |= chain
        if len(ends) != 2:
            continue
        left, right = (names_at(n, chain) for n in ends)
        common = left & right
        if len(common) == 1 and len(left) == 1 and len(right) == 1:
            name = common.pop()
            for j in chain:
                result[j] = Edge(edges[j].a, edges[j].b, name, edges[j].length_m, False, edges[j].crosses)
    return result


def _unnamed_chain(start: int, edges: list[Edge], by_node: dict[int, list[int]]) -> tuple[set[int], list[int]]:
    """Unnamed taxiway edges connected through nodes that join exactly two edges; returns (edges, end nodes)."""
    def unnamed(i: int) -> bool:
        return not edges[i].name and not edges[i].to_parking

    chain, ends = {start}, []
    for node in (edges[start].a, edges[start].b):
        prev = start
        while True:
            others = [i for i in by_node[node] if i != prev]
            if len(others) != 1 or not unnamed(others[0]) or others[0] in chain:
                ends.append(node)
                break
            prev = others[0]
            chain.add(prev)
            node = edges[prev].b if edges[prev].a == node else edges[prev].a
    return chain, ends

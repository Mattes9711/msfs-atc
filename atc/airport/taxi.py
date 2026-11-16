"""Taxiway graph built from Little Navmap taxi paths, and a router that prefers routes ATC can say simply."""
import heapq
import itertools
from collections import defaultdict
from dataclasses import dataclass

from atc.airport.geo import LocalProjection, Point, distance, point_segment_distance, segments_cross
from atc.airport.model import Airport

NAME_CHANGE_PENALTY_M = 150  # so "via A, B" beats a slightly shorter "via A, A3, A, B2, B"
RUNWAY_CROSSING_PENALTY_M = 1500  # avoid crossings unless the detour is long
HOLD_SHORT_MAX_FROM_CENTERLINE_M = 200
HOLDING_POINT_SLACK_M = 300  # consider all holding points this close to the best one near the threshold


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
            edges.append(Edge(a, b, t.name, distance(pa, pb), t.to_parking, crosses))
        for e in propagate_names(edges):
            self.adjacent[e.a].append(e)
            self.adjacent[e.b].append(Edge(e.b, e.a, e.name, e.length_m, e.to_parking, e.crosses))

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

    def route_to_runway(self, start: int, runway_end: str) -> TaxiRoute | None:
        """Cheapest route to any holding point near the departure threshold."""
        candidates = self.holding_points(runway_end)
        if not candidates:
            return None
        end = self.airport.runway_end(runway_end)
        threshold = self.proj.xy(end.lat, end.lon)
        best = distance(self.nodes[candidates[0]], threshold)
        near = [n for n in candidates if distance(self.nodes[n], threshold) <= best + HOLDING_POINT_SLACK_M]
        routes = [r for r in (self.route(start, goal) for goal in near) if r is not None]
        return min(routes, key=lambda r: r.cost, default=None)

    def route(self, start: int, goal: int) -> TaxiRoute | None:
        # State includes the taxiway we arrived on, because changing names costs extra
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
                step = e.length_m + RUNWAY_CROSSING_PENALTY_M * len(e.crosses)
                if arrived_on is not None and e.name != arrived_on:
                    step += NAME_CHANGE_PENALTY_M
                if (e.b, e.name) not in settled:
                    heapq.heappush(queue, (cost + step, next(counter), e.b, e.name, path + (e,)))
        return None


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

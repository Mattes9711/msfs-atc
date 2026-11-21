"""Where an aircraft on the ground must not be without a clearance: past the runway-holding position."""
from atc.airport.geo import distance
from atc.airport.model import Airport, Runway
from atc.airport.taxi import TaxiGraph

AT_HOLD_SHORT_M = 15


class RunwayZones:
    """For each runway, how far from the centreline its hold-short lines are (TaxiGraph.strip_limit: the taxi
    router keeps out of the same strip)."""

    def __init__(self, airport: Airport, graph: TaxiGraph):
        self.graph = graph
        self.zones = []
        for rwy in airport.runways:
            a, b = (graph.proj.xy(e.lat, e.lon) for e in rwy.ends)
            self.zones.append((rwy, a, b, rwy.ends[0].name))

    def runway_at(self, lat: float, lon: float) -> Runway | None:
        """The runway whose protected area this point is in, if any. Standing at a hold-short point never counts,
        nor past a runway end (TaxiGraph.strip_distance)."""
        p = self.graph.proj.xy(lat, lon)
        if any(distance(p, self.graph.nodes[n]) <= AT_HOLD_SHORT_M for n in self.graph.hold_short):
            return None
        inside = [(d, rwy) for rwy, a, b, name in self.zones
                  if (d := self.graph.strip_distance(name, p)) < self.graph.strip_limit(name, p)]
        return min(inside, key=lambda d_r: d_r[0])[1] if inside else None


def designator(rwy: Runway) -> str:
    """'05' for runway 05/23: the name used in 'hold short runway 05', 'cross runway 05'."""
    return rwy.ends[0].name

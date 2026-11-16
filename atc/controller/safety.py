"""Where an aircraft on the ground must not be without a clearance: past the runway-holding position."""
import statistics

from atc.airport.geo import distance, point_segment_distance
from atc.airport.model import Airport, Runway
from atc.airport.taxi import HOLD_SHORT_MAX_FROM_CENTERLINE_M, TaxiGraph

FT_TO_M = 0.3048
HOLD_LINE_MARGIN_M = 5  # an aircraft *at* the holding point is fine
DEFAULT_CLEARANCE_M = 30  # beyond the runway edge, when the scenery has no hold-short points
AT_HOLD_SHORT_M = 15


class RunwayZones:
    """For each runway, how far from the centreline its hold-short lines are, taken from the scenery's own
    hold-short points (they differ per runway: ~60 m for small runways, ~90 m or more for big ones)."""

    def __init__(self, airport: Airport, graph: TaxiGraph):
        self.graph = graph
        self.zones = []
        for rwy in airport.runways:
            a, b = (graph.proj.xy(e.lat, e.lon) for e in rwy.ends)
            holds = [d for n in graph.hold_short
                     if (d := point_segment_distance(graph.nodes[n], a, b)) <= HOLD_SHORT_MAX_FROM_CENTERLINE_M]
            limit = (statistics.median(holds) - HOLD_LINE_MARGIN_M if holds
                     else rwy.width_ft * FT_TO_M / 2 + DEFAULT_CLEARANCE_M)
            self.zones.append((rwy, a, b, limit))

    def runway_at(self, lat: float, lon: float) -> Runway | None:
        """The runway whose protected area this point is in, if any. Standing at a hold-short point never counts:
        beyond a runway end, the distance to the centreline segment is measured to the end, not sideways."""
        p = self.graph.proj.xy(lat, lon)
        if any(distance(p, self.graph.nodes[n]) <= AT_HOLD_SHORT_M for n in self.graph.hold_short):
            return None
        inside = [(point_segment_distance(p, a, b), rwy) for rwy, a, b, limit in self.zones
                  if point_segment_distance(p, a, b) < limit]
        return min(inside, key=lambda d_r: d_r[0])[1] if inside else None


def designator(rwy: Runway) -> str:
    """'05' for runway 05/23: the name used in 'hold short runway 05', 'cross runway 05'."""
    return rwy.ends[0].name

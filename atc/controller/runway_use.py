"""Which runway end the real traffic uses (Milestone 6, L2).

LiveTraffic replays real aircraft, and they land and depart on the real runway. If our ATC picked the other end from
the METAR, it would send the pilot head-on into them, so what the traffic does wins over the wind: the last landings
and takeoffs, and who is on final now, vote for a runway end.

- Departure runway: the ends the last departures took off from. With no departures seen, the direction the
  arrivals land in (an arrival on 23 means departures on 23 too, or on a parallel runway the same way).
- Arrival runway: the ends the last arrivals landed on, and the aircraft on final now; else the departures'
  direction.

Needs MIN_VOTES agreeing aircraft before it decides anything: one aircraft could be a go-around or a training
flight. Deterministic: the same transitions give the same choice.
"""
from __future__ import annotations

from collections import Counter, deque

from atc.airport.model import Airport
from atc.controller.traffic import Transition, runway_end_for

REMEMBER = 6  # the last landings and departures per airport
MIN_VOTES = 2
SAME_WAY_DEG = 30  # parallel runways: "08L" and "08R" point the same way


class RunwayUse:
    def __init__(self):
        self.landings: dict[str, deque[str]] = {}  # airport → runway end names, oldest first
        self.departures: dict[str, deque[str]] = {}

    def record(self, transitions: list[Transition], airports: list[Airport]) -> None:
        """Landings (final → on the runway) and takeoffs (on the runway → departing) in the last update."""
        by_ident = {a.ident: a for a in airports}
        for tr in transitions:
            before, after = tr.before, tr.after
            airport = by_ident.get(after.airport or "")
            if before is None or airport is None:
                continue
            if before.kind == "final" and after.kind == "on_runway":
                self.landings.setdefault(airport.ident, deque(maxlen=REMEMBER)).append(before.runway)
            elif before.kind == "on_runway" and after.kind == "departing":
                end = runway_end_for(airport, after.runway, tr.aircraft.heading_true)
                self.departures.setdefault(airport.ident, deque(maxlen=REMEMBER)).append(end)

    def in_use(self, airport: Airport, kind: str, on_final: list[str] = (), preferred: str | None = None) -> str | None:
        """The runway end the traffic uses for "departure" or "arrival", or None when it doesn't show one.
        on_final: runway ends of the aircraft on final now. preferred: our current choice, kept while it points the
        traffic's way (or its other end) when only the other kind of traffic shows the direction."""
        landed = [*self.landings.get(airport.ident, ()), *on_final]
        departed = list(self.departures.get(airport.ident, ()))
        own, other = (departed, landed) if kind == "departure" else (landed, departed)
        if len(own) >= MIN_VOTES:
            best = _most_used(own)  # the very runway: at EDDM departures use 08L/26R, arrivals 08R/26L
            counts = Counter(own)
            if preferred and counts[preferred] >= counts[best]:
                return preferred  # a tie keeps the runway (the test flight: 26R → 26L → 26R in 7 s)
            return best
        if len(other) >= MIN_VOTES:
            end = _most_used(other)  # only its direction counts: our runway that way, if it is one
            if preferred:
                for candidate in (preferred, _other_end(airport, preferred)):  # 08R, else its other end 26L
                    if candidate and _same_way(airport, candidate, end):
                        return candidate
            return end
        return None


def _most_used(ends: list[str]) -> str:
    """The end with the most votes; on a tie the one used last."""
    counts = Counter(ends)
    best = max(counts.values())
    return next(end for end in reversed(ends) if counts[end] == best)


def _same_way(airport: Airport, a: str, b: str) -> bool:
    ha, hb = airport.runway_end(a).heading_true, airport.runway_end(b).heading_true
    return abs((ha - hb + 540) % 360 - 180) <= SAME_WAY_DEG


def _other_end(airport: Airport, name: str) -> str | None:
    rwy = next((r for r in airport.runways if name in (r.ends[0].name, r.ends[1].name)), None)
    return None if rwy is None else (rwy.ends[1].name if rwy.ends[0].name == name else rwy.ends[0].name)

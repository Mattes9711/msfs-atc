"""Milestone 8, G: the other aircraft talk to Departure, Approach and Center too, from what they really do.

Every traffic update (a few seconds) each airborne aircraft is checked against the area of the controller the pilot
is tuned to: a Center's sector (from the Center data), or a terminal area of TERMINAL_NM around origin or
destination, below TERMINAL_TOP_FT, for its Departure / Approach. The Tower's own traffic (final, departing, on the
runway) is the Tower's. What can be heard, nothing made up:
    entering the area      the pilot checks in with its level ("passing flight level 123, climbing"); radar contact
    climbing / descending  the controller clears it a few thousand feet on, in the direction it really goes, and
                           again when it gets close to that level
    leaving the area       the controller hands it over to whoever has it next (the Center sector it is in, the
                           Approach of a terminal area it enters, the Tower once it is on final); it reads back
One exchange at a time, never while the pilot owes a readback or a check-in, only on a quiet radio, and at most one
every AIR_CHATTER_GAP_S ("medium to busy", the user). A part of Controller, like traffic_calls.py.
"""
import math
from dataclasses import dataclass

from atc.airport.geo import distance_nm
from atc.airport.model import Airport
from atc.controller import readback as rb
from atc.controller.common import Response, Station, center_station
from atc.controller.traffic import spoken_callsign
from atc.phraseology import spoken
from atc.sim.traffic import Traffic

TERMINAL_NM = 30  # Departure's and Approach's area around their airport
TERMINAL_TOP_FT = 15000  # and up to this level; above, the Center has it
TRANSITION_FT = 5000  # Germany's transition altitude: flight levels above
AIR_CHATTER_GAP_S = 20  # between two exchanges ("medium to busy")
AIR_QUIET_S = 8  # the radio has been quiet this long (our own calls, readbacks, the other chatter)
DUE_FOR_S = 60  # a check-in or handoff not said by then is old news
LEVEL_FPM = 500  # faster than this it is climbing or descending
LEVEL_STEP_FT = 4000  # how far on the controller clears it
REACHED_FT = 1000  # this close to its cleared level, and still going: cleared on
CENTER_FLOOR_FT = 10000  # a Center descends no lower; Approach takes over
MAX_LEVEL_FT = 41000


@dataclass
class Track:
    alt_ft: float
    at: float
    rate_fpm: float = 0.0
    inside: bool | None = None  # in the tuned controller's area at the last update; None = not looked at yet
    due: str | None = None  # "checkin" or "handoff", not said yet
    due_at: float = 0.0
    cleared_ft: int | None = None


class AirChatterMixin:
    def _air_chatter(self, tuned: Station) -> list[Response]:
        now = self.traffic_clock
        if now is None:
            return []
        if tuned.key != self.air_area_key:  # another controller: who is in its area is looked at afresh
            self.air_area_key = tuned.key
            for track in self.air_tracks.values():
                track.inside, track.due = None, None
        aircraft = {i: t for i, t in self.picture.aircraft.items() if not t.on_ground}
        self.air_tracks = {i: tr for i, tr in self.air_tracks.items() if i in aircraft}
        for i, t in aircraft.items():
            self._air_track(i, t, tuned, now)
        if not self._air_quiet(now):
            return []
        for wanted in ("handoff", "checkin", "level"):
            for i in sorted(aircraft):
                if out := self._air_exchange(wanted, aircraft[i], self.air_tracks[i], tuned):
                    self.air_chatter_at = now
                    return out
        return []

    def _air_track(self, i: int, t: Traffic, tuned: Station, now: float) -> None:
        track = self.air_tracks.get(i)
        if track is None:
            track = self.air_tracks[i] = Track(t.alt_ft, now)
        elif now > track.at:
            rate = (t.alt_ft - track.alt_ft) / (now - track.at) * 60
            track.rate_fpm, track.alt_ft, track.at = (track.rate_fpm + rate) / 2, t.alt_ft, now
        inside = self._in_area(tuned, t)
        if track.inside is not None and inside != track.inside:
            track.due, track.due_at = ("checkin" if inside else "handoff"), now
            track.cleared_ft = None  # a new controller: its own clearances
        track.inside = inside
        if track.due and now - track.due_at > DUE_FOR_S:
            track.due = None

    def _air_quiet(self, now: float) -> bool:
        if not self.chatter or self.pending or self.call_next is not None:
            return False  # never in the way of our own readback or check-in
        if self.last_radio_at is not None and now - self.last_radio_at < AIR_QUIET_S:
            return False
        return self.air_chatter_at is None or now - self.air_chatter_at >= AIR_CHATTER_GAP_S

    # --- the areas ---------------------------------------------------------------------------------------------

    def _terminal_airports(self) -> list[Airport]:
        return [a for a in (self.airport, self.destination) if a is not None]

    @staticmethod
    def _in_terminal(airport: Airport, t: Traffic) -> bool:
        return (distance_nm(airport.lat, airport.lon, t.lat, t.lon) <= TERMINAL_NM
                and t.alt_ft - airport.elevation_ft <= TERMINAL_TOP_FT)

    def _towers_traffic(self, t: Traffic) -> bool:
        s = self.picture.states.get(t.object_id)
        return s is not None and s.kind in ("final", "departing", "on_runway")

    def _in_area(self, station: Station, t: Traffic) -> bool:
        if t.on_ground or self._towers_traffic(t):
            return False
        if station.freq.role == "CTR":
            if any(self._in_terminal(a, t) for a in self._terminal_airports()):
                return False
            sector = self.centers.at(t.lat, t.lon, t.alt_ft)
            return sector is not None and center_station(sector).key == station.key
        airport = next((a for a in self._terminal_airports() if a.ident == station.ident), None)
        return airport is not None and station.freq.role in ("A", "D") and self._in_terminal(airport, t)

    def _next_station(self, t: Traffic, track: Track, tuned: Station) -> Station | None:
        """Who has it now that it has left the tuned controller's area."""
        s = self.picture.states.get(t.object_id)
        if s is not None and s.kind == "final":
            airport = next((a for a in self._terminal_airports() if a.ident == s.airport), None)
            return self._airport_station(airport, ("T",)) if airport else None
        for airport in self._terminal_airports():
            if self._in_terminal(airport, t):
                types = ("A", "D") if track.rate_fpm < 0 else ("D", "A")  # arrivals to Approach, departures to Departure
                found = self._airport_station(airport, types)
                return found if found is not None and found.key != tuned.key else None
        sector = self.centers.at(t.lat, t.lon, t.alt_ft)
        found = center_station(sector) if sector is not None and not sector.placeholder else None
        return found if found is not None and found.key != tuned.key else None

    @staticmethod
    def _airport_station(airport: Airport, types: tuple[str, ...]) -> Station | None:
        for kind in types:
            candidates = [f for f in airport.frequencies if f.role == kind]
            if candidates:
                return Station(airport.ident, min(candidates, key=lambda f: f.khz))
        return None

    # --- the exchanges -----------------------------------------------------------------------------------------

    def _air_exchange(self, wanted: str, t: Traffic, track: Track, tuned: Station) -> list[Response]:
        them, written = spoken_callsign(t), t.callsign
        if wanted == "handoff" and track.due == "handoff":
            track.due = None
            station = self._next_station(t, track, tuned)
            if station is None:
                return []
            frequency = spoken.frequency(station.freq.khz)
            return [Response(f"{them}, contact {station.name} {frequency}", spoken=True, kind="chatter",
                             station=tuned.name),
                    Response(f"{frequency}, {them}", spoken=True, kind="chatter", station=written)]
        if wanted == "checkin" and track.due == "checkin":
            track.due = None
            clearance = self._air_clearance(t, track, tuned)
            answer = ", ".join(filter(None, [them, tuned.name, "radar contact", self._expect_approach(t, tuned),
                                             clearance]))
            out = [Response(f"{tuned.name}, {them}, {level_words(t.alt_ft, track.rate_fpm)}", spoken=True,
                            kind="chatter", station=written),
                   Response(answer, spoken=True, kind="chatter", station=tuned.name)]
            if clearance:
                out.append(Response(f"{clearance}, {them}", spoken=True, kind="chatter", station=written))
            return out
        if wanted == "level" and track.inside and track.due is None:
            clearance = self._air_clearance(t, track, tuned)
            if clearance:
                return [Response(f"{them}, {clearance}", spoken=True, kind="chatter", station=tuned.name),
                        Response(f"{clearance}, {them}", spoken=True, kind="chatter", station=written)]
        return []

    def _air_clearance(self, t: Traffic, track: Track, tuned: Station) -> str | None:
        """A climb or descent a few thousand feet on, the way it really goes; None while it is level or still
        well short of its last cleared level."""
        rate = track.rate_fpm
        if abs(rate) < LEVEL_FPM:
            return None
        up = rate > 0
        if track.cleared_ft is not None:
            short = track.cleared_ft - t.alt_ft if up else t.alt_ft - track.cleared_ft
            if short > REACHED_FT:
                return None  # on its way to the last one
        if up:
            target = min(math.ceil((t.alt_ft + LEVEL_STEP_FT) / 1000) * 1000, MAX_LEVEL_FT)
        else:
            target = max(math.floor((t.alt_ft - LEVEL_STEP_FT) / 1000) * 1000, self._air_floor(tuned, t))
        if (target - t.alt_ft if up else t.alt_ft - target) < 500:
            return None
        track.cleared_ft = target
        verb = "climb" if up else "descend"
        return rb.level(target // 100, verb).phrase if target > TRANSITION_FT else rb.altitude(target, verb).phrase

    def _air_floor(self, tuned: Station, t: Traffic) -> int:
        if tuned.freq.role == "CTR":
            return CENTER_FLOOR_FT
        airport = next((a for a in self._terminal_airports() if a.ident == tuned.ident), None)
        elevation = airport.elevation_ft if airport else 0
        return math.ceil((elevation + 3000) / 1000) * 1000  # where the ILS starts

    def _expect_approach(self, t: Traffic, tuned: Station) -> str | None:
        """Approach tells an arrival what to expect: the runway the traffic lands on."""
        if tuned.freq.role != "A" or self.destination is None or tuned.ident != self.destination.ident:
            return None
        track = self.air_tracks.get(t.object_id)
        if track is None or track.rate_fpm > -LEVEL_FPM or not self.arrival_runway:
            return None
        end = self.destination.runway_end(self.arrival_runway)
        kind = "ILS" if end is not None and end.ils else "RNAV"
        return f"expect vectors {kind} approach runway {spoken.runway(self.arrival_runway)}"


def level_words(alt_ft: float, rate_fpm: float) -> str:
    """"flight level two four zero", or "passing flight level one two tree, climbing"."""
    level = abs(rate_fpm) < LEVEL_FPM
    step = 1000 if level and abs(alt_ft - round(alt_ft, -3)) < 200 else 100  # level at a round level: that one
    feet = max(100, round(alt_ft / step) * step)
    words = spoken.flight_level(feet) if feet > TRANSITION_FT else spoken.altitude(feet)
    return words if level else f"passing {words}, {'climbing' if rate_fpm > 0 else 'descending'}"

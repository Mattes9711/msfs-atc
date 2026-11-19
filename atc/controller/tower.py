"""Tower at both airports: line up, takeoff and landing clearances, waiting for the runway (traffic on it or
landing, the departure ahead, wake turbulence), vacating and the go-around. A part of Controller (atc/controller/
controller.py), split off to keep the files short; it uses the controller's state through self."""
import math

from atc.airport.geo import distance_nm, point_segment_distance
from atc.airport.model import Airport
from atc.controller import readback as rb
from atc.controller.give_way import traffic_name
from atc.controller import wake
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.controller.common import (CLOSE_PARALLEL_M, GO_AROUND_BELOW_AGL_FT, GO_AROUND_CLIMB_FT, INTERSECTION_MARGIN_M,
                                   LANDING_TRAFFIC_NM, LANDING_WAKE_S, NO_CLEARANCE_GO_AROUND_NM, OCCUPIED_GO_AROUND_NM,
                                   VFR_GO_AROUND_NM,
                                   ROLLING_KT, TURNED_DEG, WAKE_CAUTION_S, Response, Station, _wind)


class TowerMixin:
    def _line_up(self, station: Station) -> list[Response]:
        """On request: onto the runway and wait. Without other traffic ATC never needs it by itself (T2 will)."""
        if self.phase != "taxi":
            return self._takeoff(station)  # not taxiing yet / already cleared: the same answers as "ready"
        self.cleared_runways.add(self._runway_key(self.airport, self.runway))
        self.lined_up = True
        items = rb.line_up(self.runway)
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, " + rb.instruction_text(items))]

    def _intersection_on_runway(self, name: str) -> bool:
        """A taxiway of that name leads onto the departure runway: one of its ends lies on the runway."""
        rwy = next(r for r in self.airport.runways if self.runway in (r.ends[0].name, r.ends[1].name))
        a, b = (self.taxi.proj.xy(e.lat, e.lon) for e in rwy.ends)
        half_width = rwy.width_ft * 0.3048 / 2 + INTERSECTION_MARGIN_M
        return any(point_segment_distance(self.taxi.proj.xy(lat, lon), a, b) <= half_width
                   for p in self.airport.taxi_paths if p.name.upper() == name
                   for lat, lon in ((p.start_lat, p.start_lon), (p.end_lat, p.end_lon)))

    def _takeoff(self, station: Station, intersection: str | None = None) -> list[Response]:
        if intersection and self.phase == "taxi" and not self._intersection_on_runway(intersection):
            return [self._say(station, f"{self.cs}, {spoken.spell(intersection)} is not an intersection of runway "
                                       f"{spoken.runway(self.runway)}, say again")]
        if self.phase not in ("taxi", "takeoff"):
            ground = self.station("ground")
            if ground is not None and ground.key != station.key:
                return [self._say(station, f"{self.cs}, contact {ground.name} "
                                           f"{spoken.frequency(ground.freq.khz)} for taxi")]
            return [self._say(station, f"{self.cs}, request taxi first")]
        if self.phase == "taxi" and intersection:
            self.takeoff_intersection = intersection
        if self.phase == "taxi" and (busy := self._runway_traffic(self.airport, self.runway)
                                     or self._departure_spacing()):
            return self._wait_for_departure(station, busy)
        return self._takeoff_clearance(station, intersection or self.takeoff_intersection)

    def _wait_for_departure(self, station: Station, busy: str) -> list[Response]:
        """Behind a departure that is rolling or just airborne: line up and wait. Behind a heavier one: line up and
        wait for the wake turbulence time (L5). Landing traffic or someone standing on the runway: hold short.
        ATC gives the takeoff clearance by itself once the runway is free (_traffic_waits)."""
        self.departure_waiting = station
        wake_wait = busy == "wake turbulence"
        if wake_wait:
            self.wake_told = True
        if busy in ("departing traffic", "wake turbulence") and not self.lined_up:
            self.lined_up = True
            self.cleared_runways.add(self._runway_key(self.airport, self.runway))
            items = rb.line_up(self.runway)
            self._set_pending(items, station.key)
            if wake_wait:
                return [self._say(station, f"{self.cs}, {rb.instruction_text(items)}, {self._wake_wait()}")]
            return [self._say(station, f"{self.cs}, behind the departing {self._departing_name()}, "
                                       + rb.instruction_text(items))]
        if self.lined_up:
            self._hold_position(station)
            return [self._say(station, f"{self.cs}, hold position, "
                                       + (self._wake_wait() if wake_wait else f"{busy}, I will call you"))]
        item = rb.Item("hold_short", self.runway, f"hold short runway {spoken.runway(self.runway)}")
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, {item.phrase}, {busy}, I will call you")]

    def _takeoff_clearance(self, station: Station, intersection: str | None = None,
                           state: AircraftState | None = None) -> list[Response]:
        zone = self._ctr_exit_items() if self._ctr_departure() else []  # VFR: out of the zone (Milestone 9 E)
        items = rb.cleared_takeoff(self.runway)
        if intersection:
            items[0] = rb.Item("runway", self.runway, f"runway {spoken.runway(self.runway)} from intersection "
                                                      f"{spoken.spell(intersection)}")
        caution = None
        if (ahead := self._departure_ahead()) and ahead[1] and ahead[0].at is not None \
                and self.traffic_clock is not None and self.traffic_clock - ahead[0].at < WAKE_CAUTION_S:
            caution = f"caution wake turbulence from the departing {ahead[0].name.removeprefix('the ')}"
        elif landed := self._heavier_landing():
            caution = f"caution wake turbulence from the landing {landed.name.removeprefix('the ')}"
        self.phase = "takeoff"
        self.takeoff_intersection, self.wake_told = None, False
        self.cleared_runways.add(self._runway_key(self.airport, self.runway))
        self._set_pending(zone + items, station.key)
        text = f"{self.cs}, " + ", ".join(filter(None, [
            caution, rb.instruction_text(zone), _wind(self.metar), rb.instruction_text(items),
            self._ctr_report_text() if zone else None]))
        return self._transmit(station, text, state) if state else [self._say(station, text)]

    def _runway_traffic(self, airport: Airport, runway: str, final_nm: float = LANDING_TRAFFIC_NM) -> str | None:
        """Why the runway (any end name) isn't free, as ATC says it, or None. Our own aircraft is never in the
        traffic list."""
        key = self._runway_key(airport, runway)[1]
        if self.picture.on_final(airport.ident, key, final_nm, lambda end: self._runway_key(airport, end)[1]):
            return "landing traffic"
        on_it = self.picture.on_runway(airport.ident, key)
        if any(t.ground_speed_kt > ROLLING_KT for t in on_it):
            return "departing traffic"
        return "traffic on the runway" if on_it else None

    def _traffic_waits(self, state: AircraftState) -> list[Response]:
        """A runway (or the taxilane behind the stand) we are waiting for has become free: ATC calls the pilot by
        itself."""
        if self.push_waiting and not self._traffic_behind(state):
            station, self.push_waiting = self.push_waiting, None
            return self._pushback(station, state, called=True)
        if self.departure_waiting and self.phase == "taxi":
            busy = self._runway_traffic(self.airport, self.runway) or self._departure_spacing()
            if not busy:
                station, self.departure_waiting = self.departure_waiting, None
                return self._takeoff_clearance(station, self.takeoff_intersection, state=state)
            if busy == "wake turbulence" and not self.wake_told:
                self.wake_told = True
                return self._transmit(self.departure_waiting, f"{self.cs}, {self._wake_wait()}", state)
        if self.landing_waiting and self.phase == "final" and not self._runway_traffic(
                self.destination, self.arrival_runway, final_nm=0) and not self._ahead_in_sequence(state):
            station, self.landing_waiting = self.landing_waiting, None
            return self._landing_clearance(station, state)
        if self.crossing_waiting:
            station, airport, runway = self.crossing_waiting
            if not self._runway_traffic(airport, runway):
                self.crossing_waiting = None
                return self._cross(station, airport, runway, state)
        return []

    def _departure_ahead(self) -> tuple[wake.Departure, int] | None:
        """The last takeoff from our runway (either end) and the wake spacing in seconds we need behind it."""
        d = self.last_departure.get(self.airport.ident)
        if d is None or not (self._same_runway(d.end) or self._close_parallel(d.end)):
            return None
        ours = wake.category(self.plan.aircraft or "")
        return d, wake.departure_spacing_s(d.category, ours, bool(self.takeoff_intersection))

    def _heavier_landing(self) -> wake.Departure | None:
        """A heavier aircraft that landed on our runway (or a close parallel) within LANDING_WAKE_S (B5). ICAO has
        no time spacing for a takeoff behind a landing in the same direction (its wake ends where it touched down,
        and we lift off before that point), so Tower gives a caution; landing towards us, its wake lay over our
        climb-out, the caution covers that too."""
        d = self.last_landing.get(self.airport.ident)
        if d is None or d.at is None or self.traffic_clock is None:
            return None
        if self.traffic_clock - d.at > LANDING_WAKE_S or not (self._same_runway(d.end) or self._close_parallel(d.end)
                                                              or self._close_parallel(self._reciprocal(d.end))):
            return None
        return d if wake.departure_spacing_s(d.category, wake.category(self.plan.aircraft or "")) else None

    def _reciprocal(self, end: str) -> str:
        rwy = next((r for r in self.airport.runways if end in (r.ends[0].name, r.ends[1].name)), None)
        if rwy is None:
            return end
        return rwy.ends[1].name if rwy.ends[0].name == end else rwy.ends[0].name

    def _same_runway(self, end: str) -> bool:
        return self._runway_key(self.airport, end) == self._runway_key(self.airport, self.runway)

    def _close_parallel(self, end: str) -> bool:
        """That runway end points our way and its runway lies within CLOSE_PARALLEL_M of ours (EDDF 25C/25L)."""
        ours, theirs = self.airport.runway_end(self.runway), self.airport.runway_end(end)
        if ours is None or theirs is None or abs((ours.heading_true - theirs.heading_true + 540) % 360 - 180) > 30:
            return False
        rwy = next(r for r in self.airport.runways if self.runway in (r.ends[0].name, r.ends[1].name))
        (ax, ay), (bx, by) = (self.taxi.proj.xy(e.lat, e.lon) for e in rwy.ends)
        px, py = self.taxi.proj.xy(theirs.lat, theirs.lon)
        # Distance to our runway's centreline extended: staggered thresholds lie beyond its ends
        length = math.hypot(bx - ax, by - ay)
        return length > 0 and abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / length <= CLOSE_PARALLEL_M

    def _wake_left_s(self) -> float:
        """Seconds of wake turbulence spacing still to wait behind the last departure; 0 when none (or no clock)."""
        ahead = self._departure_ahead()
        if ahead is None or ahead[0].at is None or self.traffic_clock is None:
            return 0.0
        return max(0.0, ahead[1] - (self.traffic_clock - ahead[0].at))

    def _wake_wait(self) -> str:
        return f"expect departure in {wake.minutes(self._wake_left_s())}, wake turbulence"

    def _departure_spacing(self) -> str | None:
        """Why our takeoff still waits behind the last departure from our runway (L5), or None. First the wake
        turbulence time; then ICAO's runway separation: the one ahead has passed the far end or turned away."""
        if self._wake_left_s() > 0:
            return "wake turbulence"
        ahead = self._departure_ahead()
        if ahead and not self._same_runway(ahead[0].end):
            return None  # a close parallel: only the wake time, its runway is not ours
        t = self.picture.aircraft.get(ahead[0].object_id) if ahead else None
        if t is None or t.on_ground:
            return None  # gone from the traffic, or rolling (that is _runway_traffic's "departing traffic")
        start = self.airport.runway_end(ahead[0].end)
        rwy = next(r for r in self.airport.runways if ahead[0].end in (r.ends[0].name, r.ends[1].name))
        length_nm = distance_nm(rwy.ends[0].lat, rwy.ends[0].lon, rwy.ends[1].lat, rwy.ends[1].lon)
        past = distance_nm(start.lat, start.lon, t.lat, t.lon) > length_nm
        turned = abs((t.heading_true - start.heading_true + 540) % 360 - 180) > TURNED_DEG
        return None if past or turned else "departing traffic"

    def _departing_name(self) -> str:
        """"Lufthansa Airbus" for "behind the departing …": the one rolling on our runway, else the last takeoff."""
        key = self._runway_key(self.airport, self.runway)[1]
        rolling = [t for t in self.picture.on_runway(self.airport.ident, key) if t.ground_speed_kt > ROLLING_KT]
        if rolling:
            t = max(rolling, key=lambda t: t.ground_speed_kt)
            name = traffic_name(t.callsign, t.airline, t.model)
        else:
            ahead = self._departure_ahead()
            name = ahead[0].name if ahead else "the traffic"
        return name.removeprefix("the ")

    def _final_call(self, station: Station, state: AircraftState, auto: bool = False) -> list[Response]:
        """On final: the landing clearance, or "continue approach" while the runway is not free. auto: Tower calls
        by itself (a VFR flight seen turning final, Milestone 9 E)."""
        def say(text: str) -> list[Response]:
            return self._transmit(station, text, state) if auto else [self._say(station, text)]

        if self._ahead_in_sequence(state):  # landing clearance once it has landed and vacated (_traffic_waits)
            self.landing_waiting = station
            return say(f"{self.cs}, {station.name}, continue approach, {self._sequence(state)}")
        if busy := self._runway_traffic(self.destination, self.arrival_runway, final_nm=0):
            self.landing_waiting = station
            return say(f"{self.cs}, {station.name}, continue approach, {busy}, I will call you")
        return self._landing_clearance(station, state if auto else None)

    def _landing_clearance(self, station: Station, state: AircraftState | None = None) -> list[Response]:
        self.phase = "landing"
        self.cleared_runways.add(self._runway_key(self.destination, self.arrival_runway))
        items = rb.cleared_land(self.arrival_runway)
        self._set_pending(items, station.key)
        caution = None
        ours = wake.category(self.plan.aircraft or "")
        t = self.following
        if t and wake.approach_spacing_nm(wake.category(t.model, t.title), ours) > wake.RADAR_MIN_NM:
            caution = f"caution wake turbulence from the landing {traffic_name(t.callsign, t.airline, t.model)[4:]}"
        self.following, self.speed_step = None, 0
        text = f"{self.cs}, " + ", ".join(filter(None, [caution, _wind(self.destination_metar),
                                                       rb.instruction_text(items)]))
        return self._transmit(station, text, state) if state else [self._say(station, text)]

    def _vacate(self, station: Station, state: AircraftState) -> list[Response]:
        self.phase = "vacating"
        ground = self.station("arrival_ground")
        if ground is None or ground.key == station.key:
            return self._transmit(station, f"{self.cs}, vacate runway, request taxi when ready", state)
        item = rb.contact(ground.name, ground.freq.khz)
        self._set_pending([item], station.key, handoff_to=ground.key)
        return self._transmit(station, f"{self.cs}, vacate runway, {item.phrase}", state)

    def _go_around_check(self, state: AircraftState) -> list[Response]:
        """ATC sends the aircraft around when it is close in without a landing clearance, and notices a
        go-around the pilot didn't report (low on final, then climbing)."""
        if self.destination is None or self.phase not in ("approach", "final", "landing") or state.on_ground:
            return []
        if not self.destination.controlled:
            return []  # no landing clearance at a small field: nobody sends the aircraft around
        end = self.destination.runway_end(self.arrival_runway)
        if self.phase in ("final", "landing"):
            self.lowest_agl_on_final = min(self.lowest_agl_on_final, state.alt_agl_ft)
        to_threshold = distance_nm(state.lat, state.lon, end.lat, end.lon)
        # VFR in the circuit (Milestone 9 E) passes the threshold on downwind: only short final counts
        limit = (VFR_GO_AROUND_NM if self.phase == "final" else -1) if self._ctr_arrival() else NO_CLEARANCE_GO_AROUND_NM
        if self.phase != "landing" and to_threshold <= limit:
            station = self.station("arrival_tower" if self.phase == "final" else "approach")
            busy = self._runway_traffic(self.destination, self.arrival_runway, final_nm=0)
            self.landing_waiting = None
            return self._go_around(station, state, "go around, I say again, go around"
                                   + (", runway occupied" if busy else ""))
        if (self.phase == "landing" and to_threshold <= OCCUPIED_GO_AROUND_NM
                and self._runway_traffic(self.destination, self.arrival_runway, final_nm=0)):
            return self._go_around(self.station("arrival_tower"), state, "go around, I say again, go around, "
                                                                          "runway occupied")
        if (self.lowest_agl_on_final < GO_AROUND_BELOW_AGL_FT
                and state.alt_agl_ft > self.lowest_agl_on_final + GO_AROUND_CLIMB_FT):
            return [Response("go-around detected", spoken=False),
                    *self._go_around(self.station("arrival_tower"), state, None)]
        return []

    def _go_around(self, station: Station, state: AircraftState, prefix: str | None) -> list[Response]:
        """Simple missed approach: runway heading, climb, back to Approach for another approach."""
        dest = self.destination
        if self._ctr_arrival():  # VFR: round the circuit again (Milestone 9 E)
            item = self._join_item()
            self.phase, self.ctr_stage, self.landing_waiting = "approach", "joining", None
            self.lowest_agl_on_final = float("inf")
            self.cleared_runways.discard(self._runway_key(dest, self.arrival_runway))
            self._set_pending([item], station.key)
            return self._transmit(station, f"{self.cs}, " + ", ".join(filter(None, [
                prefix, item.phrase, "report downwind"])), state)
        end = dest.runway_end(self.arrival_runway)
        heading = round((end.heading_true - dest.mag_var) / 5) * 5 % 360 or 360  # ATC assigns 5-degree steps
        altitude = -(-(int(dest.elevation_ft) + 3000) // 1000) * 1000  # round up to 1000 ft
        items = [rb.heading(heading), rb.altitude(altitude)]
        approach = self.station("approach")
        handoff = approach is not None and approach.key != station.key
        if handoff:
            items.append(rb.contact(approach.name, approach.freq.khz))
        self.phase, self.vectoring, self.approach_cleared = "arrival", None, False  # the runway may change again
        self.transition_legs = None  # vectors after the go-around, not the transition again (Milestone 10 E)
        self.lowest_agl_on_final = float("inf")
        self.cleared_runways.discard(self._runway_key(dest, self.arrival_runway))
        self._set_pending(items, station.key, handoff_to=approach.key if handoff else None)
        # No Approach to check in with (EDDW, EDDN): the Tower vectors again by itself once the aircraft has climbed
        self.vectors_due = None if handoff else station
        text = f"{self.cs}, " + ", ".join(filter(None, [prefix, rb.instruction_text(items)]))
        return self._transmit(station, text, state)

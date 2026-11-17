"""The other aircraft as ATC sees them: the traffic picture updated, takeoffs and landings noted (for wake
turbulence), the runways in use taken from the traffic, traffic information and the other pilots' radio calls.
A part of Controller (atc/controller/controller.py), split off to keep the files short; it uses the controller's
state through self."""
from atc.airport.geo import bearing_deg, distance_nm
from atc.airport.model import Airport
from atc.controller.give_way import traffic_name
from atc.controller import wake
from atc.controller.arrival import plan_arrival, spoken_arrival
from atc.controller.traffic import TRAFFIC_FORGET_NM, runway_end_for, spoken_callsign, traffic_information
from atc.sim.traffic import Traffic
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.controller.common import AIR_PHASES, PHASES, TRAFFIC_INFO_GAP_S, Response, Station, _wind


class TrafficMixin:
    def update_traffic(self, traffic: list[Traffic], now: float | None = None,
                       last_radio: float | None = None) -> list[Response]:
        """The other aircraft from the sim, every few seconds (the live loop). Returns ATC calls about them.
        `now`: the live clock, for the time between departures (L5); without it there is no wake spacing.
        `last_radio`: when the radio was last busy, so the chatter in the air waits for a quiet one (G)."""
        self.traffic_clock, self.last_radio_at = now, last_radio
        places = [(self.airport, self.zones)]
        if self.destination is not None:
            self._arrival_graph()
            places.append((self.destination, self._arrival_zones))
        self.transitions = self.picture.update(traffic, places)
        self.runway_use.record(self.transitions, [a for a, _ in places])
        self._record_departures(now)
        changed = self._runways_from_traffic()
        return changed + (self._traffic_information(traffic) or self._chatter(places))

    def _record_departures(self, now: float | None) -> None:
        """Takeoffs (on the runway → departing) at our departure airport: who and when, for the wake spacing."""
        for tr in self.transitions:
            t, before, after = tr.aircraft, tr.before, tr.after
            if before and before.kind == "on_runway" and after.kind == "departing" and after.airport == self.airport.ident:
                self.last_departure[self.airport.ident] = wake.Departure(
                    t.object_id, runway_end_for(self.airport, after.runway, t.heading_true), now,
                    wake.category(t.model, t.title), traffic_name(t.callsign, t.airline, t.model))
            if before and before.kind == "final" and after.kind == "on_runway" and after.airport == self.airport.ident:
                self.last_landing[self.airport.ident] = wake.Departure(
                    t.object_id, runway_end_for(self.airport, after.runway, t.heading_true), now,
                    wake.category(t.model, t.title), traffic_name(t.callsign, t.airline, t.model))

    def _traffic_runway(self, airport: Airport, kind: str, current: str | None) -> str | None:
        """The runway end the real traffic uses there (L2), or None when it shows none."""
        finals = [s.runway for s in self.picture.states.values() if s.kind == "final" and s.airport == airport.ident]
        return self.runway_use.in_use(airport, kind, finals, current)

    def _runways_from_traffic(self) -> list[Response]:
        """Real aircraft land and depart on the real runway: use it too, or ATC sends the pilot head-on into them.
        Same limits as a new METAR: the departure runway only before the clearance, the arrival runway until the
        approach clearance (Milestone 8, B1: it froze at the first call to Approach, before the traffic near the
        destination could be seen, and the test flight was sent to 26L while the traffic landed on 26R)."""
        notes = []
        end = self._traffic_runway(self.airport, "departure", self.runway) if self.phase == "clearance" else None
        if end and end != self.runway:
            self.runway = end
            self.atis.update(self.metar, self.runway)
            notes.append(Response(f"{self.airport.ident} runway in use now {end}, as the traffic uses it "
                                  f"(ATIS information {self.atis.letter})", spoken=False))
        before_approach = (self.destination is not None and not self.approach_cleared
                           and PHASES.index(self.phase) <= PHASES.index("approach"))
        end = self._traffic_runway(self.destination, "arrival", self.arrival_runway) if before_approach else None
        if end and end != self.arrival_runway and (not self.descent_given or self._reversed(end)):
            before, self.arrival_runway = self.arrival_runway, end
            self._note_runway_change(before)
            notes.append(Response(f"{self.destination.ident} landing runway now {end}, as the traffic uses it",
                                  spoken=False))
        return notes

    def _reversed(self, end: str) -> bool:
        """The runway end points the other way than the one the arrival is planned for (26L after 08R): only that
        changes the runway once the descent is given (Milestone 10 B; the 2026-11-17 flight was moved from 26L to
        the parallel 26R ten minutes before landing, only because the traffic used it)."""
        new, old = self.destination.runway_end(end), self.destination.runway_end(self.arrival_runway)
        if new is None or old is None:
            return True
        return abs((new.heading_true - old.heading_true + 180) % 360 - 180) > 90

    def _note_runway_change(self, before: str | None) -> None:
        """After the descent clearance named the STAR, a new landing runway is told by radio (B3): the STAR may be
        for the old one, and Approach vectors to the new one anyway. The arrival is planned again for it."""
        if before and before != self.arrival_runway and self.descent_given:
            self.runway_change = self.arrival_runway
            old_star = self.arrival.star_name if self.arrival else None
            self.arrival = plan_arrival(self.destination, self.arrival_runway, self.plan, self.procedures)
            self.star_changed = self.arrival.star_name is not None and self.arrival.star_name != old_star

    def _runway_change_call(self, state: AircraftState) -> list[Response]:
        station = self.expected_station()
        if self.runway_change is None or station is None or self.phase not in ("climb", "enroute", "arrival"):
            return []
        end = self.destination.runway_end(self.runway_change)
        self.runway_change = None
        runway = spoken.runway(self.arrival_runway)
        if self.arrival and self.arrival.star_name and self.star_changed:
            # A new STAR for the new direction: "cleared Landu two Alfa arrival" (Milestone 10 B)
            star = spoken_arrival(self.arrival, self.plan)
            return self._transmit(station, f"{self.cs}, runway change, cleared {star}, expect "
                                           f"{self.arrival.approach_kind} approach runway {runway}", state)
        kind = self.arrival.approach_kind if self.arrival else ("ILS" if end is not None and end.ils else "RNAV")
        return self._transmit(station, f"{self.cs}, runway change, expect vectors {kind} approach runway {runway}",
                              state)

    def _chatter(self, places) -> list[Response]:
        """What the other aircraft and our controller say to each other (T4), on the frequency the pilot is tuned
        to, from what they really did since the last update: one exchange at a time, nothing is made up."""
        state = self.state
        tuned = self.station_at(state.com1_khz) if self.chatter and state else None
        if tuned is None:
            return []
        if tuned.freq.role == "FSS":
            return self._circuit_chatter(tuned)  # Info: the position reports in the circuit (Milestone 9 C2)
        if tuned.freq.role not in ("T", "G", "APRON"):
            return self._air_chatter(tuned)  # Departure, Approach, Center (atc/controller/air_chatter.py)
        airport = next((a for a, _ in places if a.ident == tuned.ident), None)
        if airport is None:
            return []
        metar = self.metar if airport is self.airport else self.destination_metar
        active = self.runway if airport is self.airport else self.arrival_runway
        for tr in sorted(self.transitions, key=lambda tr: tr.aircraft.object_id):
            t, before, after = tr.aircraft, tr.before, tr.after
            if after.airport != airport.ident or before is None:
                continue
            them, written = spoken_callsign(t), t.callsign
            # Each call once per aircraft: AI aircraft stop and go while taxiing (at holding points, behind others),
            # and every start looked like a new "request taxi" (the user's flight: SUBURBAN 7534 three times)
            event = ("final" if tuned.freq.role == "T" and after.kind == "final" and before.kind != "final" else
                     "takeoff" if tuned.freq.role == "T" and after.kind == "on_runway" and after.aligned
                     and before.kind in ("taxiing", "parked", "on_runway") else  # crossing is not lining up
                     "taxi" if tuned.freq.role in ("G", "APRON") and after.kind == "taxiing"
                     and before.kind == "parked" and active else None)
            if event is None or (t.callsign, event) in self.chatter_said:
                continue
            self.chatter_said.add((t.callsign, event))  # LiveTraffic may re-create it
            if event == "final":
                key = self._runway_key(airport, after.runway)[1]
                busy = [o for o in self.picture.on_runway(airport.ident, key) if o.object_id != t.object_id]
                answer = (f"{them}, continue approach" if busy else f"{them}, " + ", ".join(filter(None, [
                    _wind(metar), f"runway {spoken.runway(after.runway)}, cleared to land"])))
                return self._exchange(written, f"{tuned.name}, {them}, established ILS runway "
                                               f"{spoken.runway(after.runway)}", tuned, answer)
            if event == "takeoff":
                end = runway_end_for(airport, after.runway, t.heading_true)
                answer = f"{them}, " + ", ".join(filter(None, [_wind(metar), f"runway {spoken.runway(end)}, "
                                                                             f"cleared for takeoff"]))
                return [Response(answer, spoken=True, kind="chatter", station=tuned.name),
                        Response(f"runway {spoken.runway(end)}, cleared for takeoff, {them}", spoken=True,
                                 kind="chatter", station=written)]
            return self._exchange(written, f"{tuned.name}, {them}, request taxi", tuned,
                                  f"{them}, taxi to holding point runway {spoken.runway(active)}")
        return []

    @staticmethod
    def _exchange(pilot: str, call: str, station: Station, answer: str) -> list[Response]:
        """An AI pilot's call and the controller's answer."""
        return [Response(call, spoken=True, kind="chatter", station=pilot),
                Response(answer, spoken=True, kind="chatter", station=station.name)]

    def _traffic_information(self, traffic: list[Traffic]) -> list[Response]:
        """Close traffic in the air (T3), once per aircraft, from the controller we are talking to. Told again only
        after it was farther than TRAFFIC_FORGET_NM."""
        state = self.state
        here = [t for t in traffic if state and distance_nm(state.lat, state.lon, t.lat, t.lon) <= TRAFFIC_FORGET_NM]
        self.traffic_told &= {t.object_id for t in here}
        if state is None or state.on_ground or self.phase not in AIR_PHASES:
            return []
        station = self.expected_station()
        if station is None:
            return []
        now = self.traffic_clock
        if now is not None and self.traffic_info_at is not None and now - self.traffic_info_at < TRAFFIC_INFO_GAP_S:
            return []  # at most one a minute (B4: three in 20 s on the test flight's final)
        heading_true = (state.heading_mag + self.current_airport().mag_var) % 360
        near_airport = self.phase in ("final", "landing")
        for t in sorted(here, key=lambda t: distance_nm(state.lat, state.lon, t.lat, t.lon)):
            if t.object_id in self.traffic_told:
                continue
            behind = abs((bearing_deg(state.lat, state.lon, t.lat, t.lon) - heading_true + 540) % 360 - 180) > 110
            s = self.picture.states.get(t.object_id)
            if near_airport and (behind or (s and s.kind in ("final", "departing", "on_runway"))):
                continue  # on final: not the traffic behind, nor the airport's own landing and departing traffic
            if info := traffic_information(t, state.lat, state.lon, state.alt_msl_ft, heading_true):
                self.traffic_told.add(t.object_id)
                self.traffic_info_at = now
                return self._transmit(station, f"{self.cs}, {info}", state)
        return []

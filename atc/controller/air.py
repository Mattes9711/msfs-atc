"""In the air: handoffs, Departure and Center (levels, direct-to, sectors, the descent), Approach (vectors, the ILS,
the sequence and speed control). A part of Controller (atc/controller/controller.py), split off to keep the files
short; it uses the controller's state through self."""
import math

from atc.airport.geo import bearing_deg, distance_nm
from atc.controller import readback as rb
from atc.controller.give_way import traffic_name
from atc.controller import vectors, wake
from atc.sim.traffic import M_PER_NM, Traffic
from atc.controller.arrival import entry_fix, plan_arrival, spoken_arrival
from atc.flightplan.route import first_fix
from atc.flightplan.track import flying_to, track_to_go_nm
from atc.intent.schema import Intent
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.units import format_khz
from atc.controller.common import (APPROACH_SPEED_KT, CENTER_HANDOFF_FT, CENTER_HANDOFF_NM, CLOSE_PARALLEL_M,
                                   CLOSING_KT, DEPARTURE_CEILING_FL, DESCENT_CHECK_S, DESCENDING_FT,
                                   LEVEL_REACHED_FT, DESCENT_ALTITUDE_FT, DESCENT_FL, DESCENT_LEAD_NM,
                                   VECTOR_ALLOWANCE_NM,
                                   DESCENT_MARGIN_NM, DIRECT_MAX_NM, FINAL_CONE_DEG, FINAL_CONE_NM, FINAL_FIX_NM,
                                   FINAL_SPEED_KT, GAP_SHRINK_NM, INTERCEPT_ANGLE, MAX_FL,
                                   ON_COURSE_DEG, PATTERN_AGL_FT, PATTERN_NM, SHORTCUTS, SHORTCUT_MIN_NM,
                                   SHORTCUT_SKIPS, CENTER_TURNS_FT,
                                   SPACING_SPEED_KT, SPEED_CONTROL_UNTIL_NM, VFR_SQUAWK, Response,
                                   Station, center_station)


class AirMixin:
    def _handoff(self, from_role: str, to_role: str, next_phase: str, state: AircraftState) -> list[Response]:
        return self._hand_over(self.station(from_role), self.station(to_role), next_phase, state,
                               missing=f"no {to_role.replace('_', ' ')} frequency in the airport data")

    def _hand_over(self, sender: Station | None, receiver: Station | None, next_phase: str, state: AircraftState,
                   missing: str = "") -> list[Response]:
        self.phase = next_phase
        if receiver is None:
            return [Response(missing, spoken=False)]
        if sender is not None and sender.key == receiver.key:
            # No Approach (EDDW, EDDN): the Tower vectored the aircraft itself and must not hand it to itself. The
            # emulator's flights waited for a check-in that never came and were sent around (2026-11-19).
            return self._final_call(sender, state, auto=True) if next_phase == "final" else []
        item = rb.contact(receiver.name, receiver.freq.khz)
        self.call_next = receiver
        if sender is None:
            return [Response(f"{item.phrase}", spoken=False)]
        self._set_pending([item], sender.key, handoff_to=receiver.key)
        return self._transmit(sender, f"{self.cs}, {item.phrase}", state)

    def _radar_contact(self, station: Station) -> list[Response]:
        """Departure: climb (with Center sectors only up to FL240: Center gives the cruise level), direct to the
        first waypoint after the SID."""
        self.phase = "climb"
        items = []
        if self.plan.cruise_ft and self.plan.cruise_ft > 5000:
            fl = self.plan.cruise_ft // 100
            items.append(rb.level(min(fl, DEPARTURE_CEILING_FL) if self.centers else fl))
        if fix := first_fix(self.plan.route):
            items.append(rb.direct(fix))
        self._set_pending(items, station.key)
        return [self._say(station, ", ".join([f"{self.cs}, {station.name}, radar contact", *(i.phrase for i in items)]))]

    def _cleared_ft(self) -> int | None:
        """The last level or altitude given, in feet."""
        level = self.cleared_level or ""
        if level.startswith("FL"):
            return int(level[2:]) * 100
        return int(level.split()[0]) if level else None

    def _route_ahead(self, state: AircraftState) -> list:
        """Plan waypoints (route and STAR) still ahead: closer to the destination than the aircraft."""
        if self.destination is None or not self.plan.waypoints:
            return []
        dest = self.destination
        to_go = distance_nm(state.lat, state.lon, dest.lat, dest.lon)
        return [w for w in self.plan.waypoints if w.leg != "sid"
                and distance_nm(w.lat, w.lon, dest.lat, dest.lon) < to_go - 1]

    def _en_route_ahead(self, state: AircraftState) -> list:
        """The route points ahead up to the arrival's entry fix (LANDU), not past it: what Center may send the
        aircraft direct to before the descent (Milestone 10 C)."""
        points = [w for w in self.plan.waypoints if w.leg != "sid"]
        entry = entry_fix(self.plan, self.procedures)
        last = next((i for i, w in enumerate(points) if w.ident == entry), None)
        en_route = {id(w) for w in (points if last is None else points[:last + 1]) if w.leg == "route"}
        return [w for w in self._route_ahead(state) if id(w) in en_route]

    def _next_route_points(self, state: AircraftState) -> list:
        """In the plan's order, the waypoint the aircraft flies to (the fix it was sent direct to) and the ones after
        it up to the arrival's entry fix: a direct-to the k-th of them leaves out k points (the user, 2026-11-21)."""
        dest = (self.destination.lat, self.destination.lon)
        points = list(self.plan.waypoints)
        idents = [w.ident for w in points]
        to = flying_to(self.plan.waypoints, dest, state.lat, state.lon)
        if self.direct_fix in idents[to:]:  # straight to it: the points before it are left out already
            to = idents.index(self.direct_fix, to)
        entry = entry_fix(self.plan, self.procedures)
        last = idents.index(entry) if entry in idents[to:] else len(points) - 1
        return [w for w in points[to:last + 1] if w.leg != "star"]

    def _arrival_ahead(self, state: AircraftState) -> set[str]:
        """The fixes ahead on the arrival cleared with the descent: the STAR and the transition to the approach
        from Little Navmap, else the plan's STAR points and its entry fix."""
        dest = self.destination
        to_go = distance_nm(state.lat, state.lon, dest.lat, dest.lon)
        if self.arrival and self.arrival.star:
            legs = self.arrival.star.legs + (self.arrival.transition.legs if self.arrival.transition else ())
            return {leg.ident for leg in legs if leg.ident and leg.lat is not None
                    and distance_nm(leg.lat, leg.lon, dest.lat, dest.lon) < to_go - 1}
        entry = entry_fix(self.plan, self.procedures)
        return {w.ident for w in self._route_ahead(state) if w.leg == "star" or w.ident == entry}

    def _center_check_in(self, station: Station, state: AircraftState) -> list[Response]:
        """First call to a Center: identified, the rest of the climb to the cruise level, and a direct-to: the
        farthest route point ahead within DIRECT_MAX_NM (a shortcut, as Center often gives)."""
        items = []
        cleared, cruise = self._cleared_ft(), self.plan.cruise_ft
        if cruise and (cleared is None or cleared < cruise) and not self.descent_given:
            items.append(rb.level(cruise // 100))
        if fix := self._shortcut(state):
            items.append(rb.direct(fix))
        self._set_pending(items, station.key)
        return [self._say(station, ", ".join([f"{self.cs}, {station.name}, identified", *(i.phrase for i in items)]))]

    def _shortcut(self, state: AircraftState) -> str | None:
        """A direct-to Center gives on the check-in, only as a real shortcut (Milestone 8, A2, the user: "1-2 real
        shortcuts a flight"; the test flight got one at every check-in, Zucka and Landu twice): of the next route
        points, leaving out at most SHORTCUT_SKIPS (the user, 2026-11-21), the one within DIRECT_MAX_NM that saves
        most against the way the aircraft flies now, at least SHORTCUT_MIN_NM; at most SHORTCUTS a flight, never
        the fix already given.
        Only en route (Milestone 10 C; the test flight got "direct Landu" at the Frankfurt check-in, which cut the
        top of descent away): never after the descent, never past the STAR's first fix, never to it above
        CENTER_TURNS_FT, and only when the track left after it still reaches to the top of descent."""
        if self.shortcuts >= SHORTCUTS or self.destination is None or self.descent_given:
            return None
        dest = (self.destination.lat, self.destination.lon)
        now, room = self._track_to_go_nm(state), self._top_of_descent_nm(state)
        ahead = self._next_route_points(state)
        entry = entry_fix(self.plan, self.procedures) if state.alt_msl_ft > CENTER_TURNS_FT else None
        left = {w.ident: track_to_go_nm(self.plan.waypoints, dest, state.lat, state.lon, w.ident)
                for w in ahead[:SHORTCUT_SKIPS + 1] if w.leg == "route" and w.ident not in (self.direct_fix, entry)
                and distance_nm(state.lat, state.lon, w.lat, w.lon) <= DIRECT_MAX_NM}
        saved = {fix: now - miles for fix, miles in left.items() if miles >= room}
        fix = max(saved, key=saved.get, default=None)
        if fix is None or saved[fix] < SHORTCUT_MIN_NM:
            return None
        self.shortcuts += 1
        return fix

    def _level_request(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        """"request higher" (to the cruise level) or "request flight level 370" (up or down)."""
        fl = intent.items.get("flight_level")
        cruise = self.plan.cruise_ft
        target = fl * 100 if fl else (cruise if cruise and (self._cleared_ft() or 0) < cruise else None)
        if target is None:
            return [self._say(station, f"{self.cs}, say requested level")]
        if target > MAX_FL * 100:
            return [self._say(station, f"{self.cs}, unable {spoken.flight_level(target)}, maximum "
                                       f"{spoken.flight_level(MAX_FL * 100)}")]
        item = rb.level(target // 100, "climb" if target > state.alt_msl_ft else "descend")
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, {item.phrase}")]

    def _direct_request(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        """Direct to a waypoint of the plan that is still ahead: en route a route point up to the STAR's first fix,
        after the descent only a fix ahead on the arrival cleared (Milestone 10 C: not off the arrival route).
        Without waypoints (manual plan) any fix written in the route is accepted: there are no positions to check."""
        fix = intent.items["direct"]
        on_arrival = self.descent_given and self.destination is not None
        if not self.plan.waypoints:
            known = set(self.plan.route.upper().split())
        elif on_arrival:
            known = self._arrival_ahead(state)
        else:
            known = {w.ident for w in self._en_route_ahead(state)}
        if fix not in known:
            where = "arrival" if on_arrival and self.plan.waypoints else "route"
            return [self._say(station, f"{self.cs}, unable direct {fix.title()}, not ahead on your {where}")]
        item = rb.direct(fix)
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, {item.phrase}")]

    def _center_progress(self, state: AircraftState) -> list[Response]:
        """Departure -> Center once out of the terminal area, then Center -> Center at each sector boundary.
        Meant to run every second (tick). A sector whose frequency is not known never gets the aircraft."""
        if self.call_next is not None or (self.pending and self.handoff_to):
            # Handed over, and the pilot hasn't checked in yet: no second handoff on top (found in the user's flight:
            # Approach → Bremen 125.100, and 12 s later Bremen 125.100 → 119.825 before the pilot was there)
            return []
        if self.phase == "climb":
            from_origin = distance_nm(state.lat, state.lon, self.airport.lat, self.airport.lon)
            if state.alt_msl_ft < CENTER_HANDOFF_FT and from_origin < CENTER_HANDOFF_NM:
                return []
            sender = self.station("departure")
        else:
            sender = self.center
        sector = self.centers.at(state.lat, state.lon, state.alt_msl_ft)
        if sector is None:
            if self.phase == "enroute" and sender is None:
                return []  # radar service already terminated
            return self._radar_service_terminated(sender, state)
        if sector.placeholder:
            return []  # nobody to hand over to: whoever has the aircraft keeps it
        station = center_station(sector)
        if self.phase == "enroute" and sender is None:
            self.center = station  # back inside a sector after radar service was terminated
            return [Response(f"now inside {sector.name} airspace ({sector.fir}): call {station.name} on "
                             f"{format_khz(station.freq.khz)} for radar service", spoken=False)]
        if sender is not None and station.key == sender.key:
            return []
        self.previous_center, self.center = self.center, station
        return self._hand_over(sender, station, "enroute", state)

    def _radar_service_terminated(self, sender: Station | None, state: AircraftState) -> list[Response]:
        """Outside every known sector: nobody to hand the aircraft to."""
        self.phase, self.center = "enroute", None
        item = rb.squawk(VFR_SQUAWK)
        text = f"radar service terminated, {item.phrase}, frequency change approved"
        if sender is None:
            return [Response(text, spoken=False)]
        self.squawk = VFR_SQUAWK
        self._set_pending([item], sender.key)
        return self._transmit(sender, f"{self.cs}, {text}", state)

    def _track_to_go_nm(self, state: AircraftState) -> float:
        """Along the planned route (SID, airways, STAR) to the destination; straight there without one."""
        return track_to_go_nm(self.plan.waypoints, (self.destination.lat, self.destination.lon),
                              state.lat, state.lon, self.direct_fix)

    def _path_to_go_nm(self, state: AircraftState) -> float:
        """The miles the aircraft will really fly to the field: the planned route, but at most VECTOR_ALLOWANCE_NM
        more than straight there, as Approach vectors off a long STAR (the user's flight to EDDH: NOLG3P loops about
        45 nm north-east and back; counted along it the descent came 48 nm from the field at FL320, Approach then
        vectored straight in and the aircraft was still at FL220 12 nm out). Compared with _top_of_descent_nm.
        Shorter still when the vectors to the landing runway are (atc/controller/vectors.py path_nm): the emulator's
        flight from the south to EDDH 05 was turned in at about straight + 7 nm and came 1560 ft high at 10 nm."""
        straight = distance_nm(state.lat, state.lon, self.destination.lat, self.destination.lon)
        path = min(self._track_to_go_nm(state), straight + VECTOR_ALLOWANCE_NM)
        end = self.destination.runway_end(self.arrival_runway) if self.arrival_runway else None
        return min(path, vectors.path_nm(end, state.lat, state.lon)) if end else path

    def descent_due_in_nm(self, state: AircraftState) -> float:
        """How far ahead the descent point is (<= 0: due now). For the airport the way left as Approach vectors it
        (_path_to_go_nm); for the STAR's constraints the planned track, as the fixes before them are flown."""
        return min(self._path_to_go_nm(state) - self._airport_descent_nm(state),
                   self._track_to_go_nm(state) - self._constraint_descent_nm(state))

    def _top_of_descent_nm(self, state: AircraftState) -> float:
        """Track miles to go at which the descent is given at the latest, for the airport or the STAR's constraints
        (what a direct-to must leave, _shortcut)."""
        return max(self._airport_descent_nm(state), self._constraint_descent_nm(state))

    def _airport_descent_nm(self, state: AircraftState) -> float:
        """Miles to go at which the descent is given for the airport: DESCENT_LEAD_NM before the top of descent.
        With SimBrief's TOD (what the FMC plans): its track miles to go, moved 3 nm earlier per 1000 ft the aircraft
        cruises above the level SimBrief plans there (after a step descent lower than the cruise level). Without it
        the 3-in-1 rule: 3 nm per 1000 ft to lose, plus a margin to be down before the approach."""
        if self.plan.tod is not None:
            planned = self.plan.tod_ft or self.plan.cruise_ft
            top = max(state.alt_msl_ft, planned or 0)  # already lower: the point must not move back
            tod = track_to_go_nm(self.plan.waypoints, (self.destination.lat, self.destination.lon), *self.plan.tod)
            above = (top - (planned or top)) / 1000 * 3
            return max(0.0, tod + above) + DESCENT_LEAD_NM
        top = max(state.alt_msl_ft, self.plan.cruise_ft or 0)
        return max(0.0, top - DESCENT_ALTITUDE_FT) / 1000 * 3 + DESCENT_MARGIN_NM

    def _expected_arrival(self):
        """The arrival as it would be planned now for the landing runway (fixed with the descent, Milestone 10 B);
        None without Little Navmap's procedures. Kept until the runway or the procedures change."""
        if self.arrival is not None or self.procedures is None or self.destination is None:
            return self.arrival
        runway, procedures, arrival = self.arrival_preview or (None, None, None)
        if arrival is None or runway != self.arrival_runway or procedures is not self.procedures:
            arrival = plan_arrival(self.destination, self.arrival_runway, self.plan, self.procedures)
            self.arrival_preview = (self.arrival_runway, self.procedures, arrival)
        return arrival

    def _constraint_descent_nm(self, state: AircraftState) -> float:
        """Track miles to go at which the descent must come to meet the STAR's "at or below" constraints (Milestone
        10 D: LANDU at or below FL100), by the 3-in-1 rule from the level flown now, plus DESCENT_LEAD_NM."""
        arrival = self._expected_arrival()
        if arrival is None or arrival.star is None:
            return 0.0
        dest, top = (self.destination.lat, self.destination.lon), max(state.alt_msl_ft, self.plan.cruise_ft or 0)
        need = [track_to_go_nm(self.plan.waypoints, dest, leg.lat, leg.lon) + (top - leg.ceiling_ft) / 1000 * 3
                for leg in arrival.star.legs if leg.ceiling_ft and leg.lat is not None and top > leg.ceiling_ft]
        return max(need) + DESCENT_LEAD_NM if need else 0.0

    def _descent_level_ft(self) -> int:
        """Center's descent: to FL100, lower when the STAR's first fix must be crossed lower (Milestone 10 D)."""
        arrival = self._expected_arrival()
        first = arrival.star.legs[0] if arrival and arrival.star and arrival.star.legs else None
        if first is None or not first.ceiling_ft:
            return DESCENT_FL * 100
        return min(DESCENT_FL * 100, first.ceiling_ft // 100 * 100)

    def _descent(self, station: Station | None, state: AircraftState) -> list[Response]:
        if self.descent_given or self.destination is None or station is None:
            return [self._say(station, f"{self.cs}, roger")] if station else []
        self.descent_given = True
        # The landing runway is fixed now, with the STAR and the approach that fit it (Milestone 10 B)
        self.arrival = plan_arrival(self.destination, self.arrival_runway, self.plan, self.procedures)
        star = spoken_arrival(self.arrival, self.plan)
        level_ft = self._descent_level_ft()
        if state.alt_msl_ft > level_ft + 1000 and level_ft > DESCENT_ALTITUDE_FT:
            # In steps: Center to FL100 (and the arrival route); Approach gives the altitude and the QNH
            items = [rb.level(level_ft // 100, "descend")]
        else:
            items = [rb.altitude(DESCENT_ALTITUDE_FT, self._verb(DESCENT_ALTITUDE_FT, state))]
            if self.destination_metar and self.destination_metar.qnh_hpa:
                items.append(rb.qnh(self.destination_metar.qnh_hpa))
        self._set_pending(items, station.key)
        # The STAR is said, but not a readback item yet: whisper writes procedure names too differently to compare
        text = ", ".join([rb.instruction_text(items), *([f"cleared {star}"] if star else []),
                          f"expect {self.arrival.approach_kind} approach runway {spoken.runway(self.arrival_runway)}"])
        return self._transmit(station, f"{self.cs}, {text}", state)

    @staticmethod
    def _verb(feet: int, state: AircraftState) -> str:
        """"climb" to an altitude above the aircraft: a short flight (EDDM-EDDN at FL240) is still climbing when
        the descent comes, and an aircraft checks in low after a go-around (the emulator, 2026-11-19)."""
        return "climb" if state.alt_msl_ft < feet - 200 else "descend"

    def _watch_descent(self, item: rb.Item) -> None:
        """A level or altitude given: a descent is watched until the aircraft is there, a climb ends the watch."""
        feet = item.value * 100 if item.key == "flight_level" else item.value
        if item.phrase.startswith("descend "):
            if self.descent_watch is None or self.descent_watch[0] != feet:
                self.descent_watch = (feet, item, None, False)
        elif item.phrase.startswith("climb "):
            self.descent_watch = None

    def _descent_check(self, state: AircraftState, now: float | None) -> list[Response]:
        """The aircraft doesn't leave its level after a descent (Milestone 10 D): "confirm descending altitude four
        thousand fife hundred feet", once per descent, read back like the descent. Only with the live clock."""
        if self.descent_watch is None or now is None or state.on_ground:
            return []
        feet, item, since, asked = self.descent_watch
        if state.alt_msl_ft <= feet + LEVEL_REACHED_FT:
            self.descent_watch = None
            return []
        if since is None or since[1] - state.alt_msl_ft >= DESCENDING_FT:
            self.descent_watch = (feet, item, (now, state.alt_msl_ft), asked)
            return []
        station = self.expected_station()
        if asked or now - since[0] < DESCENT_CHECK_S or station is None:
            return []
        self.descent_watch = (feet, item, since, True)
        confirm = rb.Item(item.key, item.value, "confirm descending " + item.phrase.removeprefix("descend "))
        self._set_pending([confirm], station.key)
        return self._transmit(station, f"{self.cs}, {confirm.phrase}", state)

    def _final_geometry(self, state: AircraftState) -> tuple:
        """(runway end, final course true, distance to the threshold, side): side > 0 = left of the final course
        when facing the runway, so the intercept heading is the course + 30; side < 0 = the course - 30."""
        end = self.destination.runway_end(self.arrival_runway)
        outbound = (end.heading_true + 180) % 360
        offset = (bearing_deg(end.lat, end.lon, state.lat, state.lon) - outbound + 540) % 360 - 180
        return end, end.heading_true, distance_nm(end.lat, end.lon, state.lat, state.lon), offset

    def _on_final(self, state: AircraftState) -> bool:
        _, _, dist, offset = self._final_geometry(state)
        return dist <= FINAL_CONE_NM and abs(offset) <= FINAL_CONE_DEG

    def _magnetic(self, true_heading: float) -> int:
        """True → magnetic, in the 5-degree steps ATC uses, 360 instead of 000."""
        return round((true_heading - self.destination.mag_var) / 5) * 5 % 360 or 360

    def _vectors(self, station: Station, state: AircraftState) -> list[Response]:
        """First call to Approach: altitude with the QNH, a speed and the first heading of the radar vectors
        (atc/controller/vectors.py), which _vector_progress then follows to the localizer. Already in the final cone
        (e.g. /final in practice mode): the approach clearance at once."""
        if self._on_final(state):
            return self._approach_clearance(station, state)
        if calls := self._start_transition(station, state):  # the transition flown, vectors at its end (Milestone 10 E)
            return calls
        self.phase, self.vectoring, self.vector_own, self.vectors_due = "approach", station, False, None
        end = self.destination.runway_end(self.arrival_runway)
        heading = self._first_vector(end, state)
        items = [rb.altitude(self._approach_altitude(), self._verb(self._approach_altitude(), state))]
        if self.destination_metar and self.destination_metar.qnh_hpa:
            items.append(rb.qnh(self.destination_metar.qnh_hpa))
        items += [*([rb.speed(APPROACH_SPEED_KT)] if self._speeds_given() else []), rb.heading(heading)]
        self._set_pending(items, station.key)
        approach_type = "ILS" if end.ils else "RNAV"
        return [self._say(station, f"{self.cs}, {station.name}, " + rb.instruction_text(items) +
                          f", vectors {approach_type} approach runway {spoken.runway(end.name)}")]

    def _own_vectors(self, state: AircraftState) -> list[Response]:
        """The Tower that also works the approach, after a go-around: the vectors a check-in would have started,
        called by the controller (only heard on its frequency)."""
        station, self.vectors_due = self.vectors_due, None
        return [heard for r in self._vectors(station, state)
                for heard in (self._transmit(station, r.text, state) if r.spoken else [r])]

    def _first_vector(self, end, state: AircraftState) -> int:
        """The first leg: far out in front of the runway and near the final a 30-degree intercept heading, else to
        the base point (a downwind, or from far beside in front a long base; Milestone 10 F). Returns the magnetic
        heading and remembers the leg."""
        along, across = vectors.frame(end, state.lat, state.lon)
        self.vector_side, self.vector_at = vectors.side_of(across), None
        self.vector_inbound = along > vectors.BASE_ALONG_NM
        if vectors.straight_in(along, across):
            self.vector_leg = "base"
            true = (end.heading_true + INTERCEPT_ANGLE * self.vector_side) % 360
        else:
            self.vector_leg = "downwind"
            true = bearing_deg(state.lat, state.lon, *vectors.base_point(end, across))
        self.vector_heading = self._magnetic(true)
        return self.vector_heading

    def _vector_progress(self, state: AircraftState, now: float | None) -> list[Response]:
        """Every tick while vectored: the base turn at the base point, the intercept and the approach clearance
        near the centreline (or across it), and a corrected heading when the way to the base point drifts."""
        station = self.vectoring
        end = self.destination.runway_end(self.arrival_runway)
        along, across = vectors.frame(end, state.lat, state.lon)
        crossed =vectors.side_of(across) != self.vector_side and abs(across) > 0.2
        if self._on_final(state) or (self.vector_leg == "base" and (
                abs(across) <= vectors.INTERCEPT_ACROSS_NM or crossed)):
            self.vectoring, self.vector_leg = None, None
            return self._approach_clearance(station, state, intercept=True)
        if self.vector_leg == "downwind" and self.vector_own:
            # The transition's downwind: only the base turn, later with traffic ahead (Milestone 10 E)
            if along >= self._base_along_nm(state) - vectors.BASE_TURN_LEAD_NM:
                return self._base_turn(station, state, end, across, now)
            return []
        if self.vector_leg == "downwind":
            base = vectors.base_point(end, self.vector_side * vectors.DOWNWIND_NM)
            # Going out on the downwind: the turn 1 nm before the base point's distance, the turn's radius takes the
            # aircraft there (Milestone 10 G: within 2 nm of the point it came at 10 nm and met the localizer 7.8 nm
            # out). Coming in from in front: at the base point, or abeam it.
            if self.vector_inbound:
                level = (along <= vectors.BASE_ALONG_NM or
                         distance_nm(state.lat, state.lon, *base) <= vectors.BASE_WITHIN_NM)
            else:
                level = along >= vectors.BASE_ALONG_NM - vectors.BASE_TURN_LEAD_NM
            if level:
                return self._base_turn(station, state, end, across, now)
            wanted = self._magnetic(bearing_deg(state.lat, state.lon, *base))
            off = abs((wanted - self.vector_heading + 540) % 360 - 180)
            waited = now is None or self.vector_at is None or now - self.vector_at >= vectors.CORRECT_EVERY_S
            near = distance_nm(state.lat, state.lon, *base) <= vectors.CORRECT_NEAR_NM
            if off >= vectors.CORRECT_DEG and waited and not near:
                return self._give_vector(station, state, bearing_deg(state.lat, state.lon, *base), now)
        return []

    def _base_turn(self, station: Station, state: AircraftState, end, across: float, now: float | None):
        """The base turn, or, from a downwind close beside the centreline, the intercept heading and the approach
        clearance at once: the turn towards the centreline, the way round the base leg would have gone."""
        if vectors.base_too_short(across):
            self.vectoring, self.vector_leg = None, None
            towards = "left" if vectors.side_of(across) > 0 else "right"
            return self._approach_clearance(station, state, intercept=True, turn=towards)
        self.vector_leg = "base"
        return self._give_vector(station, state, vectors.base_heading_true(end, self.vector_side), now)

    def _give_vector(self, station: Station, state: AircraftState, true_heading: float, now: float | None):
        """"turn left heading two six zero", read back like every heading."""
        heading = self._magnetic(true_heading)
        if heading == self.vector_heading:
            return []
        item = rb.heading(heading, vectors.turn_direction(state.heading_mag, heading))
        self.vector_heading, self.vector_at = heading, now
        self._set_pending([item], station.key)
        return self._transmit(station, f"{self.cs}, {item.phrase}", state)

    def _speeds_given(self) -> bool:
        """Approach gives speeds (220 knots on the vectors, 180 on the intercept, the STAR's limits) only to aircraft
        that fly them: a light aircraft (wake category L: C172, PA28, DA40) flies 90 to 120 knots and is left at its
        own speed, as controllers do. An unknown type counts as an airliner."""
        return wake.category(self.plan.aircraft or "") != "L"

    def _approach_altitude(self) -> int:
        """The altitude for the vectors to the final: the approach's final approach fix altitude (EDDM ILS 26R:
        5000 ft, Milestone 10 D), else 3000 ft above the airport, rounded up to 100 ft."""
        elevation = int(self.destination.elevation_ft)
        arrival = self._expected_arrival()
        faf = arrival.approach.faf if arrival and arrival.approach else None
        faf_ft = (faf.floor_ft or faf.alt_ft) if faf else None
        if faf_ft and elevation + 1000 <= faf_ft <= elevation + 6000:
            return faf_ft
        return -(-(elevation + 3000) // 100) * 100

    def _approach_clearance(self, station: Station, state: AircraftState, intercept: bool = False,
                            turn: str | None = None) -> list[Response]:
        """Cleared for the approach: after vectors with a turn onto the localizer (30 degrees to the course, from the
        side the aircraft is on) and the final speed; straight in when already on final. `turn` fixes the direction
        of the turn (from the downwind more than 150 degrees, the short way round would turn away from the final)."""
        self.phase, self.approach_cleared = "approach", True
        end, course, _, offset = self._final_geometry(state)
        approach_type = "ILS" if end.ils else "RNAV"
        cleared = rb.Item("runway", end.name, f"cleared {approach_type} approach runway {spoken.runway(end.name)}")
        sequence = f"{seq}, " if (seq := self._sequence(state)) else ""  # "number two, traffic to follow …"
        speed = [rb.speed(FINAL_SPEED_KT)] if self._speeds_given() else []
        if intercept and abs(offset) <= ON_COURSE_DEG:  # already on the localizer: no turn needed
            items = [cleared, *speed]
            self._set_pending(items, station.key)
            return self._transmit(station, f"{self.cs}, {sequence}" + rb.instruction_text(items), state)
        if intercept:
            target = self._magnetic(course + (INTERCEPT_ANGLE if offset > 0 else -INTERCEPT_ANGLE))
            if target == self.vector_heading and abs((target - state.heading_mag + 540) % 360 - 180) <= 10:
                # Already on the intercept heading (a straight-in): no turn, only the clearance (Milestone 10 F)
                items = [cleared, *speed]
                text = (f"{self.cs}, {sequence}maintain {spoken.altitude(self._approach_altitude())} until "
                        f"established, " + ", ".join(i.phrase for i in items))
                self._set_pending(items, station.key)
                return self._transmit(station, text, state)
            turn = turn or vectors.turn_direction(state.heading_mag, target)
            items = [rb.heading(target, turn), cleared, *speed]
            text = (f"{self.cs}, {sequence}{items[0].phrase}, maintain {spoken.altitude(self._approach_altitude())} "
                    f"until established, " + ", ".join(i.phrase for i in items[1:]))
            self._set_pending(items, station.key)
            return self._transmit(station, text, state)
        return self._direct_approach_clearance(station, state, sequence)

    def _ahead_on_final(self, state: AircraftState) -> list[tuple[float, Traffic]]:
        """(distance to the threshold, aircraft) on final for our landing runway end and closer to it than we are:
        the one just ahead of us first."""
        end = self.destination.runway_end(self.arrival_runway)
        ours = distance_nm(end.lat, end.lon, state.lat, state.lon)
        ahead = [(s.distance_nm, self.picture.aircraft[i]) for i, s in self.picture.states.items()
                 if s.kind == "final" and s.airport == self.destination.ident and s.runway == self.arrival_runway
                 and s.distance_nm < ours]
        return sorted(ahead, key=lambda a: -a[0])

    def _ahead_in_sequence(self, state: AircraftState) -> list[tuple[float, Traffic, str]]:
        """(track miles to the threshold, aircraft, "final" | "base" | "downwind") of the arrivals ahead of us, the
        one just ahead first (B6). On final: its distance. In the pattern (low and close, not a departure climbing
        out): the way to join the final where it is level with it, plus the final from there."""
        end = self.destination.runway_end(self.arrival_runway)
        ours = distance_nm(end.lat, end.lon, state.lat, state.lon)
        ahead = [(nm, t, "final") for nm, t in self._ahead_on_final(state)]
        outbound = (end.heading_true + 180) % 360
        for i, s in self.picture.states.items():
            t = self.picture.aircraft[i]
            if s.kind != "airborne" or s.airport != self.destination.ident or t.atc_id in self.picture.departed:
                continue
            dist = distance_nm(end.lat, end.lon, t.lat, t.lon)
            if dist > PATTERN_NM or t.alt_ft - self.destination.elevation_ft > PATTERN_AGL_FT:
                continue
            off = math.radians(bearing_deg(end.lat, end.lon, t.lat, t.lon) - outbound)
            along, across = max(3.0, dist * math.cos(off)), abs(dist * math.sin(off))
            if self._for_a_parallel(end, t, across):
                continue  # flying the pattern for the other runway (B2: EDDM 26R's arrivals made us "number six")
            track = math.hypot(along - dist * math.cos(off), across) + along
            if track < ours:
                turn = abs((t.heading_true - end.heading_true + 540) % 360 - 180)
                where = "final" if turn <= 45 else "downwind" if turn >= 135 else "base"
                ahead.append((track, t, where))
        return sorted(ahead, key=lambda a: -a[0])

    def _for_a_parallel(self, end, t: Traffic, across_nm: float) -> bool:
        """Nearer to the extended centreline of another runway end pointing the same way (an independent parallel,
        not a close one under CLOSE_PARALLEL_M) than to ours: it will land there."""
        for rwy in self.destination.runways:
            for other in rwy.ends:
                if other.name == end.name or abs((other.heading_true - end.heading_true + 540) % 360 - 180) > 30:
                    continue
                apart = _line_distance_nm(end, other.lat, other.lon) * M_PER_NM
                if apart < CLOSE_PARALLEL_M:
                    continue
                if _line_distance_nm(other, t.lat, t.lon) < across_nm:
                    return True
        return False

    def _sequence(self, state: AircraftState) -> str | None:
        """"number two, traffic to follow Lufthansa Airbus on four mile final" (L6), or None with nobody ahead.
        Remembers whom we follow, for speed control and the wake turbulence caution on landing."""
        ahead = self._ahead_in_sequence(state)
        if not ahead:
            return None
        nm, t, where = ahead[0]
        if self.following is None or self.following.object_id != t.object_id:
            self.following, self.speed_step = t, 0
        name = traffic_name(t.callsign, t.airline, t.model).removeprefix("the ")
        number = spoken.digits(len(ahead) + 1)
        position = f"{spoken.digits(max(1, round(nm)))} mile final" if where == "final" else where
        if name == "traffic":  # no airline or type known: not "traffic to follow traffic on downwind" (B3)
            return f"number {number}, traffic to follow on {position}"
        return f"number {number}, traffic to follow {name} on {position}"

    def _speed_control(self, state: AircraftState) -> list[Response]:
        """Catching up with the aircraft ahead on final, closer than the spacing (3 NM, more behind a heavier one):
        first "reduce speed one six zero knots", then "reduce to final approach speed". Not inside 4 NM."""
        end = self.destination.runway_end(self.arrival_runway)
        ours = distance_nm(end.lat, end.lon, state.lat, state.lon)
        ahead = self._ahead_on_final(state)
        if ours <= SPEED_CONTROL_UNTIL_NM or not ahead or state.on_ground:
            return []
        nm, t = ahead[0]
        if self.following is None or self.following.object_id != t.object_id:
            self.following, self.speed_step = t, 0
        need = wake.approach_spacing_nm(wake.category(t.model, t.title), wake.category(self.plan.aircraft or ""))
        if ours - nm >= need or state.ground_speed_kt <= t.ground_speed_kt + CLOSING_KT or self.speed_step >= 2:
            return []
        station = self.station("approach" if self.phase == "approach" else "arrival_tower")
        if station is None:
            return []
        if self.speed_step == 1 and ours - nm > self.speed_gap - GAP_SHRINK_NM:
            return []  # told to slow down: give it time, again only if the gap keeps shrinking
        self.speed_step += 1
        self.speed_gap = ours - nm
        if self.speed_step == 1 and state.ground_speed_kt > SPACING_SPEED_KT + CLOSING_KT:
            item = rb.speed(SPACING_SPEED_KT)
            self._set_pending([item], station.key)
            return self._transmit(station, f"{self.cs}, reduce {item.phrase}, traffic ahead", state)
        self.speed_step = 2
        return self._transmit(station, f"{self.cs}, reduce to final approach speed, traffic ahead", state)

    def _direct_approach_clearance(self, station: Station, state: AircraftState,
                                   sequence: str = "") -> list[Response]:
        self.phase, self.approach_cleared = "approach", True
        end = self.destination.runway_end(self.arrival_runway)
        approach_type = "ILS" if end.ils else "RNAV"
        # "climb" after a go-around without Approach: the Tower clears it again from below
        items = [rb.altitude(self._approach_altitude(), self._verb(self._approach_altitude(), state))]
        if self.destination_metar and self.destination_metar.qnh_hpa:
            items.append(rb.qnh(self.destination_metar.qnh_hpa))  # below the transition level: altitudes on QNH
        items.append(rb.Item("runway", end.name,
                             f"cleared {approach_type} approach runway {spoken.runway(end.name)}"))
        text = (f"{self.cs}, {station.name}, {sequence}proceed direct to {spoken.digits(FINAL_FIX_NM)} miles final "
                f"runway {spoken.runway(end.name)}, " + rb.instruction_text(items))
        self._set_pending(items, station.key)
        return [self._say(station, text)]


def _line_distance_nm(end, lat: float, lon: float) -> float:
    """How far (lat, lon) is beside the infinite centreline through a runway end, in nm."""
    dist = distance_nm(end.lat, end.lon, lat, lon)
    off = math.radians(bearing_deg(end.lat, end.lon, lat, lon) - end.heading_true)
    return abs(dist * math.sin(off))

"""In the air: handoffs, Departure and Center (levels, direct-to, sectors, the descent), Approach (vectors, the ILS,
the sequence and speed control). A part of Controller (atc/controller/controller.py), split off to keep the files
short; it uses the controller's state through self."""
import math

from atc.airport.geo import bearing_deg, destination_point, distance_nm
from atc.airspace.centers import PLACEHOLDER, CenterSector
from atc.controller import readback as rb
from atc.controller.give_way import traffic_name
from atc.controller import wake
from atc.sim.traffic import Traffic
from atc.flightplan.route import first_fix, spoken_star
from atc.flightplan.track import track_to_go_nm
from atc.intent.schema import Intent
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.units import format_khz
from atc.controller.common import (APPROACH_SPEED_KT, CENTER_HANDOFF_FT, CENTER_HANDOFF_NM, CLOSING_KT,
                                   DEPARTURE_CEILING_FL, DESCENT_ALTITUDE_FT, DESCENT_FL, DESCENT_LEAD_NM,
                                   DESCENT_MARGIN_NM,
                                   DIRECT_MAX_NM, SHORTCUTS, SHORTCUT_MIN_NM, FINAL_CONE_DEG, FINAL_CONE_NM, FINAL_FIX_NM, FINAL_SPEED_KT,
                                   GAP_SHRINK_NM, INTERCEPT_ANGLE, INTERCEPT_WITHIN_NM, MAX_FL, ON_COURSE_DEG,
                                   PATTERN_AGL_FT, PATTERN_NM, SPACING_SPEED_KT, SPEED_CONTROL_UNTIL_NM,
                                   VECTOR_POINT_NM, VFR_SQUAWK, Response, Station, center_station)


class AirMixin:
    def _handoff(self, from_role: str, to_role: str, next_phase: str, state: AircraftState) -> list[Response]:
        return self._hand_over(self.station(from_role), self.station(to_role), next_phase, state,
                               missing=f"no {to_role.replace('_', ' ')} frequency in the airport data")

    def _hand_over(self, sender: Station | None, receiver: Station | None, next_phase: str, state: AircraftState,
                   missing: str = "") -> list[Response]:
        self.phase = next_phase
        if receiver is None:
            return [Response(missing, spoken=False)]
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
        shortcuts a flight"; the test flight got one at every check-in, Zucka and Landu twice): of the route points
        ahead within DIRECT_MAX_NM the one that saves most against the way the aircraft flies now, at least
        SHORTCUT_MIN_NM; at most SHORTCUTS a flight, never the fix already given, never into the STAR."""
        if self.shortcuts >= SHORTCUTS or self.destination is None:
            return None
        dest = (self.destination.lat, self.destination.lon)
        now = self._track_to_go_nm(state)
        saved = {w.ident: now - track_to_go_nm(self.plan.waypoints, dest, state.lat, state.lon, w.ident)
                 for w in self._route_ahead(state) if w.leg == "route" and w.ident != self.direct_fix
                 and distance_nm(state.lat, state.lon, w.lat, w.lon) <= DIRECT_MAX_NM}
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
        """Direct to a waypoint of the plan that is still ahead. Without waypoints (manual plan) any fix written in
        the route is accepted, because there are no positions to check."""
        fix = intent.items["direct"]
        known = ({w.ident for w in self._route_ahead(state)} if self.plan.waypoints
                 else set(self.plan.route.upper().split()))
        if fix not in known:
            return [self._say(station, f"{self.cs}, unable direct {fix.title()}, not ahead on your route")]
        item = rb.direct(fix)
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, {item.phrase}")]

    def _center_progress(self, state: AircraftState) -> list[Response]:
        """Departure -> Center once out of the terminal area, then Center -> Center at each sector boundary.
        Meant to run every second (tick). A sector whose frequency is a placeholder never gets the aircraft."""
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
            return self._placeholder_hint(sector, sender)
        station = center_station(sector)
        if self.phase == "enroute" and sender is None:
            self.center = station  # back inside a sector after radar service was terminated
            return [Response(f"now inside {sector.name} airspace ({sector.fir}): call {station.name} on "
                             f"{format_khz(station.freq.khz)} for radar service", spoken=False)]
        if sender is not None and station.key == sender.key:
            return []
        self.center = station
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

    def _placeholder_hint(self, sector: CenterSector, keeper: Station | None) -> list[Response]:
        if sector in self.placeholder_warned:
            return []
        self.placeholder_warned.add(sector)
        keeps = f"{keeper.name} keeps you" if keeper else "no controller until then"
        return [Response(f"you are in {sector.name} airspace ({sector.fir}), but its frequency is {PLACEHOLDER} in "
                         f"{self.centers.source}: please fill in the real frequency. No handoff, {keeps}",
                         spoken=False)]

    def _track_to_go_nm(self, state: AircraftState) -> float:
        """Along the planned route (SID, airways, STAR) to the destination; straight there without one."""
        return track_to_go_nm(self.plan.waypoints, (self.destination.lat, self.destination.lon),
                              state.lat, state.lon, self.direct_fix)

    def _top_of_descent_nm(self, state: AircraftState) -> float:
        """Track miles to go at which the descent is given: DESCENT_LEAD_NM before the top of descent.
        With SimBrief's TOD (what the FMC plans): its track miles to go, moved 3 nm per 1000 ft the aircraft
        cruises above (earlier) or below (later) the planned level. Without it the 3-in-1 rule: 3 nm per 1000 ft
        to lose, plus a margin to be down before the approach."""
        top = max(state.alt_msl_ft, self.plan.cruise_ft or 0)  # already lower: the point must not move back
        if self.plan.tod is not None:
            tod = track_to_go_nm(self.plan.waypoints, (self.destination.lat, self.destination.lon), *self.plan.tod)
            above = (top - (self.plan.cruise_ft or top)) / 1000 * 3
            return max(0.0, tod + above) + DESCENT_LEAD_NM
        return max(0.0, top - DESCENT_ALTITUDE_FT) / 1000 * 3 + DESCENT_MARGIN_NM

    def _descent(self, station: Station | None, state: AircraftState) -> list[Response]:
        if self.descent_given or self.destination is None or station is None:
            return [self._say(station, f"{self.cs}, roger")] if station else []
        self.descent_given = True
        star = spoken_star(self.plan.route, self.plan.star) if self.plan.route or self.plan.star else None
        if state.alt_msl_ft > DESCENT_FL * 100 + 1000:
            # In steps: Center to FL100 (and the arrival route); Approach gives the altitude and the QNH
            items = [rb.level(DESCENT_FL, "descend")]
        else:
            items = [rb.altitude(DESCENT_ALTITUDE_FT, "descend")]
            if self.destination_metar and self.destination_metar.qnh_hpa:
                items.append(rb.qnh(self.destination_metar.qnh_hpa))
        self._set_pending(items, station.key)
        # The STAR is said, but not a readback item yet: whisper writes procedure names too differently to compare
        text = ", ".join([rb.instruction_text(items), *([f"cleared {star}"] if star else [])])
        return self._transmit(station, f"{self.cs}, {text}", state)

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
        """First call to Approach: altitude with the QNH, a speed and a heading towards a point on the extended
        centreline; the approach clearance follows near that point (_intercept). Already in the final cone (e.g.
        /final in practice mode): the approach clearance at once."""
        if self._on_final(state):
            return self._approach_clearance(station, state)
        self.phase, self.vectoring = "approach", station
        end, course, _, _ = self._final_geometry(state)
        point = destination_point(end.lat, end.lon, (course + 180) % 360, VECTOR_POINT_NM)
        heading = self._magnetic(bearing_deg(state.lat, state.lon, *point))
        items = [rb.altitude(self._approach_altitude(), "descend")]
        if self.destination_metar and self.destination_metar.qnh_hpa:
            items.append(rb.qnh(self.destination_metar.qnh_hpa))
        items += [rb.speed(APPROACH_SPEED_KT), rb.heading(heading)]
        self._set_pending(items, station.key)
        approach_type = "ILS" if end.ils else "RNAV"
        return [self._say(station, f"{self.cs}, {station.name}, " + rb.instruction_text(items) +
                          f", vectors {approach_type} approach runway {spoken.runway(end.name)}")]

    def _intercept(self, state: AircraftState) -> list[Response]:
        end, course, _, offset = self._final_geometry(state)
        point = destination_point(end.lat, end.lon, (course + 180) % 360, VECTOR_POINT_NM)
        if distance_nm(state.lat, state.lon, *point) > INTERCEPT_WITHIN_NM and not self._on_final(state):
            return []
        station, self.vectoring = self.vectoring, None
        return self._approach_clearance(station, state, intercept=True)

    def _approach_altitude(self) -> int:
        return -(-(int(self.destination.elevation_ft) + 3000) // 100) * 100  # round up to 100 ft

    def _approach_clearance(self, station: Station, state: AircraftState, intercept: bool = False) -> list[Response]:
        """Cleared for the approach: after vectors with a turn onto the localizer (30 degrees to the course, from the
        side the aircraft is on) and the final speed; straight in when already on final."""
        self.phase = "approach"
        end, course, _, offset = self._final_geometry(state)
        approach_type = "ILS" if end.ils else "RNAV"
        cleared = rb.Item("runway", end.name, f"cleared {approach_type} approach runway {spoken.runway(end.name)}")
        sequence = f"{seq}, " if (seq := self._sequence(state)) else ""  # "number two, traffic to follow …"
        if intercept and abs(offset) <= ON_COURSE_DEG:  # already on the localizer: no turn needed
            items = [cleared, rb.speed(FINAL_SPEED_KT)]
            self._set_pending(items, station.key)
            return self._transmit(station, f"{self.cs}, {sequence}" + rb.instruction_text(items), state)
        if intercept:
            target = self._magnetic(course + (INTERCEPT_ANGLE if offset > 0 else -INTERCEPT_ANGLE))
            turn = "right" if (target - state.heading_mag + 540) % 360 - 180 > 0 else "left"
            items = [rb.heading(target, turn), cleared, rb.speed(FINAL_SPEED_KT)]
            text = (f"{self.cs}, {sequence}{items[0].phrase}, maintain {spoken.altitude(self._approach_altitude())} "
                    f"until established, {cleared.phrase}, {items[2].phrase}")
            self._set_pending(items, station.key)
            return self._transmit(station, text, state)
        return self._direct_approach_clearance(station, sequence)

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
            track = math.hypot(along - dist * math.cos(off), across) + along
            if track < ours:
                turn = abs((t.heading_true - end.heading_true + 540) % 360 - 180)
                where = "final" if turn <= 45 else "downwind" if turn >= 135 else "base"
                ahead.append((track, t, where))
        return sorted(ahead, key=lambda a: -a[0])

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

    def _direct_approach_clearance(self, station: Station, sequence: str = "") -> list[Response]:
        self.phase = "approach"
        end = self.destination.runway_end(self.arrival_runway)
        approach_type = "ILS" if end.ils else "RNAV"
        altitude = -(-(int(self.destination.elevation_ft) + 3000) // 100) * 100  # round up to 100 ft
        items = [rb.altitude(altitude, "descend")]
        if self.destination_metar and self.destination_metar.qnh_hpa:
            items.append(rb.qnh(self.destination_metar.qnh_hpa))  # below the transition level: altitudes on QNH
        items.append(rb.Item("runway", end.name,
                             f"cleared {approach_type} approach runway {spoken.runway(end.name)}"))
        text = (f"{self.cs}, {station.name}, {sequence}proceed direct to {spoken.digits(FINAL_FIX_NM)} miles final "
                f"runway {spoken.runway(end.name)}, " + rb.instruction_text(items))
        self._set_pending(items, station.key)
        return [self._say(station, text)]

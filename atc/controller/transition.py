"""The approach transition flown by the pilot, followed by Approach (Milestone 10 E).

Munich ILS 26R, transition LANDU: LANDU, DM411, DM422, DM429 (the downwind), then "FM": from DM429 on the downwind
course until Approach turns the aircraft base. Approach's first call clears the transition ("cleared transition
Landu, expect ILS approach runway two six right") instead of giving a heading; then it follows the aircraft from fix
to fix and gives the altitudes ("descend altitude five thousand feet") and speeds ("reduce speed two two zero
knots") in time for the fixes ahead. At the end of the transition the radar vectors take over: on the downwind the
base turn (later with traffic ahead, the "trombone"), then the intercept (atc/controller/air.py _vector_progress).
A transition flown to its end without vectors ends in the approach clearance.

An aircraft far off the transition (not flying it, or a runway change) gets the radar vectors as before.
A part of Controller (atc/controller/controller.py), split off to keep the files short; it uses the controller's
state through self.
"""
from atc.airport.geo import LocalProjection, distance_nm, point_segment_distance
from atc.airport.procedures import Leg
from atc.controller import readback as rb
from atc.controller import vectors, wake
from atc.controller.arrival import Arrival
from atc.controller.common import Response, Station
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.sim.traffic import M_PER_NM

OFF_PATH_NM = 6  # farther than this beside the transition: not flying it, radar vectors instead
PASSED_NM = 1.5  # this close to a fix: passed (the FMC turns before it)
SPEED_AHEAD_NM = 12  # a speed limit this close ahead: "reduce speed …" now
CLEARANCE_AHEAD_NM = 8  # a transition without vectors: the approach clearance this far before its end
STAR_SPEED_KT = 250  # what the aircraft flies when Approach takes it: the speed below FL100
TROMBONE_MAX_NM = 25  # the downwind is made longer for traffic ahead, up to this far out


def path_legs(arrival: Arrival) -> list[Leg]:
    """The fixes Approach follows: the STAR's up to the transition's first fix, then the transition's up to the
    fix the vectors start at (included). Legs without a position are left out."""
    transition = arrival.transition
    star = list(arrival.star.legs) if arrival.star else []
    start = next((i for i, leg in enumerate(star) if leg.ident == transition.name), len(star))
    legs = star[:start] + list(transition.legs)
    end = next((i for i, leg in enumerate(legs) if leg.vectors and i >= start), len(legs) - 1)
    return [leg for leg in legs[:end + 1] if leg.lat is not None]


def later_legs(arrival: Arrival) -> list[Leg]:
    """After the path, down to the final approach fix: the transition's legs after the vectors and the approach's
    up to the FAF. Their lowest altitudes still count for the altitude Approach gives."""
    legs = list(arrival.transition.legs)
    start = next((i + 1 for i, leg in enumerate(legs) if leg.vectors), len(legs))
    approach = list(arrival.approach.legs) if arrival.approach else []
    faf = arrival.approach.faf if arrival.approach else None
    upto = approach.index(faf) + 1 if faf in approach else 0
    return legs[start:] + approach[:upto]


def nearest(points: list[tuple[float, float]], lat: float, lon: float) -> tuple[int, float]:
    """(the index of the fix the aircraft flies to, how far beside the path it is in nm): the end of the leg it is
    nearest to; before the first leg the first fix."""
    proj = LocalProjection(lat, lon)
    here, xy = proj.xy(lat, lon), [proj.xy(*p) for p in points]
    best = (0, distance_nm(lat, lon, *points[0]))
    for i in range(1, len(points)):
        off = point_segment_distance(here, xy[i - 1], xy[i]) / M_PER_NM
        if off < best[1]:
            best = (i, off)
    return best


def passed(before: tuple[float, float], fix: tuple[float, float], lat: float, lon: float) -> bool:
    """Close to the fix, or beyond it seen from the point before it."""
    if distance_nm(lat, lon, *fix) <= PASSED_NM:
        return True
    proj = LocalProjection(*fix)
    (ax, ay), (bx, by) = proj.xy(*before), proj.xy(lat, lon)
    return ax * bx + ay * by < 0  # the fix lies between them


def off_path_nm(before: tuple[float, float], fix: tuple[float, float], lat: float, lon: float) -> float:
    proj = LocalProjection(lat, lon)
    return point_segment_distance(proj.xy(lat, lon), proj.xy(*before), proj.xy(*fix)) / M_PER_NM


class TransitionMixin:
    def _start_transition(self, station: Station, state: AircraftState) -> list[Response]:
        """Approach's first call when the arrival has a transition and the aircraft is on its way along it:
        altitude, QNH, a speed when one is due, "cleared transition …". [] when it can't be flown (then vectors)."""
        arrival = self.arrival
        if (arrival is None or arrival.transition is None or self.transition_flown
                or arrival.runway != self.arrival_runway):
            return []
        legs = path_legs(arrival)
        if not legs:
            return []
        target, off = nearest([(leg.lat, leg.lon) for leg in legs], state.lat, state.lon)
        if off > OFF_PATH_NM:
            return []
        self.phase, self.transition_flown, self.transition_station = "approach", True, station
        self.transition_legs, self.transition_at = legs, target
        self.transition_from = (state.lat, state.lon) if target == 0 else (legs[target - 1].lat, legs[target - 1].lon)
        self.transition_alt, self.transition_speed = None, None
        items = self._transition_items(state)
        if self.destination_metar and self.destination_metar.qnh_hpa:
            at = 1 if items and items[0].key == "altitude_ft" else 0
            items.insert(at, rb.qnh(self.destination_metar.qnh_hpa))
        self._set_pending(items, station.key)
        text = ", ".join([*(i.phrase for i in items), f"cleared transition {arrival.transition.name.title()}",
                          f"expect {arrival.approach_kind} approach runway {spoken.runway(arrival.runway)}"])
        return [self._say(station, f"{self.cs}, {station.name}, {text}")]

    def _transition_items(self, state: AircraftState) -> list[rb.Item]:
        """What is due now: a lower altitude when the fixes ahead allow one, a speed limit coming close."""
        legs = self.transition_legs[self.transition_at:] + later_legs(self.arrival)
        floor = max([leg.floor_ft for leg in legs if leg.floor_ft] + [self._approach_altitude()])
        floor = -(-floor // 100) * 100
        items = []
        current = self.transition_alt or self._cleared_ft() or state.alt_msl_ft
        if floor < current and floor < state.alt_msl_ft:
            self.transition_alt = floor
            items.append(rb.altitude(floor, "descend"))
        ahead = [leg for leg in self.transition_legs[self.transition_at:] if leg.speed_kt]
        limit = ahead[0] if ahead else None
        if (limit and limit.speed_kt < (self.transition_speed or STAR_SPEED_KT)
                and distance_nm(state.lat, state.lon, limit.lat, limit.lon) <= SPEED_AHEAD_NM):
            self.transition_speed = limit.speed_kt
            item = rb.speed(limit.speed_kt)
            items.append(rb.Item(item.key, item.value, f"reduce {item.phrase}"))
        return items

    def _transition_progress(self, state: AircraftState, now: float | None) -> list[Response]:
        """Every tick on the transition: the fixes passed, the altitude and speed due, the vectors or the approach
        clearance at its end; radar vectors when the aircraft has left it."""
        station, legs = self.transition_station, self.transition_legs
        while self.transition_at < len(legs):
            fix = (legs[self.transition_at].lat, legs[self.transition_at].lon)
            if not passed(self.transition_from, fix, state.lat, state.lon):
                break
            self.transition_from, self.transition_at = fix, self.transition_at + 1
        if self.transition_at == len(legs):
            self.transition_legs = None
            return self._transition_end(station, state, legs[-1], now)
        fix = legs[self.transition_at]
        if (self.arrival.runway != self.arrival_runway
                or off_path_nm(self.transition_from, (fix.lat, fix.lon), state.lat, state.lon) > OFF_PATH_NM):
            self.transition_legs = None
            return self._vectors_instead(station, state)
        if (not legs[-1].vectors and self.transition_at == len(legs) - 1
                and distance_nm(state.lat, state.lon, fix.lat, fix.lon) <= CLEARANCE_AHEAD_NM):
            self.transition_legs = None
            return self._transition_clearance(station, state)
        if items := self._transition_items(state):
            self._set_pending(items, station.key)
            return self._transmit(station, f"{self.cs}, " + rb.instruction_text(items), state)
        return []

    def _transition_end(self, station: Station, state: AircraftState, last: Leg, now: float | None):
        """The vectors fix passed: Approach vectors from here, the downwind flown on the procedure's course until the
        base turn. A transition without vectors: the approach clearance."""
        if not last.vectors:
            return self._transition_clearance(station, state)
        end = self.destination.runway_end(self.arrival_runway)
        along, across = vectors.frame(end, state.lat, state.lon)
        self.vectoring = station
        if along >= vectors.STRAIGHT_IN_ALONG_NM:
            return self._vectors_instead(station, state)  # already far out in front: turned in at once
        self.vector_leg, self.vector_side, self.vector_at = "downwind", vectors.side_of(across), now
        course = last.course if last.course is not None else state.heading_mag
        self.vector_heading, self.vector_own = round(course / 5) * 5 % 360 or 360, True
        return []

    def _vectors_instead(self, station: Station, state: AircraftState) -> list[Response]:
        """Off the transition: radar vectors, the first heading as a turn."""
        self.vectoring, self.vector_own = station, False
        end = self.destination.runway_end(self.arrival_runway)
        heading = self._first_vector(end, state)
        items = [rb.heading(heading, vectors.turn_direction(state.heading_mag, heading))]
        self._set_pending(items, station.key)
        kind = "ILS" if end.ils else "RNAV"
        return self._transmit(station, f"{self.cs}, {items[0].phrase}, vectors {kind} approach runway "
                                       f"{spoken.runway(end.name)}", state)

    def _transition_clearance(self, station: Station, state: AircraftState) -> list[Response]:
        """At the end of a transition flown without vectors (it ends on the final): "cleared ILS approach …"."""
        self.phase, self.approach_cleared = "approach", True
        end = self.destination.runway_end(self.arrival_runway)
        cleared = rb.Item("runway", end.name,
                          f"cleared {self.arrival.approach_kind} approach runway {spoken.runway(end.name)}")
        sequence = f"{seq}, " if (seq := self._sequence(state)) else ""
        self._set_pending([cleared], station.key)
        return self._transmit(station, f"{self.cs}, {sequence}{cleared.phrase}", state)

    def _base_along_nm(self, state: AircraftState) -> float:
        """How far out the base turn comes on the procedure's downwind: BASE_ALONG_NM, farther with an arrival ahead
        so it is the spacing ahead after the turn (the "trombone")."""
        ahead = self._ahead_in_sequence(state)
        if not ahead:
            return vectors.BASE_ALONG_NM
        nm, t, _ = ahead[0]
        need = wake.approach_spacing_nm(wake.category(t.model, t.title), wake.category(self.plan.aircraft or ""))
        _, across = vectors.frame(self.destination.runway_end(self.arrival_runway), state.lat, state.lon)
        return min(TROMBONE_MAX_NM, max(vectors.BASE_ALONG_NM, nm + need + 1 - abs(across)))

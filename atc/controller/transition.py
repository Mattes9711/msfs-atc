"""The approach transition flown by the pilot, followed by Approach (Milestone 10 E).

Munich ILS 26R, transition LANDU: LANDU, DM411, DM422, DM429 (the downwind), then "FM": from DM429 on the downwind
course until Approach turns the aircraft base. Approach's first call clears the transition ("cleared transition
Landu, expect ILS approach runway two six right") instead of giving a heading; then it follows the aircraft from fix
to fix and gives the altitudes ("descend altitude five thousand feet") and speeds ("reduce speed two two zero
knots") in time for the fixes ahead. At the end of the transition the radar vectors take over: on the downwind the
base turn (later with traffic ahead, the "trombone"), then the intercept (atc/controller/air.py _vector_progress).
A transition flown to its end without vectors ends in the approach clearance.

An aircraft far off the transition (not flying it, or a runway change) gets the radar vectors as before.

Without a transition (no procedure data, or an approach without one) the STAR is followed the same way, from
Little Navmap's legs or the flight plan's STAR points: "descend altitude …, QNH …, expect vectors ILS approach
runway …", and the vectors come only after its last fix (Milestone 10 F).
A part of Controller (atc/controller/controller.py), split off to keep the files short; it uses the controller's
state through self.
"""
from atc.airport.geo import LocalProjection, bearing_deg, distance_nm, point_segment_distance
from atc.airport.procedures import Leg
from atc.controller import readback as rb
from atc.controller import vectors, wake
from atc.flightplan.model import FlightPlan
from atc.controller.arrival import Arrival, entry_fix
from atc.controller.common import APPROACH_SPEED_KT, Response, Station
from atc.phraseology import spoken
from atc.sim.base import AircraftState
from atc.sim.traffic import M_PER_NM

OFF_PATH_NM = 6  # farther than this beside the transition: not flying it, radar vectors instead
PASSED_NM = 1.5  # this close to a fix: passed (the FMC turns before it)
SPEED_AHEAD_NM = 12  # a speed limit this close ahead: "reduce speed …" now
CLEARANCE_AHEAD_NM = 8  # a transition without vectors: the approach clearance this far before its end
STAR_SPEED_KT = 250  # what the aircraft flies when Approach takes it: the speed below FL100
TROMBONE_MAX_NM = 25  # the downwind is made longer for traffic ahead, up to this far out
ON_THE_WAY_DEG = 45  # before the transition's first fix, heading within this of it: on the way to it


def path_legs(arrival: Arrival) -> list[Leg]:
    """The fixes Approach follows: the STAR's up to the transition's first fix, then the transition's up to the
    fix the vectors start at (included). Legs without a position are left out."""
    transition = arrival.transition
    star = list(arrival.star.legs) if arrival.star else []
    start = next((i for i, leg in enumerate(star) if leg.ident == transition.name), len(star))
    legs = star[:start] + list(transition.legs)
    end = next((i for i, leg in enumerate(legs) if leg.vectors and i >= start), len(legs) - 1)
    return [leg for leg in legs[:end + 1] if leg.lat is not None]


def star_legs(arrival: Arrival, plan: FlightPlan) -> list[Leg]:
    """Without a transition: the STAR's fixes up to a vectors leg (Little Navmap), else the flight plan's STAR
    points from its entry fix (SimBrief: LANDU, MIQ). Legs without a position are left out."""
    if arrival.star:
        legs = list(arrival.star.legs)
        end = next((i for i, leg in enumerate(legs) if leg.vectors), len(legs) - 1)
        legs = legs[:end + 1]
    else:
        entry = entry_fix(plan, None)
        legs = [Leg(w.ident, w.lat, w.lon, "TF") for w in plan.waypoints if w.leg == "star" or w.ident == entry]
    return [leg for leg in legs if leg.lat is not None]


def later_legs(arrival: Arrival) -> list[Leg]:
    """After the path, down to the final approach fix: the transition's legs after the vectors and the approach's
    up to the FAF. Their lowest altitudes still count for the altitude Approach gives."""
    legs = list(arrival.transition.legs) if arrival.transition else []
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


def path_to_go_nm(legs: list[Leg], end, lat: float, lon: float, to_first_nm: float | None = None,
                  join_nm: float = vectors.ESTABLISHED_BY_NM) -> float | None:
    """The miles still to fly along the transition to the threshold (the user, 2026-11-21: the descent was planned
    on a straight-in while Munich's LANDU transition to 08 is 75 nm and to 26 97 nm): to the fix flown to, along
    the legs, then from the vectors fix as Approach vectors (vectors.path_nm), else straight to the threshold.
    to_first_nm: the miles to the first fix while it is still ahead (along the route). None when the aircraft is
    beside the transition, not on its way along it."""
    if len(legs) < 2:
        return None
    points = [(leg.lat, leg.lon) for leg in legs]
    target, off = nearest(points, lat, lon)
    if to_first_nm is not None and to_first_nm > PASSED_NM:  # still ahead on the route, even when beside a leg
        target, off = 0, distance_nm(lat, lon, *points[0])
    if target == 0:
        lead = off if to_first_nm is None else max(off, to_first_nm)
    elif off > OFF_PATH_NM:
        return None
    else:
        lead = distance_nm(lat, lon, *points[target])
    along = sum(distance_nm(*points[i], *points[i + 1]) for i in range(target, len(points) - 1))
    last = legs[-1]
    tail = (vectors.path_nm(end, last.lat, last.lon, join_nm) if last.vectors
            else distance_nm(last.lat, last.lon, end.lat, end.lon))
    return lead + along + tail


class TransitionMixin:
    def _start_transition(self, station: Station, state: AircraftState) -> list[Response]:
        """Approach's first call when the aircraft is on its way along the transition: altitude, QNH, a speed when
        one is due, "cleared transition …". Without a transition along the STAR: "expect vectors …". [] when
        neither can be flown (then vectors at once)."""
        arrival = self.arrival
        if arrival is None or self.transition_flown or arrival.runway != self.arrival_runway:
            return []
        star = arrival.transition is None
        legs = star_legs(arrival, self.plan) if star else path_legs(arrival)
        if len(legs) < 2:
            return []
        target, off = nearest([(leg.lat, leg.lon) for leg in legs], state.lat, state.lon)
        if off > OFF_PATH_NM:
            if not self._on_the_way_to(legs[0], state):
                return []
            target = 0
        self.phase, self.transition_flown, self.transition_station = "approach", True, station
        self.transition_legs, self.transition_at = legs, target
        self.transition_from = (state.lat, state.lon) if target == 0 else (legs[target - 1].lat, legs[target - 1].lon)
        self.transition_alt, self.transition_speed, self.transition_star = None, None, star
        items = self._transition_items(state)
        if self.destination_metar and self.destination_metar.qnh_hpa:
            at = 1 if items and items[0].key == "altitude_ft" else 0
            items.insert(at, rb.qnh(self.destination_metar.qnh_hpa))
        self._set_pending(items, station.key)
        approach = f"{arrival.approach_kind} approach runway {spoken.runway(arrival.runway)}"
        said = [f"expect vectors {approach}"] if star else             [f"cleared transition {arrival.transition.name.title()}", f"expect {approach}"]
        text = ", ".join([*(i.phrase for i in items), *said])
        return [self._say(station, f"{self.cs}, {station.name}, {text}")]

    def _on_the_way_to(self, fix: Leg, state: AircraftState) -> bool:
        """Still before the transition's first fix and flying to it: sent direct to it, or heading within
        ON_THE_WAY_DEG of it (the emulator's flight 2026-11-21: handed over 16 nm before LANDU, flying to it, and
        Approach gave heading 220 instead of the transition)."""
        if self.direct_fix == fix.ident:
            return True
        heading_true = (state.heading_mag + (self.destination.mag_var or 0)) % 360
        off = abs((bearing_deg(state.lat, state.lon, fix.lat, fix.lon) - heading_true + 180) % 360 - 180)
        return off <= ON_THE_WAY_DEG

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
        if (limit and self._speeds_given() and limit.speed_kt < (self.transition_speed or STAR_SPEED_KT)
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
        if (not legs[-1].vectors and not self.transition_star and self.transition_at == len(legs) - 1
                and distance_nm(state.lat, state.lon, fix.lat, fix.lon) <= CLEARANCE_AHEAD_NM):
            self.transition_legs = None
            return self._transition_clearance(station, state)
        if items := self._transition_items(state):
            self._set_pending(items, station.key)
            return self._transmit(station, f"{self.cs}, " + rb.instruction_text(items), state)
        return []

    def _transition_end(self, station: Station, state: AircraftState, last: Leg, now: float | None):
        """The vectors fix passed: Approach vectors from here, the downwind flown on the procedure's course until the
        base turn. A transition without vectors: the approach clearance. The STAR's last fix: the vectors."""
        if self.transition_star:
            return self._vectors_instead(station, state, said=True)
        if not last.vectors:
            return self._transition_clearance(station, state)
        end = self.destination.runway_end(self.arrival_runway)
        along, across = vectors.frame(end, state.lat, state.lon)
        self.vectoring = station
        if vectors.straight_in(along, across, self._join_nm()):
            return self._vectors_instead(station, state)  # already far out in front: turned in at once
        self.vector_leg, self.vector_side, self.vector_at = "downwind", vectors.side_of(across), now
        course = last.course if last.course is not None else state.heading_mag
        self.vector_heading, self.vector_own = round(course / 5) * 5 % 360 or 360, True
        return []

    def _vectors_instead(self, station: Station, state: AircraftState, said: bool = False) -> list[Response]:
        """Off the transition: radar vectors, the first heading as a turn. After the STAR (said: "expect vectors"
        was in the first call) the heading and the approach speed, without the vectors repeated."""
        self.vectoring, self.vector_own = station, False
        end = self.destination.runway_end(self.arrival_runway)
        heading = self._first_vector(end, state)
        items = [rb.heading(heading, vectors.turn_direction(state.heading_mag, heading))]
        if said:
            if self._speeds_given() and (self.transition_speed or STAR_SPEED_KT) > APPROACH_SPEED_KT:
                speed = rb.speed(APPROACH_SPEED_KT)
                items.append(rb.Item(speed.key, speed.value, f"reduce {speed.phrase}"))
            self._set_pending(items, station.key)
            return self._transmit(station, f"{self.cs}, " + rb.instruction_text(items), state)
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
        """How far out the base turn comes on the procedure's downwind: so the intercept joins the final at the
        approach's first fix (vectors.base_along_nm); farther when the aircraft is still high (vectors.energy_along_nm),
        or with an arrival ahead so it is the spacing ahead after the turn (the "trombone"); TROMBONE_MAX_NM at the
        most."""
        _, across = vectors.frame(self.destination.runway_end(self.arrival_runway), state.lat, state.lon)
        base = vectors.base_along_nm(self._join_nm())
        along = max(base, vectors.energy_along_nm(state.alt_msl_ft - self.destination.elevation_ft, across))
        if ahead := self._ahead_in_sequence(state):
            nm, t, _ = ahead[0]
            need = wake.approach_spacing_nm(wake.category(t.model, t.title), wake.category(self.plan.aircraft or ""))
            along = max(along, nm + need + 1 - abs(across))
        return min(max(TROMBONE_MAX_NM, base), along)

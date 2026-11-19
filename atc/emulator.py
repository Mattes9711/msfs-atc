"""Flight emulator, a developer tool: python -m atc.emulator EDDM-EDDH EDDH-EDDM, or --simbrief.

A simulated aircraft flies a whole IFR flight, gate to gate, on the local airport data. The co-pilot works the radio
in the live loop (atc/runtime.py, as in MSFS with "/copilot on"), and the aircraft only does what ATC says. It pushes
back, taxis the cleared route, stops at each crossing and at the holding point, and takes off. It flies the route,
the direct-tos, the cleared levels, the STAR and the transition, the vectors, the localizer and the glide path. Then
it lands, vacates and taxis to the stand.

The report at the end lists what looked wrong: too high on final, a phase that never ended, ATC saying "say again",
the co-pilot giving the radio back, an exception. It also gives the timeline of the phases. The whole flight (radio,
positions, findings) goes to a log file in the logs folder, under "emulator".
"""
import argparse
import sys
import time
import traceback
from dataclasses import dataclass, field

from atc.airport.geo import bearing_deg, destination_point, distance_nm
from atc.controller import vectors
from atc.events import Collector
from atc.runtime import LiveSession

AIR_STEP_S, GROUND_STEP_S = 2.0, 1.0
TAXI_KT, PUSH_KT, EXIT_KT = 15, 3, 15
PUSH_S = 25
ROTATE_KT, TAKEOFF_ACCEL_KT_S = 150, 4
TURN_DEG_S = 3.0  # a standard rate turn
ACCEL_KT_S = 2.0
TOUCHDOWN_PAST_NM = 0.15  # 300 m past the threshold
ROLLOUT_DECEL_KT_S, EXIT_SPEED_KT = 4.0, 30
GLIDE_FT_PER_NM = 318  # 3 degrees
LOC_CAPTURE_NM, LOC_LOOKAHEAD_NM = 0.4, 1.5
PASSED_NM = 1.5  # a route point this close counts as passed (the turn starts before it)
LIMIT_S = 6 * 3600
# On the ground the aircraft waits for ATC; this long without anything changing is stuck
STUCK_S = 600
PHASE_LIMIT_S = {"clearance": 300, "cleared": 600, "pushback": 600, "takeoff": 300, "airborne": 300,
                 "approach": 2700, "final": 900, "landing": 900, "vacating": 600}
# (distance from the threshold, allowed above the 3 degree path, allowed below it)
GLIDE_CHECKS = ((10, 500, 300), (5, 250, 200))
VACATE_BEYOND_M = 40  # off the runway the pilot stops this far past the hold line, not at the next node (EDDB:
# 116 m on along M5, away from the route Ground had just given, and Ground called "you appear to be on Mike fife")
MIN_ESTABLISHED_NM = 6  # intercepting the localizer closer in than this is too tight
COMPLAINTS = ("say again", "negative", "stop immediately", "go around", "confirm descending", "unable")


@dataclass
class Finding:
    t: float
    text: str


@dataclass
class Report:
    flight: str
    finished: bool = False
    seconds: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)  # what was measured, also when it was fine
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.finished and not self.findings

    def text(self) -> str:
        head = (f"{self.flight}: {'finished' if self.finished else 'NOT finished'} after {clock(self.seconds)}, "
                f"{len(self.findings)} finding(s)")
        lines = [head, "", "Phases:", *(f"  {t}" for t in self.timeline)]
        if self.checks:
            lines += ["", "Measured:", *(f"  {c}" for c in self.checks)]
        lines += ["", "Findings:" if self.findings else "Findings: none"]
        lines += [f"  {clock(f.t)}  {f.text}" for f in self.findings]
        return "\n".join(lines)


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def crossing_points(route, graph) -> list[tuple[str, int]]:
    """(runway, node to hold at) for each runway the route crosses, as the controller works them out
    (Controller.crossing_points), for the departure or the arrival graph."""
    points, seen = [], set()
    for i, edge in enumerate(route.edges):
        for runway in edge.crosses:
            if runway in seen:
                continue
            seen.add(runway)
            before = [e.a for e in route.edges[:i + 1] if e.a in graph.hold_short]
            points.append((runway, before[-1] if before else edge.a))
    return points


def turn_towards(heading: float, wanted: float, max_deg: float) -> float:
    turn = (wanted - heading + 540) % 360 - 180
    return (heading + max(-max_deg, min(max_deg, turn))) % 360


class Taxi:
    """Along a taxi route from node to node at a steady speed, holding at the crossings not cleared yet."""

    def __init__(self, route, graph, airport_ident: str, end: tuple[float, float] | None = None,
                 here: tuple[float, float] | None = None):
        self.route = route
        nodes = [route.edges[0].a] + [e.b for e in route.edges] if route.edges else []
        self.points = [graph.latlon[n] for n in nodes] + ([end] if end else [])
        self.holds = {}
        for runway, node in crossing_points(route, graph):
            if node in nodes:
                self.holds.setdefault(nodes.index(node), (airport_ident, runway))
        self.at = 0  # the last point reached
        if here is not None and self.points:  # joins the route where it is nearest, up to the first hold
            first_hold = min(self.holds, default=len(self.points) - 1)
            self.at = min(range(first_hold + 1), key=lambda i: distance_nm(*here, *self.points[i]))

    def done(self) -> bool:
        return self.at >= len(self.points) - 1

    def move(self, lat: float, lon: float, seconds: float, kt: float, cleared: set) -> tuple[float, float, float, float]:
        """(lat, lon, true heading, speed) after `seconds`; speed 0 when holding or at the end."""
        left_m = kt * 1852 / 3600 * seconds
        heading = None
        while left_m > 0 and not self.done():
            hold = self.holds.get(self.at)
            if hold is not None and hold not in cleared:
                break
            target = self.points[self.at + 1]
            d = distance_nm(lat, lon, *target) * 1852
            if d > 0.1:
                heading = bearing_deg(lat, lon, *target)
            if d <= left_m:
                lat, lon = target
                left_m -= d
                self.at += 1
            else:
                lat, lon = destination_point(lat, lon, heading, left_m / 1852)
                left_m = 0
        moved = left_m < kt * 1852 / 3600 * seconds
        return lat, lon, heading, kt if moved else 0.0


class Pilot:
    """Flies the fake sim as ATC says, one step at a time. `stage` is what the aircraft does now."""

    def __init__(self, atc, sim):
        self.atc, self.sim = atc, sim
        self.stage = "parked"
        self.until = 0.0
        self.taxi: Taxi | None = None
        self.taxi_route = None
        self.heading_cmd: int | None = None  # magnetic, the last heading given
        self.speed_cmd: int | None = None
        self.seen_items = None
        self.route: list[tuple[str, float, float]] = []
        self.route_star = None
        self.direct_seen = None
        self.wp = 0
        self.loc = False  # established on the localizer
        self.loc_at_nm: float | None = None
        self.abort: str | None = None
        self._build_route()

    # --- what ATC said
    def _listen(self) -> None:
        items = self.atc.last_items
        if items is self.seen_items or items == self.seen_items:
            return
        self.seen_items = items
        for item in items:
            if item.key == "heading":
                self.heading_cmd = int(item.value)
            elif item.key == "direct":
                self.heading_cmd = None
            elif item.key == "speed_kt":
                self.speed_cmd = int(item.value)

    def _build_route(self) -> None:
        atc = self.atc
        idents = {atc.airport.ident, atc.destination.ident if atc.destination else None}
        points = [w for w in atc.plan.waypoints if w.ident not in idents]
        star = atc.arrival.star if atc.arrival else None
        if star is not None:  # the STAR cleared: flown as published, in place of the plan's STAR points
            points = [w for w in points if w.leg != "star"]
            first = next((leg.ident for leg in star.legs if leg.lat is not None), None)
            cut = next((i for i, w in enumerate(points) if w.ident == first), None)
            if cut is not None:
                points = points[:cut]
            self.route = [(w.ident, w.lat, w.lon) for w in points] + [
                (leg.ident, leg.lat, leg.lon) for leg in star.legs if leg.lat is not None]
        else:
            self.route = [(w.ident, w.lat, w.lon) for w in points]
        self.route_star = star
        if hasattr(self, "wp"):
            self._skip_passed(*self._here())

    def _here(self) -> tuple[float, float, float]:
        s = self.sim.read()
        return s.lat, s.lon, (s.heading_mag + self._mag_var(s.lat, s.lon)) % 360

    def _mag_var(self, lat: float, lon: float) -> float:
        a, d = self.atc.airport, self.atc.destination
        if d is None or distance_nm(lat, lon, a.lat, a.lon) < distance_nm(lat, lon, d.lat, d.lon):
            return a.mag_var
        return d.mag_var

    def _elevation(self, lat: float, lon: float) -> float:
        a, d = self.atc.airport, self.atc.destination
        if d is None or distance_nm(lat, lon, a.lat, a.lon) < distance_nm(lat, lon, d.lat, d.lon):
            return a.elevation_ft
        return d.elevation_ft

    def _skip_passed(self, lat: float, lon: float, hdg: float) -> None:
        self.wp = 0 if not hasattr(self, "wp") else self.wp
        if self.wp >= len(self.route):  # a new route (the STAR): start again where the aircraft is
            self.wp = 0
        while self.wp < len(self.route):
            _, plat, plon = self.route[self.wp]
            d = distance_nm(lat, lon, plat, plon)
            rel = abs((bearing_deg(lat, lon, plat, plon) - hdg + 540) % 360 - 180)
            dest = self.atc.destination
            # behind the aircraft, or farther from the field than the aircraft is: passed
            farther = dest is not None and distance_nm(plat, plon, dest.lat, dest.lon) > distance_nm(
                lat, lon, dest.lat, dest.lon) + 1
            if d <= PASSED_NM or (rel > 100 and d < 30) or farther:
                self.wp += 1
                continue
            break

    # --- one step
    def step(self, now: float) -> float:
        """Moves the aircraft; returns the seconds the step took."""
        self._listen()
        stage = self.stage
        return getattr(self, f"_{stage}")(now)

    def _parked(self, now: float) -> float:
        atc = self.atc
        if atc.phase in ("cleared", "pushback") and not atc.pending and not self.sim.read().beacon:
            self.sim.update(beacon=True)
        if atc.phase == "pushback" and not atc.pending:
            self.sim.update(engines_running=True, parking_brake=False)
            self.stage, self.until = "pushing", now + PUSH_S
        elif atc.phase == "taxi" and not atc.pending:  # no pushback (a stand to taxi out of)
            self.sim.update(beacon=True, engines_running=True, parking_brake=False)
            self.stage = "wait_taxi"
        return GROUND_STEP_S

    def _pushing(self, now: float) -> float:
        if now >= self.until:
            self.sim.update(ground_speed_kt=0)
            self.stage = "wait_taxi"
        else:
            self.sim.update(ground_speed_kt=PUSH_KT)
        return GROUND_STEP_S

    def _wait_taxi(self, now: float) -> float:
        atc = self.atc
        if atc.phase == "taxi" and not atc.pending and atc.route_out is not None and atc.route_out.edges:
            self.taxi, self.taxi_route = Taxi(atc.route_out, atc.taxi, atc.airport.ident), atc.route_out
            self.stage = "taxi_out"
        return GROUND_STEP_S

    def _ground_move(self, kt: float, seconds: float) -> None:
        s = self.sim.read()
        lat, lon, heading, speed = self.taxi.move(s.lat, s.lon, seconds, kt, self.atc.cleared_runways)
        changes = {"lat": lat, "lon": lon, "ground_speed_kt": speed, "on_ground": True}
        if heading is not None:
            changes["heading_mag"] = (heading - self._mag_var(lat, lon)) % 360
        self.sim.update(**changes)

    def _taxi_out(self, now: float) -> float:
        atc = self.atc
        if atc.route_out is not self.taxi_route and atc.route_out is not None and atc.route_out.edges:
            self.taxi, self.taxi_route = Taxi(atc.route_out, atc.taxi, atc.airport.ident), atc.route_out  # rerouted
        if atc.pending and any(i.key in ("hold_position",) for i in atc.pending):
            self.sim.update(ground_speed_kt=0)
            return GROUND_STEP_S
        if atc.phase == "takeoff" and not atc.pending and self.taxi.done():
            return self._line_up(now)
        self._ground_move(TAXI_KT, GROUND_STEP_S)
        if self.taxi.done():
            self.sim.update(ground_speed_kt=0)
            self.stage = "holding"
        return GROUND_STEP_S

    def _holding(self, now: float) -> float:
        atc = self.atc
        if atc.pending:
            return GROUND_STEP_S
        if atc.phase == "takeoff":
            return self._line_up(now)
        if atc.lined_up:
            self._line_up(now)
            self.stage = "lined_up"
        return GROUND_STEP_S

    def _line_up(self, now: float) -> float:
        atc = self.atc
        end = atc.airport.runway_end(atc.runway)
        s = self.sim.read()
        along, _ = vectors.frame(end, s.lat, s.lon)
        lat, lon = vectors.point(end, min(along, 0.0), 0.0)
        self.sim.update(lat=lat, lon=lon, ground_speed_kt=0, on_ground=True,
                        heading_mag=(end.heading_true - atc.airport.mag_var) % 360)
        self.stage = "takeoff_roll" if atc.phase == "takeoff" else "lined_up"
        return GROUND_STEP_S

    def _lined_up(self, now: float) -> float:
        if self.atc.phase == "takeoff" and not self.atc.pending:
            self.stage = "takeoff_roll"
        return GROUND_STEP_S

    def _takeoff_roll(self, now: float) -> float:
        s = self.sim.read()
        hdg = (s.heading_mag + self.atc.airport.mag_var) % 360
        gs = s.ground_speed_kt + TAKEOFF_ACCEL_KT_S * GROUND_STEP_S
        lat, lon = destination_point(s.lat, s.lon, hdg, gs * GROUND_STEP_S / 3600)
        if gs >= ROTATE_KT:
            elev = self.atc.airport.elevation_ft
            self.sim.update(lat=lat, lon=lon, ground_speed_kt=gs, on_ground=False, alt_msl_ft=elev + 50,
                            alt_agl_ft=50)
            self.stage = "air"
        else:
            self.sim.update(lat=lat, lon=lon, ground_speed_kt=gs)
        return GROUND_STEP_S

    # --- in the air
    def _target_track(self, lat: float, lon: float, hdg: float) -> float:
        atc, dest = self.atc, self.atc.destination
        mag = dest.mag_var if dest else 0.0
        end = dest.runway_end(atc.arrival_runway) if dest and atc.arrival_runway else None
        if end is not None:
            along, across = vectors.frame(end, lat, lon)
            near = abs(across) <= LOC_CAPTURE_NM and along > 1
            facing = abs((end.heading_true - hdg + 540) % 360 - 180) <= 60
            if not self.loc and atc.approach_cleared and near and facing:
                self.loc, self.loc_at_nm = True, along
            if self.loc and atc.phase not in ("approach", "final", "landing"):
                self.loc = False  # sent around, or a new runway
            if self.loc:
                return bearing_deg(lat, lon, *vectors.point(end, max(along - LOC_LOOKAHEAD_NM, -2.0), 0.0))
        if atc.vectoring and atc.vector_heading is not None:
            return (atc.vector_heading + mag) % 360
        if atc.approach_cleared and end is not None:
            if self.heading_cmd is not None:
                return (self.heading_cmd + mag) % 360
            along, _ = vectors.frame(end, lat, lon)
            return bearing_deg(lat, lon, *vectors.point(end, max(min(along, 12.0) - 2.0, 4.0), 0.0))
        legs = atc.transition_legs
        if legs and atc.transition_at < len(legs):
            leg = legs[atc.transition_at]
            if leg.lat is not None:
                return bearing_deg(lat, lon, leg.lat, leg.lon)
            if leg.course is not None:
                return (leg.course + mag) % 360
        if self.heading_cmd is not None and atc.phase in ("arrival", "approach"):
            return (self.heading_cmd + mag) % 360
        star = atc.arrival.star if atc.arrival else None
        if star is not self.route_star:
            self._build_route()
        if atc.direct_fix and atc.direct_fix != self.direct_seen:
            self.direct_seen = atc.direct_fix
            i = next((i for i, r in enumerate(self.route) if r[0] == atc.direct_fix and i >= self.wp), None)
            if i is not None:
                self.wp = i
        self._skip_passed(lat, lon, hdg)
        if self.wp < len(self.route):
            return bearing_deg(lat, lon, *self.route[self.wp][1:])
        return bearing_deg(lat, lon, dest.lat, dest.lon) if dest else hdg

    def _target_speed(self, alt: float, agl: float, along: float | None) -> float:
        atc = self.atc
        if self.loc and along is not None:
            return 145 if along <= 5 else min(180, self.speed_cmd or 180)
        if atc.phase in ("approach", "final", "landing") or atc.approach_cleared:
            return min(220, self.speed_cmd or 220)
        if agl < 3000 and atc.phase in ("airborne", "climb"):
            return 180
        if alt < 10000:
            return min(250, self.speed_cmd or 250)
        return min(450, 250 + (alt - 10000) / 15000 * 200)

    def _target_alt(self, alt: float, along: float | None) -> float:
        atc = self.atc
        cleared = atc._cleared_ft()
        target = float(cleared) if cleared is not None else alt
        if self.loc and atc.approach_cleared and along is not None:
            glide = atc.destination.elevation_ft + along * GLIDE_FT_PER_NM
            target = min(target, glide) if alt >= glide - 50 else target
        return target

    def _air(self, now: float) -> float:
        dt = AIR_STEP_S
        atc, s = self.atc, self.sim.read()
        lat, lon, alt = s.lat, s.lon, s.alt_msl_ft
        hdg = (s.heading_mag + self._mag_var(lat, lon)) % 360
        dest = atc.destination
        end = dest.runway_end(atc.arrival_runway) if dest and atc.arrival_runway else None
        along = vectors.frame(end, lat, lon)[0] if end is not None else None
        if self.loc and along is not None and along <= 0:
            return self._touchdown(now, alt)
        wanted = self._target_track(lat, lon, hdg)
        hdg = turn_towards(hdg, wanted, TURN_DEG_S * dt)
        agl = alt - self._elevation(lat, lon)
        gs = s.ground_speed_kt
        speed = self._target_speed(alt, agl, along if self.loc else None)
        gs = gs + max(-ACCEL_KT_S * dt, min(ACCEL_KT_S * dt, speed - gs))
        target = self._target_alt(alt, along)
        if target > alt:
            fpm = 3000 if alt < 10000 else 2200 if alt < 25000 else 1500
            alt = min(target, alt + fpm * dt / 60)
        elif target < alt:
            fpm = 3000 if self.loc else min(3000, max(1000, gs * 1000 / 3 / 60))
            alt = max(target, alt - fpm * dt / 60)
        lat, lon = destination_point(lat, lon, hdg, gs * dt / 3600)
        self.sim.update(lat=lat, lon=lon, alt_msl_ft=alt, alt_agl_ft=max(0.0, alt - self._elevation(lat, lon)),
                        on_ground=False, ground_speed_kt=gs, heading_mag=(hdg - self._mag_var(lat, lon)) % 360)
        return dt

    def _touchdown(self, now: float, alt: float) -> float:
        atc, dest = self.atc, self.atc.destination
        above = alt - dest.elevation_ft
        if atc.phase != "landing":
            self.abort = f"over the threshold without a landing clearance (phase {atc.phase})"
            return GROUND_STEP_S
        if above > 300:
            self.abort = f"over the threshold {above:.0f} ft above the field: too high to land"
            return GROUND_STEP_S
        end = dest.runway_end(atc.arrival_runway)
        lat, lon = destination_point(end.lat, end.lon, end.heading_true, TOUCHDOWN_PAST_NM)
        self.sim.update(lat=lat, lon=lon, alt_msl_ft=dest.elevation_ft + 9, alt_agl_ft=9.0, on_ground=True,
                        heading_mag=(end.heading_true - dest.mag_var) % 360)
        self.stage = "rollout"
        return GROUND_STEP_S

    # --- the destination
    def _rollout(self, now: float) -> float:
        dest, s = self.atc.destination, self.sim.read()
        hdg = (s.heading_mag + dest.mag_var) % 360
        gs = max(EXIT_SPEED_KT, s.ground_speed_kt - ROLLOUT_DECEL_KT_S * GROUND_STEP_S)
        lat, lon = destination_point(s.lat, s.lon, hdg, gs * GROUND_STEP_S / 3600)
        self.sim.update(lat=lat, lon=lon, ground_speed_kt=gs)
        if gs <= EXIT_SPEED_KT:
            self._plan_exit()
        return GROUND_STEP_S

    def _plan_exit(self) -> None:
        """Off the runway at the next exit ahead: the abeam point on the centreline, the exit's hold-short node and
        the next node beyond it."""
        atc, s = self.atc, self.sim.read()
        graph = atc._arrival_graph()
        end = atc.destination.runway_end(atc.arrival_runway)
        here, _ = vectors.frame(end, s.lat, s.lon)
        found = []
        for n in graph.hold_short:
            along, across = vectors.frame(end, *graph.latlon[n])
            if abs(across) < 0.15 and along <= here + 0.02:
                found.append((here - along, n, along, across))
        if not found:  # none ahead: the nearest one at all
            found = [(distance_nm(s.lat, s.lon, *graph.latlon[n]), n, *vectors.frame(end, *graph.latlon[n]))
                     for n in graph.hold_short]
        # The way off must touch no other runway and end off every runway: where two runways cross (EDDW 23 and
        # 26) the other one's hold short lies near the centreline too, and leaving by it rolled onto it (2026-11-19)
        _, zones = atc._ground_zones()

        def other_runway(lat, lon):
            rwy = zones.runway_at(lat, lon)
            return rwy is not None and atc.arrival_runway not in (rwy.ends[0].name, rwy.ends[1].name)

        def way_off(node, along, across):
            after = [e.b for e in graph.adjacent.get(node, [])
                     if abs(vectors.frame(end, *graph.latlon[e.b])[1]) > abs(across)
                     and zones.runway_at(*graph.latlon[e.b]) is None]
            beyond = []
            if after:
                d = distance_nm(*graph.latlon[node], *graph.latlon[after[0]]) * 1852
                beyond = [destination_point(*graph.latlon[node], bearing_deg(*graph.latlon[node], *graph.latlon[after[0]]),
                                            min(d, VACATE_BEYOND_M) / 1852)]
            points = [vectors.point(end, along, 0.0), graph.latlon[node]] + beyond
            clean = not any(other_runway(a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10)
                            for a, b in zip(points, points[1:]) for k in range(11))
            return points, bool(after) and clean
        found.sort()
        ways = [way_off(n, along, across) for _, n, along, across in found]
        points = next((points for points, ok in ways if ok), ways[0][0])
        self.exit_points, self.exit_total = points, len(points)
        self.stage = "vacating"

    def _vacating(self, now: float) -> float:
        s = self.sim.read()
        kt = EXIT_SPEED_KT if len(self.exit_points) == self.exit_total else EXIT_KT  # down the runway, then off it
        lat, lon, left_m = s.lat, s.lon, kt * 1852 / 3600 * GROUND_STEP_S
        heading = None
        while left_m > 0 and self.exit_points:
            target = self.exit_points[0]
            d = distance_nm(lat, lon, *target) * 1852
            if d > 0.1:
                heading = bearing_deg(lat, lon, *target)
            if d <= left_m:
                lat, lon = target
                left_m -= d
                self.exit_points.pop(0)
            else:
                lat, lon = destination_point(lat, lon, heading, left_m / 1852)
                left_m = 0
        changes = {"lat": lat, "lon": lon, "ground_speed_kt": 0.0 if not self.exit_points else kt}
        if heading is not None:
            changes["heading_mag"] = (heading - self.atc.destination.mag_var) % 360
        self.sim.update(**changes)
        if not self.exit_points:
            self.stage = "wait_taxi_in"
        return GROUND_STEP_S

    def _wait_taxi_in(self, now: float) -> float:
        atc = self.atc
        if atc.phase == "taxi_in" and not atc.pending and atc.route_in is not None:
            stand = atc.stand_in
            end = (stand.lat, stand.lon) if stand else None
            s = self.sim.read()
            self.taxi = Taxi(atc.route_in, atc._arrival_graph(), atc.destination.ident, end, here=(s.lat, s.lon))
            self.taxi_route = atc.route_in
            self.stage = "taxi_in"
        return GROUND_STEP_S

    def _taxi_in(self, now: float) -> float:
        self._ground_move(TAXI_KT, GROUND_STEP_S)
        if self.taxi.done():
            self.sim.update(ground_speed_kt=0, parking_brake=True, engines_running=False, beacon=False)
            self.stage = "at_stand"
        return GROUND_STEP_S

    def _at_stand(self, now: float) -> float:
        return GROUND_STEP_S


class Emulator:
    """One flight: the controller and the fake sim of a session, the live loop with a fake clock, the pilot."""

    def __init__(self, atc, sim, name: str = "", limit_s: float = LIMIT_S):
        self.atc, self.sim = atc, sim
        self.sink, self.t = Collector(), [0.0]
        self.live = LiveSession(sim, self.sink, atc, clock=lambda: self.t[0])
        self.pilot = Pilot(atc, sim)
        self.limit_s = limit_s
        self.report = Report(name or f"{atc.plan.callsign} {atc.airport.ident}-"
                                     f"{atc.destination.ident if atc.destination else '?'}")
        self.seen_events = 0
        self.phase, self.phase_at = None, 0.0
        self.last_change, self.last_key = 0.0, None
        self.glide_done: set[int] = set()
        self.descent_at: str | None = None

    def find(self, text: str) -> None:
        self.report.findings.append(Finding(self.t[0], text))
        self.report.log.append(f"{clock(self.t[0])}  !!  {text}")

    def run(self) -> Report:
        self.live.step("/copilot on")
        while self.t[0] < self.limit_s:
            dt = self.pilot.step(self.t[0])
            if self.pilot.abort:
                self.find(self.pilot.abort)
                break
            self.t[0] += dt
            try:
                self.live.step()
            except Exception:
                self.find("exception in the live loop:\n" + traceback.format_exc().rstrip())
                break
            self._events()
            if self._checks():
                break
            if self.atc.said_goodbye and self.pilot.stage == "at_stand":
                self.report.finished = True
                break
        else:
            self.find(f"time limit {clock(self.limit_s)} reached")
        self._phase_line(final=True)
        self.report.seconds = self.t[0]
        landed = self.pilot.stage in ("rollout", "vacating", "wait_taxi_in", "taxi_in", "at_stand")
        if self.pilot.loc_at_nm is not None:
            self.report.checks.append(f"established on the localizer {self.pilot.loc_at_nm:.1f} nm out")
            if self.pilot.loc_at_nm < MIN_ESTABLISHED_NM:
                self.find(f"established on the localizer only {self.pilot.loc_at_nm:.1f} nm out")
        elif landed:
            self.find("landed without being established on the localizer")
        if self.descent_at is not None:
            self.report.checks.append(self.descent_at)
        return self.report

    def _events(self) -> None:
        for e in self.sink.events[self.seen_events:]:
            if e.kind == "track":
                self.report.log.append(f"{clock(self.t[0])}  POS {e.text}")
                continue
            if e.kind in ("atc", "copilot", "pilot", "notice", "tuning", "traffic"):
                self.report.log.append(f"{clock(self.t[0])}  {e.kind:8} {e.text}")
            if e.kind == "atc" and any(c in e.text.lower() for c in COMPLAINTS):
                self.find(f"ATC: {e.text}")
            elif e.kind == "notice" and e.text.startswith("Co-pilot: that readback didn't work"):
                self.find(e.text)
        self.seen_events = len(self.sink.events)

    def _phase_line(self, final: bool = False) -> None:
        atc, s = self.atc, self.sim.read()
        if atc.phase == self.phase and not final:
            return
        dest = atc.destination
        to_go = f", {distance_nm(s.lat, s.lon, dest.lat, dest.lon):.0f} nm to {dest.ident}" if dest else ""
        where = "on the ground" if s.on_ground else f"{s.alt_msl_ft:.0f} ft"
        label = "end" if final else atc.phase
        self.report.timeline.append(f"{clock(self.t[0])}  {label:9} {where}, pilot {self.pilot.stage}{to_go}")
        self.phase, self.phase_at = atc.phase, self.t[0]

    def _checks(self) -> bool:
        """True = stop the flight."""
        atc, s, now = self.atc, self.sim.read(), self.t[0]
        self._phase_line()
        limit = PHASE_LIMIT_S.get(atc.phase)
        if limit and now - self.phase_at > limit:
            self.find(f"phase {atc.phase} lasted more than {clock(limit)} (pilot {self.pilot.stage})")
            return True
        key = (atc.phase, self.pilot.stage, tuple(i.key for i in atc.pending), atc.call_next and atc.call_next.name,
               round(s.lat, 4), round(s.lon, 4))
        if key != self.last_key or self.pilot.stage == "air":
            self.last_key, self.last_change = key, now
        elif now - self.last_change > STUCK_S:
            self.find(f"nothing happened for {clock(STUCK_S)}: phase {atc.phase}, pilot {self.pilot.stage}, "
                      f"pending {[i.key for i in atc.pending]}, call_next "
                      f"{atc.call_next.name if atc.call_next else None}")
            return True
        if self.descent_at is None and atc.descent_given and atc.destination:
            to_go = distance_nm(s.lat, s.lon, atc.destination.lat, atc.destination.lon)
            self.descent_at = f"descent given {to_go:.0f} nm from {atc.destination.ident} at {s.alt_msl_ft:.0f} ft"
        if not atc.copilot_on:
            self.find("the co-pilot gave the radio back")
            return True
        if self.pilot.stage == "air" and atc.destination and atc.arrival_runway:
            end = atc.destination.runway_end(atc.arrival_runway)
            along, across = vectors.frame(end, s.lat, s.lon)
            for nm, high, low in GLIDE_CHECKS:
                if nm in self.glide_done or not (0 < along <= nm) or abs(across) > 1.0:
                    continue  # measured on the extended centreline, where the glide path is
                self.glide_done.add(nm)
                above = s.alt_msl_ft - atc.destination.elevation_ft
                path = nm * GLIDE_FT_PER_NM
                on = "on the localizer" if self.pilot.loc else "NOT on the localizer"
                self.report.checks.append(f"{nm} nm from the threshold: {above:.0f} ft above the field "
                                          f"(3 degrees: {path:.0f}), {on}, phase {atc.phase}")
                if above > path + high:
                    self.find(f"{above - path:.0f} ft above the glide path {nm} nm out ({above:.0f} ft)")
                elif above < min(path, atc._approach_altitude() - atc.destination.elevation_ft) - low:
                    # level at the approach altitude below the glide path is the intercept from below (EDDB 24L:
                    # 3000 ft, the glide path at 10 nm is 3340), only lower than that is too low
                    self.find(f"{path - above:.0f} ft below the glide path {nm} nm out ({above:.0f} ft)")
                if not self.pilot.loc and nm <= MIN_ESTABLISHED_NM:
                    self.find(f"not on the localizer {nm} nm out (phase {atc.phase})")
        return False


# --- the command line
class NoWeather:
    def metar(self, icao):
        return None

    def nearby(self, lat, lon, radius_nm):
        return []


class FixedWind(NoWeather):
    """The same made-up METAR everywhere, to fly other runway directions than today's: --wind 230/15."""

    def __init__(self, wind: str):
        direction, _, speed = wind.partition("/")
        self.group = f"{int(direction):03d}{int(speed or 10):02d}KT"

    def metar(self, icao):
        return f"{icao} {time.strftime('%d%H%MZ', time.gmtime())} {self.group} 9999 FEW030 12/06 Q1013"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m atc.emulator",
                                description="Fly whole flights with a simulated aircraft and the co-pilot on the "
                                            "radio; report what looked wrong.")
    p.add_argument("flights", nargs="*", metavar="FROM-TO", help="e.g. EDDM-EDDH EDDH-EDDM")
    p.add_argument("--simbrief", nargs="?", const="", metavar="USER", help="fly the latest SimBrief plan")
    p.add_argument("--callsign", default=None, help="default DLH4AB (SimBrief's with --simbrief)")
    p.add_argument("--cruise", default=None, help="e.g. FL340 (default FL340 without SimBrief)")
    p.add_argument("--weather", choices=("live", "none"), default="live",
                   help="live: the real METAR (runway in use); none: no weather")
    p.add_argument("--wind", default=None, metavar="DDD/SS",
                   help="the same wind at every airport instead (e.g. 230/15): other runways in use")
    p.add_argument("--config", default=None, help="settings file")
    p.add_argument("--log", action="store_true", help="print the whole radio log, not only the report")
    return p


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path

    from atc import paths
    from atc.config import load_config
    from atc.session import PlanRequest, SessionOptions, SetupError, build_session
    from atc.units import parse_level

    args = build_parser().parse_args(argv)
    if not args.flights and args.simbrief is None:
        build_parser().error("give FROM-TO pairs (EDDM-EDDH) or --simbrief")
    config = load_config(Path(args.config) if args.config else None)
    weather = FixedWind(args.wind) if args.wind else NoWeather() if args.weather == "none" else None
    requests = []
    if args.simbrief is not None:
        requests.append(PlanRequest(simbrief=args.simbrief, callsign=args.callsign,
                                    cruise_ft=parse_level(args.cruise) if args.cruise else None))
    for pair in args.flights:
        origin, _, dest = pair.upper().partition("-")
        requests.append(PlanRequest(callsign=args.callsign or "DLH4AB", departure=origin, destination=dest or None,
                                    cruise_ft=parse_level(args.cruise or "FL340")))
    folder = paths.logs_dir() / "emulator"
    folder.mkdir(parents=True, exist_ok=True)
    failed = 0
    for request in requests:
        try:
            session = build_session(request, SessionOptions(nosim=True), config, weather=weather)
        except SetupError as e:
            print(f"cannot set up {request.departure}-{request.destination}: {e}")
            failed += 1
            continue
        started = time.time()
        report = Emulator(session.controller, session.sim).run()
        took = time.time() - started
        path = folder / (time.strftime("%Y-%m-%d_%H%M%S", time.localtime(started))
                         + f"_{session.plan.callsign}_{session.airport.ident}-{report.flight.split('-')[-1]}_EMU.txt")
        path.write_text("\n".join(["# EMU " + line for line in session.banner()] + [report.text(), "", "Radio:"]
                                  + report.log) + "\n", encoding="utf-8")
        print(report.text())
        if args.log:
            print("\nRadio:\n" + "\n".join(report.log))
        print(f"(emulated in {took:.0f} s; log: {path})\n")
        failed += not report.ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""The controller: one state machine for the whole flight (state, pilot calls, readbacks, tick).

Its parts live in their own files, as mixins of the one Controller class sharing its state through self:
    ground.py         clearance, pushback, taxi out and in, runway crossings and incursions
    tower.py          line up, takeoff and landing, waiting for the runway, wake turbulence, go-around
    air.py            handoffs, Departure and Center, the descent, Approach and the sequence
    traffic_calls.py  the other aircraft: the traffic picture, traffic information, their radio calls
    info.py           the Info station of a small field without a controller, and blind calls (Milestone 9 B)
    common.py         the limits, roles and phases, Response and Station
"""
import random
import re
from typing import Callable

from atc.airport.geo import distance_nm
from atc.airport.model import Airport, Parking
from atc.airport.taxi import TaxiGraph, TaxiRoute
from atc.airspace.centers import CenterSector, CenterSectors
from atc.controller import readback as rb
from atc.controller.atis import Atis, weather_text
from atc.controller.runway_use import RunwayUse
from atc.controller.safety import RunwayZones
from atc.controller import wake
from atc.controller.traffic import TrafficPicture
from atc.sim.traffic import Traffic
from atc.flightplan.model import FlightPlan
from atc.intent.parser import parse
from atc.intent.schema import Intent
from atc.phraseology import spoken
from atc.phraseology.farewell import farewell
from atc.sim.base import AircraftState
from atc.units import format_khz
from atc.airport.procedures import Procedures
from atc.weather.metar import Metar
from atc.weather.runway_choice import choose_runway
from atc.controller.common import (AIR_PHASES, AIRBORNE_AGL_FT, APPROACH_HANDOFF_NM, CALL_KINDS, NEAR_HOLDING_POINT_M, PHASES,
                                   PHASE_ROLE, READBACK_REMINDER_S, RESERVED_SQUAWKS, ROLES, SECTOR_NEAR_DEG,
                                   CIRCUIT_NM, INFO_CALL_NM, TOWER_HANDOFF_NM, VFR_SQUAWK,
                                   VACATE_SPEED_KT, Response, Station, _wind, center_station, describe_intent,
                                   frequency_list, wrong_frequency_hint)  # frequency_list: for atc.session
from atc.controller.ground import GroundMixin, stand_words
from atc.controller.tower import TowerMixin
from atc.controller.air import AirMixin
from atc.controller.arrival import Arrival
from atc.controller.traffic_calls import TrafficMixin
from atc.controller.air_chatter import AirChatterMixin
from atc.controller.info import InfoMixin, uncontrolled
from atc.controller.vfr import VfrMixin
from atc.controller.transition import TransitionMixin


class Controller(GroundMixin, TowerMixin, AirMixin, TransitionMixin, TrafficMixin, AirChatterMixin, InfoMixin,
                 VfrMixin):
    """The deterministic ATC brain: one state machine for the whole flight. Pilot calls go to handle(); position
    changes go to tick(), which is where ATC calls the pilot by itself. Only `rng` (squawks) is random."""

    def __init__(self, airport: Airport, plan: FlightPlan, metar: Metar | None, strict_freq: bool = False,
                 destination: Airport | None = None, destination_metar: Metar | None = None,
                 rng: random.Random | None = None, centers: CenterSectors | None = None, chatter: bool = True,
                 strict_readback: bool = False, procedures: Procedures | None = None,
                 crossing_fields: tuple[Airport, ...] = ()):
        self.airport = airport
        self.plan = plan
        self.metar = metar
        self.runway = choose_runway(airport, metar).name  # departure runway end in use
        self.destination = destination
        self.destination_metar = destination_metar
        self.arrival_runway = choose_runway(destination, destination_metar).name if destination else None
        self.procedures = procedures  # the destination's STARs and approaches (Milestone 10), None without the data
        self.arrival: Arrival | None = None  # runway, STAR, approach, transition: fixed with the descent (10 B)
        self.strict_freq = strict_freq
        # Strict readbacks (the user's wish, 2026-11-15): no switching frequency before the readback, the pushback
        # approval is read back too, and ATC asks once after READBACK_REMINDER_S of silence
        self.strict_readback = strict_readback
        self.pending_since: float | None = None
        self.readback_reminded = False
        self.pending_heard = True
        self.blocked = False  # the transmission being handled was sent back: "read back first"
        self.rng = rng or random.Random()
        self.taxi = TaxiGraph(airport)
        self._arrival_taxi: TaxiGraph | None = None
        self.atis = Atis(airport)
        self.atis.update(metar, self.runway)
        self.cs = spoken.callsign(plan.callsign)
        self.cs_short = spoken.short_callsign(plan.callsign)  # registrations only (A2)
        self.abbreviated: set[tuple[str, str]] = set()  # controllers who have called us: from then on the short form

        self.zones = RunwayZones(airport, self.taxi)
        self._arrival_zones: RunwayZones | None = None

        # VFR (Milestone 9, A1) has its own sequence: no IFR clearance (squawk 7000 from the start) and no
        # pushback, so its first call is the taxi request. In the air it still flies like IFR until parts B-E.
        self.vfr = plan.rules == "VFR"
        self.phase = "cleared" if self.vfr else "clearance"
        self.squawk: str | None = VFR_SQUAWK if self.vfr else None
        self.qnh_given = False
        self.descent_given = False
        self.centers = centers or CenterSectors()
        self.center: Station | None = None  # Center controller in charge while en route; None = no radar service
        self.previous_center: Station | None = None  # the one before: it waits for the readback of its "contact"
        self.pending: tuple[rb.Item, ...] = ()  # issued, not yet correctly read back
        self.pending_key: tuple[str, str] | None = None  # station that issued them
        self.handoff_to: tuple[str, str] | None = None  # station the pending instruction sends the pilot to
        self.after_readback: Callable[[Station, AircraftState], list[Response]] | None = None
        self.last_said: dict[tuple[str, str], str] = {}  # per station, for "say again"

        self.route_out: TaxiRoute | None = None
        self.at_holding_point = False
        self.lined_up = False
        self.vectoring: Station | None = None  # the Approach controller vectoring us to the ILS
        self.vector_leg: str | None = None  # "downwind" or "base" while vectored (H)
        self.vector_side = 1  # +1 left of the final facing the runway, -1 right
        self.vector_heading: int | None = None  # the last heading given
        self.vector_at: float | None = None  # when it was given (live clock)
        self.vector_own = False  # the downwind is the transition's, flown on its course: only the base turn (E)
        self.vector_inbound = False  # flying in towards the base point from farther out in front (F)
        # The approach transition (Milestone 10 E): its fixes still followed (None: not on it), the one flown to, the
        # point before it, the altitude and speed given on it, the Approach station; flown once (then vectors)
        self.transition_legs: list | None = None
        self.transition_at = 0
        self.transition_from: tuple[float, float] | None = None
        self.transition_alt: int | None = None
        self.transition_speed: int | None = None
        self.transition_station: Station | None = None
        self.transition_flown = False
        self.transition_star = False  # no transition: the STAR's fixes followed, vectors after its last (F)
        self.apron_handed = False  # Apron has handed the departure over to Ground
        self.apron_in = False  # Ground has handed the arrival over to Apron
        self.route_in: TaxiRoute | None = None
        self.stand_in: Parking | None = None
        self.said_goodbye = False  # parked at the stand, the last controller has said goodbye
        self.waiting_since: tuple[str, float] | None = None  # (runway, time) stopped at its hold short
        self.hinted_crossings: set[str] = set()
        self.cleared_runways: set[tuple[str, str]] = set()  # (airport, designator) the aircraft may be on
        self.incursion: tuple[str, str] | None = None  # runway we already shouted "stop" about
        self.lowest_agl_on_final = float("inf")
        self.first_tick = True
        self.state: AircraftState | None = None  # last state seen by tick()
        self.cleared_level: str | None = None  # "5000 FT", "FL350"
        self.call_next: Station | None = None  # handed over to it, and the pilot hasn't called it yet
        self.first_contact = False  # the transmission being handled is the check-in after a handoff
        self.last_items: tuple[rb.Item, ...] = ()  # the last instruction given, for "confirm …"
        self.picture = TrafficPicture()  # the other aircraft (T1), updated by update_traffic()
        self.transitions: list = []  # what changed in the last update
        self.traffic_told: set[int] = set()  # aircraft we gave traffic information about (T3)
        self.chatter_said: set[tuple[str, str]] = set()  # (callsign, "final" | "takeoff" | "taxi"): once each
        self.chatter = chatter  # the AI's radio calls on our frequency (T4)
        self.runway_use = RunwayUse()  # which runway ends the real traffic lands on and departs from (L2)
        # Waiting for a runway to become free (T2): ATC calls by itself when it is
        self.departure_waiting: Station | None = None
        self.push_waiting: Station | None = None  # pushback held for traffic passing behind (L3)
        self.give_way_told: set[tuple[str, str]] = set()  # (callsign, "crossing" | "follow" | "opposite") (L4)
        self.taxi_hold: str | None = None  # held for this aircraft coming towards us: "continue taxi" when clear
        self.route_joined = False  # on the cleared taxi route once: leaving it from then on gets a new route (27)
        self.route_start_off_m: float | None = None  # how far off the route when the watch began (C4)
        self.speeding = False  # "reduce taxi speed" said, until slower again
        self.progressive: str | None = None  # the phase ("taxi", "taxi_in") with progressive taxi: turns called
        self.turns_told: set[int] = set()  # progressive taxi: route edges whose turn was called
        self.last_landing: dict[str, wake.Departure] = {}  # airport → the last landing seen there (B5)
        self.last_departure: dict[str, wake.Departure] = {}  # airport → the last takeoff seen there (L5)
        self.traffic_clock: float | None = None  # the live clock at the last traffic update
        self.last_radio_at: float | None = None  # when the radio was last busy, at the last traffic update
        self.air_tracks: dict = {}  # object id -> air_chatter.Track: the other aircraft in the air (G)
        self.air_area_key: tuple[str, str] | None = None  # whose area the tracks were looked at for
        self.air_chatter_at: float | None = None  # the last exchange in the air
        self.takeoff_intersection: str | None = None  # asked to depart from it, kept while waiting
        self.wake_told = False  # "expect departure in two minutes, wake turbulence" said
        self.following: Traffic | None = None  # the aircraft ahead of us on final we were told to follow (L6)
        self.speed_step = 0  # speed control behind it: 1 = "reduce speed 160 knots", 2 = "final approach speed"
        self.speed_gap = 0.0  # the gap to it when we were last told to slow down
        self.runway_change: str | None = None  # landing runway changed after the STAR was given: tell the pilot (B3)
        self.star_changed = False  # ... and with it the STAR (Milestone 10 B): the new one is said
        self.arrival_preview = None  # the arrival as planned before the descent, for its constraints (Milestone 10 D)
        # The last descent given, watched until the aircraft is down (Milestone 10 D): (target ft, the item, (time,
        # altitude) when it last lost 300 ft, asked "confirm descending")
        self.descent_watch: tuple | None = None
        self.copilot_on = False  # the co-pilot has the radio (C2)
        self.direct_fix: str | None = None  # the last fix ATC cleared the aircraft direct to (A1)
        self.approach_cleared = False  # cleared for the approach: the landing runway stays (B1)
        self.landed_on: tuple[str, str] | None = None  # the runway the aircraft touched down on (B5)
        self.traffic_info_at: float | None = None  # when the last traffic information was given (B4)
        self.shortcuts = 0  # Center's direct-tos given so far (A2)
        self.copilot_tries: tuple[str, int] = ("", 0)  # his last call and how often he made it
        self.landing_waiting: Station | None = None
        self.crossing_waiting: tuple[Station, Airport, str] | None = None  # (station, airport, runway as said)
        self.info_left: set[str] = set()  # airports whose Info the pilot has said "leaving the frequency" to
        self.info_released = False  # close to an uncontrolled destination: sent to its Info (Milestone 9 B)
        # The circuit at a small field (Milestone 9 C): the legs we reported since joining it, touched down on this
        # circuit, circuits flown again after a touch-and-go or go-around; the other aircraft's legs (chatter)
        self.circuit_reported: set[str] = set()
        self.touched = False
        self.circuits = 0
        self.circuit_legs: dict[int, str | None] = {}
        self.circuit_due: dict[int, tuple[str, float]] = {}
        # Through a control zone (Milestone 9 E, atc/controller/vfr.py): the stage, the point to leave or enter
        # by, the closest the aircraft came to it, "check altitude" said; the destination's ATIS letter
        self.ctr_stage: str | None = None
        self.ctr_point = None
        self.ctr_closest = float("inf")
        self.ctr_altitude_told = False
        # Crossing another field's zone (E3): the fields with a zone on the way, the one being crossed, the point to
        # leave it by (ctr_point is the next point to report), whether the aircraft was inside yet
        self.crossing_fields = crossing_fields
        self.crossing: Airport | None = None
        self.ctr_exit = None
        self.ctr_entered = False
        self.crossed: set[str] = set()  # fields whose zone we were cleared through, or flew through anyway
        self.crossing_hinted: set[str] = set()  # ... entered without a clearance: the hint shown
        self.dest_atis = Atis(destination) if destination else None
        if self.dest_atis:
            self.dest_atis.update(destination_metar, self.arrival_runway)

    # --- public -----------------------------------------------------------------------------------------------

    def broadcast(self, khz: int) -> str | None:
        """What a receiver tuned to this frequency hears without transmitting (the ATIS), if anything."""
        freq = self.airport.frequency_at(khz)
        return self.atis.broadcast() if freq and freq.type == "ATIS" else None

    def update_weather(self, metar: Metar | None, destination_metar: Metar | None) -> list[str]:
        """New METARs during the session. The departure runway can only change before the clearance, the
        arrival runway only before the approach clearance. Returns what changed, for the screen."""
        changes = []
        if metar and metar.raw != (self.metar.raw if self.metar else None):
            self.metar = metar
            if self.phase == "clearance":
                self.runway = (self._traffic_runway(self.airport, "departure", self.runway)
                               or choose_runway(self.airport, metar, self.runway).name)
            letter = self.atis.letter
            self.atis.update(metar, self.runway)
            changes.append(f"{self.airport.ident} weather: {metar.raw}" + (
                f", ATIS information {self.atis.letter}" if self.atis.letter != letter else ""))
        dest_raw = self.destination_metar.raw if self.destination_metar else None
        if self.destination and destination_metar and destination_metar.raw != dest_raw:
            self.destination_metar = destination_metar
            if PHASES.index(self.phase) < PHASES.index("approach"):
                before = self.arrival_runway
                self.arrival_runway = (self._traffic_runway(self.destination, "arrival", self.arrival_runway)
                                       or choose_runway(self.destination, destination_metar, self.arrival_runway).name)
                self._note_runway_change(before)
            if self.dest_atis:
                self.dest_atis.update(destination_metar, self.arrival_runway)
            changes.append(f"{self.destination.ident} weather: {destination_metar.raw}, "
                           f"landing runway {self.arrival_runway}")
        return changes

    def station(self, role: str) -> Station | None:
        """Primary frequency for a job (the lowest of the controller's frequencies)."""
        if role == "center":
            return self.center
        which, types = ROLES[role]
        airport = self.airport if which == "origin" else self.destination
        if airport is None:
            return None
        for t in types:
            candidates = [f for f in airport.frequencies if f.role == t]
            if candidates:
                return Station(airport.ident, min(candidates, key=lambda f: f.khz))
        return None

    def status(self) -> dict:
        """What the pilot needs at a glance, for the app window. Only reads state; safe from another thread."""
        from atc.controller.mapdata import moving  # these read the controller, so imported here
        from atc.controller.panel import airport_panel, flight_line, next_station
        from atc.controller.suggest import suggestion, written_callsign

        state = self.state
        com = state.com1_khz if state else 0
        tuned = self.station_at(com) if com else None
        expected = self.expected_station()
        on_destination_runway = PHASES.index(self.phase) >= PHASES.index("approach") and self.arrival_runway
        return {
            "phase": self.phase,
            "com1_khz": com,
            "tuned": tuned.name if tuned else None,
            "controller": expected.name if expected else None,
            "controller_khz": expected.freq.khz if expected else None,
            "on_frequency": bool(expected and tuned and expected.key == tuned.key),
            "runway": self.arrival_runway if on_destination_runway else self.runway,
            "atis": self.atis.letter,
            "squawk": self.squawk,
            "cleared": self.cleared_level,
            "altitude_ft": round(state.alt_msl_ft) if state else None,
            "on_ground": state.on_ground if state else None,
            "ground_speed_kt": round(state.ground_speed_kt) if state else None,
            "suggestion": suggestion(self),
            "map": moving(self),  # our position and the traffic, for the map (A6)
            "callsign": written_callsign(self.plan.callsign),  # "Lufthansa 4AB", for the quick buttons
            "airport": airport_panel(self),
            "next": next_station(self),
            "flight": flight_line(self),
            "copilot": self.copilot_on,  # the co-pilot has the radio (C2)
        }

    def speech_context(self) -> str:
        """The words this flight uses, for the whisper prompt: callsign, controllers, route waypoints, and the call
        ATC expects next (the readback or the suggestion). Kept short: whisper reads at most ~220 tokens."""
        from atc.controller.suggest import suggestion, written_callsign

        names = {s.name for s in (self.expected_station(), self.readback_station(),
                                  self.station_at(self.state.com1_khz) if self.state else None) if s}
        waypoints = " ".join(w.ident.title() for w in self.plan.waypoints if w.leg != "sid")[:200]
        parts = [written_callsign(self.plan.callsign), ", ".join(sorted(names)), waypoints]
        if sug := suggestion(self):
            parts.append(sug["text"])
        return ". ".join(p for p in parts if p) + "."

    def expected_station(self) -> Station | None:
        """The controller to tune next (the CALL display): the one handed over to, else the phase's. A readback of
        "contact …" still goes to the old controller: see readback_station()."""
        expected = self._station_by_key(self.handoff_to) if self.handoff_to else None
        if expected is None and self.call_next is not None:
            expected = self.call_next
        if expected is None and (field := self.crossing_ahead()):
            expected = self._zone_tower(field)  # a control zone on the way (Milestone 9 E3)
        if expected is None:
            expected = self.station(self._phase_role())
        return expected

    def _ground_role(self) -> str:
        """Apron or Ground: at an airport with an Apron frequency, Apron has the aircraft on the apron."""
        if self._arrived():
            return "arrival_apron" if self.apron_in and self.station("arrival_apron") else "arrival_ground"
        return "apron" if self.station("apron") and not self.apron_handed else "ground"

    def _phase_role(self) -> str:
        """Who a plain call (check-in, report, readback) is for now."""
        if info := self._info_role():
            return info
        if zone := self._ctr_role():
            return zone  # through a control zone (Milestone 9 E): Tower, no Departure or Approach
        if self.phase == "taxi" and self.at_holding_point:
            return "tower"  # handed off at the holding point
        role = PHASE_ROLE[self.phase]
        return self._ground_role() if role in ("ground", "arrival_ground") else role

    def _info_role(self) -> str | None:
        """At an uncontrolled field (Milestone 9 B): "info" on the ground and until leaving the circuit at the
        origin, "arrival_info" from INFO_CALL_NM before the destination; else None."""
        index, airborne = PHASES.index(self.phase), PHASES.index("airborne")
        state = self.state
        dest = self.destination
        local = dest is not None and dest.ident == self.airport.ident  # a local flight: back to the circuit
        if uncontrolled(self.airport):
            if index < airborne:
                return "info"
            near = state is not None and distance_nm(state.lat, state.lon, self.airport.lat,
                                                     self.airport.lon) <= 2 * CIRCUIT_NM  # leaving the circuit
            if near and not local and self.airport.ident not in self.info_left and self.phase in ("climb", "enroute"):
                return "info"
        if uncontrolled(dest) and index >= airborne:
            if index >= PHASES.index("approach"):
                return "arrival_info"
            if state is not None and distance_nm(state.lat, state.lon, dest.lat, dest.lon) <= INFO_CALL_NM:
                return "arrival_info"
        return None

    def readback_station(self) -> Station | None:
        """The controller waiting for a readback, if any."""
        return self._station_by_key(self.pending_key) if self.pending and self.pending_key else None

    def _station_by_key(self, key) -> Station | None:
        # The previous Center too (D1): it handed over and waits for the readback, while self.center is already the
        # next one; without it the co-pilot saw no readback due, only a check-in, and never tuned: stuck for good
        candidates = [self.station(role) for role in ROLES] + [self.center, self.previous_center]
        candidates += [self._zone_tower(a) for a in self.crossing_fields]
        return next((s for s in candidates if s is not None and s.key == key), None)

    def current_airport(self) -> Airport:
        """Whose frequencies matter now: the origin's until airborne, then the destination's."""
        if self.destination and PHASES.index(self.phase) >= PHASES.index("airborne"):
            return self.destination
        return self.airport

    def handle(self, text: str, state: AircraftState) -> list[Response]:
        station = self.station_at(state.com1_khz)
        if station is None and (blind := self.blind_call(state.com1_khz)):  # B4: nobody answers
            intent = parse(text, self.plan.callsign)
            if intent.kind == "leaving_frequency" and self._info_role() == "info":
                self.info_left.add(self.airport.ident)
            return [Response(describe_intent(intent), spoken=False, kind="understood"), blind]
        if station is None:
            if self.strict_freq:
                return []
            center = self.center if self.phase == "enroute" else None
            return [Response(wrong_frequency_hint(self.current_airport(), state.com1_khz, center), spoken=False)]
        intent = parse(text, self.plan.callsign)
        self.pending_since = None  # the pilot just talked: the "read back" reminder starts again
        self.first_contact = (self.call_next is not None and station.key == self.call_next.key
                              and intent.addressed_to_us)
        self.blocked = False
        responses = self._respond(intent, station, state)
        if self.first_contact and not self.blocked:
            self.call_next = None  # the pilot has checked in (not when sent back to read back first)
        return [Response(describe_intent(intent), spoken=False, kind="understood"), *responses]

    def tick(self, state: AircraftState, now: float | None = None) -> list[Response]:
        """ATC-initiated calls triggered by where the aircraft is. Call it whenever the position changes.
        Safety calls come first and don't wait for outstanding readbacks. `now` (seconds, from the live loop's
        clock) is only needed for hints that wait; without it they are left out, so ATC stays deterministic."""
        self.state = state  # for status()
        safety = self._runway_incursion(state) or self._go_around_check(state)
        self.first_tick = False
        if safety:
            return safety
        if self.pending and self.strict_readback and now is not None:
            if reminder := self._readback_reminder(state, now):
                return reminder
        if self.ctr_stage == "out" and (out := self._ctr_tick(state)) is not None:
            return out  # leaving the origin's control zone (Milestone 9 E)
        if self.ctr_stage == "crossing":
            return self._crossing_tick(state)  # through another field's zone (E3)
        if hint := self._zone_hint(state):
            return hint
        if (info := self._info_tick(state)) is not None:
            return info  # at an uncontrolled field (Milestone 9 B)
        if self.pending and not all(i.key == "frequency_khz" for i in self.pending):
            return []  # waiting for a readback before the next instruction
        if waited := self._traffic_waits(state):
            return waited
        if self.phase in AIR_PHASES and (check := self._descent_check(state, now)):
            return check
        if (zone := self._ctr_tick(state)) is not None:
            return zone  # into the destination's control zone (Milestone 9 E)
        if self.phase == "taxi":
            return self._taxi_progress(state, now)
        if self.phase == "taxi_in":
            return self._taxi_in_progress(state)
        if self.phase == "takeoff" and not state.on_ground and state.alt_agl_ft > AIRBORNE_AGL_FT:
            return self._handoff("tower", "departure", "airborne", state)
        to_airport = (distance_nm(state.lat, state.lon, self.destination.lat, self.destination.lon)
                      if self.destination else float("inf"))
        # VFR flies without Center (Milestone 9 B; Langen Information is part D)
        if self.phase in ("climb", "enroute") and self.centers and not self.vfr and to_airport > APPROACH_HANDOFF_NM:
            if calls := self._center_progress(state):
                return calls
        if self.destination is None:
            return []
        if change := self._runway_change_call(state):
            return change
        if self.phase in ("climb", "enroute"):
            role = "center" if self.phase == "enroute" else "departure"
            en_route = self.station(role)  # None after "radar service terminated"
            if self.call_next is not None:
                return []  # handed over, not called yet: the new controller can't instruct yet (A3)
            if (not self.descent_given and en_route
                    and self._track_to_go_nm(state) <= self._top_of_descent_nm(state)):
                return self._descent(en_route, state)
            if to_airport <= APPROACH_HANDOFF_NM and (
                    self.descent_given or state.alt_msl_ft < 10000 or en_route is None):
                return self._handoff(role, "approach", "arrival", state)
        if self.phase == "approach" and self.transition_legs:
            return self._transition_progress(state, now)
        if self.phase == "approach" and self.vectoring:
            return self._vector_progress(state, now)
        if self.phase in ("approach", "final") and (spacing := self._speed_control(state)):
            return spacing
        if self.phase == "approach":
            end = self.destination.runway_end(self.arrival_runway)
            if distance_nm(state.lat, state.lon, end.lat, end.lon) <= TOWER_HANDOFF_NM:
                return self._handoff("approach", "arrival_tower", "final", state)
        if self.phase == "landing" and state.on_ground and state.ground_speed_kt < VACATE_SPEED_KT:
            return self._vacate(self.station("arrival_tower"), state)
        return []

    # --- pilot calls ------------------------------------------------------------------------------------------

    def _respond(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        if not intent.addressed_to_us:
            return [self._say(station, f"station calling {station.name}, say again your callsign")]
        if intent.kind == "say_again":
            last = self.last_said.get(station.key)
            return [Response(last, spoken=True, station=station.name)] if last else [self._say(station, f"{self.cs}, {station.name}")]
        if intent.kind == "radio_check":
            return [self._say(station, f"{self.cs}, {station.name}, read you fife")]
        if intent.kind == "request_wind":  # information any controller gives
            return self._wind_check(station)
        if intent.kind == "request_qnh":
            return self._qnh(station)
        if intent.kind == "request_weather":
            return self._weather_report(station)
        if intent.kind == "confirm":
            return self._confirm(intent, station)
        if intent.kind == "unable":
            return self._unable(station)

        info_here = station.freq.type == "FSS" and uncontrolled(self.airport if station.ident == self.airport.ident
                                                                else self.destination)
        if intent.kind == "going_around" and self.phase in ("approach", "final", "landing") and not info_here:
            return self._go_around(station, state, "roger")
        if self.pending:
            if station.key == self.pending_key:
                return self._check_readback(intent, station, state)
            if station.key == self.handoff_to or all(i.key == "frequency_khz" for i in self.pending):
                read_back_here = any(i.key == "frequency_khz" and intent.items.get("frequency_khz") == i.value
                                     for i in self.pending)
                if self.strict_readback and intent.addressed_to_us and self.pending_heard and not read_back_here:
                    old = self._station_by_key(self.pending_key)
                    where = f" to {old.name} on {format_khz(old.freq.khz)}" if old else ""
                    self.blocked = True
                    return [Response(f"read back first{where}: {rb.instruction_text(self.pending)}", spoken=False)]
                self._set_pending(())  # handed off and the pilot switched: that counts
        if info_here:
            return self._info_call(intent, station, state)  # Info informs, it doesn't clear (Milestone 9 B)
        if (crossing := self._crossing_call(intent, station, state)) is not None:
            return crossing  # through another field's control zone (Milestone 9 E3)
        if intent.kind == "request_other":  # a request ATC doesn't know: always an answer (C3, "ground services")
            return [self._say(station, f"{self.cs}, say again")]
        role = self._role_for(intent)
        if role is None:
            return [self._say(station, f"{self.cs}, say again")]
        expected = self.station(role)
        if expected is not None and expected.key != station.key and self._tower_near_holding_point(station, role, state):
            role, expected = "tower", station
        if expected is not None and expected.key != station.key:
            return self._redirect(station, expected, role)
        if (zone := self._ctr_call(intent, station, state)) is not None:
            return zone  # through a control zone (Milestone 9 E)

        kind = intent.kind
        if kind == "request_clearance":
            return self._vfr_no_clearance(station) if self.vfr else self._clearance(intent, station)
        if self.phase == "clearance" and kind not in ("checkin", "acknowledge"):  # a first call gets "go ahead"
            return [self._no_clearance(station)]
        if kind == "request_pushback":
            return self._pushback(station, state)
        if kind == "request_taxi":
            progressive = bool(intent.items.get("progressive"))
            if progressive and self.phase in ("taxi", "taxi_in"):  # cleared already: from now on
                self.progressive = self.phase
                return [self._say(station, f"{self.cs}, roger, progressive taxi, I will call your turns")]
            calls = self._taxi_in(station, state) if self._arrived() else self._taxi_out(station, state)
            self.progressive = self.phase if progressive else None
            return calls
        if kind == "ready_departure":
            return self._takeoff(station, intent.items.get("intersection"))
        if kind == "holding_short":
            return self._holding_short(intent, station, state)
        if kind == "request_line_up":
            return self._line_up(station)
        if kind == "request_descent":
            return self._descent(station, state)
        if kind == "request_level":
            return self._level_request(intent, station, state)
        if kind == "request_direct":
            return self._direct_request(intent, station, state)
        if kind == "vacated":
            return self._vacate(station, state)
        if self.phase == "airborne":
            return self._radar_contact(station)
        is_center = self.center is not None and station.key == self.center.key
        if self.phase == "enroute" and is_center and self.first_contact:
            return self._center_check_in(station, state)
        if self.phase == "enroute" and kind == "checkin" and is_center:
            return [self._say(station, f"{self.cs}, {station.name}, identified")]
        if self.phase == "arrival":
            return self._vectors(station, state)
        if self.phase == "final":
            return self._final_call(station, state)
        if kind == "unknown":
            return [self._say(station, f"{self.cs}, say again")]
        if kind in ("checkin", "leaving_frequency", "inbound", "on_final", "point_report") or (kind == "readback" and not self.pending
                                     and set(intent.items) not in ({"pushback"}, {"hold_position"})):
            return self._plain_call(intent, station, state)
        return []  # "roger", "wilco": needs no answer

    def _redirect(self, station: Station, expected: Station, role: str) -> list[Response]:
        """Called the wrong controller: "contact Tower 121.280", a handoff like any other, read back and then
        checked in with (Milestone 8, C2: as a plain redirect the readback wasn't recognised and Ground and Tower
        sent the aircraft back and forth). With another instruction waiting for its readback, only where to call."""
        item = rb.contact(expected.name, expected.freq.khz)
        if self.pending:
            return [self._say(station, f"{self.cs}, {item.phrase}")]
        if self.phase == "taxi" and role == "tower":
            self.at_holding_point = True  # Ground has handed over: Tower's from now on
        self.call_next = expected
        self._set_pending([item], station.key, handoff_to=expected.key)
        return [self._say(station, f"{self.cs}, {item.phrase}")]

    def _tower_near_holding_point(self, station: Station, role: str, state: AircraftState) -> bool:
        """Tower takes a call from an aircraft taxiing out that is at or near a holding point of the departure
        runway, also one Ground didn't hand over yet (C2: it sent the check-in back to Ground)."""
        tower = self.station("tower")
        if (self.phase != "taxi" or tower is None or station.key != tower.key
                or role not in ("ground", "apron") or self.taxi is None):
            return False
        near = any(self.taxi.distance_m(n, state.lat, state.lon) <= NEAR_HOLDING_POINT_M
                   for n in self.taxi.holding_points(self.runway))
        if near:
            self.at_holding_point = True
        return near

    def _plain_call(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        """A call without a request: a first call, "with you", a position report. ATC always answers (V3: a
        silent controller sounds like a broken radio), with what comes next where there is something."""
        if self.phase in ("clearance", "cleared"):
            return [self._say(station, f"{self.cs}, {station.name}, go ahead")]
        if self.phase == "pushback":
            return [self._say(station, f"{self.cs}, roger, report ready for taxi")]
        if self.phase == "taxi" and station.key == getattr(self.station("tower"), "key", None):
            return [self._say(station, f"{self.cs}, {station.name}, report when ready for departure")]
        if self.phase == "taxi":  # e.g. checking in with Ground after Apron
            return [self._say(station, f"{self.cs}, {station.name}, continue taxi to holding point runway "
                                       f"{spoken.runway(self.runway)}")]
        if self.phase == "taxi_in" and self.stand_in is not None:
            return [self._say(station, f"{self.cs}, {station.name}, continue to {stand_words(self.stand_in)}")]
        if self.phase == "approach" and re.search(r"\bestablished\b", intent.text):
            tower = self.station("arrival_tower")
            if tower is not None and tower.key != station.key:
                return self._handoff("approach", "arrival_tower", "final", state)
        if self.phase == "vacating":
            return self._taxi_in(station, state)  # calling Ground after landing means: where to?
        return [self._say(station, f"{self.cs}, roger")]

    def _role_for(self, intent: Intent) -> str | None:
        kind = intent.kind
        if kind == "request_clearance":
            return "clearance"
        if kind in ("request_pushback", "request_taxi"):
            return self._ground_role()
        if kind in ("ready_departure", "request_line_up"):
            return "tower"
        if kind == "holding_short":
            if self.phase == "taxi" and self._is_departure_runway(self._reported_runway(intent)):
                return "tower"
            return self._ground_role()
        if kind in ("request_descent", "request_level", "request_direct"):
            if PHASES.index(self.phase) >= PHASES.index("arrival"):
                return "approach"
            return "center" if self.phase == "enroute" else "departure"
        if kind == "vacated":
            return "arrival_tower"
        if kind in CALL_KINDS:
            return self._phase_role()
        return None

    def _arrived(self) -> bool:
        return PHASES.index(self.phase) >= PHASES.index("vacating")

    # --- readbacks --------------------------------------------------------------------------------------------

    def _set_pending(self, items, key=None, after=None, handoff_to=None) -> None:
        if items:
            self.last_items = tuple(items)  # for "confirm …", also after the readback
        self.pending, self.pending_key, self.after_readback = tuple(items), key, after
        self.pending_since, self.readback_reminded = None, False
        self.pending_heard = True  # set False by _transmit when the pilot wasn't tuned to hear it
        self.handoff_to = handoff_to
        for item in items:  # the last level or altitude given, for the status display
            if item.key == "direct":
                self.direct_fix = item.value  # the track miles to go follow it (A1)
            if item.key == "flight_level":
                self.cleared_level = f"FL{item.value:03d}"
            elif item.key == "altitude_ft":
                self.cleared_level = f"{item.value} FT"
            if item.key in ("flight_level", "altitude_ft"):
                self._watch_descent(item)

    def _check_readback(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        if intent.kind != "readback" and all(i.key == "frequency_khz" for i in self.pending):
            # Called the old controller again instead of switching: repeat the handoff
            return [self._say(station, f"{self.cs}, {rb.instruction_text(self.pending)}")]
        result = rb.check_readback(self.pending, intent.items)
        if not result.ok:
            # What was read back correctly counts: after "negative, I say again" only the rest is needed
            self.pending = tuple(i for i in self.pending if i in result.wrong or i in result.missing)
            return [self._say(station, f"{self.cs}, {result.correction}")]
        after, handoff = self.after_readback, all(i.key == "frequency_khz" for i in self.pending)
        self._set_pending(())
        tick = Response("readback correct", spoken=False, kind="readback")  # the app's tick behind the readback
        then = after(station, state) if after else []
        tuned = self.station_at(state.com1_khz)
        if tuned is None or tuned.key != station.key:
            return [tick, *then]  # read back on the new frequency already: the old controller isn't heard
        if then and then[0].spoken and then[0].station == station.name and then[0].text.startswith(f"{self.cs}, "):
            if "readback correct" not in then[0].text:  # one transmission: "…, readback correct, taxi to …"
                rest = then[0].text[len(self.cs) + 2:]
                then[0] = self._say(station, f"{self.cs}, readback correct, {rest}")
            return [tick, *then]
        # Always confirmed aloud (the user's wish); a handoff gets the controller's goodbye
        confirm = farewell(station.ident, station.name) if handoff else f"{self.cs}, readback correct"
        return [tick, self._say(station, confirm), *then]

    def _readback_reminder(self, state: AircraftState, now: float) -> list[Response]:
        """Strict readbacks: the pilot says nothing after an instruction; ATC asks once."""
        if self.pending_since is None:
            self.pending_since = now
            return []
        station = self._station_by_key(self.pending_key)
        if self.readback_reminded or now - self.pending_since < READBACK_REMINDER_S or station is None:
            return []
        self.readback_reminded = True
        return self._transmit(station, f"{self.cs}, read back", state)

    # --- what any controller tells -----------------------------------------------------------------------------

    def _current_metar(self) -> Metar | None:
        return self.destination_metar if self.current_airport() is self.destination else self.metar

    def _qnh(self, station: Station) -> list[Response]:
        """The QNH is read back (ICAO), so it becomes a pending item."""
        metar = self._current_metar()
        if metar is None or metar.qnh_hpa is None:
            return [self._say(station, f"{self.cs}, no QNH available")]
        item = rb.qnh(metar.qnh_hpa)
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, {item.phrase}")]

    def _weather_report(self, station: Station) -> list[Response]:
        """The destination's weather once there is one (that is what pilots ask for), else the current airport's."""
        airport = self.destination if self.destination and self.destination_metar else self.current_airport()
        metar = self.destination_metar if airport is self.destination else self.metar
        if metar is None:
            return [self._say(station, f"{self.cs}, no weather available for {airport.name}")]
        return [self._say(station, f"{self.cs}, {airport.name} weather, {weather_text(metar)}")]

    def _confirm(self, intent: Intent, station: Station) -> list[Response]:
        """"confirm cleared ILS runway 08R?": affirm if the values match the last instruction, else negative with the
        right values. Without values it means "repeat that"."""
        if not intent.items:
            last = self.last_said.get(station.key)
            return [Response(last, spoken=True, station=station.name)] if last else [self._say(station, f"{self.cs}, say again")]
        given = {i.key: i for i in self.last_items}
        asked = {k: v for k, v in intent.items.items() if k in given}
        if not asked:
            return [self._say(station, f"{self.cs}, negative, say again")]
        wrong = [given[k] for k, v in asked.items() if given[k].value != v]
        if not wrong:
            return [self._say(station, f"{self.cs}, affirm")]
        return [self._say(station, f"{self.cs}, negative, " + rb.instruction_text(wrong))]

    def _unable(self, station: Station) -> list[Response]:
        """The pilot can't comply: the instruction waiting for its readback is withdrawn."""
        if self.pending and station.key == self.pending_key:
            self._set_pending(())
            return [self._say(station, f"{self.cs}, roger, maintain present heading and level, standby"),
                    Response("the instruction is cancelled; tell ATC what you can do, or ask again", spoken=False)]
        return [self._say(station, f"{self.cs}, roger")]

    def _wind_check(self, station: Station) -> list[Response]:
        metar = self.destination_metar if self.current_airport() is self.destination else self.metar
        wind = _wind(metar)
        return [self._say(station, f"{self.cs}, {wind}" if wind else f"{self.cs}, no wind information")]

    # --- helpers ----------------------------------------------------------------------------------------------

    def station_at(self, khz: int) -> Station | None:
        """The controller on this frequency: airport stations of origin, destination and the zones on the way, and
        Center sectors."""
        found = [Station(a.ident, f) for a in (self.airport, self.destination, *self.crossing_fields) if a
                 for f in a.frequencies if f.khz == khz and f.station]
        found += [center_station(s) for s in self.centers.on_frequency(khz) if self._near(s)]
        if not found:
            return None
        current, preferred = self.center and self.center.key, self.current_airport().ident
        return min(found, key=lambda s: (s.key != current, s.ident != preferred))

    def _near(self, sector: CenterSector) -> bool:
        """A sector close enough to matter: within SECTOR_NEAR_DEG of the aircraft (or of the origin before the
        first position). Frequencies repeat around the world."""
        lat, lon = (self.state.lat, self.state.lon) if self.state else (self.airport.lat, self.airport.lon)
        south, north, west, east = sector.bbox
        return (south - SECTOR_NEAR_DEG <= lat <= north + SECTOR_NEAR_DEG
                and west - SECTOR_NEAR_DEG <= lon <= east + SECTOR_NEAR_DEG)

    def _abbreviate(self, station: Station, text: str, heard: bool = True) -> str:
        """A registration callsign (A2, ICAO): each controller says it in full in its first call to us, and in the
        short form "Delta Bravo Charlie" from then on. Only after that may the pilot use it too."""
        if self.cs_short is None:
            return text
        if station.key in self.abbreviated:
            return text.replace(self.cs, self.cs_short)
        if heard and self.cs in text:
            self.abbreviated.add(station.key)
        return text

    def short_form_used(self, station: Station | None) -> bool:
        """This controller has used the short callsign, so the pilot may (for the suggestions)."""
        return self.cs_short is not None and station is not None and station.key in self.abbreviated

    def _say(self, station: Station, text: str) -> Response:
        text = self._abbreviate(station, text)
        self.last_said[station.key] = text
        return Response(text, spoken=True, station=station.name)

    def _transmit(self, station: Station, text: str, state: AircraftState) -> list[Response]:
        """An ATC-initiated call: only heard if the pilot is tuned to that controller."""
        tuned = self.station_at(state.com1_khz)
        heard = tuned is not None and tuned.key == station.key
        text = self._abbreviate(station, text, heard)
        self.last_said[station.key] = text
        if heard:
            return [Response(text, spoken=True, station=station.name)]
        if self.pending and self.pending_key == station.key:
            self.pending_heard = False  # a missed call: strict readbacks must not wait for its readback
        if self.strict_freq:
            return []
        return [Response(f"{station.name} is calling you on {format_khz(station.freq.khz)}: {text}", spoken=False,
                         kind="missed_call", station=station.name)]

    def _new_squawk(self) -> str:
        while True:
            code = str(self.rng.randint(1, 6)) + "".join(str(self.rng.randint(0, 7)) for _ in range(3))
            if code not in RESERVED_SQUAWKS:
                return code

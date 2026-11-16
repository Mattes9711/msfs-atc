"""Ground at both airports: clearance delivery, pushback, the taxi out with its runway crossings, the taxi in to
the stand, the runway incursion check and the traffic on the taxi route. A part of Controller (atc/controller/
controller.py), split off to keep the files short; it uses the controller's state through self."""
import math

from atc.airport.geo import bearing_deg, distance, distance_nm
from atc.airport.model import Airport, Parking
from atc.airport.taxi import TaxiGraph, TaxiRoute
from atc.controller import readback as rb
from atc.controller.give_way import Conflict, conflict, path_ahead, route_points, traffic_name
from atc.controller.safety import RunwayZones, designator
from atc.controller import taxi_watch
from atc.sim.traffic import M_PER_NM, Traffic
from atc.flightplan.route import spoken_sid
from atc.intent.schema import Intent
from atc.phraseology import spoken
from atc.phraseology.farewell import farewell
from atc.phraseology.taxi import route_hold_short, route_names, taxi_items
from atc.sim.base import AircraftState
from atc.controller.common import (APRON_RADIUS_M, AT_POINT_M, AT_STAND_M, FOLLOW_WITHIN_M, GIVE_WAY_AHEAD_M,
                                   HOLD_SHORT_HINT_S, INITIAL_CLIMB_FT, PHASES, PUSH_BEHIND_M, STOPPED_BEHIND_M,
                                   STOPPED_KT, VFR_SQUAWK, Response, Station)


def stand_words(stand: Parking | None) -> str:
    """How a controller names the stand: "stand Golf two zero one" for a gate, "parking one two" for a spot on a GA
    ramp (its letters, "P" for parking, aren't said), "the apron" when there is none or it has no number."""
    if stand is None:
        return "the apron"
    if not stand.is_ga:
        return f"stand {spoken.spell(stand.name)}"
    number = stand.name.split()[-1] if stand.name else ""
    return f"parking {spoken.spell(number)}" if any(c.isdigit() for c in number) else "the apron"


class GroundMixin:
    def _clearance(self, intent: Intent, station: Station) -> list[Response]:
        self.squawk = self.squawk or self._new_squawk()
        climb = min(INITIAL_CLIMB_FT, self.plan.cruise_ft or INITIAL_CLIMB_FT) // 100 * 100
        items = [rb.Item("runway", self.runway, f"runway {spoken.runway(self.runway)}"),
                 rb.altitude(climb), rb.squawk(self.squawk)]
        phrases = [self._cleared_to(), *(i.phrase for i in items)]

        letter = self.atis.letter
        if intent.items.get("atis") != letter.lower() and self.metar and self.metar.qnh_hpa:
            current = "is now current" if "atis" in intent.items else "is current"
            qnh = rb.qnh(self.metar.qnh_hpa)
            phrases += [f"information {spoken.ALPHABET[letter]} {current}", qnh.phrase]
            items.append(qnh)
        self.qnh_given = self.qnh_given or any(i.key == "qnh" for i in items) or "atis" in intent.items

        if self.phase == "clearance":
            self.phase = "cleared"
        self._set_pending(items, station.key, self._after_clearance)
        return [self._say(station, f"{self.cs}, " + ", ".join(phrases))]

    def _vfr_no_clearance(self, station: Station) -> list[Response]:
        """A VFR flight asking for a clearance: it needs none to taxi (Milestone 9, A1)."""
        item = rb.squawk(VFR_SQUAWK)
        self._set_pending([item], station.key)
        return [self._say(station, f"{self.cs}, VFR, no clearance required, {item.phrase}, report ready to taxi")]

    def _cleared_to(self) -> str:
        dest = self.destination.name if self.destination else (
            spoken.spell(self.plan.destination) if self.plan.destination else None)
        via = spoken_sid(self.plan.route) or "flight planned route"
        return f"cleared to {dest} via {via}" if dest else f"cleared via {via}"

    def _after_clearance(self, station: Station, state: AircraftState) -> list[Response]:
        ground = self.station(self._ground_role())  # Apron at an airport that has one
        if ground is not None and ground.key != station.key:
            handoff = rb.contact(ground.name, ground.freq.khz)
            self._set_pending([handoff], station.key, handoff_to=ground.key)
            return [self._say(station, f"{self.cs}, readback correct, {handoff.phrase}")]
        return [self._say(station, f"{self.cs}, readback correct")]

    def _no_clearance(self, station: Station) -> Response:
        delivery = self.station("clearance")
        if delivery is None or delivery.key == station.key:
            return self._say(station, f"{self.cs}, request IFR clearance first")
        return self._say(station, f"{self.cs}, no clearance yet, contact {delivery.name} "
                                  f"{spoken.frequency(delivery.freq.khz)}")

    def _pushback(self, station: Station, state: AircraftState, called: bool = False) -> list[Response]:
        """called: ATC calls by itself after holding the push (heard only when tuned)."""
        if self._arrived():
            return [self._say(station, f"{self.cs}, say again")]
        if self.vfr:  # a small aircraft at a GA ramp: no tug, it taxis out by itself (A3)
            return [self._say(station, f"{self.cs}, no pushback required, report ready to taxi")]
        if self._traffic_behind(state):
            # LiveTraffic doesn't listen to us, so it goes first (the user's rule): no push into it
            self.push_waiting = station
            self._hold_position(station)
            return [self._say(station, f"{self.cs}, hold position, traffic passing behind, I will call you")]
        self.phase = max(self.phase, "pushback", key=PHASES.index)
        item = rb.pushback(self._facing_after_push(state))
        if self.strict_readback:
            self._set_pending([item], station.key)
        text = f"{self.cs}, {item.phrase}"
        return self._transmit(station, text, state) if called else [self._say(station, text)]

    def _hold_position(self, station: Station) -> None:
        """With strict readbacks a "hold position" is read back like any instruction (B1; ICAO: holds are)."""
        if self.strict_readback:
            self._set_pending([rb.hold_position()], station.key)

    def _traffic_behind(self, state: AircraftState) -> bool:
        """An aircraft taxiing (or pushing) within PUSH_BEHIND_M behind us, where the push would go."""
        heading_true = (state.heading_mag + self.airport.mag_var) % 360
        for oid, s in self.picture.states.items():
            if s.kind not in ("taxiing", "parked") or s.airport != self.airport.ident:
                continue
            t = self.picture.aircraft[oid]
            limit = PUSH_BEHIND_M if s.kind == "taxiing" else STOPPED_BEHIND_M
            if distance_nm(state.lat, state.lon, t.lat, t.lon) * M_PER_NM > limit:
                continue
            if s.kind == "parked" and self._at_stand(self.airport, t):
                continue  # our neighbours at their stands (B2: only one stopped on the taxilane counts)
            off_nose = abs((bearing_deg(state.lat, state.lon, t.lat, t.lon) - heading_true + 540) % 360 - 180)
            if off_nose > 90:
                return True
        return False

    @staticmethod
    def _at_stand(airport: Airport, t: Traffic) -> bool:
        """Standing at a parking position, not on a taxiway."""
        return any(distance_nm(p.lat, p.lon, t.lat, t.lon) * M_PER_NM <= AT_STAND_M for p in airport.parking)

    def _facing_after_push(self, state: AircraftState) -> str | None:
        """Push so the nose points the way the taxi route leaves the stand: the direction of its first taxiway
        segment after the lead-in line, as north/east/south/west. None when not at a stand."""
        route = self.taxi_route(state)
        if route is None or not route.edges or not route.edges[0].to_parking:
            return None
        edge = next((e for e in route.edges if not e.to_parking), None)
        if edge is None:
            return None
        (x1, y1), (x2, y2) = self.taxi.nodes[edge.a], self.taxi.nodes[edge.b]
        bearing = math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360  # x east, y north
        return ("north", "east", "south", "west")[round(bearing / 90) % 4]

    def taxi_route(self, state: AircraftState) -> TaxiRoute | None:
        start = self.taxi.nearest_node(state.lat, state.lon)
        return None if start is None else self.taxi.route_to_runway(start, self.runway)

    def _taxi_out(self, station: Station, state: AircraftState) -> list[Response]:
        self.route_out = self.taxi_route(state)
        self.route_joined, self.turns_told, self.route_start_off_m = False, set(), None
        items = taxi_items(self.route_out, self.runway)
        if not self.qnh_given and self.metar and self.metar.qnh_hpa:
            items.append(rb.qnh(self.metar.qnh_hpa))
            self.qnh_given = True
        self.phase = "taxi"
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, " + rb.instruction_text(items))]

    def _taxi_progress(self, state: AircraftState, now: float | None) -> list[Response]:
        """While taxiing out: a hint at a crossing the pilot doesn't report, and the handoff to Tower at the
        holding point. ATC doesn't clear a crossing on its own: the pilot reports holding short (F2)."""
        route = self.route_out
        if route is None or not route.edges:
            return []
        if watched := self._watch_taxi(state, self.airport, self.taxi, route):
            return watched
        route = self.route_out
        if traffic := self._give_way(state, self.airport, self.taxi, route):
            return traffic
        apron, ground = self.station("apron"), self.station("ground")
        if (apron and ground and not self.apron_handed and apron.key != ground.key
                and self._off_apron(self.airport, state)):
            self.apron_handed = True
            return self._ground_handoff(apron, ground, state)
        ground = self.station(self._ground_role())
        for runway, hold_node in self.crossing_points(route):
            if (self.airport.ident, runway) in self.cleared_runways:
                continue
            if self.taxi.distance_m(hold_node, state.lat, state.lon) > AT_POINT_M:
                self.waiting_since = None
                return []  # not at the next crossing yet
            return self._crossing_hint(runway, ground, state, now)
        tower = self.station("tower")
        if (not self.at_holding_point and tower and ground and tower.key != ground.key
                and self.taxi.distance_m(route.edges[-1].b, state.lat, state.lon) <= AT_POINT_M):
            self.at_holding_point = True
            item = rb.contact(tower.name, tower.freq.khz)
            self._set_pending([item], ground.key, handoff_to=tower.key)
            return self._transmit(ground, f"{self.cs}, {item.phrase}", state)
        return []

    def _give_way(self, state: AircraftState, airport: Airport, graph: TaxiGraph, route: TaxiRoute) -> list[Response]:
        """Traffic in the way of our taxi route ahead (L4). It never listens to ATC, so the pilot gives way: "give
        way to the Airfrans Airbus crossing left to right", "follow the Lufthansa Airbus", or "hold position" for
        one coming towards us, then "continue taxi" once it no longer is. Each said once per aircraft."""
        station = self._taxi_station(airport, state)
        if station is None:
            return []
        path = path_ahead(route_points(graph, route), graph.proj.xy(state.lat, state.lon), GIVE_WAY_AHEAD_M)
        found = {}
        for oid, s in self.picture.states.items():
            if s.airport != airport.ident or s.kind not in ("taxiing", "parked"):
                continue
            t = self.picture.aircraft[oid]
            standing = s.kind == "parked"
            if standing and self._at_stand(airport, t):
                continue  # parked at a stand beside the route (LiveTraffic fills the free stands)
            if c := conflict(path, graph.proj.xy(t.lat, t.lon), t.heading_true, t.ground_speed_kt):
                if standing and c.kind != "follow":
                    c = Conflict("blocking", c.distance_m)  # stopped across or against our way (B2)
                found[t.callsign] = (t, c)
        if self.taxi_hold is not None:
            if self.taxi_hold in found and found[self.taxi_hold][1].kind in ("opposite", "blocking"):
                return []  # still coming, or still standing there
            self.taxi_hold = None
            return self._transmit(station, f"{self.cs}, continue taxi", state)
        for callsign, (t, c) in sorted(found.items(), key=lambda item: item[1][1].distance_m):
            if (callsign, c.kind) in self.give_way_told or (c.kind == "follow" and c.distance_m > FOLLOW_WITHIN_M):
                continue
            self.give_way_told.add((callsign, c.kind))
            name = traffic_name(t.callsign, t.airline, t.model)
            if c.kind in ("opposite", "blocking"):
                self.taxi_hold = callsign
                self._hold_position(station)
                why = "coming towards you" if c.kind == "opposite" else "stopped ahead"
                return self._transmit(station, f"{self.cs}, hold position, {name} {why}", state)
            if c.kind == "crossing":
                return self._transmit(station, f"{self.cs}, give way to {name} crossing {c.direction}", state)
            return self._transmit(station, f"{self.cs}, follow {name}", state)
        return []

    def _watch_taxi(self, state: AircraftState, airport: Airport, graph: TaxiGraph,
                    route: TaxiRoute) -> list[Response]:
        """Ground's radar on the taxiing aircraft (27): too fast, off the cleared route, the next turn of a
        progressive taxi. On a runway (crossing it, lined up) the incursion check and Tower are in charge."""
        station = self._taxi_station(airport, state)
        if station is None or self.lined_up or self._ground_zones()[1].runway_at(state.lat, state.lon) is not None:
            return []
        if state.ground_speed_kt < taxi_watch.TAXI_SPEED_OK_KT:
            self.speeding = False
        elif state.ground_speed_kt > taxi_watch.TAXI_SPEED_MAX_KT and not self.speeding:
            self.speeding = True
            return self._transmit(station, f"{self.cs}, reduce taxi speed", state)
        off = taxi_watch.off_route_m(graph, route, state.lat, state.lon)
        if self.route_start_off_m is None:
            self.route_start_off_m = off
        if off <= taxi_watch.ON_ROUTE_M:
            self.route_joined = True  # before: still leaving the stand towards the route
        elif ((off > taxi_watch.OFF_ROUTE_M if self.route_joined
               else off > self.route_start_off_m + taxi_watch.OFF_ROUTE_M)  # moved away without joining it (C4)
              and state.ground_speed_kt > STOPPED_KT
              and not taxi_watch.near_route_end(graph, route, state.lat, state.lon)):
            return self._reroute(station, state, graph)
        if self.progressive == self.phase and (turn := taxi_watch.next_turn(graph, route, state.lat, state.lon)):
            index, name, direction = turn
            if (index not in self.turns_told
                    and taxi_watch.turn_distance_m(graph, route, index, state.lat, state.lon) <= taxi_watch.TURN_AHEAD_M):
                self.turns_told.add(index)
                return self._transmit(station, f"{self.cs}, {taxi_watch.turn_phrase(direction, name)}", state)
        return []

    def _reroute(self, station: Station, state: AircraftState, graph: TaxiGraph) -> list[Response]:
        """Off the cleared route: where the aircraft is, and a new route from there (read back like the first)."""
        name = taxi_watch.taxiway_at(graph, state.lat, state.lon)
        where = f"you appear to be on {spoken.spell(name)}" if name else "you are off your cleared route"
        start = graph.nearest_node(state.lat, state.lon)
        self.route_joined, self.turns_told, self.route_start_off_m = False, set(), None
        if self.phase == "taxi":
            self.route_out = graph.route_to_runway(start, self.runway)
            items = taxi_items(self.route_out, self.runway)
            text, after = rb.instruction_text(items), None
        else:
            stand = self.stand_in
            goal = graph.nearest_node(stand.lat, stand.lon) if stand else None
            self.route_in = graph.route(start, goal) if goal is not None else None
            items = rb.taxi_to_stand(route_names(self.route_in), route_hold_short(self.route_in))
            text = f"taxi to {stand_words(stand)}" + (
                ", " + rb.instruction_text(items) if items else "")
            after = self._after_taxi_in
        self._set_pending(items, station.key, after)
        return self._transmit(station, f"{self.cs}, {where}, new route, {text}", state)

    def _taxi_station(self, airport: Airport, state: AircraftState) -> Station | None:
        """Who talks to us while taxiing there: the Ground or Apron frequency we are on, else Ground."""
        tuned = self.station_at(state.com1_khz)
        if tuned is not None and tuned.ident == airport.ident and tuned.freq.role in ("G", "APRON"):
            return tuned
        return self.station("ground" if airport is self.airport else "arrival_ground")

    def _off_apron(self, airport: Airport, state: AircraftState) -> bool:
        graph = self.taxi if airport is self.airport else self._arrival_graph()
        here = graph.proj.xy(state.lat, state.lon)
        return all(distance(here, graph.proj.xy(p.lat, p.lon)) > APRON_RADIUS_M for p in airport.parking)

    def _ground_handoff(self, sender: Station, receiver: Station, state: AircraftState) -> list[Response]:
        """Apron → Ground leaving the apron, Ground → Apron entering it. The pilot then checks in."""
        item = rb.contact(receiver.name, receiver.freq.khz)
        self._set_pending([item], sender.key, handoff_to=receiver.key)
        self.call_next = receiver
        return self._transmit(sender, f"{self.cs}, {item.phrase}", state)

    def _crossing_hint(self, runway: str, ground: Station | None, state: AircraftState,
                       now: float | None) -> list[Response]:
        """Stopped at a crossing for HOLD_SHORT_HINT_S without a call: show (once) what to say. A hint, not an
        ATC call: in reality the pilot reports holding short, and the student should practise that."""
        if now is None or state.ground_speed_kt > STOPPED_KT or runway in self.hinted_crossings:
            self.waiting_since = None
            return []
        if self.waiting_since is None or self.waiting_since[0] != runway:
            self.waiting_since = (runway, now)
            return []
        if now - self.waiting_since[1] < HOLD_SHORT_HINT_S:
            return []
        self.hinted_crossings.add(runway)
        who = f"{ground.name}, " if ground else ""
        return [Response(f'you are holding short of runway {runway}: report it, e.g. "{who}{self.cs}, '
                         f'holding short runway {spoken.runway(runway)}"', spoken=False)]

    def _reported_runway(self, intent: Intent) -> str | None:
        """The runway in "holding short (runway) 05" / "ready to cross runway 05"; without one, the next runway
        to cross on the taxi route, or after the last crossing the departure runway ("on holding point")."""
        named = intent.items.get("hold_short") or intent.items.get("runway")
        if named or self.phase != "taxi" or self.route_out is None:
            return named
        return next((r for r, _ in self.crossing_points(self.route_out)
                     if (self.airport.ident, r) not in self.cleared_runways), self.runway)

    def _is_departure_runway(self, name: str | None) -> bool:
        if name is None or self.airport.runway_end(name) is None:
            return False
        return self._runway_key(self.airport, name) == self._runway_key(self.airport, self.runway)

    def _holding_short(self, intent: Intent, station: Station, state: AircraftState) -> list[Response]:
        """The pilot reports holding short of a runway. The departure runway means ready for departure (Tower).
        Any other runway of the airport gets a crossing clearance, also one that is not on our taxi route,
        because the pilot may have taxied another way."""
        name = self._reported_runway(intent)
        airport, _ = self._ground_zones()
        if name is None or airport.runway_end(name) is None:
            return [self._say(station, f"{self.cs}, say again the runway")]
        if self.phase == "taxi" and self._is_departure_runway(name):
            return self._takeoff(station)
        self.waiting_since = None
        if busy := self._runway_traffic(airport, name):
            self.crossing_waiting = (station, airport, name)
            item = rb.Item("hold_short", name, f"hold short runway {spoken.runway(name)}")
            self._set_pending([item], station.key)
            return [self._say(station, f"{self.cs}, {item.phrase}, {busy}, I will call you")]
        return self._cross(station, airport, name, state)

    def _cross(self, station: Station, airport: Airport, name: str, state: AircraftState) -> list[Response]:
        """"cross runway 05", and with another runway further along the route "…, hold short runway 15" (A4)."""
        self.cleared_runways.add(self._runway_key(airport, name))
        items = [rb.Item("runway", name, f"cross runway {spoken.runway(name)}")]
        route = self.route_out if airport is self.airport and self.phase == "taxi" else self.route_in
        crossings = route.crossings if route else []
        if name in crossings and crossings.index(name) + 1 < len(crossings):
            following = crossings[crossings.index(name) + 1]
            items.append(rb.Item("hold_short", following, f"hold short runway {spoken.runway(following)}"))
        self._set_pending(items, station.key)
        return self._transmit(station, f"{self.cs}, " + rb.instruction_text(items), state)

    def crossing_points(self, route: TaxiRoute) -> list[tuple[str, int]]:
        """(runway, node to hold at) for each crossing in order. A crossing is often several segments and only
        the one over the centreline is marked, so hold at the last hold-short node *before* it."""
        points, seen = [], set()
        for i, edge in enumerate(route.edges):
            for runway in edge.crosses:
                if runway in seen:
                    continue
                seen.add(runway)
                before = [e.a for e in route.edges[:i + 1] if e.a in self.taxi.hold_short]
                points.append((runway, before[-1] if before else edge.a))
        return points

    def next_crossing_here(self) -> str | None:
        """The runway to cross, if the aircraft is at its hold short and not cleared yet (for the suggestion)."""
        if self.phase != "taxi" or self.route_out is None or self.state is None:
            return None
        for runway, node in self.crossing_points(self.route_out):
            if (self.airport.ident, runway) in self.cleared_runways:
                continue
            return runway if self.taxi.distance_m(node, self.state.lat, self.state.lon) <= AT_POINT_M else None
        return None

    def at_departure_holding_point(self) -> bool:
        if self.route_out is None or not self.route_out.edges or self.state is None:
            return False
        end = self.route_out.edges[-1].b
        return self.taxi.distance_m(end, self.state.lat, self.state.lon) <= AT_POINT_M

    def _taxi_in(self, station: Station, state: AircraftState) -> list[Response]:
        self.phase = "taxi_in"
        stand = self._stand()
        graph = self._arrival_graph()
        start = graph.nearest_node(state.lat, state.lon)
        goal = graph.nearest_node(stand.lat, stand.lon) if stand else None
        route = graph.route(start, goal) if start is not None and goal is not None else None
        self.route_in, self.stand_in = route, stand
        self.route_joined, self.turns_told, self.speeding, self.route_start_off_m = False, set(), False, None
        items = rb.taxi_to_stand(route_names(route), route_hold_short(route))
        where = stand_words(stand)
        text = f"{self.cs}, taxi to {where}" + (", " + rb.instruction_text(items) if items else "")
        self._set_pending(items, station.key, self._after_taxi_in)
        return [self._say(station, text)]

    def _after_taxi_in(self, station: Station, state: AircraftState) -> list[Response]:
        return [Response("flight complete", spoken=False)]

    def _stand(self) -> Parking | None:
        """A gate of our airline if the scenery assigns one, else any gate, else any parking spot. A VFR flight gets
        a GA ramp: a small aircraft doesn't park at an airliner's gate."""
        parking = self.destination.parking
        airline = self.plan.callsign[:3]
        gates = [p for p in parking if p.is_gate]
        choices = ([p for p in parking if p.is_ga], list(parking)) if self.vfr else (
            [p for p in gates if airline in p.airline_codes], gates, list(parking))
        for choice in choices:
            if choice:
                return min(choice, key=lambda p: p.name)
        return None

    def _taxi_in_progress(self, state: AircraftState) -> list[Response]:
        if self.route_in is not None and self.route_in.edges and (
                watched := self._watch_taxi(state, self.destination, self._arrival_graph(), self.route_in)):
            return watched
        if self.route_in is not None and (traffic := self._give_way(state, self.destination, self._arrival_graph(),
                                                                     self.route_in)):
            return traffic
        apron, ground = self.station("arrival_apron"), self.station("arrival_ground")
        if (apron and ground and not self.apron_in and apron.key != ground.key
                and not self._off_apron(self.destination, state)):
            self.apron_in = True
            return self._ground_handoff(ground, apron, state)
        return self._parked_goodbye(state)

    def _parked_goodbye(self, state: AircraftState) -> list[Response]:
        """Stopped at its stand: the controller it is with says goodbye (Milestone 8, C6: nothing more came)."""
        if (self.said_goodbye or self.call_next is not None
                or state.ground_speed_kt > STOPPED_KT or not self._at_stand(self.destination, state)):
            return []
        station = self.station(self._ground_role())
        if station is None:
            return []
        self.said_goodbye = True
        return self._transmit(station, f"{self.cs}, {farewell(station.ident, station.name)}", state)

    def _runway_incursion(self, state: AircraftState) -> list[Response]:
        """On the ground past a holding position without a clearance for that runway: stop."""
        if not state.on_ground:
            self.incursion = None
            return []
        airport, zones = self._ground_zones()
        rwy = zones.runway_at(state.lat, state.lon)
        key = (airport.ident, designator(rwy)) if rwy else None
        if self.phase == "landing" and key is not None and self.landed_on is None:
            # Touched down: the runway it rolls out on is its own, even another than cleared (B5: the test flight
            # landed on 26R with the traffic, cleared for 26L, and got "stop immediately" while rolling out)
            self.landed_on = key
            if key not in self.cleared_runways:
                self.cleared_runways.add(key)
                return [Response(f"landed on runway {rwy.ends[0].name}/{rwy.ends[1].name}, not the runway cleared "
                                 f"({self.arrival_runway})", spoken=False)]
        if self._arrived() and self.destination:
            landed_on = self.landed_on or self._runway_key(self.destination, self.arrival_runway)
            if key != landed_on:
                self.cleared_runways.discard(landed_on)  # vacated: going back onto it needs a clearance
        if key is None or key in self.cleared_runways or key == self.incursion:
            self.incursion = key if key not in self.cleared_runways else None
            return []
        self.incursion = key
        if self.first_tick:  # the flight was loaded on the runway: nobody moved onto it, so no "stop"
            return [Response(f"the aircraft starts on runway {rwy.ends[0].name}/{rwy.ends[1].name}; ATC expects "
                             f"a start at a gate or parking position", spoken=False)]
        tuned = self.station_at(state.com1_khz)
        station = tuned if tuned and tuned.ident == airport.ident else self.station(self._ground_role())
        hint = Response(f"runway incursion: runway {rwy.ends[0].name}/{rwy.ends[1].name} without clearance",
                        spoken=False)
        return [hint, *self._transmit(station, f"{self.cs}, stop immediately, stop immediately", state)]

    def _ground_zones(self) -> tuple[Airport, RunwayZones]:
        if self.destination and PHASES.index(self.phase) >= PHASES.index("airborne"):
            self._arrival_graph()
            return self.destination, self._arrival_zones
        return self.airport, self.zones

    def _arrival_graph(self) -> TaxiGraph:
        if self._arrival_taxi is None:
            self._arrival_taxi = TaxiGraph(self.destination)
            self._arrival_zones = RunwayZones(self.destination, self._arrival_taxi)
        return self._arrival_taxi

    @staticmethod
    def _runway_key(airport: Airport, end_name: str) -> tuple[str, str]:
        rwy = next(r for r in airport.runways if end_name in (r.ends[0].name, r.ends[1].name))
        return airport.ident, designator(rwy)

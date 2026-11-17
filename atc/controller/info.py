"""A small field without a controller (Milestone 9 B): its Info station informs, it never clears.

"Uetersen Info" gives the runway in use, wind, QNH, the circuit side and the traffic it knows of; the pilot decides
and reports. At a field with no Info station at all (only a UNICOM frequency), the pilot's calls are blind calls:
"Uetersen traffic, ...", logged and unanswered. The phases still follow the flight, from what the aircraft does.

Only used where the airport has no controller (Airport.controlled): at a controlled field an Info frequency is
a frequency like any other, and calls on it go to the controller in charge.
"""
from atc.airport.geo import distance_nm
from atc.airport.model import Airport
from atc.controller import readback as rb
from atc.controller.common import (AIRBORNE_AGL_FT, APPROACH_HANDOFF_NM, AT_STAND_M, CIRCUIT_AGL_FT, CIRCUIT_NM,
                                   PHASES, STOPPED_KT, TAXIING_KT, VACATE_SPEED_KT, Response, Station, _wind)
from atc.phraseology import spoken
from atc.phraseology.farewell import farewell
from atc.sim.base import AircraftState
from atc.units import format_khz

GROUND_PHASES = ("clearance", "cleared", "pushback", "taxi", "takeoff")
COUNT = {1: "one", 2: "two", 3: "tree", 4: "four"}


def uncontrolled(airport: Airport | None) -> bool:
    return airport is not None and not airport.controlled


class InfoMixin:
    """Part of Controller: the Info station of an uncontrolled origin or destination."""

    def _info_side(self, station: Station) -> str:
        """"departure" or "arrival": which of our airports this Info belongs to (both: by the phase)."""
        dest = self.destination
        if dest is None or station.ident != dest.ident:
            return "departure"
        if station.ident == self.airport.ident and PHASES.index(self.phase) < PHASES.index("airborne"):
            return "departure"
        return "arrival"

    def _info_call(self, intent, station: Station, state: AircraftState) -> list[Response]:
        """A call to the Info station of an uncontrolled field."""
        kind = intent.kind
        if kind == "leaving_frequency":
            self.info_left.add(station.ident)
            return [self._say(station, f"{self.cs}, {farewell(station.ident, station.name)}")]
        if kind == "request_clearance":
            if self.vfr:
                return self._vfr_no_clearance(station)
            return [self._say(station, f"{self.cs}, {station.name}, no clearance available on this frequency")]
        if self._info_side(station) == "departure":
            return self._info_departure_call(intent, station)
        return self._info_arrival_call(intent, station, state)

    def _info_departure_call(self, intent, station: Station) -> list[Response]:
        kind, ground = intent.kind, self.phase in GROUND_PHASES
        if kind == "request_taxi" and ground:
            return self._taxi_information(station)
        if kind in ("ready_departure", "request_line_up") and ground:
            return self._departure_information(station)
        if kind == "checkin" and self.phase in ("clearance", "cleared"):
            return [self._say(station, f"{self.cs}, {station.name}, go ahead")]
        if kind == "readback" and "runway" in intent.items and self.phase in ("clearance", "cleared"):
            self.phase = "taxi"  # "taxiing to runway 27": taxi information known already
            return [self._say(station, f"{self.cs}, roger")]
        if kind == "unknown":
            return [self._say(station, f"{self.cs}, say again")]
        return [self._say(station, f"{self.cs}, roger")]

    def _info_arrival_call(self, intent, station: Station, state: AircraftState) -> list[Response]:
        kind = intent.kind
        air = not state.on_ground
        if kind == "on_final" and air:
            return self._final_information(station)
        if kind in ("inbound", "checkin") and air:
            return self._arrival_information(station, state)
        if kind == "vacated" or (kind == "request_taxi" and not air):
            if self.phase in ("landing", "vacating") or not air:
                self.phase = "taxi_in"
            return [self._say(station, f"{self.cs}, roger")]
        if kind == "unknown":
            return [self._say(station, f"{self.cs}, say again")]
        return [self._say(station, f"{self.cs}, roger")]

    # --- what Info says ---------------------------------------------------------------------------------------

    def _airfield_items(self, runway: str, metar) -> list[rb.Item]:
        """Runway and QNH, which the pilot reads back."""
        items = [rb.Item("runway", runway, f"runway {spoken.runway(runway)}")]
        if metar is not None and metar.qnh_hpa is not None:
            items.append(rb.qnh(metar.qnh_hpa))
        return items

    @staticmethod
    def _circuit(airport: Airport, runway: str) -> str:
        end = airport.runway_end(runway)
        return "right hand circuit" if end is not None and end.circuit == "R" else "left hand circuit"

    def _taxi_information(self, station: Station) -> list[Response]:
        """B1: "runway 27, wind 250 degrees 8 knots, QNH 1013, left hand circuit"; runway and QNH read back."""
        items = self._airfield_items(self.runway, self.metar)
        parts = [items[0].phrase, _wind(self.metar), *(i.phrase for i in items[1:]),
                 self._circuit(self.airport, self.runway)]
        self.phase = "taxi"
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, {station.name}, " + ", ".join(p for p in parts if p))]

    def _info_runway_traffic(self, airport: Airport, runway: str, final_nm: float | None = None) -> str:
        """What is on or close to the runway, as Info says it: it reports, it doesn't clear."""
        busy = self._runway_traffic(airport, runway) if final_nm is None else \
            self._runway_traffic(airport, runway, final_nm=final_nm)
        said = spoken.runway(runway)
        return {"landing traffic": f"traffic on final runway {said}",
                "departing traffic": f"traffic departing runway {said}",
                None: f"runway {said} free"}.get(busy, busy)

    def _departure_information(self, station: Station) -> list[Response]:
        """B2: "wind 250 degrees 8 knots, runway 27 free", or the traffic. No readback: the pilot decides."""
        self.phase = "takeoff"
        parts = [_wind(self.metar), self._info_runway_traffic(self.airport, self.runway)]
        return [self._say(station, f"{self.cs}, " + ", ".join(p for p in parts if p))]

    def _circuit_traffic(self, airport: Airport) -> str:
        """The other aircraft flying in the circuit: in the air, close to the field and low."""
        n = sum(1 for t in self.picture.aircraft.values()
                if not t.on_ground and distance_nm(t.lat, t.lon, airport.lat, airport.lon) <= CIRCUIT_NM
                and t.alt_ft < airport.elevation_ft + CIRCUIT_AGL_FT)
        if n == 0:
            return "no reported traffic"
        return f"{COUNT.get(n, 'several')} aircraft in the circuit"

    def _arrival_information(self, station: Station, state: AircraftState) -> list[Response]:
        """B3, the inbound call: runway, wind, QNH, circuit side and the traffic; runway and QNH read back."""
        dest = self.destination
        runway = self.arrival_runway
        items = self._airfield_items(runway, self.destination_metar)
        traffic = [self._circuit_traffic(dest)]
        busy = self._runway_traffic(dest, runway)
        if busy is not None:
            traffic = [self._info_runway_traffic(dest, runway)] + (traffic if traffic[0] != "no reported traffic"
                                                                    else [])
        parts = [items[0].phrase, _wind(self.destination_metar), *(i.phrase for i in items[1:]),
                 self._circuit(dest, runway), *traffic]
        self.phase = "approach"
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, {station.name}, " + ", ".join(p for p in parts if p))]

    def _final_information(self, station: Station) -> list[Response]:
        """B3, on final: "wind 250 degrees 8 knots, runway 27 free", or the traffic on it."""
        self.phase = "landing"
        parts = [_wind(self.destination_metar),
                 self._info_runway_traffic(self.destination, self.arrival_runway, final_nm=0)]
        return [self._say(station, f"{self.cs}, " + ", ".join(p for p in parts if p))]

    # --- without a call: the phases follow the aircraft --------------------------------------------------------

    def _drop_info_pending(self, airport: Airport) -> None:
        """Info's runway and QNH are not waited for once the flight has moved on."""
        if self.pending and self.pending_key and self.pending_key[0] == airport.ident:
            self._set_pending(())

    def _info_tick(self, state: AircraftState) -> list[Response] | None:
        """tick() at an uncontrolled field. None: not at one now, the controlled-field logic goes on."""
        origin, dest = self.airport, self.destination
        index = PHASES.index(self.phase)
        if uncontrolled(origin) and index < PHASES.index("airborne"):
            if not state.on_ground and state.alt_agl_ft > AIRBORNE_AGL_FT:
                self.phase = "enroute"  # no Departure: on its way (Langen Information is part D)
                self._drop_info_pending(origin)
            elif self.phase in ("clearance", "cleared", "pushback") and state.ground_speed_kt > TAXIING_KT:
                self.phase = "taxi"  # taxiing without asking: the pilot knows the field
            return []
        if not uncontrolled(dest):
            return None
        to_field = distance_nm(state.lat, state.lon, dest.lat, dest.lon)
        if PHASES.index("airborne") <= index <= PHASES.index("landing"):
            if state.on_ground and to_field <= CIRCUIT_NM and state.ground_speed_kt < VACATE_SPEED_KT:
                self.phase = "vacating"  # landed
                self._drop_info_pending(dest)
                return []
            if to_field > APPROACH_HANDOFF_NM or self.pending and self.pending_key[0] != dest.ident:
                return None  # en route as at any destination; or a readback for the controller in charge
            if not self.info_released:
                self.info_released = True
                return self._release_to_info(state)
            return []
        if self.phase == "vacating" and state.on_ground:
            _, zones = self._ground_zones()
            if zones.runway_at(state.lat, state.lon) is None:
                self.phase = "taxi_in"
            return []
        if self.phase == "taxi_in" and not self.said_goodbye and state.ground_speed_kt < STOPPED_KT:
            if any(distance_nm(state.lat, state.lon, p.lat, p.lon) * 1852 <= AT_STAND_M for p in dest.parking):
                self.said_goodbye = True
                return [Response("parked, flight complete", spoken=False)]
            return []
        return [] if index >= PHASES.index("vacating") else None

    def _release_to_info(self, state: AircraftState) -> list[Response]:
        """Close to an uncontrolled destination: the controller in charge (Departure, Center) lets the aircraft
        go to the Info frequency; without one in charge the pilot just changes over."""
        sender = self.center if self.phase == "enroute" else self.station("departure")
        self.call_next = None
        info = self.station("arrival_info")
        if sender is None:
            return []
        if info is None:
            return self._transmit(sender, f"{self.cs}, radar service terminated, frequency change approved", state)
        return self._transmit(sender, f"{self.cs}, radar service terminated, {info.name} on "
                                      f"{spoken.frequency(info.freq.khz)}", state)

    def blind_call(self, khz: int) -> Response | None:
        """B4: "Uetersen traffic, ..." at an uncontrolled field without an Info station, on a frequency with no
        station on it: logged, nobody answers."""
        role = self._info_role()
        if role is None or self.station(role) is not None:
            return None
        airport = self.airport if role == "info" else self.destination
        return Response(f"blind call on {format_khz(khz)}: {airport.name} has no Info station, nobody answers",
                        spoken=False)

"""VFR flights through the control zone of a controlled field (Milestone 9 E). A part of Controller (atc/controller/
controller.py), split off to keep the files short; it uses the controller's state through self.

Departure (E1): with the takeoff clearance Tower says how to leave the zone, "leave the control zone via November,
one thousand five hundred feet or below, squawk 7000", and "report November". At the point (or out of the zone)
Tower lets the flight go: "leaving the control zone, frequency change approved".
Arrival (E2): the inbound call to the destination's Tower gets "enter the control zone via Sierra, one thousand five
hundred feet or below, report Sierra"; at Sierra "join right downwind runway 25, report downwind"; on downwind
"report final"; on final the landing clearance. No Approach, no Departure, no radar vectors.

The points are the field's visual reporting points (Little Navmap's VFR waypoints); without any, a direction
("leave the control zone to the north"). Like the taxi route (Milestone 8 C) Tower watches: the altitude limit
inside the zone, and whether the point was passed.

    ctr_stage   None     no zone flight now (or not yet called)
                "out"    cleared to leave the origin's zone, not out yet
                "in"     cleared to enter the destination's zone, the point not yet reached
                "joining" told to join downwind, downwind not yet reported
                "final_due" downwind reported, final not yet
                "final"  on final: the landing clearance follows (or "continue approach")
                "crossing" cleared through another field's zone (E3), not out of it again yet

Crossing (E3): a zone of another field on the way (zones_along, loaded at the start). Its Tower: "request crossing of
the control zone from November to Sierra" gets "cleared to cross the control zone via November and Sierra, one
thousand five hundred feet or below, report November"; at November "report Sierra"; at Sierra (or out of the zone)
"leaving the control zone, frequency change approved". A point the pilot doesn't name (or the field doesn't have):
the one toward the aircraft to enter by, the one toward the destination to leave by.
"""
import math
import re
from dataclasses import dataclass

from atc.airport.geo import bearing_deg, distance_nm, point_in_polygon, segment_distance_nm, segments_cross
from atc.airport.model import Airport, VfrPoint
from atc.controller import readback as rb
from atc.controller.circuit import circuit_leg, circuit_side, leg_words
from atc.controller.common import AIRBORNE_AGL_FT, INFO_CALL_NM, Response, Station
from atc.phraseology import spoken
from atc.sim.base import AircraftState

NO_ZONE_NM = 5  # without a control zone in the data: this close to the field counts as in it
NO_ZONE_CEILING_FT = 2500  # ... and this high above it
POINT_PASSED_NM = 2  # a point is passed once we came this close and fly away from it again
PASSED_MARGIN_NM = 0.5
ALTITUDE_MARGIN_FT = 300  # above the limit by more than this: "check altitude"
COMPASS = ("north", "east", "south", "west")
ZONE_STAGES = ("in", "joining", "final_due", "final")
ZONE_SEARCH_NM = 15  # fields this close to the line origin-destination may have a zone on the way (E3)
ZONE_NEAR_NM = 2  # a zone this close to the line is on the way


@dataclass(frozen=True)
class ZonePoint:
    code: str  # as the parser hears it: "N", "S1", "EWEST", or a direction "NORTH"
    words: str  # as ATC says it: "November", "Sierra one", "Ewest", "north"
    point: VfrPoint | None  # None: a direction, no point


def point_words(ident: str) -> str:
    """How ATC says a reporting point: "N1" → "November one"; "NOVMR", "WHISY", "SIERA" (a phonetic word cut to
    five letters) → "November", "Whiskey", "Sierra"; any other name as a word, "Ewest"."""
    if re.fullmatch(r"[A-Z]\d{0,2}", ident):
        return spoken.spell(ident)
    word = _phonetic_word(ident)
    return word or ident.title()


def point_code(ident: str) -> str:
    """The point as the parser reads it back (atc.intent.parser.point_code): "N1", "N" for NOVMR, "EWEST"."""
    if re.fullmatch(r"[A-Z]\d{0,2}", ident):
        return ident
    return ident[0] if _phonetic_word(ident) else ident


def point_written(code: str) -> str:
    """The point as the pilot writes it in a suggestion: "November", "Sierra 1", "Ewest", "north"."""
    if code.lower() in COMPASS:
        return code.lower()
    if m := re.fullmatch(r"([A-Z])(\d{0,2})", code):
        return " ".join(filter(None, [spoken.ALPHABET[m[1]], m[2]]))
    return code.title()


def _phonetic_word(ident: str) -> str | None:
    """The phonetic word whose letters the ident keeps in order and starts with ("NOVMR" in "November")."""
    word = spoken.ALPHABET.get(ident[0])
    if word is None or len(ident) < 3:
        return None
    letters = iter(word.upper().replace("-", ""))
    return word if all(c in letters for c in ident) else None


def ctr_limit_ft(airport: Airport) -> int:
    """The altitude VFR flights keep to in the zone: 1000 ft below its ceiling in 500 ft steps, at least 1000 ft above
    the field, and below the ceiling (Hamburg, Lubeck, Frankfurt 1500 ft; Munich 2500 ft)."""
    zone = airport.control_zone
    ceiling = zone.ceiling_ft if zone else airport.elevation_ft + NO_ZONE_CEILING_FT
    limit = math.floor((ceiling - 1000) / 500) * 500
    limit = max(limit, math.ceil((airport.elevation_ft + 1000) / 500) * 500)
    return int(min(limit, ceiling - 500))


def in_zone(airport: Airport, lat: float, lon: float, alt_ft: float) -> bool:
    zone = airport.control_zone
    if zone is None:
        return (distance_nm(lat, lon, airport.lat, airport.lon) <= NO_ZONE_NM
                and alt_ft < airport.elevation_ft + NO_ZONE_CEILING_FT)
    return alt_ft < zone.ceiling_ft and point_in_polygon(lat, lon, zone.polygon)


def zone_point(airport: Airport, lat: float, lon: float) -> ZonePoint:
    """The point to enter or leave the zone by, on the side of (lat, lon): of each route of points (S1, S2 or one
    point per letter) the one farthest out, and of those the one whose bearing from the field is closest."""
    toward = bearing_deg(airport.lat, airport.lon, lat, lon)
    outer: dict[str, tuple[float, VfrPoint]] = {}
    for p in airport.vfr_points:
        nm = distance_nm(airport.lat, airport.lon, p.lat, p.lon)
        if nm > outer.get(p.ident[0], (-1.0, p))[0]:
            outer[p.ident[0]] = (nm, p)

    def off(p: VfrPoint) -> float:
        return abs((bearing_deg(airport.lat, airport.lon, p.lat, p.lon) - toward + 540) % 360 - 180)

    if outer:
        p = min((p for _, p in outer.values()), key=lambda p: (off(p), p.ident))
        return ZonePoint(point_code(p.ident), point_words(p.ident), p)
    side = COMPASS[round(toward / 90) % 4]
    return ZonePoint(side.upper(), side, None)


def named_point(airport: Airport, code: str | None) -> ZonePoint | None:
    """The point the pilot named, if the field has it (of N1 and N2 the one farther out); a direction only at a
    field without points."""
    if not code:
        return None
    if not airport.vfr_points:
        return ZonePoint(code, code.lower(), None) if code.lower() in COMPASS else None
    found = [p for p in airport.vfr_points if point_code(p.ident) == code]
    if not found:
        return None
    p = max(found, key=lambda p: distance_nm(airport.lat, airport.lon, p.lat, p.lon))
    return ZonePoint(code, point_words(p.ident), p)


def zones_along(fields, origin: Airport, dest: Airport) -> tuple[Airport, ...]:
    """The fields whose control zone is on the way from origin to dest (E3), nearest first, one per zone: the
    zone's own field, the one with the longest runway (Finkenwerder lies in Hamburg's zone). Not the zones of
    origin and destination."""
    a, b = (origin.lat, origin.lon), (dest.lat, dest.lon)
    ends = {z.polygon for z in (origin.control_zone, dest.control_zone) if z}
    owners: dict = {}
    for f in fields:
        zone = f.control_zone
        if (zone is None or tuple(zone.polygon) in ends or f.ident in (origin.ident, dest.ident)
                or not _has_tower(f) or not _on_the_way(zone.polygon, a, b)):
            continue
        held = owners.get(tuple(zone.polygon))
        if held is None or _longest(f) > _longest(held):
            owners[tuple(zone.polygon)] = f
    return tuple(sorted(owners.values(), key=lambda f: distance_nm(*a, f.lat, f.lon)))


def _longest(airport: Airport) -> float:
    return max((r.length_ft for r in airport.runways), default=0)


def _on_the_way(polygon, a: tuple[float, float], b: tuple[float, float]) -> bool:
    poly = list(polygon)
    return (any(segment_distance_nm(lat, lon, a, b) <= ZONE_NEAR_NM for lat, lon in poly)
            or any(segments_cross(a, b, p, q) for p, q in zip(poly, poly[1:] + poly[:1]))
            or point_in_polygon(*a, poly))


def _has_tower(airport: Airport | None) -> bool:
    return airport is not None and any(f.type == "T" for f in airport.frequencies)


class VfrMixin:
    # --- when ---------------------------------------------------------------------------------------------------

    def _ctr_departure(self) -> bool:
        """VFR from a controlled field to another one: out through the control zone."""
        dest = self.destination
        return self.vfr and _has_tower(self.airport) and dest is not None and dest.ident != self.airport.ident

    def _ctr_arrival(self) -> bool:
        """VFR to a controlled field from somewhere else: in through the control zone, no Approach."""
        dest = self.destination
        return self.vfr and _has_tower(dest) and dest.ident != self.airport.ident

    def _ctr_role(self) -> str | None:
        """Who a plain call is for during a zone flight; None: the usual roles."""
        if self.ctr_stage == "out":
            return "tower"
        if not self._ctr_arrival() or self.phase not in ("airborne", "climb", "enroute", "arrival", "approach",
                                                          "final"):
            return None
        if self.ctr_stage in ZONE_STAGES:
            return "arrival_tower"
        state, dest = self.state, self.destination
        if state is not None and distance_nm(state.lat, state.lon, dest.lat, dest.lon) <= INFO_CALL_NM:
            return "arrival_tower"
        return None

    # --- departure (E1) -----------------------------------------------------------------------------------------

    def _ctr_exit_items(self) -> list[rb.Item]:
        """"leave the control zone via November, one thousand five hundred feet or below, squawk 7000", for the
        takeoff clearance."""
        dest = self.destination
        self.ctr_point = zone_point(self.airport, dest.lat, dest.lon)
        self.ctr_stage, self.ctr_closest, self.ctr_altitude_told = "out", math.inf, False
        limit = ctr_limit_ft(self.airport)
        p = self.ctr_point
        how = f"via {p.words}" if p.point else f"to the {p.words}"
        return [rb.Item("vfr_point", p.code, f"leave the control zone {how}"),
                rb.Item("altitude_ft", limit, f"{spoken.altitude(limit)} or below"),
                rb.squawk(self.squawk or "7000")]

    def _ctr_report_text(self) -> str:
        return f"report {self.ctr_point.words}" if self.ctr_point.point else "report leaving the control zone"

    def _ctr_leave(self, station: Station, state: AircraftState | None = None) -> list[Response]:
        self.phase, self.ctr_stage, self.ctr_point = "enroute", None, None
        self.crossing, self.ctr_exit, self.ctr_entered = None, None, False
        text = f"{self.cs}, leaving the control zone, frequency change approved"
        return self._transmit(station, text, state) if state else [self._say(station, text)]

    def _ctr_out_tick(self, state: AircraftState) -> list[Response]:
        origin, tower = self.airport, self.station("tower")
        inside = in_zone(origin, state.lat, state.lon, state.alt_msl_ft)
        if check := self._ctr_altitude_check(origin, tower, inside, state):
            return check
        if not inside or self._ctr_passed(state):
            return self._ctr_leave(tower, state)
        return []

    # --- arrival (E2) -------------------------------------------------------------------------------------------

    def _ctr_entry(self, intent, station: Station, state: AircraftState) -> list[Response]:
        """The inbound call: where to enter the zone, how low, and the QNH when the pilot has no current ATIS."""
        dest, runway = self.destination, self.arrival_runway
        p = self.ctr_point = zone_point(dest, state.lat, state.lon)
        self.ctr_closest, self.ctr_altitude_told = math.inf, False
        limit = ctr_limit_ft(dest)
        how = f"via {p.words}" if p.point else f"from the {p.words}"
        items = [rb.Item("vfr_point", p.code, f"enter the control zone {how}"),
                 rb.Item("altitude_ft", limit, f"{spoken.altitude(limit)} or below")]
        has_atis = any(f.type == "ATIS" for f in dest.frequencies)
        current = has_atis and intent.items.get("atis") == self.dest_atis.letter.lower()
        if not current:
            if p.point:
                items.append(rb.Item("runway", runway, f"runway {spoken.runway(runway)}"))
            if self.destination_metar and self.destination_metar.qnh_hpa:
                items.append(rb.qnh(self.destination_metar.qnh_hpa))
        if p.point:
            self.phase, self.ctr_stage = "arrival", "in"
            report = f"report {p.words}"
        else:  # no point to report: straight into the circuit
            items.append(self._join_item())
            self.phase, self.ctr_stage = "approach", "joining"
            report = "report downwind"
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, {station.name}, {rb.instruction_text(items)}, {report}")]

    def _join_item(self) -> rb.Item:
        runway = self.arrival_runway
        side = circuit_side(self.destination, runway)
        return rb.Item("runway", runway, f"join {leg_words('downwind', side)} runway {spoken.runway(runway)}")

    def _ctr_join(self, station: Station, state: AircraftState | None = None) -> list[Response]:
        """At the point: into the circuit."""
        item = self._join_item()
        self.phase, self.ctr_stage = "approach", "joining"
        self._set_pending([item], station.key)
        traffic = self._ctr_traffic()
        text = f"{self.cs}, " + ", ".join(filter(None, [item.phrase, traffic, "report downwind"]))
        return self._transmit(station, text, state) if state else [self._say(station, text)]

    def _ctr_traffic(self) -> str | None:
        traffic = self._circuit_traffic(self.destination, self.arrival_runway)
        return None if traffic == "no reported traffic" else traffic

    def _ctr_in_tick(self, state: AircraftState) -> list[Response]:
        dest, tower = self.destination, self.station("arrival_tower")
        inside = in_zone(dest, state.lat, state.lon, state.alt_msl_ft)
        if check := self._ctr_altitude_check(dest, tower, inside, state):
            return check
        leg = self._ctr_leg(state)
        if leg == "final":
            return self._ctr_final(tower, state)
        if self._ctr_passed(state) or leg in ("crosswind", "downwind", "base"):
            return self._ctr_join(tower, state)
        return []

    def _ctr_leg(self, state: AircraftState) -> str | None:
        dest = self.destination
        return circuit_leg(dest, self.arrival_runway, state.lat, state.lon, (state.heading_mag + dest.mag_var) % 360,
                           state.alt_msl_ft, state.on_ground)

    def _ctr_final(self, station: Station, state: AircraftState, called: bool = False) -> list[Response]:
        self.phase, self.ctr_stage = "final", "final"
        return self._final_call(station, state, auto=not called)

    # --- crossing (E3) ------------------------------------------------------------------------------------------

    def _zone_tower(self, airport: Airport) -> Station | None:
        towers = [f for f in airport.frequencies if f.type == "T"]
        return Station(airport.ident, min(towers, key=lambda f: f.khz)) if towers else None

    def _crossing_field(self, station: Station) -> Airport | None:
        return next((a for a in self.crossing_fields if a.ident == station.ident and station.freq.type == "T"), None)

    def _crossing_call(self, intent, station: Station, state: AircraftState) -> list[Response] | None:
        """A call to the Tower of a zone on the way; None: not one, the usual answers."""
        if not self.vfr or state.on_ground or self.phase not in ("airborne", "climb", "enroute"):
            return None
        field, kind = self._crossing_field(station), intent.kind
        if field is None:
            if kind != "request_crossing" or self.ctr_stage is not None or not self.crossing_fields:
                return None
            ahead = min(self.crossing_fields, key=lambda a: distance_nm(state.lat, state.lon, a.lat, a.lon))
            return self._redirect(station, self._zone_tower(ahead), "tower")  # the wrong station: whose zone it is
        if self.ctr_stage is None:
            if kind == "request_crossing":
                return self._crossing_clearance(intent, field, station, state)
            if kind in ("checkin", "inbound", "point_report"):
                return [self._say(station, f"{self.cs}, {station.name}, go ahead")]
            return None
        if self.ctr_stage != "crossing" or self.crossing is not field:
            return None
        if kind in ("acknowledge", "readback"):
            return []
        if kind == "unknown":
            return [self._say(station, f"{self.cs}, say again")]
        said = intent.items.get("vfr_point", "")
        if kind == "leaving_frequency" or (kind == "point_report" and said in ("", self.ctr_exit.code)):
            return self._ctr_leave(station)
        if kind == "point_report" and said == self.ctr_point.code:
            self._crossing_next()
        return [self._say(station, f"{self.cs}, roger, {self._ctr_report_text()}")]

    def _crossing_clearance(self, intent, field: Airport, station: Station, state: AircraftState) -> list[Response]:
        """"cleared to cross the control zone via November and Sierra, one thousand five hundred feet or below,
        report November"."""
        dest = self.destination
        entry = named_point(field, intent.items.get("vfr_point")) or zone_point(field, state.lat, state.lon)
        exit_ = named_point(field, intent.items.get("vfr_exit")) or zone_point(field, dest.lat, dest.lon)
        self.crossing, self.ctr_point, self.ctr_exit = field, entry, exit_
        self.ctr_stage, self.ctr_closest, self.ctr_altitude_told, self.ctr_entered = "crossing", math.inf, False, False
        how = (f"via {entry.words} and {exit_.words}" if entry.point and exit_.point
               else f"from the {entry.words} to the {exit_.words}")
        limit = ctr_limit_ft(field)
        items = [rb.Item("vfr_point", entry.code, f"cleared to cross the control zone {how}"),
                 rb.Item("altitude_ft", limit, f"{spoken.altitude(limit)} or below")]
        self._set_pending(items, station.key)
        return [self._say(station, f"{self.cs}, {station.name}, {rb.instruction_text(items)}, "
                                   f"{self._ctr_report_text()}")]

    def _crossing_next(self) -> None:
        """The entry point reached: from now on the exit point."""
        if self.ctr_point is not self.ctr_exit:
            self.ctr_point, self.ctr_closest = self.ctr_exit, math.inf

    def _crossing_tick(self, state: AircraftState) -> list[Response]:
        if self.pending and not all(i.key == "frequency_khz" for i in self.pending):
            return []  # the crossing clearance not read back yet
        field = self.crossing
        tower = self._zone_tower(field)
        inside = in_zone(field, state.lat, state.lon, state.alt_msl_ft)
        if check := self._ctr_altitude_check(field, tower, inside, state):
            return check
        self.ctr_entered = self.ctr_entered or inside
        if self._ctr_passed(state):
            if self.ctr_point is self.ctr_exit:
                return self._ctr_leave(tower, state)
            self._crossing_next()
        if self.ctr_entered and not inside:
            return self._ctr_leave(tower, state)
        return []

    # --- both ---------------------------------------------------------------------------------------------------

    def _ctr_altitude_check(self, airport: Airport, station: Station | None, inside: bool,
                            state: AircraftState) -> list[Response]:
        limit = ctr_limit_ft(airport)
        if station is None or self.ctr_altitude_told or not inside or state.alt_msl_ft <= limit + ALTITUDE_MARGIN_FT:
            return []
        self.ctr_altitude_told = True
        return self._transmit(station, f"{self.cs}, check altitude, {spoken.altitude(limit)} or below", state)

    def _ctr_passed(self, state: AircraftState) -> bool:
        """Came close to the point and flies away from it again."""
        p = self.ctr_point.point if self.ctr_point else None
        if p is None:
            return False
        nm = distance_nm(state.lat, state.lon, p.lat, p.lon)
        self.ctr_closest = min(self.ctr_closest, nm)
        return self.ctr_closest <= POINT_PASSED_NM and nm > self.ctr_closest + PASSED_MARGIN_NM

    def _ctr_tick(self, state: AircraftState) -> list[Response] | None:
        """tick() during a zone flight. None: none now, the rest of tick() goes on."""
        if self.ctr_stage == "out":
            if self.phase == "takeoff":
                if not state.on_ground and state.alt_agl_ft > AIRBORNE_AGL_FT:
                    self.phase = "climb"  # no Departure: Tower keeps the flight until it is out of the zone
                return []
            if self.pending and not all(i.key == "frequency_khz" for i in self.pending):
                return []  # the takeoff clearance not read back yet
            return self._ctr_out_tick(state)
        if not self._ctr_arrival() or self.phase in ("clearance", "cleared", "pushback", "taxi", "takeoff"):
            return None
        if self.phase in ("airborne", "climb", "enroute", "arrival"):
            return self._ctr_in_tick(state) if self.ctr_stage == "in" else []  # no descent, no Approach
        if self.phase == "approach":
            if self.ctr_stage in ("joining", "final_due") and self._ctr_leg(state) == "final":
                return self._ctr_final(self.station("arrival_tower"), state)
            return []  # no speed control in the circuit
        if self.phase == "final":
            return []
        return None  # landing and after: as at any field

    def _ctr_call(self, intent, station: Station, state: AircraftState) -> list[Response] | None:
        """A call during a zone flight; None: not one, the usual answers."""
        kind, stage = intent.kind, self.ctr_stage
        if stage == "out":
            tower = self.station("tower")
            airborne = self.phase in ("airborne", "climb", "enroute")
            if airborne and tower is not None and station.key == tower.key and kind in ("point_report",
                                                                                        "leaving_frequency"):
                return self._ctr_leave(station)
            return None
        tower = self.station("arrival_tower")
        if (not self._ctr_arrival() or state.on_ground or tower is None or station.key != tower.key
                or self.phase not in ("airborne", "climb", "enroute", "arrival", "approach", "final")):
            return None
        if stage is None and kind in ("inbound", "checkin", "point_report"):
            return self._ctr_entry(intent, station, state)
        if stage == "in" and kind == "point_report":
            return self._ctr_join(station)
        if stage in ("in", "joining") and kind == "circuit_report":
            self.phase, self.ctr_stage = "approach", "final_due"
            text = ", ".join(filter(None, [self.cs, self._ctr_traffic(), "report final"]))
            return [self._say(station, text)]
        if stage in ZONE_STAGES and kind == "on_final":
            return self._ctr_final(station, state, called=True)
        if stage in ZONE_STAGES and self.phase != "final":  # anything else: no radar vectors, no Approach
            if kind in ("acknowledge", "readback"):
                return []
            if kind == "unknown":
                return [self._say(station, f"{self.cs}, say again")]
            then = {"in": self._ctr_report_point(), "joining": "report downwind", "final_due": "report final"}
            return [self._say(station, f"{self.cs}, roger, {then[stage]}")]
        return None

    def _ctr_report_point(self) -> str:
        return f"report {self.ctr_point.words}" if self.ctr_point and self.ctr_point.point else "report downwind"

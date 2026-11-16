"""The traffic picture (step T1): what each other aircraft is doing, worked out from where it is.

SimConnect only tells position, speed, heading and "on ground" (atc/sim/traffic.py). From that and the airport data
each aircraft gets a state, the way a tower controller sees it:
    parked, taxiing        on the ground, off the runways
    on_runway              on the ground inside a runway's protected area (lined up, rolling, landed)
    final                  in the air, lined up with a runway end, within 10 nm and low
    departing              in the air, close to the airport and low, after being on a runway
    airborne               anything else in the air
LiveTraffic, FSLTL and MSFS's own AI look the same here. Everything is deterministic: same positions, same states.
The changes between two updates are kept as transitions ("final → on_runway" = landed), for ATC calls about traffic
(T2) and the AI's radio calls (T4).
"""
from dataclasses import dataclass

from atc.airport.geo import bearing_deg, distance_nm
from atc.airport.model import Airport
from atc.phraseology import spoken
from atc.phraseology.airlines import TELEPHONY
from atc.controller.safety import RunwayZones, designator
from atc.sim.traffic import Traffic

NEAR_AIRPORT_NM = 15  # farther away an aircraft belongs to no airport
FINAL_NM, FINAL_AGL_FT = 10, 4000
FINAL_OFFSET_DEG, FINAL_HEADING_DEG = 10, 30  # off the extended centreline / off the runway's heading
DEPARTING_NM, DEPARTING_AGL_FT = 5, 4000
TAXI_KT = 3
ALIGNED_DEG = 20  # on a runway and pointing along it: lined up (or landing), not crossing


@dataclass(frozen=True)
class TrafficState:
    kind: str  # parked, taxiing, on_runway, final, departing, airborne
    airport: str | None = None  # ICAO, None far from both airports
    runway: str | None = None  # on_runway: the designator ("05" for 05/23); final: the runway end ("23")
    distance_nm: float | None = None  # final: to the threshold
    aligned: bool = False  # on_runway: pointing along the runway, not across it


def classify(t: Traffic, airport: Airport, zones: RunwayZones, was: TrafficState | None = None) -> TrafficState:
    if distance_nm(t.lat, t.lon, airport.lat, airport.lon) > NEAR_AIRPORT_NM:
        return TrafficState("airborne" if not t.on_ground else "parked")
    if t.on_ground:
        if rwy := zones.runway_at(t.lat, t.lon):
            aligned = any(abs((e.heading_true - t.heading_true + 540) % 360 - 180) <= ALIGNED_DEG for e in rwy.ends)
            return TrafficState("on_runway", airport.ident, designator(rwy), aligned=aligned)
        return TrafficState("taxiing" if t.ground_speed_kt > TAXI_KT else "parked", airport.ident)
    agl = t.alt_ft - airport.elevation_ft
    for rwy in airport.runways:
        for end in rwy.ends:
            dist = distance_nm(end.lat, end.lon, t.lat, t.lon)
            outbound = (end.heading_true + 180) % 360
            offset = abs((bearing_deg(end.lat, end.lon, t.lat, t.lon) - outbound + 540) % 360 - 180)
            heading_off = abs((t.heading_true - end.heading_true + 540) % 360 - 180)
            if dist <= FINAL_NM and agl <= FINAL_AGL_FT and offset <= FINAL_OFFSET_DEG \
                    and heading_off <= FINAL_HEADING_DEG:
                return TrafficState("final", airport.ident, end.name, round(dist, 1))
    near = distance_nm(t.lat, t.lon, airport.lat, airport.lon) <= DEPARTING_NM and agl <= DEPARTING_AGL_FT
    if near and was is not None and was.kind in ("on_runway", "departing"):
        return TrafficState("departing", airport.ident, was.runway)
    return TrafficState("airborne", airport.ident)


TRAFFIC_INFO_NM, TRAFFIC_INFO_FT, TRAFFIC_FORGET_NM = 5, 1500, 8  # traffic information (T3)


def traffic_information(t: Traffic, lat: float, lon: float, alt_ft: float, heading_true: float) -> str | None:
    """"traffic, two o'clock, four miles, opposite direction, one thousand feet above" for an aircraft close in
    distance and height; None when it isn't. The clock is the bearing to it from our nose (12 = straight ahead)."""
    dist = distance_nm(lat, lon, t.lat, t.lon)
    above = round((t.alt_ft - alt_ft) / 100) * 100
    if t.on_ground or dist > TRAFFIC_INFO_NM or abs(above) > TRAFFIC_INFO_FT:
        return None
    relative = (bearing_deg(lat, lon, t.lat, t.lon) - heading_true) % 360
    clock = round(relative / 30) % 12 or 12
    course = (t.heading_true - heading_true + 540) % 360 - 180  # its course against ours, -180..180
    if abs(course) <= 45:
        direction = "same direction"
    elif abs(course) >= 135:
        direction = "opposite direction"
    else:
        direction = "crossing left to right" if course > 0 else "crossing right to left"
    level = "same level" if abs(above) < 300 else \
        f"{spoken.altitude(abs(above))} {'above' if above > 0 else 'below'}"
    miles = max(1, round(dist))
    clock_words = {10: "ten", 11: "eleven", 12: "twelve"}.get(clock) or spoken.digits(clock)  # whole, not digits
    return (f"traffic, {clock_words} o'clock, {spoken.digits(miles)} mile{'s' if miles > 1 else ''}, "
            f"{direction}, {level}")


def spoken_callsign(t: Traffic) -> str:
    """How the AI aircraft is called on the radio: "Lufthansa one two three", else its registration spelled."""
    airline = TELEPHONY.get(t.airline.upper(), t.airline) if t.airline else ""  # "DLH" or "Lufthansa"
    if airline and t.flight_number:
        number = t.flight_number.upper()
        return f"{airline} {spoken.digits(number) if number.isdigit() else spoken.spell(number)}"
    # LiveTraffic leaves airline and flight number empty and puts the real ADS-B callsign in ATC ID: "AFR49KP" is
    # "Airfrans four niner Kilo Papa"; a registration ("D-ANCH") or an unknown airline is spelled
    return spoken.callsign(t.atc_id) if t.atc_id else "unknown traffic"


def runway_end_for(airport: Airport, designator_name: str, heading_true: float) -> str:
    """The end of that runway an aircraft on it is pointing at: the one whose heading is closest to its own."""
    rwy = next(r for r in airport.runways if designator_name in (r.ends[0].name, r.ends[1].name))
    return min(rwy.ends, key=lambda e: abs((e.heading_true - heading_true + 540) % 360 - 180)).name


@dataclass(frozen=True)
class Transition:
    aircraft: Traffic
    before: TrafficState | None  # None: newly seen
    after: TrafficState


class TrafficPicture:
    """The other aircraft and their states, updated every few seconds from the sim."""

    def __init__(self):
        self.aircraft: dict[int, Traffic] = {}
        self.states: dict[int, TrafficState] = {}
        self.departed: set[str] = set()  # callsigns seen departing: climbing out, not in the arrival pattern (B6)

    def update(self, traffic: list[Traffic], places: list[tuple[Airport, RunwayZones]]) -> list[Transition]:
        """places: the airports that matter (origin, destination) with their runway zones; each aircraft is judged
        against the nearest one."""
        transitions, states = [], {}
        # B4: after an ADS-B drop-out the sim may re-create an aircraft under a new ID; its callsign tells it is the
        # same one, so it keeps its state (a landing stays a landing, not "newly seen" on the runway)
        here = {t.object_id for t in traffic}
        vanished = {a.atc_id: self.states[i] for i, a in self.aircraft.items()
                    if i not in here and a.atc_id and i in self.states}
        for t in traffic:
            airport, zones = min(places, key=lambda p: distance_nm(t.lat, t.lon, p[0].lat, p[0].lon))
            before = self.states.get(t.object_id) or vanished.get(t.atc_id)
            after = classify(t, airport, zones, before)
            states[t.object_id] = after
            if before is None or (before.kind, before.runway, before.aligned) != (after.kind, after.runway,
                                                                                after.aligned):
                transitions.append(Transition(t, before, after))
        self.aircraft = {t.object_id: t for t in traffic}
        self.states = states
        self.departed |= {self.aircraft[i].atc_id for i, s in states.items() if s.kind == "departing"}
        return transitions

    def on_runway(self, airport: str, runway_designator: str) -> list[Traffic]:
        """Aircraft on the ground on that runway (lined up, rolling, landed and not yet off)."""
        return [self.aircraft[i] for i, s in self.states.items()
                if s.kind == "on_runway" and s.airport == airport and s.runway == runway_designator]

    def on_final(self, airport: str, runway_designator: str, within_nm: float, designator_of) -> list[Traffic]:
        """Aircraft on final for either end of that runway, closer than within_nm. designator_of(end) → "05"."""
        return [self.aircraft[i] for i, s in self.states.items()
                if s.kind == "final" and s.airport == airport and designator_of(s.runway) == runway_designator
                and s.distance_nm <= within_nm]

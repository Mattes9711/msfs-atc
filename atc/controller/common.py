"""What the controller's parts share: limits, the controller roles and phases, Response and Station, and small
helpers."""
from dataclasses import dataclass

from atc.airport.model import Airport, Frequency
from atc.airspace.centers import CenterSector
from atc.intent.schema import Intent
from atc.phraseology import spoken
from atc.units import format_khz
from atc.weather.metar import Metar

INITIAL_CLIMB_FT = 5000
DESCENT_FL = 100  # Center's descent: to FL100 (with the STAR); Approach then gives altitudes with the QNH
DESCENT_ALTITUDE_FT = 5000
DESCENT_MARGIN_NM = 15  # be down at DESCENT_ALTITUDE_FT this far from the airport
DESCENT_LEAD_NM = 5  # the descent comes this far before the top of descent: time to read back and start down
# Approach vectors: the way left is at most this much longer than straight to the field (downwind, base, intercept).
# A long STAR loop (EDDH NOLG3P, about 45 nm) is cut short, so its track miles would give the descent far too late
VECTOR_ALLOWANCE_NM = 15
DESCENT_REQUEST_NM = 20  # the co-pilot offers "request descent" this far before the descent point
APPROACH_HANDOFF_NM = 40
TOWER_HANDOFF_NM = 12  # from the landing threshold
FINAL_FIX_NM = 10
# Radar vectors: downwind, base and intercept, see atc/controller/vectors.py (Milestone 8, H)
INTERCEPT_ANGLE = 30
FINAL_CONE_DEG, FINAL_CONE_NM = 15, 18
ON_COURSE_DEG = 3  # this close to the extended centreline counts as established
APPROACH_SPEED_KT, FINAL_SPEED_KT = 220, 180
AIRBORNE_AGL_FT = 500
VACATE_SPEED_KT = 40
AT_POINT_M = 30  # "at" a holding point or hold short
NEAR_HOLDING_POINT_M = 150  # Tower takes a call from one this close to a departure holding point (C2)
HOLD_SHORT_HINT_S = 15  # stopped at a crossing this long without reporting: show the call to make
STOPPED_KT = 2
NO_CLEARANCE_GO_AROUND_NM = 2
VFR_GO_AROUND_NM = 0.5  # a VFR flight in a control zone's circuit: sent around only this close without clearance
DEPARTURE_CEILING_FL = 240  # with Center sectors, Departure climbs to this at most; Center gives the rest
MAX_FL = 410
DIRECT_MAX_NM = 150  # Center's direct-to: the farthest route point ahead within this distance
SHORTCUTS = 2  # Center's direct-tos a flight (the user: "1-2 real shortcuts")
SHORTCUT_MIN_NM = 10  # a direct-to must save at least this much
CENTER_HANDOFF_FT, CENTER_HANDOFF_NM = 10000, 30  # Departure -> Center: passing FL100 or this far out
VFR_SQUAWK = "7000"
GO_AROUND_BELOW_AGL_FT, GO_AROUND_CLIMB_FT = 300, 200  # low on final, then climbing this much
RESERVED_SQUAWKS = {"1000", "1200", "2000", "7000"}  # 75xx/76xx/77xx can't occur: first digit is 1-6
INTERSECTION_MARGIN_M = 60  # a taxiway end this far beside the runway edge still leads onto it
READBACK_REMINDER_S = 20
# "confirm descending" (Milestone 10 D): asked once when the aircraft hasn't lost DESCENDING_FT in DESCENT_CHECK_S
# since the descent was read back (or since it last did); within LEVEL_REACHED_FT of the level it is there
DESCENT_CHECK_S, DESCENDING_FT, LEVEL_REACHED_FT = 90, 300, 300
PUSH_BEHIND_M = 150  # a taxiing aircraft this close behind the stand holds the pushback (L3)
STOPPED_BEHIND_M = 80  # one standing still this close behind, off the stands, holds it too (B2)
AT_STAND_M = 25  # an aircraft this close to a parking position is parked there, not in the way
GIVE_WAY_AHEAD_M = 300  # how much of our taxi route ahead ATC watches for traffic (L4)
FOLLOW_WITHIN_M = 200  # "follow the …" only for an aircraft this close ahead
TURNED_DEG = 30  # a departure this far off the runway heading has turned away: the runway is ours (L5)
CLOSE_PARALLEL_M = 760  # ICAO: parallel runways closer than this count as one for wake turbulence (B5)
TRAFFIC_INFO_GAP_S = 60  # traffic information at most this often (B4)
WAKE_CAUTION_S = 300  # "caution wake turbulence" behind a heavier departure up to this long after it
LANDING_WAKE_S = 120  # … and after a heavier landing on our runway (B5)
# Approach sequence (L6): speed control behind the aircraft ahead on final, not closer in than ICAO's 4 NM
SPEED_CONTROL_UNTIL_NM = 4
PATTERN_NM, PATTERN_AGL_FT = 12, 4000  # an arrival on downwind or base: this close to the threshold and low (B6)
SPACING_SPEED_KT = 160
CLOSING_KT = 5  # faster than the one ahead by more than this: we are catching up
GAP_SHRINK_NM = 0.5  # after "reduce speed": the gap shrank this much more, then "reduce to final approach speed"
SECTOR_NEAR_DEG = 3
APRON_RADIUS_M = 150
# Traffic (T2): a runway is not free with someone on it, or landing within this distance
LANDING_TRAFFIC_NM = 4
ROLLING_KT = 40  # faster than this on the runway = taking off (line up behind it), slower = landed or waiting
OCCUPIED_GO_AROUND_NM = 1  # cleared to land, but the runway is still occupied this close in  # farther than this from every parking position = off the apron

# role -> (which airport, frequency types that can do the job, best first). Missing stations fold up.
ROLES = {
    "clearance": ("origin", ("C", "G", "T")),
    # No Ground, but an Apron (EDDH with the VATGER roles): Apron taxis the aircraft all the way
    "ground": ("origin", ("G", "APRON", "T")),
    "tower": ("origin", ("T",)),
    "departure": ("origin", ("D", "A")),  # without Center sectors, departure keeps the aircraft until arrival
    # "center" is not here: it depends on where the aircraft is (centers.json), see _center_progress
    "approach": ("destination", ("A", "T")),
    "arrival_tower": ("destination", ("T",)),
    "arrival_ground": ("destination", ("G", "APRON", "T")),
    "apron": ("origin", ("APRON",)),  # only where the data has one (EDDM: yes, EDDH: no)
    "arrival_apron": ("destination", ("APRON",)),
    # A small field's Info station (Milestone 9 B): only used where the airport has no controller
    "info": ("origin", ("FSS",)),
    "arrival_info": ("destination", ("FSS",)),
}
PHASES = ("clearance", "cleared", "pushback", "taxi", "takeoff",  # ground, origin
          "airborne", "climb", "enroute", "arrival", "approach", "final", "landing",  # air
          "vacating", "taxi_in")  # ground, destination
# Who a plain call (check-in, readback, "with you") is for in each phase
CALL_ROLE = {"airborne": "departure", "climb": "departure", "enroute": "center", "arrival": "approach", "approach": "approach",
             "final": "arrival_tower", "landing": "arrival_tower", "vacating": "arrival_ground",
             "taxi_in": "arrival_ground"}
# Who the pilot should be talking to in each phase (for the status display)
PHASE_ROLE = {"clearance": "clearance", "cleared": "ground", "pushback": "ground", "taxi": "ground",
              "takeoff": "tower", **CALL_ROLE}
AIR_PHASES = ("airborne", "climb", "enroute", "arrival", "approach", "final")  # traffic information
CALL_KINDS = ("checkin", "readback", "acknowledge", "unknown", "request_other", "leaving_frequency", "inbound",
              "on_final", "circuit_report", "point_report")
# Uncontrolled fields (Milestone 9 B): who counts as in the circuit, and when a moving aircraft taxis
CIRCUIT_NM, CIRCUIT_AGL_FT = 3, 2500
TAXIING_KT = 5
INFO_CALL_NM = 15  # the inbound call to the destination's Info is suggested from this close in


@dataclass(frozen=True)
class Response:
    text: str
    spoken: bool  # False = on-screen hint only, never transmitted
    kind: str = ""  # event kind (atc.events.KINDS); empty = "atc" if spoken, else "notice"
    station: str | None = None  # who transmitted (or who called on another frequency)

    @property
    def event_kind(self) -> str:
        return self.kind or ("atc" if self.spoken else "notice")


@dataclass(frozen=True)
class Station:
    ident: str  # airport ICAO, or "FIR/sector name" for a Center
    freq: Frequency

    @property
    def name(self) -> str:
        return self.freq.station or self.freq.name  # a Center's name is complete already ("Bremen Radar")

    @property
    def key(self) -> tuple[str, str]:
        """Same key = same controller, even on another of its frequencies. Apron and Ground are both typed Ground
        in the data, so the key uses the role. A VFR Tower (EDDH 121.280) is a controller of its own."""
        return self.ident, self.freq.role + ("/VFR" if self.freq.qualifier == "VFR" else "")


def best_frequency(frequencies, vfr: bool) -> Frequency:
    """The one to call of a controller's frequencies: the lowest, but a VFR Tower only for VFR flights (and first
    for them)."""
    return min(frequencies, key=lambda f: ((f.qualifier == "VFR") != vfr, f.khz))


def labelled(label: str, f: Frequency) -> str:
    """A frequency list's short label with the part of the field: "APRON E", "TWR VFR" (VATGER roles)."""
    return f"{label} {f.qualifier}" if f.qualifier else label


def center_station(sector: CenterSector) -> Station:
    # The frequency is part of the key: Bremen Radar on 125.100 and on 119.825 are two sectors, so moving from one
    # to the other is a handoff. Sectors sharing name and frequency are one controller.
    return Station(f"{sector.fir}/{sector.name}/{sector.khz}", Frequency("CTR", sector.name, sector.khz))


def _wind(metar: Metar | None) -> str | None:
    if metar is None or metar.wind_kt is None:
        return None
    return spoken.wind(metar.wind_dir, metar.wind_kt, metar.gust_kt)


def describe_intent(intent: Intent) -> str:
    if intent.callsign is None:
        who = "no callsign"
    else:
        who = f"callsign {intent.callsign} ({'yours' if intent.addressed_to_us else 'not yours'})"
    items = " ".join(f"{k}={v}" for k, v in intent.items.items())
    return f"understood: {intent.kind}, {who}" + (f", {items}" if items else "")


def wrong_frequency_hint(airport: Airport, com1_khz: int, center: Station | None = None) -> str:
    freq = airport.frequency_at(com1_khz)
    if com1_khz == 0:
        start = "COM1 is not tuned."
    elif freq is not None:
        start = f"{format_khz(com1_khz)} is {airport.ident} {freq.type}, not a controller."
    else:
        start = f"Nobody on {format_khz(com1_khz)}."
    en_route = f" En route: {center.name} {format_khz(center.freq.khz)}." if center else ""
    return f"{start}{en_route} {airport.ident} frequencies: {frequency_list(airport)}. Tune with /com <MHz>."


def frequency_list(airport: Airport) -> str:
    order = ["C", "G", "APRON", "T", "A", "D", "FSS", "ATIS"]
    groups: dict[str, list[str]] = {}
    for f in sorted(airport.frequencies, key=lambda f: (order.index(f.role) if f.role in order else 99, f.khz)):
        if f.station or f.type == "ATIS":
            name = f"{f.station} (VFR)" if f.station and f.qualifier == "VFR" else f.station
            groups.setdefault(name or "ATIS", []).append(format_khz(f.khz))
    return " | ".join(f"{name} {', '.join(khz)}" for name, khz in groups.items())

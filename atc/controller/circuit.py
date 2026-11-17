"""The traffic circuit at a small field (Milestone 9 C1): which leg an aircraft flies, from where it is and where
it points, relative to the runway in use and the side of its circuit.

    upwind      past the threshold on the centreline, pointing the runway's way (after takeoff, a go-around)
    crosswind   past the threshold, turned towards the circuit side
    downwind    on the circuit side, pointing the opposite way
    base        on the circuit side before the threshold, turned back towards the centreline
    final       on the centreline before the threshold, pointing the runway's way

Only in the air within CIRCUIT_NM of the field and below CIRCUIT_AGL_FT above it; anywhere else, or pointing
some other way (joining, orbiting, on the dead side), it is on no leg: None. The geometry is loose on purpose:
real circuits are flown wide or tight, and a leg only has to be told apart from the others.
"""
import math

from atc.airport.geo import LocalProjection, distance_nm
from atc.airport.model import Airport
from atc.controller.common import CIRCUIT_AGL_FT, CIRCUIT_NM
from atc.phraseology import spoken

LEGS = ("upwind", "crosswind", "downwind", "base", "final")
REPORTED = ("downwind", "base", "final")  # the legs a pilot reports at a small field
CENTRELINE_M = 500  # this close beside the extended centreline counts as on it (final, upwind)
FINAL_NM = 4  # a final starts no farther out
TOLERANCE_DEG = 45  # pointing within this of a leg's direction


def circuit_side(airport: Airport, runway: str) -> str:
    end = airport.runway_end(runway)
    return "R" if end is not None and end.circuit == "R" else "L"


def circuit_leg(airport: Airport, runway: str, lat: float, lon: float, heading_true: float, alt_ft: float,
                on_ground: bool = False) -> str | None:
    """The leg of the circuit for runway `runway` (the landing direction) an aircraft is on, or None."""
    end = airport.runway_end(runway)
    if end is None or on_ground or alt_ft - airport.elevation_ft > CIRCUIT_AGL_FT \
            or distance_nm(lat, lon, airport.lat, airport.lon) > CIRCUIT_NM:
        return None
    x, y = LocalProjection(end.lat, end.lon).xy(lat, lon)
    h = math.radians(end.heading_true)
    along = x * math.sin(h) + y * math.cos(h)  # metres past the threshold, in the landing direction
    right = x * math.cos(h) - y * math.sin(h)  # metres right of the centreline
    sign = 1 if end.circuit == "R" else -1
    beside = right * sign  # metres to the circuit side
    turn = ((heading_true - end.heading_true + 540) % 360 - 180) * sign  # +90: pointing to the circuit side
    if abs(turn) <= TOLERANCE_DEG:
        if abs(beside) > CENTRELINE_M:
            return None
        if along < 0:
            return "final" if -along <= FINAL_NM * 1852 else None
        return "upwind"
    if abs(turn - 90) <= TOLERANCE_DEG:
        return "crosswind" if along > 0 else None
    if abs(turn) >= 180 - TOLERANCE_DEG:
        return "downwind" if beside > CENTRELINE_M else None
    if abs(turn + 90) <= TOLERANCE_DEG:
        return "base" if beside > 0 and along < 0 else None
    return None


def leg_words(leg: str, side: str) -> str:
    """"left downwind", "right base", "final", "upwind"."""
    if leg in ("crosswind", "downwind", "base"):
        return f"{'right' if side == 'R' else 'left'} {leg}"
    return leg


def position_report(leg: str, side: str, runway: str) -> str:
    """What a pilot says on a leg: "left downwind runway two seven"."""
    return f"{leg_words(leg, side)} runway {spoken.runway(runway)}"

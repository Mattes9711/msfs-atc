"""Other aircraft around us (step S2): every aircraft in the sim, whoever put it there.

LiveTraffic (real aircraft from ADS-B), FSLTL and MSFS's own AI all inject sim objects; SimConnect lists every
aircraft within a radius. Nothing of them is used or shipped: we only read what the sim reports. The ATC uses it from
step T1 on.
"""
from dataclasses import dataclass
from typing import Protocol

from atc.sim.native import STRING32, STRING256, Var

RADIUS_NM = 40
M_PER_NM = 1852

# One data definition for every aircraft. IS USER SIM tells our own aircraft apart (it is in the list too).
TRAFFIC_VARS = (
    Var("PLANE_LATITUDE", "degrees"), Var("PLANE_LONGITUDE", "degrees"), Var("PLANE_ALTITUDE", "feet"),
    Var("GROUND_VELOCITY", "knots"), Var("PLANE_HEADING_DEGREES_TRUE", "degrees"), Var("SIM_ON_GROUND", "bool"),
    Var("IS_USER_SIM", "bool"),
    Var("ATC_ID", None, STRING32),  # registration, e.g. "D-AIZA"
    Var("ATC_AIRLINE", None, STRING32),  # e.g. "Lufthansa" (FSLTL fills it from the flight schedule)
    Var("ATC_FLIGHT_NUMBER", None, STRING32),  # e.g. "123"
    Var("ATC_MODEL", None, STRING32),  # the type, e.g. "A320", or an MSFS text key
    Var("TITLE", None, STRING256),  # the model, e.g. "FSLTL A320 Lufthansa": tells who injected it
)
# MSFS's own parked AI reports SIM ON GROUND = 0 (the user's sim check at EDDH, 2026-11-15: 0 kt at 55 ft, "air").
# No aeroplane flies this slowly, so below it the aircraft is on the ground whatever the sim says.
AIRBORNE_MIN_KT = 30


@dataclass(frozen=True)
class Traffic:
    object_id: int  # the sim's ID, stable while the aircraft exists
    lat: float
    lon: float
    alt_ft: float
    ground_speed_kt: float
    heading_true: float
    on_ground: bool
    atc_id: str
    airline: str
    flight_number: str
    model: str
    title: str = ""

    @property
    def callsign(self) -> str:
        """How ATC would call it: "Lufthansa 123", else the registration."""
        return f"{self.airline} {self.flight_number}" if self.airline and self.flight_number else self.atc_id


def traffic_from_simvars(object_id: int, v: dict) -> Traffic | None:
    """None for our own aircraft."""
    if v["IS_USER_SIM"] >= 0.5:
        return None
    return Traffic(object_id, v["PLANE_LATITUDE"], v["PLANE_LONGITUDE"], v["PLANE_ALTITUDE"], v["GROUND_VELOCITY"],
                   v["PLANE_HEADING_DEGREES_TRUE"] % 360,
                   v["SIM_ON_GROUND"] >= 0.5 or v["GROUND_VELOCITY"] < AIRBORNE_MIN_KT,
                   v["ATC_ID"], v["ATC_AIRLINE"], v["ATC_FLIGHT_NUMBER"], v["ATC_MODEL"], v.get("TITLE", ""))


class TrafficSource(Protocol):
    def traffic(self) -> list[Traffic]:
        """The other aircraft within RADIUS_NM, possibly an empty list."""


class FakeTraffic:
    """For tests and practice mode: aircraft placed by hand."""

    def __init__(self, aircraft: list[Traffic] | None = None):
        self.aircraft = list(aircraft or [])

    def traffic(self) -> list[Traffic]:
        return list(self.aircraft)

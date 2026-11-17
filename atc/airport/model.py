import re
from dataclasses import dataclass
from typing import Protocol

# Little Navmap COM type codes -> ICAO station suffix. Types not listed (ATIS, UC, ...) are not controllers.
# FSS is a small field's flight information station ("Uetersen Info", Milestone 9 B): it informs, never clears.
STATION_SUFFIX = {"C": "Delivery", "G": "Ground", "T": "Tower", "A": "Approach", "D": "Departure", "FSS": "Info"}
CONTROLLER_TYPES = ("C", "G", "T", "A", "D")  # an airport with none of these is uncontrolled
# Apron (and ramp) frequencies are typed Ground in the MSFS data; only the name tells, e.g. "MUNICHAPRON1"
APRON = re.compile(r"\s*(?:APRON|RAMP)\s*\d*", re.IGNORECASE)


@dataclass(frozen=True)
class Frequency:
    type: str
    name: str
    khz: int

    @property
    def role(self) -> str:
        """The controller's job: the type, except "APRON" for an apron frequency typed Ground."""
        return "APRON" if self.type == "G" and APRON.search(self.name) else self.type

    @property
    def station(self) -> str | None:
        """As spoken: "Hamburg Ground"; "Munichapron1" → "Munich Apron"."""
        if self.role == "APRON":
            return f"{APRON.sub(' ', self.name).strip().title() or self.name} Apron"
        suffix = STATION_SUFFIX.get(self.type)
        return f"{self.name} {suffix}" if suffix else None


@dataclass(frozen=True)
class Ils:
    ident: str
    khz: int
    course_true: float


@dataclass(frozen=True)
class RunwayEnd:
    name: str
    heading_true: float
    lat: float
    lon: float
    offset_threshold_ft: float
    ils: Ils | None
    circuit: str = "L"  # the side of the traffic circuit (pattern), "L" or "R"


@dataclass(frozen=True)
class Runway:
    length_ft: float
    width_ft: float
    ends: tuple[RunwayEnd, RunwayEnd]


@dataclass(frozen=True)
class Parking:
    name: str  # "G 1", "P 707A"
    type: str  # Little Navmap codes: G* = gate, RGA* = GA ramp, RC = cargo ramp, ...
    lat: float
    lon: float
    heading: float
    airline_codes: tuple[str, ...]

    @property
    def is_gate(self) -> bool:
        return self.type.startswith("G")

    @property
    def is_ga(self) -> bool:
        return self.type.startswith("RGA")


@dataclass(frozen=True)
class TaxiPath:
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    name: str  # often "" in MSFS data
    type: str  # Little Navmap: P = path to a parking spot, PT/T = taxiway
    start_type: str  # N = normal, HSND = hold short, P = parking
    end_type: str

    @property
    def to_parking(self) -> bool:
        return self.type == "P"


@dataclass(frozen=True)
class VfrPoint:
    """A visual reporting point of the field ("NOVMR", "S1"): where VFR flights enter and leave the control zone."""
    ident: str
    lat: float
    lon: float


@dataclass(frozen=True)
class ControlZone:
    """The field's control zone (CTR), from the ground up to ceiling_ft MSL."""
    name: str
    ceiling_ft: float
    polygon: tuple[tuple[float, float], ...]  # (lat, lon)


@dataclass(frozen=True)
class Airport:
    ident: str
    name: str
    lat: float  # airport reference point, often somewhere between the runways
    lon: float
    elevation_ft: float
    mag_var: float
    frequencies: tuple[Frequency, ...]
    runways: tuple[Runway, ...]
    parking: tuple[Parking, ...] = ()
    taxi_paths: tuple[TaxiPath, ...] = ()
    vfr_points: tuple[VfrPoint, ...] = ()
    control_zone: ControlZone | None = None

    def runway_end(self, name: str) -> RunwayEnd | None:
        return next((e for r in self.runways for e in r.ends if e.name == name), None)

    @property
    def controlled(self) -> bool:
        """Has a controller (Delivery, Ground, Tower, Approach or Departure); else at most an Info station."""
        return any(f.type in CONTROLLER_TYPES for f in self.frequencies)

    def frequency_at(self, khz: int) -> Frequency | None:
        return next((f for f in self.frequencies if f.khz == khz), None)

    def default_parking(self, ga: bool = False) -> Parking | None:
        """A gate if there is one, so the fake sim starts somewhere an airliner would; with ga a spot on a GA ramp."""
        return min(self.parking, key=lambda p: (not (p.is_ga if ga else p.is_gate), p.name), default=None)


class AirportData(Protocol):
    name: str  # shown to the user, e.g. "Little Navmap"

    def get(self, ident: str) -> Airport | None: ...

    def procedures(self, ident: str):
        """The airport's STARs and approaches (atc.airport.procedures.Procedures), or None without them."""

    def nearest(self, lat: float, lon: float, max_nm: float) -> str | None:
        """Ident of the closest airport with a runway, measured to its reference point, or None."""

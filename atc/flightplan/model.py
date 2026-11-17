from dataclasses import dataclass


@dataclass(frozen=True)
class Waypoint:
    ident: str
    lat: float
    lon: float
    leg: str  # "sid", "route" or "star": which part of the flight it belongs to


@dataclass(frozen=True)
class FlightPlan:
    callsign: str
    departure: str
    destination: str | None = None
    cruise_ft: int | None = None
    route: str = ""
    aircraft: str | None = None
    rules: str = "IFR"
    # From SimBrief's navlog; empty for a manual plan (ATC then works without direct-tos and the STAR)
    waypoints: tuple[Waypoint, ...] = ()
    sid: str | None = None  # "AMLU2G"
    star: str | None = None  # "LAND2A"
    tod: tuple[float, float] | None = None  # SimBrief's top of descent (lat, lon), as the FMC plans it
    # ... and the altitude SimBrief plans there: lower than cruise_ft after a step descent (FL350, then FL310)
    tod_ft: int | None = None

    def route_points(self) -> tuple[Waypoint, ...]:
        """The en-route waypoints, without the SID and STAR points."""
        return tuple(w for w in self.waypoints if w.leg == "route")

from dataclasses import replace

from atc.airport.geo import along_route, bearing_deg, destination_point, distance_nm
from atc.airport.model import Airport, RunwayEnd
from atc.sim.base import AircraftState

CLIMB_FT_PER_NM = 500
DESCENT_FT_PER_NM = 318  # 3 degree glide path on final
ARRIVAL_ALT_FT, ARRIVAL_DISTANCE_NM = 5000, 15  # where the en-route descent ends
M_PER_NM = 1852


class FakeSim:
    """Stands in for MSFS in --nosim mode and in tests; the state only changes when told to."""

    def __init__(self, state: AircraftState):
        self.state = state

    @classmethod
    def parked_at(cls, airport: Airport, ga: bool = False) -> "FakeSim":
        # The airport reference point can be on a runway, so prefer a real parking spot
        spot = airport.default_parking(ga)
        lat, lon = (spot.lat, spot.lon) if spot else (airport.lat, airport.lon)
        return cls(AircraftState(
            lat=lat, lon=lon, alt_msl_ft=airport.elevation_ft + 9, alt_agl_ft=9.0, on_ground=True, heading_mag=0.0,
            ground_speed_kt=0.0, com1_khz=0, wind_dir_true=0.0, wind_speed_kt=0.0,
        ))

    def read(self) -> AircraftState:
        return self.state

    def update(self, **changes) -> None:
        self.state = replace(self.state, **changes)

    def set_com1(self, khz: int) -> None:
        """The co-pilot tunes COM1 (C2)."""
        self.update(com1_khz=khz)

    def fly(self, origin: Airport, dest: Airport, nm: float, cruise_ft: int | None) -> None:
        """Airborne nm along the great circle: climb, cruise, then 3 degrees down to 5000 ft at 15 nm out,
        the same profile ATC plans its descent clearance with."""
        total = distance_nm(origin.lat, origin.lon, dest.lat, dest.lon)
        nm = max(0.5, min(nm, total - 0.5))
        lat, lon = along_route(origin.lat, origin.lon, dest.lat, dest.lon, nm)
        alt = min(cruise_ft or 10000,
                  origin.elevation_ft + 1000 + nm * CLIMB_FT_PER_NM,
                  ARRIVAL_ALT_FT + max(0.0, total - nm - ARRIVAL_DISTANCE_NM) * 1000 / 3)
        ground = origin.elevation_ft if nm < total / 2 else dest.elevation_ft
        self.update(lat=lat, lon=lon, alt_msl_ft=round(alt, -2), alt_agl_ft=round(alt - ground, -2),
                    on_ground=False, ground_speed_kt=420,
                    heading_mag=bearing_deg(lat, lon, dest.lat, dest.lon) - dest.mag_var)

    def on_final(self, airport: Airport, end: RunwayEnd, nm: float) -> None:
        """On the extended centreline, nm before the threshold, on a 3 degree glide path."""
        lat, lon = destination_point(end.lat, end.lon, (end.heading_true + 180) % 360, nm)
        agl = nm * DESCENT_FT_PER_NM
        self.update(lat=lat, lon=lon, alt_msl_ft=airport.elevation_ft + agl, alt_agl_ft=agl, on_ground=False,
                    ground_speed_kt=140, heading_mag=end.heading_true - airport.mag_var)

    def landed(self, airport: Airport, end: RunwayEnd) -> None:
        """Rolling out, slow, 1500 m down the runway."""
        lat, lon = destination_point(end.lat, end.lon, end.heading_true, 1500 / M_PER_NM)
        self.update(lat=lat, lon=lon, alt_msl_ft=airport.elevation_ft + 9, alt_agl_ft=9.0, on_ground=True,
                    ground_speed_kt=30, heading_mag=end.heading_true - airport.mag_var)

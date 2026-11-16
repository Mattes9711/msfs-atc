from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AircraftState:
    lat: float
    lon: float
    alt_msl_ft: float
    alt_agl_ft: float  # ~9 ft when parked: measured at the aircraft reference point, not the wheels
    on_ground: bool
    heading_mag: float
    ground_speed_kt: float
    com1_khz: int  # 0 = not tuned
    wind_dir_true: float
    wind_speed_kt: float
    beacon: bool = False  # the red anti-collision beacon: on = ready to push and start (the co-pilot asks then)


class SimSource(Protocol):
    def read(self) -> AircraftState: ...

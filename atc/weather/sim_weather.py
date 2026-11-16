"""--weather sim: a METAR built from what MSFS reports at the aircraft, so ATC's wind matches the cockpit.

The sim's wind jumps around (8-13 kt within a minute in the spike), so it is averaged first. The result goes
through the normal METAR parser, which keeps runway choice and ATIS on one code path."""
import math
from datetime import datetime
from typing import Sequence

from atc.sim.simconnect import SimWeather

CALM_KT = 1


def average_wind(samples: Sequence[tuple[float, float]]) -> tuple[int, int]:
    """(direction true, knots) as a vector average: 350° and 010° average to 360°, not 180°.
    Direction rounded to 10° like a METAR, 360 for north."""
    if not samples:
        return 0, 0
    east = sum(kt * math.sin(math.radians(d)) for d, kt in samples) / len(samples)
    north = sum(kt * math.cos(math.radians(d)) for d, kt in samples) / len(samples)
    speed = round(math.hypot(east, north))
    direction = round(math.degrees(math.atan2(east, north)) / 10) * 10 % 360 or 360
    return direction, speed


def metar_from_sim(icao: str, when: datetime, winds: Sequence[tuple[float, float]], weather: SimWeather | None) -> str:
    """No clouds or dew point: MSFS doesn't report them as simvars, so the ATIS leaves them out."""
    direction, speed = average_wind(winds)
    groups = [icao.upper(), when.strftime("%d%H%MZ"),
              "00000KT" if speed < CALM_KT else f"{direction:03d}{speed:02d}KT"]
    if weather is not None:
        groups += [f"{min(9999, int(weather.visibility_m) // 100 * 100):04d}", f"Q{round(weather.sea_level_hpa)}"]
    return " ".join(groups + ["RMK", "MSFS"])

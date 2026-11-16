import math
from dataclasses import dataclass

from atc.airport.model import Airport, Runway, RunwayEnd
from atc.weather.metar import Metar

TAILWIND_LIMIT_KT = 5
CALM_BELOW_KT = 5


@dataclass(frozen=True)
class WindComponents:
    headwind: float  # negative = tailwind
    crosswind: float  # positive = from the right


def wind_components(runway_heading_true: float, wind_dir_true: float, wind_kt: float) -> WindComponents:
    # Both must be true headings: METAR wind and Little Navmap runway headings are true
    angle = math.radians(wind_dir_true - runway_heading_true)
    return WindComponents(wind_kt * math.cos(angle), wind_kt * math.sin(angle))


def choose_runway(airport: Airport, metar: Metar | None, current: str | None = None) -> RunwayEnd:
    """Pick the runway end in use. Keeps `current` while its tailwind stays within limits (hysteresis),
    so a wind swinging around 90 degrees off the runway doesn't flip the runway every METAR."""
    ends = [(rwy, end) for rwy in airport.runways for end in rwy.ends]
    by_name = {end.name: end for _, end in ends}
    current_end = by_name.get(current) if current else None

    calm = metar is None or metar.wind_kt is None or metar.wind_dir is None or metar.wind_kt < CALM_BELOW_KT
    if calm:
        if current_end:
            return current_end
        return _longest(ends, metar)

    strongest = max(metar.wind_kt, metar.gust_kt or 0)
    if current_end and wind_components(current_end.heading_true, metar.wind_dir, strongest).headwind >= -TAILWIND_LIMIT_KT:
        return current_end
    return max(ends, key=lambda pair: (_headwind(pair[1], metar), pair[0].length_ft, pair[1].name))[1]


def _headwind(end: RunwayEnd, metar: Metar) -> float:
    return round(wind_components(end.heading_true, metar.wind_dir, metar.wind_kt).headwind, 1)


def _longest(ends: list[tuple[Runway, RunwayEnd]], metar: Metar | None) -> RunwayEnd:
    longest = max(rwy.length_ft for rwy, _ in ends)
    candidates = [end for rwy, end in ends if rwy.length_ft == longest]
    if metar and metar.wind_dir is not None and metar.wind_kt:
        return max(candidates, key=lambda e: _headwind(e, metar))
    return min(candidates, key=lambda e: e.name)

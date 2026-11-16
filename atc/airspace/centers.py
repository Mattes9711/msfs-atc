"""En-route Center sectors. They come from the user's Little Navmap database (atc/airspace/littlenavmap.py: the
real MSFS sectors and frequencies), without it from the shipped VATSIM sectors (data/centers_vatsim.json, Germany,
atc/airspace/vatsim.py), and from a hand-maintained centers.json, for corrections and for tests.

Format (see data/centers.json):
    {"sectors": [{"name": "Bremen Radar", "fir": "EDWW", "frequency": "123.450",
                  "lower_ft": 0, "upper_ft": 66000, "polygon": [[lat, lon], ...]}, ...]}

"frequency" is MHz as a string, or exactly "PLACEHOLDER" when the real value is not known yet. A placeholder
sector is still found by position, but its frequency is None and the controller never hands off to it, nor says
anything about it: frequencies are never made up. The session drops such sectors when it loads its own file.
"""
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from atc.airport.geo import point_in_polygon
from atc.units import parse_mhz

PLACEHOLDER = "PLACEHOLDER"
SECTOR_KEYS = {"name", "fir", "frequency", "lower_ft", "upper_ft", "polygon"}
OPTIONAL_KEYS = {"note"}


class CentersError(Exception):
    pass


@dataclass(frozen=True)
class CenterSector:
    name: str  # station name as spoken, e.g. "Bremen Radar"
    fir: str
    khz: int | None  # None = PLACEHOLDER: the frequency is not known yet
    lower_ft: int  # MSL, inclusive
    upper_ft: int  # MSL, exclusive
    polygon: tuple[tuple[float, float], ...]  # (lat, lon)

    @property
    def placeholder(self) -> bool:
        return self.khz is None

    @cached_property
    def bbox(self) -> tuple[float, float, float, float]:
        lats, lons = [p[0] for p in self.polygon], [p[1] for p in self.polygon]
        return min(lats), max(lats), min(lons), max(lons)

    def contains(self, lat: float, lon: float, alt_ft: float) -> bool:
        south, north, west, east = self.bbox  # a cheap test first: with Little Navmap there are thousands
        return (self.lower_ft <= alt_ft < self.upper_ft and south <= lat <= north and west <= lon <= east
                and point_in_polygon(lat, lon, self.polygon))


class CenterSectors:
    def __init__(self, sectors: list[CenterSector] | tuple[CenterSector, ...] = (), source: str = "centers.json"):
        self.sectors = tuple(sectors)
        self.source = source

    def __bool__(self) -> bool:
        return bool(self.sectors)

    def at(self, lat: float, lon: float, alt_ft: float) -> CenterSector | None:
        """The sector the aircraft is in. Overlaps: the first one in the file wins, so order matters."""
        return next((s for s in self.sectors if s.contains(lat, lon, alt_ft)), None)

    def on_frequency(self, khz: int) -> list[CenterSector]:
        return [s for s in self.sectors if s.khz == khz]

    @property
    def placeholders(self) -> list[CenterSector]:
        return [s for s in self.sectors if s.placeholder]


def with_imported(own: CenterSectors, imported: list[CenterSector], source: str = "Little Navmap") -> CenterSectors:
    """centers.json sectors with a real frequency come first, so a correction wins; then the imported ones.
    PLACEHOLDER sectors are dropped: the imported data has the real frequencies."""
    if not imported:
        return own
    corrections = [s for s in own.sectors if not s.placeholder]
    return CenterSectors(corrections + list(imported),
                         source=source + (f" + {own.source}" if corrections else ""))


def load_centers(path: Path) -> CenterSectors:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise CentersError(f"{path}: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("sectors"), list):
        raise CentersError(f'{path}: expected {{"sectors": [...]}}')
    return CenterSectors([parse_sector(s, f"{path.name} sector {i + 1}") for i, s in enumerate(data["sectors"])],
                         source=path.name)


def parse_sector(raw: dict, where: str) -> CenterSector:
    if not isinstance(raw, dict):
        raise CentersError(f"{where}: not an object")
    missing, unknown = SECTOR_KEYS - set(raw), set(raw) - SECTOR_KEYS - OPTIONAL_KEYS
    if missing or unknown:
        raise CentersError(f"{where}: " + "; ".join(filter(None, [
            missing and f"missing {', '.join(sorted(missing))}", unknown and f"unknown {', '.join(sorted(unknown))}"])))
    name, fir = str(raw["name"]).strip(), str(raw["fir"]).strip().upper()
    if not name or not fir:
        raise CentersError(f"{where}: name and fir must not be empty")
    where = f"{where} ({name})"

    freq = raw["frequency"]
    if freq == PLACEHOLDER:
        khz = None
    else:
        try:
            khz = parse_mhz(str(freq))
        except ValueError as e:
            raise CentersError(f'{where}: {e}; use "{PLACEHOLDER}" if you don\'t know it yet') from None

    lower, upper = raw["lower_ft"], raw["upper_ft"]
    if not all(isinstance(v, int) for v in (lower, upper)) or not lower < upper:
        raise CentersError(f"{where}: lower_ft and upper_ft must be whole feet with lower_ft < upper_ft")

    polygon = raw["polygon"]
    try:
        points = tuple((float(lat), float(lon)) for lat, lon in polygon)
    except (TypeError, ValueError):
        raise CentersError(f"{where}: polygon must be a list of [lat, lon] pairs") from None
    if len(points) < 3:
        raise CentersError(f"{where}: polygon needs at least 3 points")
    if not all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in points):
        raise CentersError(f"{where}: polygon point out of range (is it [lat, lon]?)")
    return CenterSector(name, fir, khz, lower, upper, points)

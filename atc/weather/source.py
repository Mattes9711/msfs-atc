import json
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from atc.airport.geo import distance_nm

# DATA SOURCE: aviationweather.gov (US National Weather Service), public data, no key needed.
URL = "https://aviationweather.gov/api/data/metar?ids={}"
# Every METAR in a box (south, west, north, east), with each station's position
NEARBY_URL = "https://aviationweather.gov/api/data/metar?bbox={:.3f},{:.3f},{:.3f},{:.3f}&format=json"
NEARBY_NM = 25  # a small field without a METAR borrows the nearest one this close (Milestone 9, A4)


@dataclass(frozen=True)
class Report:
    """A METAR with where it was observed."""
    station: str
    lat: float
    lon: float
    raw: str


class WeatherSource(Protocol):
    def metar(self, icao: str) -> str | None:
        """Latest raw METAR, or None when nothing is available."""

    def nearby(self, lat: float, lon: float, radius_nm: float) -> list[Report]:
        """The METARs around a point, perhaps a few beyond radius_nm (a box); empty when none can be had."""


class StaticWeather:
    """Fixed METARs, for tests and scripted scenarios; `positions` (icao -> (lat, lon)) for nearby()."""

    def __init__(self, metars: dict[str, str], positions: dict[str, tuple[float, float]] | None = None):
        self.metars = metars
        self.positions = positions or {}

    def metar(self, icao: str) -> str | None:
        return self.metars.get(icao.upper())

    def nearby(self, lat: float, lon: float, radius_nm: float) -> list[Report]:
        return [Report(icao, *self.positions[icao], raw) for icao, raw in self.metars.items() if icao in self.positions]


def nearest_report(weather: WeatherSource, lat: float, lon: float, not_from: str,
                   radius_nm: float = NEARBY_NM) -> tuple[Report, float] | None:
    """The nearest METAR within radius_nm of another station, and how far it is."""
    found = [(r, distance_nm(lat, lon, r.lat, r.lon)) for r in weather.nearby(lat, lon, radius_nm)
             if r.station.upper() != not_from.upper()]
    return min(((r, d) for r, d in found if d <= radius_nm), key=lambda f: f[1], default=None)


def _http_get(url: str, timeout: float) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class LiveWeather:
    """aviationweather.gov with a per-airport file cache, so the last METAR survives going offline."""

    def __init__(self, cache_dir: Path, timeout: float = 5, fetch: Callable[[str, float], str] = _http_get):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.fetch = fetch

    def metar(self, icao: str) -> str | None:
        icao = icao.upper()
        cache = self.cache_dir / f"{icao}.txt"
        try:
            lines = self.fetch(URL.format(icao), self.timeout).strip().splitlines()
        except OSError:  # includes URLError, HTTPError and timeouts
            lines = []
        if lines:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(lines[0] + "\n", encoding="utf-8")
            return lines[0]
        if cache.exists():
            return cache.read_text(encoding="utf-8").strip()
        return None

    def nearby(self, lat: float, lon: float, radius_nm: float) -> list[Report]:
        dlat, dlon = radius_nm / 60, radius_nm / (60 * max(0.1, math.cos(math.radians(lat))))
        cache = self.cache_dir / f"nearby_{lat:.1f}_{lon:.1f}.json"
        try:
            text = self.fetch(NEARBY_URL.format(lat - dlat, lon - dlon, lat + dlat, lon + dlon), self.timeout)
            reports = [Report(r["icaoId"], float(r["lat"]), float(r["lon"]), r["rawOb"]) for r in json.loads(text)
                       if r.get("icaoId") and r.get("rawOb") and r.get("lat") is not None]
        except (OSError, ValueError, KeyError, TypeError):  # offline, or not the JSON we know
            reports = None
        if reports:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([r.__dict__ for r in reports]), encoding="utf-8")
            return reports
        if reports is None and cache.exists():
            return [Report(**r) for r in json.loads(cache.read_text(encoding="utf-8"))]
        return []

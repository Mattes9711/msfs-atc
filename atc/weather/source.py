import urllib.request
from pathlib import Path
from typing import Callable, Protocol

# DATA SOURCE: aviationweather.gov (US National Weather Service), public data, no key needed.
URL = "https://aviationweather.gov/api/data/metar?ids={}"


class WeatherSource(Protocol):
    def metar(self, icao: str) -> str | None:
        """Latest raw METAR, or None when nothing is available."""


class StaticWeather:
    """Fixed METARs, for tests and scripted scenarios."""

    def __init__(self, metars: dict[str, str]):
        self.metars = metars

    def metar(self, icao: str) -> str | None:
        return self.metars.get(icao.upper())


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

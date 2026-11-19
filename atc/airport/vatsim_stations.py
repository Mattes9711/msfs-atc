"""The real roles of the German airports' frequencies, from data/stations_vatsim.json (atc/airspace/vatsim.py).

The sim's data types most of them just Ground or Tower: at EDDH it has three Grounds (121.705, 121.805, 121.980) and
two Towers (121.280, 126.855). The VATGER datahub says 121.805 is Delivery, 121.705 and 121.980 are the Aprons East
and West and 121.280 is the VFR Tower. A sim frequency gets the role of the datahub position with the same airport
and frequency; frequencies the sim does not have are never added. Elsewhere nothing changes.
"""
import dataclasses
import json
from pathlib import Path

from atc.airport.model import Airport, AirportData, AirportSummary, Frequency

ROLES = ("C", "G", "APRON", "T")


def load(path: Path) -> dict[str, dict[int, dict]]:
    """Airport -> kHz -> its entry; {} without the file (or a broken one: the sim's own roles still work)."""
    try:
        airports = json.loads(path.read_text(encoding="utf-8"))["airports"]
        return {ident: {int(e["khz"]): e for e in entries if e.get("role") in ROLES}
                for ident, entries in airports.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def apply(frequencies: tuple[Frequency, ...], entries: dict[int, dict] | None) -> tuple[Frequency, ...]:
    """The frequencies with the datahub's role where airport and frequency match. ATIS and the like stay as they are:
    only controller frequencies (Delivery, Ground, Tower) are given a role."""
    if not entries:
        return frequencies
    return tuple(dataclasses.replace(f, real_role=e["role"], word=e.get("word") or None,
                                     qualifier=e.get("qualifier") or "")
                 if f.type in ("C", "G", "T") and (e := entries.get(f.khz)) else f
                 for f in frequencies)


class WithStations:
    """An airport source whose airports have the datahub's roles. Everything else is the source's own."""

    def __init__(self, source: AirportData, stations: dict[str, dict[int, dict]]):
        self.source, self.stations = source, stations

    def __getattr__(self, name):
        return getattr(self.source, name)

    def get(self, ident: str) -> Airport | None:
        airport = self.source.get(ident)
        if airport is None or airport.ident not in self.stations:
            return airport
        return dataclasses.replace(airport, frequencies=apply(airport.frequencies, self.stations[airport.ident]))

    def in_area(self, south: float, west: float, north: float, east: float, limit: int) -> list[AirportSummary]:
        return [dataclasses.replace(a, frequencies=apply(a.frequencies, self.stations.get(a.ident)))
                for a in self.source.in_area(south, west, north, east, limit)]

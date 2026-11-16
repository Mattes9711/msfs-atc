"""En-route Center sectors from Little Navmap's MSFS database (step F3).

DATA SOURCE / LICENCE: the `boundary` table of the user's Little Navmap database, which Little Navmap builds on the
user's machine from MSFS's own airspace data. It is read in place and never shipped, like the airport data in
atc/airport/littlenavmap.py (see BUILD.md). Not Navigraph data.

What the table has for Centers (type 'C', com_type 'CTR'), e.g. EDWW0814, BREMEN, 119825:
- `name` is the FIR/ACC code plus a sector number, `com_name` the station, `com_frequency` the frequency in kHz
  (unlike the `com` table of airports, which is in Hz);
- `geometry` is a blob: a big-endian int32 point count, then that many big-endian float32 (lon, lat) pairs;
- every Center row is ground to unlimited, so the sectors have no altitude bands. Where they overlap, the
  smallest one wins (CenterSectors.at() takes the first match, so they are sorted by size).
"""
import math
import re
import sqlite3
import struct
from pathlib import Path

from atc.airspace.centers import CenterSector

UNLIMITED_FT = 99999
SUFFIXES = ("RADAR", "CONTROL", "CENTER", "CENTRE")
# How the ACCs call themselves on the radio. Germany (DFS) and the Netherlands say "Radar"; elsewhere the ICAO word
# for an area control centre, "Control", is used. Wrong names can be corrected in centers.json.
RADAR_FIRS = ("ED", "EH")


def load_littlenavmap_centers(db_path: Path) -> list[CenterSector]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("select name, com_name, com_frequency, geometry from boundary "
                           "where type = 'C' and com_frequency is not null and geometry is not null").fetchall()
    finally:
        con.close()
    sectors = []
    for name, com_name, khz, geometry in rows:
        polygon = decode_polygon(geometry)
        if len(polygon) < 3 or not com_name:
            continue
        fir = fir_code(name, com_name)
        sectors.append(CenterSector(station_name(com_name, fir), fir, int(khz), 0, UNLIMITED_FT, polygon))
    return sorted(sectors, key=area)


def decode_polygon(blob: bytes) -> tuple[tuple[float, float], ...]:
    """→ ((lat, lon), ...), the order CenterSector uses."""
    (count,) = struct.unpack_from(">i", blob)
    values = struct.unpack_from(f">{2 * count}f", blob, 4)
    return tuple((values[i + 1], values[i]) for i in range(0, len(values), 2))


def fir_code(name: str, com_name: str) -> str:
    """'EDWW0814' → 'EDWW'."""
    m = re.match(r"([A-Z]{4})\d*$", name or "")
    return m[1] if m else com_name.split()[0][:4].upper()


def station_name(com_name: str, fir: str) -> str:
    """'BREMEN' → 'Bremen Radar', 'LANGEN RADAR' → 'Langen Radar', 'MALMO CONTROL' → 'Malmo Control',
    'FRANKFURT 1' → 'Frankfurt Radar' (the sector number isn't said on the radio)."""
    words = [w for w in com_name.split() if not w.isdigit()]
    if not words or words[-1].upper() not in SUFFIXES:
        words.append("RADAR" if fir.startswith(RADAR_FIRS) else "CONTROL")
    return " ".join(w.capitalize() for w in words)


def area(sector: CenterSector) -> float:
    """Rough size in square degrees of latitude (shoelace, longitudes shrunk by cos(latitude)): only for sorting."""
    points = sector.polygon
    scale = math.cos(math.radians(sum(lat for lat, _ in points) / len(points)))
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:] + points[:1]):
        total += lon1 * scale * lat2 - lon2 * scale * lat1
    return abs(total) / 2

"""Builds data/centers_vatsim.json: real German Center sectors with real frequencies, from VATSIM community data.
Also data/stations_vatsim.json: the roles of the German airports' frequencies (which one is Delivery, Apron, Tower).

Both sources are CC BY-SA 4.0, which may be shipped with a GPL-3.0 app (with attribution, and the derived file under
CC BY-SA 4.0 too; see the file's "licence"):
    VATSpy Data Project  https://github.com/vatsimnetwork/vatspy-data-project  VATSpy.dat + Boundaries.geojson:
                         the sector outlines (no altitude bands)
    VATGER datahub       https://github.com/VATGER-Nav/datahub  data/<fir>/ctr.json: the frequency of each
                         Center position (EDWW_ALR_CTR 126.325 "Bremen Radar (Aller)")
A VATSpy sector "EDWW-ALR" (callsign prefix EDWW_ALR) gets the frequency of the datahub position EDWW_ALR_CTR. If the
datahub also has its "... High" position (EDGG_GIH_CTR "Langen Radar (Giessen High)"), that one has the sector from
HIGH_FT up. Sectors without a datahub frequency are left out: frequencies are never made up. Only Germany so far.

The stations come from the datahub's del.json, gnd.json and twr.json (EDDH_E_GND 121.705 "Hamburg Apron (East)"). The
sim's data types most of them just Ground or Tower: at EDDH 121.805 is Delivery, 121.705 and 121.980 are the two
Aprons and 121.280 is the VFR Tower. atc/airport/vatsim_stations.py gives a sim frequency the role of the datahub
position with the same airport and frequency; it never adds one. De-icing positions are left out.

Not run by the app. Rebuild the files (needs the internet):  python -m atc.airspace.vatsim
or from files downloaded before:                              python -m atc.airspace.vatsim <folder>
only one of them:                                             python -m atc.airspace.vatsim --only stations [<folder>]
"""
import re
import json
import sys
import urllib.request
from pathlib import Path

from atc.config import ROOT

VATSPY = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/"
DATAHUB = "https://raw.githubusercontent.com/VATGER-Nav/datahub/production/data/"
FIRS = {"EDWW": "Bremen Radar", "EDGG": "Langen Radar", "EDMM": "Munich Radar"}  # how they are called on the radio
HIGH_FT = 24500  # Germany's upper airspace: FL245 and above
TOP_FT = 66000
OUTPUT = ROOT / "data" / "centers_vatsim.json"
STATIONS_OUTPUT = ROOT / "data" / "stations_vatsim.json"
LICENCE = ("CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). Made from the VATSpy Data Project "
           "(https://github.com/vatsimnetwork/vatspy-data-project, CC BY-SA 4.0: sector outlines) and the VATGER "
           "datahub (https://github.com/VATGER-Nav/datahub, CC BY-SA 4.0: frequencies), by "
           "atc/airspace/vatsim.py: joined, High positions as upper sectors, rounded. For the simulator only, "
           "not for real navigation.")
STATIONS_LICENCE = ("CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). Made from the VATGER datahub "
                    "(https://github.com/VATGER-Nav/datahub, CC BY-SA 4.0: del.json, gnd.json, twr.json) by "
                    "atc/airspace/vatsim.py: the role, the station's word and its part of the field. For the simulator "
                    "only, not for real navigation.")
STATION_FILES = ("del", "gnd", "twr")
WORDS = ("Delivery", "Ground", "Apron", "Tower")  # how the station is called, from the description
# The part of the field in brackets, shortened for the labels: "Hamburg Apron (East)" -> "E"
PARTS = {"EAST": "E", "WEST": "W", "NORTH": "N", "NORD": "N", "SOUTH": "S", "SUED": "S", "SÜD": "S", "CENTER": "C",
         "CENTRE": "C"}
DEICING = re.compile(r"de-?icing", re.IGNORECASE)


def vatspy_firs(dat: str) -> dict[str, str]:
    """[FIRs] of VATSpy.dat: boundary id -> callsign prefix ("EDWW-ALR" -> "EDWW_ALR")."""
    firs, section = {}, None
    for line in dat.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == "[FIRs]" and line and not line.startswith(";"):
            parts = line.split("|")
            if len(parts) >= 4 and parts[3]:
                firs.setdefault(parts[3], parts[2] or parts[0])
    return firs


def outlines(geojson: dict) -> dict[str, list[list[tuple[float, float]]]]:
    """Boundary id -> its outer rings as (lat, lon), rounded to about 10 m."""
    found = {}
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        found[feature["properties"]["id"]] = [[(round(lat, 4), round(lon, 4)) for lon, lat in polygon[0]]
                                              for polygon in polygons]
    return found


def area(ring: list[tuple[float, float]]) -> float:
    """In square degrees: only to order the sectors, small ones first."""
    return abs(sum(a[1] * b[0] - b[1] * a[0] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2


def build(dat: str, geojson: dict, positions: list[dict]) -> list[dict]:
    """The sectors in centers.json form, the smallest first so a sector wins over the bandbox around it."""
    by_logon = {p["logon"]: p for p in positions}
    by_description = {p.get("description", ""): p for p in positions}
    rings = outlines(geojson)
    sectors = []
    for boundary, prefix in sorted(vatspy_firs(dat).items()):
        fir = prefix.split("_")[0]
        position = by_logon.get(f"{prefix}_CTR")
        if fir not in FIRS or position is None or boundary not in rings:
            continue
        description = position.get("description", "")
        high = by_description.get(description[:-1] + " High)") if description.endswith(")") else None
        bands = [(position, 0, HIGH_FT if high else TOP_FT)] + ([(high, HIGH_FT, TOP_FT)] if high else [])
        for ring in rings[boundary]:
            for band, lower, upper in bands:
                sectors.append({"name": FIRS[fir], "fir": fir, "frequency": band["frequency"], "lower_ft": lower,
                                "upper_ft": upper, "polygon": [list(p) for p in ring], "note": band["logon"]})
    return sorted(sectors, key=lambda s: area([tuple(p) for p in s["polygon"]]))


def station(kind: str, position: dict) -> tuple[str, dict] | None:
    """(airport, entry) of a datahub position, or None for one that is no station of its own (de-icing) or that has
    no description to tell what it is called."""
    logon, description = position.get("logon", ""), (position.get("description") or "").strip()
    parts = logon.split("_")
    if len(parts) < 2 or not description or DEICING.search(description):
        return None
    words = [w for w in re.findall(r"[A-Za-z]+", description.split("(")[0]) if w in WORDS]
    if not words:
        return None
    word = words[-1]
    role = "C" if kind == "del" else "T" if kind == "twr" else "APRON" if word == "Apron" else "G"
    inside = re.search(r"\(([^)]*)\)", description)
    part = inside.group(1).upper().removeprefix("APRON ").strip() if inside else ""
    qualifier = "VFR" if "VFR" in parts[1:-1] or "VFR" in description.upper() else PARTS.get(part, part)
    khz = round(float(position["frequency"]) * 1000)
    return parts[0], {"khz": khz, "role": role, "word": word, "qualifier": qualifier, "logon": logon}


def stations(positions: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Airport -> its stations, by frequency. positions: "del"/"gnd"/"twr" -> the datahub positions of that file."""
    found: dict[str, list[dict]] = {}
    for kind in STATION_FILES:
        for position in positions.get(kind, []):
            if (got := station(kind, position)) is not None:
                found.setdefault(got[0], []).append(got[1])
    return {ident: sorted(entries, key=lambda e: e["khz"]) for ident, entries in sorted(found.items())}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as answer:
        return answer.read()


def main(argv: list[str]) -> None:
    only = None
    if argv[:1] == ["--only"]:
        only, argv = argv[1], argv[2:]
    folder = Path(argv[0]) if argv else None

    def read(name: str, url: str) -> bytes:
        return (folder / name).read_bytes() if folder else fetch(url)

    def datahub(kind: str) -> list[dict]:
        return [p for fir in FIRS
                for p in json.loads(read(f"{fir.lower()}-{kind}.json", f"{DATAHUB}{fir.lower()}/{kind}.json"))]

    if only in (None, "centers"):
        dat = read("VATSpy.dat", VATSPY + "VATSpy.dat").decode("utf-8", errors="replace")
        geojson = json.loads(read("Boundaries.geojson", VATSPY + "Boundaries.geojson"))
        sectors = build(dat, geojson, datahub("ctr"))
        OUTPUT.write_text(json.dumps({"licence": LICENCE, "sectors": sectors}, ensure_ascii=False,
                                     separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"{len(sectors)} sectors -> {OUTPUT}")
    if only in (None, "stations"):
        airports = stations({kind: datahub(kind) for kind in STATION_FILES})
        STATIONS_OUTPUT.write_text(json.dumps({"licence": STATIONS_LICENCE, "airports": airports},
                                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{sum(map(len, airports.values()))} stations at {len(airports)} airports -> {STATIONS_OUTPUT}")


if __name__ == "__main__":
    main(sys.argv[1:])

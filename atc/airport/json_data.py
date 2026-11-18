import json

from atc.airport.geo import distance_nm, segment_distance_nm
from pathlib import Path

from atc.airport.model import Airport, ControlZone, Frequency, Ils, Parking, Runway, RunwayEnd, TaxiPath, VfrPoint


class JsonAirportData:
    """Airports stored as one JSON file per ICAO code, e.g. data/airports/EDDH.json."""

    name = "JSON"

    def __init__(self, directory: Path):
        self.directory = directory

    def get(self, ident: str) -> Airport | None:
        path = self.directory / f"{ident.upper()}.json"
        if not path.exists():
            return None
        return airport_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def procedures(self, ident: str) -> None:
        """No STARs or approaches in the exported files: the arrival falls back to plain vectors."""
        return None

    def nearest(self, lat: float, lon: float, max_nm: float) -> str | None:
        found = [(distance_nm(lat, lon, a.lat, a.lon), a.ident)
                 for a in map(self.get, (p.stem for p in sorted(self.directory.glob("*.json")))) if a and a.runways]
        found = [f for f in found if f[0] <= max_nm]
        return min(found)[1] if found else None

    def towered_near(self, a: tuple[float, float], b: tuple[float, float], max_nm: float) -> list[str]:
        found = map(self.get, (p.stem for p in sorted(self.directory.glob("*.json"))))
        return [x.ident for x in found if x and any(f.type == "T" for f in x.frequencies)
                and segment_distance_nm(x.lat, x.lon, a, b) <= max_nm]

    def save(self, airport: Airport) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{airport.ident}.json"
        path.write_text(to_json(airport), encoding="utf-8")
        return path


def to_json(airport: Airport) -> str:
    # Hundreds of taxi paths: one compact line each keeps the file readable and diffs small
    data = airport_to_dict(airport)
    paths = data.pop("taxi_paths")
    head = json.dumps(data, indent=2)[:-2]  # drop the closing "\n}"
    lines = ",\n".join(f"    {json.dumps(p)}" for p in paths)
    return f'{head},\n  "taxi_paths": [\n{lines}\n  ]\n}}\n'


def airport_from_dict(d: dict) -> Airport:
    return Airport(
        ident=d["ident"],
        name=d["name"],
        lat=d["lat"],
        lon=d["lon"],
        elevation_ft=d["elevation_ft"],
        mag_var=d["mag_var"],
        frequencies=tuple(Frequency(f["type"], f["name"], f["khz"]) for f in d["frequencies"]),
        runways=tuple(
            Runway(r["length_ft"], r["width_ft"], (_end(r["ends"][0]), _end(r["ends"][1]))) for r in d["runways"]
        ),
        parking=tuple(
            Parking(p["name"], p["type"], p["lat"], p["lon"], p["heading"], tuple(p["airline_codes"]))
            for p in d.get("parking", [])
        ),
        # [start_lat, start_lon, end_lat, end_lon, name, type, start_type, end_type]
        taxi_paths=tuple(TaxiPath(*t) for t in d.get("taxi_paths", [])),
        vfr_points=tuple(VfrPoint(*p) for p in d.get("vfr_points", [])),  # [ident, lat, lon]
        control_zone=_zone(d.get("control_zone")),
    )


def _zone(z: dict | None) -> ControlZone | None:
    return ControlZone(z["name"], z["ceiling_ft"], tuple(tuple(p) for p in z["polygon"])) if z else None


def _end(e: dict) -> RunwayEnd:
    ils = e.get("ils")
    return RunwayEnd(
        name=e["name"],
        heading_true=e["heading_true"],
        lat=e["lat"],
        lon=e["lon"],
        offset_threshold_ft=e["offset_threshold_ft"],
        ils=Ils(ils["ident"], ils["khz"], ils["course_true"]) if ils else None,
        circuit=e.get("circuit", "L"),
    )


def airport_to_dict(a: Airport) -> dict:
    return {
        "ident": a.ident, "name": a.name, "lat": round(a.lat, 7), "lon": round(a.lon, 7),
        "elevation_ft": a.elevation_ft, "mag_var": round(a.mag_var, 2),
        "frequencies": [{"type": f.type, "name": f.name, "khz": f.khz} for f in a.frequencies],
        "runways": [
            {"length_ft": r.length_ft, "width_ft": r.width_ft, "ends": [_end_to_dict(e) for e in r.ends]}
            for r in a.runways
        ],
        "parking": [
            {"name": p.name, "type": p.type, "lat": round(p.lat, 7), "lon": round(p.lon, 7),
             "heading": round(p.heading, 1), "airline_codes": list(p.airline_codes)}
            for p in a.parking
        ],
        "vfr_points": [[p.ident, round(p.lat, 7), round(p.lon, 7)] for p in a.vfr_points],
        "control_zone": {"name": a.control_zone.name, "ceiling_ft": a.control_zone.ceiling_ft,
                         "polygon": [[round(lat, 6), round(lon, 6)] for lat, lon in a.control_zone.polygon]}
        if a.control_zone else None,
        "taxi_paths": [
            [round(t.start_lat, 7), round(t.start_lon, 7), round(t.end_lat, 7), round(t.end_lon, 7),
             t.name, t.type, t.start_type, t.end_type]
            for t in a.taxi_paths
        ],
    }


def _end_to_dict(e: RunwayEnd) -> dict:
    return {
        "name": e.name, "heading_true": round(e.heading_true, 2), "lat": round(e.lat, 7), "lon": round(e.lon, 7),
        "offset_threshold_ft": e.offset_threshold_ft,
        "ils": {"ident": e.ils.ident, "khz": e.ils.khz, "course_true": round(e.ils.course_true, 2)} if e.ils else None,
        "circuit": e.circuit,
    }

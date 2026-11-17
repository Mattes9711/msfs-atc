"""Airport data from Little Navmap's MSFS database.

LICENCE: this database is built on the user's machine from the scenery they installed, payware add-ons included
(e.g. EDDH here comes from simwings). The app only reads it locally. Never ship the database or anything exported
from it, and don't use Little Navmap's Navigraph database (little_navmap_navigraph.sqlite): that data is licensed
per user. See BUILD.md.
"""
import math
import sqlite3
from pathlib import Path

from atc.airport.geo import M_PER_DEG_LAT, distance_nm, point_in_polygon
from atc.airport.model import Airport, ControlZone, Frequency, Ils, Parking, Runway, RunwayEnd, TaxiPath, VfrPoint
from atc.airport.procedures import Procedures, load_procedures
from atc.airspace.littlenavmap import decode_polygon


class LittleNavmapAirportData:
    """Reads Little Navmap's MSFS scenery database (read-only). Matches the pilot's installed scenery, add-ons included."""

    name = "Little Navmap"

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get(self, ident: str) -> Airport | None:
        con = self._connect()
        try:
            return _load(con, ident.upper())
        finally:
            con.close()

    def procedures(self, ident: str) -> Procedures | None:
        """The airport's STARs and approaches (Milestone 10 A); None for an airport the database doesn't know."""
        con = self._connect()
        try:
            if con.execute("select 1 from airport where ident = ?", (ident.upper(),)).fetchone() is None:
                return None
            return load_procedures(con, ident)
        except sqlite3.OperationalError:  # an old database without the procedure tables
            return None
        finally:
            con.close()

    def nearest(self, lat: float, lon: float, max_nm: float) -> str | None:
        dlat = max_nm * 1852 / M_PER_DEG_LAT
        dlon = dlat / max(0.01, math.cos(math.radians(lat)))
        con = self._connect()
        try:
            rows = con.execute(
                "select ident, laty, lonx from airport where laty between ? and ? and lonx between ? and ? "
                "and exists (select 1 from runway r where r.airport_id = airport.airport_id)",
                (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
        finally:
            con.close()
        found = [(distance_nm(lat, lon, r["laty"], r["lonx"]), r["ident"]) for r in rows]
        found = [f for f in found if f[0] <= max_nm]
        return min(found)[1] if found else None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con


def _load(con: sqlite3.Connection, ident: str) -> Airport | None:
    a = con.execute("select * from airport where ident = ?", (ident,)).fetchone()
    if a is None:
        return None
    airport_id, name = a["airport_id"], a["name"].title()

    frequencies = tuple(
        # com.frequency is in Hz, unlike airport.*_frequency and ils.frequency which are kHz
        Frequency(c["type"], _station_name(c["name"], ident, name), round(c["frequency"] / 1000))
        for c in con.execute("select type, name, frequency from com where airport_id = ? order by type, frequency",
                             (airport_id,))
    )
    # runway_end.ils_ident is empty in the MSFS database, so join on airport + runway name instead
    ils = {
        i["loc_runway_name"]: Ils(i["ident"], i["frequency"], i["loc_heading"])
        for i in con.execute("select ident, frequency, loc_runway_name, loc_heading from ils where loc_airport_ident = ?",
                             (ident,))
    }

    def end(end_id: int) -> RunwayEnd:
        e = con.execute("select * from runway_end where runway_end_id = ?", (end_id,)).fetchone()
        return RunwayEnd(e["name"], e["heading"], e["laty"], e["lonx"], e["offset_threshold"], ils.get(e["name"]),
                         "R" if "is_pattern" in e.keys() and e["is_pattern"] == "R" else "L")

    runways = tuple(
        Runway(r["length"], r["width"], (end(r["primary_end_id"]), end(r["secondary_end_id"])))
        for r in con.execute("select * from runway where airport_id = ? order by runway_id", (airport_id,))
    )
    parking = tuple(
        Parking(
            name=" ".join(part for part in (_parking_name(p["name"]), f"{p['number'] or ''}{p['suffix'] or ''}")
                          if part),
            type=p["type"], lat=p["laty"], lon=p["lonx"], heading=p["heading"],
            airline_codes=tuple(c for c in (p["airline_codes"] or "").split(",") if c),
        )
        for p in con.execute("select * from parking where airport_id = ? order by name, number, suffix", (airport_id,))
    )
    taxi_paths = tuple(
        TaxiPath(t["start_laty"], t["start_lonx"], t["end_laty"], t["end_lonx"], t["name"] or "", t["type"],
                 t["start_type"] or "N", t["end_type"] or "N")
        for t in con.execute("select * from taxi_path where airport_id = ? order by taxi_path_id", (airport_id,))
    )
    vfr_points = tuple(
        VfrPoint(w["ident"], round(w["laty"], 7), round(w["lonx"], 7))
        for w in con.execute("select ident, laty, lonx from waypoint where airport_ident = ? and type = 'VFR' "
                             "order by ident", (ident,))
    )
    return Airport(
        ident=ident, name=name, lat=a["laty"], lon=a["lonx"], elevation_ft=a["altitude"], mag_var=a["mag_var"],
        frequencies=frequencies, runways=runways, parking=parking, taxi_paths=taxi_paths, vfr_points=vfr_points,
        control_zone=_control_zone(con, a["laty"], a["lonx"]),
    )


def _control_zone(con: sqlite3.Connection, lat: float, lon: float) -> ControlZone | None:
    """The smallest control zone (boundary type CD) from the ground up that contains the field. Zones with a floor
    above the ground (e.g. "HAMBURG-FINKENWERDER (D)", 2500-3500 ft) belong to no field's circuit."""
    rows = con.execute(
        "select name, max_altitude, geometry, (max_laty - min_laty) * (max_lonx - min_lonx) as area from boundary "
        "where type = 'CD' and min_altitude = 0 and ? between min_laty and max_laty and ? between min_lonx and max_lonx "
        "order by area", (lat, lon)).fetchall()
    for r in rows:
        polygon = tuple((round(p_lat, 6), round(p_lon, 6)) for p_lat, p_lon in decode_polygon(r["geometry"]))
        if polygon and point_in_polygon(lat, lon, polygon):
            return ControlZone((r["name"] or "").title(), r["max_altitude"], polygon)
    return None


def _parking_name(name: str | None) -> str:
    """Little Navmap's short parking names ("G" gate, "P" parking); "NONE" is a spot without one: just its number."""
    return "" if not name or name.upper() == "NONE" else name


def _station_name(com_name: str | None, ident: str, airport_name: str) -> str:
    # ATIS entries are often named after the ICAO code ("EDDH"); a station needs a spoken name
    if not com_name or com_name.upper() == ident:
        return airport_name
    return com_name.title()

import sqlite3
import struct

import pytest

from atc.airport.json_data import airport_from_dict, airport_to_dict
from atc.airport import lnm_files
from atc.airport.littlenavmap import LittleNavmapAirportData
from atc.config import Config

# The subset of Little Navmap's MSFS schema that the backend reads (column names as in the real database)
SCHEMA = """
create table airport (airport_id integer, ident text, name text, laty real, lonx real, altitude integer, mag_var real);
create table com (airport_id integer, type text, frequency integer, name text);
create table runway (runway_id integer, airport_id integer, primary_end_id integer, secondary_end_id integer,
                     length real, width real);
create table runway_end (runway_end_id integer, name text, heading real, laty real, lonx real, offset_threshold real);
create table ils (ident text, frequency integer, loc_airport_ident text, loc_runway_name text, loc_heading real);
create table parking (airport_id integer, type text, name text, number integer, suffix text, heading real,
                      airline_codes text, laty real, lonx real);
create table taxi_path (taxi_path_id integer, airport_id integer, type text, name text, start_type text,
                        end_type text, start_laty real, start_lonx real, end_laty real, end_lonx real);
create table waypoint (ident text, airport_ident text, type text, laty real, lonx real);
create table boundary (type text, name text, min_altitude integer, max_altitude integer, min_laty real,
                       max_laty real, min_lonx real, max_lonx real, geometry blob);
"""


def polygon(points):
    """Little Navmap's geometry blob: the count, then lon, lat as big-endian floats."""
    return struct.pack(f">i{2 * len(points)}f", len(points), *[v for lat, lon in points for v in (lon, lat)])


def box(lat_min, lat_max, lon_min, lon_max, kind, name, floor, ceiling):
    return (kind, name, floor, ceiling, lat_min, lat_max, lon_min, lon_max, polygon(
        [(lat_min, lon_min), (lat_max, lon_min), (lat_max, lon_max), (lat_min, lon_max)]))


@pytest.fixture
def lnm(tmp_path):
    path = tmp_path / "little_navmap_msfs.sqlite"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("insert into airport values (1, 'EXMP', 'EXAMPLE CITY', 50.0, 8.0, 300, 2.5)")
    con.executemany("insert into com values (1, ?, ?, ?)", [
        ("T", 118505000, "EXAMPLE CITY"),  # Hz, like the real database
        ("ATIS", 127000000, "EXMP"),  # ATIS named after the ICAO code
        ("G", 121900000, None),
    ])
    con.execute("insert into runway values (10, 1, 100, 101, 9000, 150)")
    con.executemany("insert into runway_end values (?, ?, ?, ?, ?, ?)", [
        (100, "09", 92.5, 50.0, 7.98, 0), (101, "27", 272.5, 50.0, 8.02, 300),
    ])
    con.execute("insert into ils values ('IEXW', 110300, 'EXMP', '27', 272.4)")
    con.executemany("insert into parking values (1, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("RGAM", "P", 3, None, 90.0, None, 50.001, 8.001),
        ("GM", "G", 12, "A", 180.0, "DLH,EWG", 50.002, 8.002),
    ])
    con.execute("insert into taxi_path values (1, 1, 'PT', '', 'N', 'HSND', 50.001, 8.0, 50.0005, 8.0)")
    con.executemany("insert into waypoint values (?, ?, ?, ?, ?)", [
        ("NOVMR", "EXMP", "VFR", 50.125, 8.0), ("S1", "EXMP", "VFR", 49.875, 8.0),
        ("ABCDE", "EXMP", "WN", 50.5, 8.0),  # an IFR waypoint: not a reporting point
    ])
    con.executemany("insert into boundary values (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        box(49.75, 50.25, 7.75, 8.25, "CD", "EXAMPLE CITY", 0, 2500),
        box(49.5, 50.5, 7.5, 8.5, "CD", "BIGGER ZONE", 0, 3500),  # contains it too, but larger
        box(49.9, 50.1, 7.9, 8.1, "CD", "UP HIGH", 2500, 3500),  # not from the ground up
        box(49.9, 50.1, 7.9, 8.1, "C", "CLASS C", 0, 10000),  # no control zone
    ])
    con.commit()
    con.close()
    return LittleNavmapAirportData(path)


def test_nearest_airport_needs_a_runway_and_the_distance(lnm):
    assert lnm.nearest(50.01, 8.01, 5) == "EXMP"
    assert lnm.nearest(50.5, 8.0, 5) is None  # 30 nm away
    con = sqlite3.connect(lnm.db_path)
    con.execute("insert into airport values (2, 'EXHP', 'HELIPORT', 50.011, 8.011, 300, 2.5)")  # no runway
    con.commit()
    con.close()
    assert lnm.nearest(50.011, 8.011, 5) == "EXMP"


def test_towered_fields_near_a_line(lnm):
    con = sqlite3.connect(lnm.db_path)
    con.execute("insert into airport values (2, 'EXUN', 'NO TOWER', 50.0, 8.1, 300, 2.5)")  # Info only
    con.execute("insert into com values (2, 'CTAF', 122600000, 'NO TOWER')")
    con.commit()
    con.close()
    assert lnm.towered_near((49.0, 7.9), (51.0, 7.9), 10) == ["EXMP"]  # 3.9 nm beside the line
    assert lnm.towered_near((49.0, 7.0), (51.0, 7.0), 10) == []  # 39 nm


def test_unknown_airport_is_none(lnm):
    assert lnm.get("ZZZZ") is None


def test_frequencies_are_converted_from_hz_and_named(lnm):
    a = lnm.get("exmp")
    assert a.name == "Example City"
    assert a.frequency_at(118505).station == "Example City Tower"
    assert a.frequency_at(121900).station == "Example City Ground"  # missing name -> airport name
    assert a.frequency_at(127000).name == "Example City"  # not "Exmp"


def test_ils_is_joined_by_runway_name(lnm):
    ends = {e.name: e for r in lnm.get("EXMP").runways for e in r.ends}
    assert ends["27"].ils.ident == "IEXW" and ends["27"].ils.khz == 110300
    assert ends["09"].ils is None
    assert ends["27"].offset_threshold_ft == 300


def test_parking_names_and_default_gate(lnm):
    a = lnm.get("EXMP")
    assert sorted(p.name for p in a.parking) == ["G 12A", "P 3"]
    gate = a.default_parking()
    assert gate.name == "G 12A" and gate.airline_codes == ("DLH", "EWG")


def test_taxi_paths_are_loaded(lnm):
    [t] = lnm.get("EXMP").taxi_paths
    assert (t.name, t.type, t.end_type) == ("", "PT", "HSND")


def test_vfr_points_and_the_control_zone(lnm):
    a = lnm.get("EXMP")
    assert [p.ident for p in a.vfr_points] == ["NOVMR", "S1"]
    assert (a.control_zone.name, a.control_zone.ceiling_ft) == ("Example City", 2500)
    assert len(a.control_zone.polygon) == 4


def test_json_round_trip_keeps_everything(lnm):
    a = lnm.get("EXMP")
    assert airport_from_dict(airport_to_dict(a)) == a


def test_json_eddh_has_parking(eddh):
    assert eddh.default_parking().is_gate


@pytest.mark.skipif(lnm_files.find(Config().littlenavmap_db) is None, reason="no Little Navmap database here")
def test_real_database_matches_exported_json(eddh):
    real = LittleNavmapAirportData(lnm_files.find(Config().littlenavmap_db)).get("EDDH")
    assert airport_from_dict(airport_to_dict(real)) == eddh

"""Center sectors from Little Navmap's boundary table (F3), read from a small database made in the test."""
import sqlite3
import struct

import pytest

from atc.airspace.centers import CenterSectors, with_imported
from atc.airspace.littlenavmap import area, decode_polygon, load_littlenavmap_centers, station_name
from atc.config import Config
from atc.session import center_sectors, describe_centers
from tests.test_centers import CS, airborne, box, check_in, contact, next_call


def geometry(points):
    """Little Navmap's format: big-endian int32 count, then float32 (lon, lat) pairs."""
    return struct.pack(f">i{2 * len(points)}f", len(points), *[v for lat, lon in points for v in (lon, lat)])


def square(lat_min, lat_max, lon_min, lon_max):
    return [(lat_min, lon_min), (lat_max, lon_min), (lat_max, lon_max), (lat_min, lon_max)]


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("create table boundary (boundary_id integer primary key, type text, name text, com_type text, "
                "com_frequency integer, com_name text, geometry blob)")
    con.executemany("insert into boundary (type, name, com_type, com_frequency, com_name, geometry) "
                    "values (?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    return path


ROWS = [
    ("C", "EDWW0817", "CTR", 125100, "BREMEN", geometry(square(51.3, 55.0, 8.5, 10.4))),
    ("C", "EDWW0815", "CTR", 119825, "BREMEN", geometry(square(51.3, 53.0, 9.8, 11.1))),
    ("C", "EDLL0810", "CTR", 118750, "LANGEN RADAR", geometry(square(50.0, 51.3, 7.0, 12.0))),
    ("C", "EDMM0811", "CTR", 120650, "MUNICH", geometry(square(47.3, 50.0, 9.0, 13.0))),
    ("C", "ESAA0900", "CTR", 118000, "MALMO CONTROL", geometry(square(55.0, 58.0, 10.6, 13.2))),
    ("CD", "BREMEN CTR", None, None, None, geometry(square(52.9, 53.1, 8.6, 9.0))),  # a control zone: not a Center
    ("C", "XXXX0001", "CTR", None, "NO FREQUENCY", geometry(square(0, 1, 0, 1))),
]


@pytest.fixture
def db(tmp_path):
    return make_db(tmp_path / "little_navmap_msfs.sqlite", ROWS)


def test_geometry_is_decoded_to_lat_lon():
    points = decode_polygon(geometry([(53.0, 10.1), (54.7, 10.4), (54.6, 10.5)]))
    assert [v for point in points for v in point] == pytest.approx([53.0, 10.1, 54.7, 10.4, 54.6, 10.5], abs=1e-5)


@pytest.mark.parametrize("com_name, fir, spoken", [
    ("BREMEN", "EDWW", "Bremen Radar"), ("LANGEN RADAR", "EDLL", "Langen Radar"),
    ("FRANKFURT 1", "EDFF", "Frankfurt Radar"), ("MALMO CONTROL", "ESAA", "Malmo Control"),
    ("AMSTERDAM", "EHAA", "Amsterdam Radar"), ("BRUSSELS", "EBBU", "Brussels Control")])
def test_station_names_as_spoken(com_name, fir, spoken):
    assert station_name(com_name, fir) == spoken


def test_only_centers_with_a_frequency_are_read_smallest_first(db):
    sectors = load_littlenavmap_centers(db)
    assert sorted((s.name, s.fir, s.khz) for s in sectors) == [
        ("Bremen Radar", "EDWW", 119825), ("Bremen Radar", "EDWW", 125100), ("Langen Radar", "EDLL", 118750),
        ("Malmo Control", "ESAA", 118000), ("Munich Radar", "EDMM", 120650)]
    sizes = [area(s) for s in sectors]
    assert sizes == sorted(sizes)
    assert all((s.lower_ft, s.upper_ft) == (0, 99999) for s in sectors)  # the data has no altitude bands
    # Where the two Bremen sectors overlap (10.0E), the smaller one is found
    assert CenterSectors(sectors).at(52.0, 10.0, 35000).khz == 119825


def test_corrections_in_centers_json_win_and_placeholders_go(db):
    own = CenterSectors([box("Langen Radar", "EDGG", 127325, 50.0, 51.3), box("Bremen Radar", "EDWW", None, 52, 55)],
                        source="centers.json")
    sectors = with_imported(own, load_littlenavmap_centers(db))
    assert sectors.source == "Little Navmap + centers.json"
    assert sectors.at(50.5, 10.0, 35000).khz == 127325  # the correction
    assert not sectors.placeholders
    assert describe_centers(sectors) == "Center sectors: 6 from Little Navmap + centers.json"


def test_the_session_reads_little_navmap_when_the_database_is_there(db, tmp_path, monkeypatch):
    monkeypatch.setattr("atc.session.load_littlenavmap_centers", load_littlenavmap_centers)  # undo the test guard
    with_db = center_sectors(Config(littlenavmap_db=db))
    assert with_db.source == "Little Navmap" and len(with_db.sectors) == 5
    without = center_sectors(Config(littlenavmap_db=tmp_path / "missing.sqlite"))
    assert without.source == "centers.json" and without.placeholders  # the shipped file


def test_two_sectors_with_the_same_name_are_a_handoff(eddh, eddm, db):
    # Bremen Radar on 125.100 and on 119.825 are different controllers: moving across is a handoff
    s = airborne(eddh, eddm, CenterSectors(load_littlenavmap_centers(db)))
    nm, calls = next_call(s, 3, 60)
    assert calls == [contact("Bremen Radar", 125100)]
    check_in(s, 125100, "Bremen Radar")
    nm, calls = next_call(s, nm + 1, 400)
    assert calls == [contact("Bremen Radar", 119825)]


@pytest.mark.skipif(not Config().littlenavmap_db.exists(), reason="no Little Navmap database on this machine")
def test_real_database_has_bremen_radar_over_hamburg():
    sectors = CenterSectors(load_littlenavmap_centers(Config().littlenavmap_db))
    bremen = sectors.at(53.63, 9.99, 20000)
    assert bremen.fir == "EDWW" and bremen.name == "Bremen Radar" and bremen.khz is not None

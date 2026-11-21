"""Milestone 10 A: STARs, approaches and transitions from Little Navmap's database.

The procedures here are made up (fixes TANGO, MIKEY, …), laid out like Munich's: a STAR per runway direction from
the same entry fix, an ILS with a transition that ends in vectors on the downwind. No real data in the repo."""
import sqlite3

import pytest

from atc.airport.json_data import JsonAirportData
from atc.airport.littlenavmap import LittleNavmapAirportData
from atc.airport.procedures import load_procedures

LEG_COLUMNS = ("type text, fix_ident text, fix_laty real, fix_lonx real, alt_descriptor text, altitude1 real, "
               "altitude2 real, speed_limit_type text, speed_limit integer, course real")
SCHEMA = f"""
create table airport (airport_id integer, ident text, name text, laty real, lonx real, altitude integer, mag_var real);
create table approach (approach_id integer, airport_ident text, runway_name text, type text, suffix text,
                       fix_ident text, arinc_name text);
create table approach_leg (approach_leg_id integer primary key, approach_id integer, is_missed integer, {LEG_COLUMNS});
create table transition (transition_id integer, approach_id integer, type text, fix_ident text);
create table transition_leg (transition_leg_id integer primary key, transition_id integer, {LEG_COLUMNS});
"""


def leg(kind, fix="", lat=0.0, lon=0.0, alt=None, alt1=0.0, alt2=0.0, speed=None, course=0.0):
    return (kind, fix, lat, lon, alt, alt1, alt2, "-" if speed else None, speed, course)


APPROACHES = [  # id, runway, type, suffix, name, arinc
    (1, "26R", "GPS", "A", "TANGO2B", "RW26R"),
    (2, "26L", "GPS", "A", "TANGO2B", "RW26L"),
    (3, "08R", "GPS", "A", "TANGO2A", "RW08R"),
    (4, "26R", "GPS", "A", "VICTR1B", "RW26R"),
    (5, "26R", "GPS", "D", "SIERA1N", "RW26R"),  # a SID: not read
    (6, "26R", "ILS", None, "GOLFF", "I26R"),
    (7, "26R", "RNAV", None, "GOLFF", "R26R"),
    (8, "26L", "ILS", "Y", "HOTEL", "I26LY"),
    (9, "26L", "ILS", "Z", "HOTEL", "I26LZ"),
    (10, None, "GPS", "A", "ALLRW1", None),  # a STAR for every runway
]
APPROACH_LEGS = {  # approach id: [(is_missed, leg), …]
    1: [(0, leg("IF", "TANGO", 48.60, 12.27, "-", 10000, speed=250)), (0, leg("TF", "MIKEY", 48.57, 11.60, "+", 5000))],
    2: [(0, leg("IF", "TANGO", 48.60, 12.27, "-", 10000, speed=250)), (0, leg("TF", "MIKEY", 48.57, 11.60, "+", 5000))],
    3: [(0, leg("IF", "TANGO", 48.60, 12.27, "-", 10000)), (0, leg("TF", "OSCAR", 48.30, 12.10, "B", 9000, 7000))],
    4: [(0, leg("IF", "VICTR", 48.90, 12.90)), (0, leg("TF", "MIKEY", 48.57, 11.60))],
    5: [(0, leg("CA", course=263))],
    6: [(0, leg("IF", "DX438", 48.36, 12.00, "+", 5000)), (0, leg("TF", "GOLFF", 48.36, 11.95, "A", 5000, 5000)),
        (0, leg("TF", "MX039", 48.36, 11.90, "+", 2690)), (0, leg("TF", "RW26R", 48.35, 11.80, "A", 1500)),
        (1, leg("CA", course=263, alt="+", alt1=5000)), (1, leg("DF", "MIKEY", 48.57, 11.60))],
    7: [(0, leg("IF", "DX438", 48.36, 12.00)), (0, leg("TF", "RW26R", 48.35, 11.80))],
    8: [(0, leg("IF", "HY001", 48.32, 12.00)), (0, leg("TF", "RW26L", 48.32, 11.80))],
    9: [(0, leg("IF", "HZ001", 48.32, 12.00)), (0, leg("TF", "RW26L", 48.32, 11.80))],
    10: [(0, leg("IF", "ALLFX", 48.0, 11.0))],
}
TRANSITIONS = [  # id, approach id, name, legs
    (100, 6, "TANGO", [leg("IF", "TANGO", 48.60, 12.27), leg("TF", "DX411", 48.50, 12.20),
                       leg("TF", "DX429", 48.45, 12.30), leg("FM", "DX429", 48.45, 12.30, course=80),
                       leg("CF", "DX438", 48.36, 12.00, "+", 5000, course=261)]),
    (101, 6, "MIKEY", [leg("IF", "MIKEY", 48.57, 11.60, "+", 5000), leg("CI", "", alt="+", alt1=5000, course=201)]),
    (102, 1, "ROMEO", [leg("IF", "ROMEO", 49.0, 12.6, "B", 27000, 25000), leg("TF", "TANGO", 48.60, 12.27)]),
]


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "little_navmap_msfs.sqlite"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("insert into airport values (1, 'EXMP', 'EXAMPLE', 48.35, 11.79, 1487, 4.1)")
    con.executemany("insert into approach values (?, 'EXMP', ?, ?, ?, ?, ?)", APPROACHES)
    for approach_id, legs in APPROACH_LEGS.items():
        con.executemany("insert into approach_leg (approach_id, is_missed, type, fix_ident, fix_laty, fix_lonx, "
                        "alt_descriptor, altitude1, altitude2, speed_limit_type, speed_limit, course) "
                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(approach_id, m, *l) for m, l in legs])
    for transition_id, approach_id, name, legs in TRANSITIONS:
        con.execute("insert into transition values (?, ?, 'F', ?)", (transition_id, approach_id, name))
        con.executemany("insert into transition_leg (transition_id, type, fix_ident, fix_laty, fix_lonx, "
                        "alt_descriptor, altitude1, altitude2, speed_limit_type, speed_limit, course) "
                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(transition_id, *l) for l in legs])
    con.commit()
    con.close()
    return LittleNavmapAirportData(path)


def test_stars_per_runway_without_sids(source):
    p = source.procedures("exmp")
    assert [(s.name, s.runway) for s in p.stars] == [
        ("TANGO2B", "26R"), ("TANGO2B", "26L"), ("TANGO2A", "08R"), ("VICTR1B", "26R"), ("ALLRW1", None)]
    assert [s.name for s in p.stars_for("26L")] == ["TANGO2B", "ALLRW1"]
    assert p.star("tango2b", "26L").runway == "26L" and p.star("TANGO2B").runway == "26R"
    assert p.star("NOSUCH") is None


def test_a_stars_constraints(source):
    star = source.procedures("EXMP").star("TANGO2B")
    entry, end = star.legs
    assert (entry.ident, entry.alt, entry.alt_ft, entry.speed_kt) == ("TANGO", "at_or_below", 10000, 250)
    assert (entry.ceiling_ft, entry.floor_ft) == (10000, None)
    assert (end.floor_ft, end.ceiling_ft, end.speed_kt) == (5000, None, None)
    assert (star.first_fix, star.last_fix) == ("TANGO", "MIKEY")
    between = source.procedures("EXMP").star("TANGO2A").legs[1]
    assert (between.alt, between.ceiling_ft, between.floor_ft) == ("between", 9000, 7000)


def test_the_star_for_the_landing_runway(source):
    p = source.procedures("EXMP")
    assert p.star_from("TANGO", "26R").name == "TANGO2B"
    assert p.star_from("TANGO", "08R").name == "TANGO2A"
    assert p.star_from("ROMEO", "26R").name == "TANGO2B"  # by its transition
    assert p.star_from("TANGO", "08L") is None


def test_the_approach_prefers_the_ils(source):
    p = source.procedures("EXMP")
    ils = p.approach("26R")
    assert (ils.name, ils.approach_type, ils.kind) == ("I26R", "ILS", "approach")
    assert p.approach("26R", ("RNAV",)).name == "R26R"
    assert p.approach("26L").name == "I26LZ"  # of Z and Y: Z
    assert p.approach("09") is None


def test_the_approach_legs_faf_and_missed(source):
    ils = source.procedures("EXMP").approach("26R")
    assert [l.ident for l in ils.legs] == ["DX438", "GOLFF", "MX039", "RW26R"]
    assert ils.faf.ident == "GOLFF" and (ils.faf.alt, ils.faf.alt_ft) == ("at", 5000)
    assert [l.path for l in ils.missed] == ["CA", "DF"]
    assert ils.missed[0].ident == "" and ils.missed[0].lat is None
    assert ils.last_fix == "MX039"  # not the runway


def test_a_transition_ends_in_vectors(source):
    ils = source.procedures("EXMP").approach("26R")
    assert [t.name for t in ils.transitions] == ["TANGO", "MIKEY"]
    tango = ils.transition("tango")
    assert [l.ident for l in tango.legs] == ["TANGO", "DX411", "DX429", "DX429", "DX438"]
    assert tango.vectors_from.ident == "DX429" and tango.vectors_from.course == 80
    assert tango.legs[-1].floor_ft == 5000 and tango.legs[-1].course == 261
    assert ils.transition("MIKEY").vectors_from is None
    assert ils.transition("NOSUCH") is None


def test_unknown_airport_and_old_databases(source, tmp_path):
    assert source.procedures("XXXX") is None
    old = tmp_path / "old.sqlite"
    con = sqlite3.connect(old)
    con.execute("create table airport (airport_id integer, ident text)")
    con.execute("insert into airport values (1, 'EXMP')")
    con.commit()
    con.close()
    assert LittleNavmapAirportData(old).procedures("EXMP") is None
    assert JsonAirportData(tmp_path).procedures("EXMP") is None


def test_fix_positions_from_the_navaid_tables():
    """As in Little Navmap's MSFS database: the legs carry no coordinates, only ident, type and region. A fix
    found twice is taken from its region, of several in it the nearest to the airport; a runway is no navaid."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA.replace("course real", "course real, fix_type text, fix_region text") + """
        create table waypoint (ident text, region text, airport_ident text, laty real, lonx real);
        create table vor (ident text, region text, laty real, lonx real);
        create table ndb (ident text, region text, laty real, lonx real);
    """)
    con.execute("insert into airport values (1, 'EXMP', 'EXAMPLE', 48.35, 11.79, 1487, 4.1)")
    con.execute("insert into approach values (1, 'EXMP', '26R', 'GPS', 'A', 'TANGO2B', 'RW26R')")
    con.executemany("insert into waypoint values (?, ?, ?, ?, ?)", [
        ("TANGO", "XX", None, 48.60, 12.27), ("TANGO", "YY", None, 48.40, 11.90),  # the other region: nearer
        ("DX411", "XX", "EXMP", 48.50, 12.20), ("DX411", "XX", "EOTH", 51.00, 7.00)])  # another airport's
    con.execute("insert into vor values ('MIKEY', 'XX', 48.57, 11.60)")
    con.executemany("insert into approach_leg (approach_id, is_missed, type, fix_ident, fix_type, fix_region) "
                    "values (1, 0, ?, ?, ?, ?)", [("IF", "TANGO", "W", "XX"), ("TF", "DX411", "TW", "XX"),
                                                  ("TF", "MIKEY", "V", "XX"), ("TF", "NOFIX", "W", "XX"),
                                                  ("TF", "RW26R", "R", "XX")])
    star = load_procedures(con, "EXMP").star("TANGO2B")
    assert [(l.ident, l.lat, l.lon) for l in star.legs] == [
        ("TANGO", 48.60, 12.27), ("DX411", 48.50, 12.20), ("MIKEY", 48.57, 11.60), ("NOFIX", None, None),
        ("RW26R", None, None)]

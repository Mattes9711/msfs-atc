"""En-route Center sectors: loading centers.json, finding the sector, and the handoffs along EDDH -> EDDM.

The test sectors are boxes across the route (EDDH 53.6N, EDDM 48.4N, both near 10-12E) with made-up test
frequencies, so positions along the fake-sim route fall into known sectors:
    North (52.5-55N, all levels) -> Middle (51-52.5N, all levels) -> South Upper (47.5-51N, FL245+)
                                                                   -> South     (47.5-51N, below FL245)
"""
import json

import pytest

from atc.airport.geo import point_in_polygon
from atc.airspace.centers import CenterSector, CenterSectors, CentersError, load_centers
from atc.config import ROOT
from atc.session import describe_centers
from atc.phraseology import spoken
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH, cleared_for_takeoff

CS = "Lufthansa four Alfa Bravo"
NORTH, MIDDLE, SOUTH_UPPER, SOUTH = 123450, 127300, 132600, 129100  # test values, not real frequencies


def box(name, fir, khz, lat_min, lat_max, lower=0, upper=66000):
    return CenterSector(name, fir, khz, lower, upper,
                        ((lat_max, 8.0), (lat_max, 13.0), (lat_min, 13.0), (lat_min, 8.0)))


SECTORS = CenterSectors([
    box("North Radar", "TST1", NORTH, 52.5, 55.0),
    box("Middle Radar", "TST2", MIDDLE, 51.0, 52.5),
    box("South Upper Radar", "TST3", SOUTH_UPPER, 47.5, 51.0, lower=24500),
    box("South Radar", "TST3", SOUTH, 47.5, 51.0, upper=24500),
], source="test centers.json")


def contact(name, khz):
    return f"{CS}, contact {name} {spoken.frequency(khz)}"


def airborne(eddh, eddm, sectors=SECTORS):
    """Climbing out with Hamburg Approach (EDDH's departure controller), radar contact read back."""
    s = cleared_for_takeoff(eddh, eddm, centers=sectors)
    fly(s, 2)
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    level = 240 if sectors else 350  # with Center sectors, Departure stops at FL240 and Center gives the rest
    assert confirmed(s.say(HAMBURG_APPROACH, f"climb flight level {level}, direct Amluh, Lufthansa 4AB"))
    return s


def check_in(s, khz, name):
    """First call to a Center after the handoff: it gives the rest of the climb, read back at once."""
    out = s.say(khz, f"{name}, Lufthansa 4AB, with you")
    if s.atc.pending:
        assert confirmed(s.say(khz, "climb flight level 350, Lufthansa 4AB"))
    return out


def fly(s, nm):
    s.sim.fly(s.atc.airport, s.atc.destination, nm, s.atc.plan.cruise_ft)
    return s.tick()


def next_call(s, start, end):
    """Fly 1 nm at a time (the tick is what runs every second in the sim) until ATC says something."""
    for nm in range(start, end):
        if out := fly(s, nm):
            return nm, out
    return None, []


# --- sectors and lookup ---------------------------------------------------------------------------------------

def test_point_in_a_concave_polygon():
    l_shape = [(0, 0), (0, 10), (5, 10), (5, 5), (10, 5), (10, 0)]  # (lat, lon)
    assert point_in_polygon(2, 2, l_shape)
    assert point_in_polygon(8, 2, l_shape)
    assert point_in_polygon(2, 8, l_shape)
    assert not point_in_polygon(8, 8, l_shape)  # the cut-out corner
    assert not point_in_polygon(11, 2, l_shape)


def test_sector_by_position_and_altitude():
    assert SECTORS.at(53.0, 10.0, 3000).name == "North Radar"
    assert SECTORS.at(53.0, 10.0, 39000).name == "North Radar"
    assert SECTORS.at(49.0, 11.0, 35000).name == "South Upper Radar"
    assert SECTORS.at(49.0, 11.0, 24499).name == "South Radar"
    assert SECTORS.at(49.0, 11.0, 24500).name == "South Upper Radar"  # lower bound inclusive, upper exclusive
    assert SECTORS.at(49.0, 14.0, 10000) is None  # east of every box
    assert SECTORS.at(53.0, 10.0, 70000) is None  # above every band


def test_first_sector_in_the_file_wins_where_they_overlap():
    sectors = CenterSectors([box("A Radar", "TSTA", NORTH, 50, 54), box("B Radar", "TSTB", MIDDLE, 52, 56)])
    assert sectors.at(53, 10, 10000).name == "A Radar"
    assert sectors.at(55, 10, 10000).name == "B Radar"


# --- centers.json -----------------------------------------------------------------------------------------------

def write(tmp_path, *sectors):
    path = tmp_path / "centers.json"
    path.write_text(json.dumps({"sectors": list(sectors)}), encoding="utf-8")
    return path


def raw(**changes):
    sector = {"name": "Test Radar", "fir": "tst1", "frequency": "123.45", "lower_ft": 0, "upper_ft": 66000,
              "polygon": [[52, 8], [52, 13], [50, 13], [50, 8]]}
    return sector | changes


def test_load_centers(tmp_path):
    centers = load_centers(write(tmp_path, raw(), raw(name="Other Radar", frequency="PLACEHOLDER", note="todo")))
    real, placeholder = centers.sectors
    assert (real.name, real.fir, real.khz, real.placeholder) == ("Test Radar", "TST1", 123450, False)
    assert (placeholder.khz, placeholder.placeholder) == (None, True)
    assert centers.placeholders == [placeholder]
    assert centers.on_frequency(123450) == [real]


@pytest.mark.parametrize("changes, message", [
    ({"frequency": "123.4x"}, 'use "PLACEHOLDER"'),
    ({"frequency": "placeholder"}, 'use "PLACEHOLDER"'),  # must be exactly the marker, so it can't slip through
    ({"frequency": "140.000"}, "outside the VHF COM band"),
    ({"lower_ft": 24500, "upper_ft": 24500}, "lower_ft < upper_ft"),
    ({"polygon": [[52, 8], [52, 13]]}, "at least 3 points"),
    ({"polygon": [[52, 8], [52, 200], [50, 8]]}, "out of range"),
    ({"freq": "123.45"}, "unknown freq"),
])
def test_bad_sectors_are_reported(tmp_path, changes, message):
    with pytest.raises(CentersError, match=message):
        load_centers(write(tmp_path, raw(**changes)))


def test_missing_key_is_reported(tmp_path):
    sector = raw()
    del sector["fir"]
    with pytest.raises(CentersError, match="missing fir"):
        load_centers(write(tmp_path, sector))


def test_shipped_centers_json_loads_and_marks_unknown_frequencies():
    centers = load_centers(ROOT / "data" / "centers.json")
    assert centers.sectors
    assert all(s.placeholder for s in centers.sectors)  # none of the real frequencies are filled in yet
    assert "PLACEHOLDER frequency" in describe_centers(centers)


def test_banner_without_sectors():
    assert "Departure keeps you until Approach" in describe_centers(CenterSectors())


# --- handoffs ---------------------------------------------------------------------------------------------------

def test_full_flight_through_the_center_sectors(eddh, eddm):
    s = airborne(eddh, eddm)
    # Departure -> the sector the aircraft is in, passing FL100
    assert next_call(s, 3, 60) == (18, [contact("North Radar", NORTH)])
    assert s.atc.phase == "enroute"
    # First Center: identified and the rest of the climb (Departure only gave FL240)
    assert s.say(NORTH, "North Radar, Lufthansa 4AB, with you, climbing flight level 240") == [
        f"{CS}, North Radar, identified, climb flight level tree fife zero"]
    assert confirmed(s.say(NORTH, "climb flight level 350, Lufthansa 4AB"))
    assert fly(s, 19) == []  # same sector: no second handoff

    # Sector crossing: North -> Middle at 52.5N
    assert next_call(s, 20, 150) == (70, [contact("Middle Radar", MIDDLE)])
    s.say(MIDDLE, "Middle Radar, Lufthansa 4AB, with you, flight level 350")
    # Middle -> South Upper at 51N (FL350 is above South Radar's band)
    assert next_call(s, 71, 200) == (162, [contact("South Upper Radar", SOUTH_UPPER)])
    s.say(SOUTH_UPPER, "South Upper Radar, Lufthansa 4AB, with you, flight level 350")

    # Top of descent: the Center in charge gives it
    assert next_call(s, 163, 240) == (219, [f"{CS}, descend flight level one hundred"])
    assert confirmed(s.say(SOUTH_UPPER, "descend flight level 100, Lufthansa 4AB"))
    # Descending through FL245: same area, lower sector
    assert next_call(s, 220, 280) == (251, [contact("South Radar", SOUTH)])
    assert s.sim.read().alt_msl_ft < 24500
    s.say(SOUTH, "South Radar, Lufthansa 4AB, with you, descending flight level 100")

    # Center -> Approach of the destination
    assert next_call(s, 252, 300) == (284, [contact("Munich Approach", MUNICH_APPROACH)])
    assert s.atc.phase == "arrival"
    assert "vectors ILS approach" in s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, with you")[0]


def test_calling_the_wrong_center_gets_the_right_one(eddh, eddm):
    s = airborne(eddh, eddm)
    next_call(s, 3, 60)  # handed to North Radar
    assert s.say(MIDDLE, "Middle Radar, Lufthansa 4AB, with you") == [contact("North Radar", NORTH)]


def test_handoff_is_only_heard_on_the_controllers_frequency(eddh, eddm):
    s = airborne(eddh, eddm)
    next_call(s, 3, 60)
    check_in(s, NORTH, "North Radar")
    s.sim.update(com1_khz=HAMBURG_APPROACH)  # went back to the old frequency
    nm, [hint] = next_call(s, 20, 150)
    assert hint == f"(North Radar is calling you on 123.450: {contact('Middle Radar', MIDDLE)})"


def test_pilot_can_request_descent_from_center(eddh, eddm):
    s = airborne(eddh, eddm)
    next_call(s, 3, 60)
    check_in(s, NORTH, "North Radar")
    # Still below FL110 (18 nm out): straight to the altitude, with the QNH
    assert s.say(NORTH, "Lufthansa 4AB, request descent") == [
        f"{CS}, descend altitude fife thousand feet, QNH one zero one niner"]


def test_leaving_every_sector_terminates_radar_service(eddh, eddm):
    s = airborne(eddh, eddm, CenterSectors([box("North Radar", "TST1", NORTH, 52.5, 55.0)]))
    next_call(s, 3, 60)
    check_in(s, NORTH, "North Radar")
    assert next_call(s, 20, 150) == (70, [
        f"{CS}, radar service terminated, squawk seven zero zero zero, frequency change approved"])
    assert confirmed(s.say(NORTH, "squawk 7000, Lufthansa 4AB"))
    assert s.atc.squawk == "7000" and s.atc.center is None
    # Nobody to give the descent or the handoff: at 40 nm the pilot only gets a hint whom to call
    assert next_call(s, 71, 300) == (284, [f"(contact Munich Approach {spoken.frequency(MUNICH_APPROACH)})"])


def test_no_sector_at_the_departure_handoff(eddh, eddm):
    s = airborne(eddh, eddm, CenterSectors([box("Middle Radar", "TST2", MIDDLE, 51.0, 52.5)]))
    assert next_call(s, 3, 60) == (18, [
        f"{CS}, radar service terminated, squawk seven zero zero zero, frequency change approved"])
    s.say(HAMBURG_APPROACH, "squawk 7000, Lufthansa 4AB")
    # Entering a sector later: a hint whom to call, no made-up call from a controller who never had us
    assert next_call(s, 19, 150) == (70, ["(now inside Middle Radar airspace (TST2): call Middle Radar on 127.300 "
                                          "for radar service)"])
    assert s.say(MIDDLE, "Middle Radar, Lufthansa 4AB, with you")[0] == f"{CS}, Middle Radar, identified"


def test_placeholder_frequency_is_never_used_in_a_handoff(eddh, eddm):
    sectors = CenterSectors([box("North Radar", "TST1", None, 52.5, 55.0),
                             box("Middle Radar", "TST2", MIDDLE, 51.0, 52.5)], source="centers.json")
    s = airborne(eddh, eddm, sectors)
    assert next_call(s, 3, 60) == (18, [
        "(you are in North Radar airspace (TST1), but its frequency is PLACEHOLDER in centers.json: please fill in "
        "the real frequency. No handoff, Hamburg Approach keeps you)"])
    assert s.atc.phase == "climb"  # still with Departure
    # Said once, and the first sector with a real frequency gets the aircraft from Departure
    assert next_call(s, 19, 150) == (70, [contact("Middle Radar", MIDDLE)])


def test_placeholder_sector_after_a_real_one_keeps_the_current_center(eddh, eddm):
    sectors = CenterSectors([box("North Radar", "TST1", NORTH, 52.5, 55.0),
                             box("Middle Radar", "TST2", None, 51.0, 52.5)])
    s = airborne(eddh, eddm, sectors)
    next_call(s, 3, 60)
    check_in(s, NORTH, "North Radar")
    nm, [hint] = next_call(s, 20, 150)
    assert nm == 70 and hint.startswith("(you are in Middle Radar airspace") and "North Radar keeps you" in hint
    assert s.atc.center.name == "North Radar"


def test_without_sectors_departure_keeps_the_aircraft(eddh, eddm):
    s = airborne(eddh, eddm, CenterSectors())
    assert next_call(s, 3, 240) == (219, [f"{CS}, descend flight level one hundred"])
    assert s.atc.phase == "climb"

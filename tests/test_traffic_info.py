"""T3: traffic information in the air: clock position, distance, direction and height, once per aircraft."""
import pytest

from atc.airport.geo import destination_point
from atc.controller.traffic import traffic_information
from atc.intent.parser import parse
from atc.sim.traffic import Traffic
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff

CS = "Lufthansa four Alfa Bravo"


def around(lat, lon, bearing, nm, alt, heading, oid=7):
    plat, plon = destination_point(lat, lon, bearing, nm)
    return Traffic(oid, plat, plon, alt, 250, heading % 360, False, "D-AIZA", "Lufthansa", "123", "A320")


@pytest.mark.parametrize("relative, nm, above, its_heading, words", [
    (60, 4, 1000, 180, "traffic, two o'clock, four miles, opposite direction, one thousand feet above"),
    (0, 3, -500, 10, "traffic, twelve o'clock, tree miles, same direction, fife hundred feet below"),
    (270, 1, 100, 90, "traffic, niner o'clock, one mile, crossing left to right, same level"),
    (90, 4.9, 1400, 270, "traffic, tree o'clock, fife miles, crossing right to left, one thousand four hundred feet above"),
])
def test_how_traffic_is_described(relative, nm, above, its_heading, words):
    # We fly heading 000 at 10000 ft
    t = around(53.0, 10.0, relative, nm, 10000 + above, its_heading)
    assert traffic_information(t, 53.0, 10.0, 10000, 0) == words


def test_too_far_too_high_or_on_the_ground_is_no_traffic_information():
    assert traffic_information(around(53, 10, 0, 6, 10000, 0), 53, 10, 10000, 0) is None
    assert traffic_information(around(53, 10, 0, 3, 12000, 0), 53, 10, 10000, 0) is None
    on_ground = Traffic(1, 53.01, 10, 50, 0, 0, True, "D-AIZA", "", "", "")
    assert traffic_information(on_ground, 53, 10, 60, 0) is None


def climbing(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    s.sim.fly(eddh, eddm, 8, 35000)
    s.tick()
    return s


def test_the_controller_tells_it_once(eddh, eddm):
    s = climbing(eddh, eddm)
    st = s.sim.read()
    heading_true = st.heading_mag + eddh.mag_var
    other = around(st.lat, st.lon, heading_true + 60, 4, st.alt_msl_ft + 1000, heading_true + 180)
    [info] = s._texts(s.atc.update_traffic([other]))
    assert info == f"{CS}, traffic, two o'clock, four miles, opposite direction, one thousand feet above"
    assert s.atc.update_traffic([other]) == []  # once
    assert parse("traffic in sight, Lufthansa 4AB", "DLH4AB").kind == "acknowledge"
    assert s.say(HAMBURG_APPROACH, "looking out, Lufthansa 4AB") == []
    far = around(st.lat, st.lon, 0, 20, st.alt_msl_ft, 0)
    s.atc.update_traffic([far])  # gone out of range: forgotten
    assert s.atc.update_traffic([other]) != []  # back close: told again


def test_no_traffic_information_on_the_ground(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    st = s.sim.read()
    assert s.atc.update_traffic([around(st.lat, st.lon, 0, 2, 1500, 0)]) == []

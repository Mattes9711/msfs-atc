"""P4: line up and wait on request, intersection departures, wind check."""
from atc.phraseology import spoken
from tests.test_ground_flow import confirmed
from tests.test_air_flow import MUNICH_TOWER, cleared_for_takeoff
from tests.test_ground_flow import GROUND, TOWER, Session
from tests.test_safety import midpoint, rwy_05_23

CS = "Lufthansa four Alfa Bravo"
WIND = "wind two two zero degrees seven knots"


def taxiing(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "holding point A3 runway 23, Lufthansa 4AB")
    return s


def test_line_up_and_wait_then_takeoff(eddh, eddm):
    s = taxiing(eddh, eddm)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, request line up runway 23") == [
        f"{CS}, runway two tree, line up and wait"]
    assert confirmed(s.say(TOWER, "line up and wait runway 23, Lufthansa 4AB"))
    s.sim.update(lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1])
    assert s.tick() == []  # on the runway with a line-up clearance: no "stop immediately"
    assert s.atc.status()["suggestion"]["title"] == "Ready for departure"
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == [
        f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def test_departure_from_an_intersection(eddh, eddm):
    s = taxiing(eddh, eddm)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure from intersection alpha 4") == [
        f"{CS}, {WIND}, runway two tree from intersection Alfa four, cleared for takeoff"]
    assert confirmed(s.say(TOWER, "runway 23, cleared for takeoff, Lufthansa 4AB"))


def test_an_intersection_of_another_runway_is_refused(eddh, eddm):
    s = taxiing(eddh, eddm)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure from intersection bravo 4") == [
        f"{CS}, {spoken.spell('B4')} is not an intersection of runway two tree, say again"]
    assert s.atc.phase == "taxi"


def test_wind_check_on_the_ground_and_on_final(eddh, eddm):
    assert taxiing(eddh, eddm).say(TOWER, "Hamburg Tower, Lufthansa 4AB, wind check") == [f"{CS}, {WIND}"]
    s = cleared_for_takeoff(eddh, eddm)
    s.atc.phase = "final"
    assert s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, wind check") == [
        f"{CS}, wind zero eight zero degrees eight knots"]

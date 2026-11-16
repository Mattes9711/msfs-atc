"""Strict readbacks (the user's wish): no switching before the readback, the pushback is read back, ATC asks once."""
from tests.test_ground_flow import confirmed
from tests.test_ground_flow import GROUND, TOWER, Session

CS = "Lufthansa four Alfa Bravo"


def strict(eddh, eddm=None):
    s = Session(eddh, destination=eddm)
    s.atc.strict_readback = True
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    return s


def test_the_pushback_is_read_back(eddh):
    s = strict(eddh)
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == [f"{CS}, push and start approved, facing west"]
    assert s.say(GROUND, "Lufthansa 4AB, request taxi") == [f"{CS}, read back pushback"]
    assert confirmed(s.say(GROUND, "push and start approved, facing west, Lufthansa 4AB"))
    assert s.atc.status()["suggestion"]["title"] == "Request taxi"


def test_no_switching_before_the_frequency_readback(eddh, eddm):
    s = strict(eddh, eddm)
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "taxi to holding point runway 23, Lufthansa 4AB")
    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])
    s.tick()  # "contact Hamburg Tower one two one decimal two eight zero"
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        "(read back first to Hamburg Ground on 121.705: contact Hamburg Tower one two one decimal two eight zero)"]
    assert s.atc.phase == "taxi"
    assert confirmed(s.say(GROUND, "contact Tower 121.280, Lufthansa 4AB"))
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure")[0].endswith("cleared for takeoff")


def test_atc_asks_once_after_20_seconds(eddh):
    s = strict(eddh)
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.tick(now=100) == [] and s.tick(now=119) == []
    assert s.tick(now=120) == [f"{CS}, read back"]
    assert s.tick(now=200) == []  # once


def test_without_strict_readbacks_nothing_changes(eddh):
    s = Session(eddh)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.atc.pending == ()
    assert s.say(GROUND, "push and start approved, facing west, Lufthansa 4AB") == []
    assert s.tick(now=100) == [] and s.tick(now=200) == []

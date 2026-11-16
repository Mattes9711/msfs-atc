"""P6: calls that work at any time: say again, standby, unable, QNH, weather, confirm."""
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff
from tests.test_ground_flow import GROUND, Session

CS = "Lufthansa four Alfa Bravo"


def cleared(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    return s


def test_say_again_repeats_the_last_transmission(eddh, eddm):
    s = cleared(eddh, eddm)
    clearance = s.atc.last_said[s.atc.station_at(GROUND).key]
    assert s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, say again") == [clearance]
    assert s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, confirm") == [clearance]  # "confirm" alone: the same


def test_standby_needs_no_answer(eddh):
    assert Session(eddh).say(GROUND, "Hamburg Ground, Lufthansa 4AB, standby") == []


def test_unable_withdraws_the_instruction(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")  # climb FL350, direct Amluh
    assert s.say(HAMBURG_APPROACH, "unable flight level 350, Lufthansa 4AB") == [
        f"{CS}, roger, maintain present heading and level, standby",
        "(the instruction is cancelled; tell ATC what you can do, or ask again)"]
    assert not s.atc.pending
    assert s.say(HAMBURG_APPROACH, "Lufthansa 4AB, request flight level 330") == [
        f"{CS}, climb flight level tree tree zero"]


def test_qnh_on_request_is_read_back(eddh, eddm):
    s = cleared(eddh, eddm)
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request QNH") == [f"{CS}, QNH one zero one eight"]
    assert confirmed(s.say(GROUND, "QNH 1018, Lufthansa 4AB"))


def test_weather_of_the_destination(eddh, eddm):
    [weather] = Session(eddh, destination=eddm).say(GROUND, "Hamburg Ground, Lufthansa 4AB, request weather at Munich")
    assert weather.startswith(f"{CS}, Munich weather, wind zero eight zero degrees eight knots, cav okay")
    assert weather.endswith("QNH one zero one niner")


def test_confirm_against_the_last_instruction(eddh, eddm):
    s = cleared(eddh, eddm)
    assert s.say(GROUND, "Lufthansa 4AB, confirm runway 23") == [f"{CS}, affirm"]
    assert s.say(GROUND, "Lufthansa 4AB, confirm runway 33") == [f"{CS}, negative, runway two tree"]
    assert s.say(GROUND, "Lufthansa 4AB, confirm heading 230") == [f"{CS}, negative, say again"]  # no heading given
    assert s.atc.pending  # confirming is not the readback: it is still due

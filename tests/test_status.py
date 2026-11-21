"""Controller.status(): what the app shows at a glance (D6)."""
from atc.app.server import App
from atc.config import Config
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff
from tests.test_app import INJECT, PLAN
from tests.test_ground_flow import GROUND, TOWER, Session


def status(s):
    s.tick()
    return s.atc.status()


def test_at_the_gate(eddh, eddm):
    s = Session(eddh, destination=eddm)
    st = status(s)
    assert (st["phase"], st["com1_khz"], st["tuned"]) == ("clearance", 0, None)
    # EDDH has no Delivery: Ground gives the clearance
    assert (st["controller"], st["controller_khz"], st["on_frequency"]) == ("Hamburg Ground", GROUND, False)
    assert (st["runway"], st["atis"], st["squawk"], st["cleared"]) == ("23", "A", None, None)
    assert st["on_ground"] is True and st["ground_speed_kt"] == 0


def test_after_the_clearance(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    st = status(s)
    assert (st["tuned"], st["on_frequency"]) == ("Hamburg Ground", True)
    assert st["cleared"] == "5000 FT" and st["squawk"] == s.atc.squawk


def test_a_handoff_points_at_the_next_controller(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "holding point A3 runway 23, Lufthansa 4AB")
    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])
    st = status(s)  # Ground: "contact Hamburg Tower"
    assert (st["controller"], st["controller_khz"], st["on_frequency"]) == ("Hamburg Tower", TOWER, False)


def test_in_the_climb(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(s.atc.airport, s.atc.destination, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000")
    st = status(s)
    assert (st["phase"], st["controller"], st["cleared"]) == ("climb", "Hamburg Approach", "FL350")
    assert st["on_ground"] is False and st["altitude_ft"] > 1000


def test_status_endpoint_needs_a_running_session():
    app = App(Config(), INJECT)
    assert app.status() is None
    app.start(PLAN)
    assert app.status()["phase"] == "clearance"
    app.stop()
    assert app.status() is None

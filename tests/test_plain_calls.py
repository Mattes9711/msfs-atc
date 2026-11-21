"""V3: ATC answers every call to the right controller (no silence, no needless "say again"), and the voice doesn't
talk over the pilot."""
import threading
import time

import pytest

from atc.airport.geo import destination_point
from atc.audio.tts import QueuedSpeech
from atc.phraseology.spoken import runway as spoken_runway
from atc.intent.parser import parse
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH, cleared_for_takeoff
from tests.test_ground_flow import GROUND, TOWER, Session

CS = "Lufthansa four Alfa Bravo"


def spoken(out):
    return [line for line in out if not line.startswith("(")]


@pytest.mark.parametrize("text", ["Hamburg Ground, Lufthansa 4AB", "Lufthansa 4AB, Hamburg Ground",
                                  "Hamburg Ground, Lufthansa 4AB, with you"])
def test_a_first_call_gets_go_ahead(eddh, text):
    assert parse(text, "DLH4AB").kind == "checkin"
    assert Session(eddh).say(GROUND, text) == [f"{CS}, Hamburg Ground, go ahead"]


def cleared(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    return s


def test_pushback_complete_is_answered(eddh, eddm):
    s = cleared(eddh, eddm)
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, pushback complete") == [
        f"{CS}, roger, report ready for taxi"]


def test_tower_check_in_at_the_holding_point_is_answered(eddh, eddm):
    s = cleared(eddh, eddm)
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "taxi to holding point A3 runway 23, Lufthansa 4AB")
    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])
    s.tick()  # "contact Hamburg Tower"
    s.say(GROUND, "contact Tower 121.280, Lufthansa 4AB")
    for call in ("Hamburg Tower, Lufthansa 4AB, with you", "Hamburg Tower, Lufthansa 4AB, holding point runway 23"):
        assert s.say(TOWER, call) == [f"{CS}, Hamburg Tower, report when ready for departure"]
    assert spoken(s.say(TOWER, "Lufthansa 4AB, ready for departure"))[0].endswith("cleared for takeoff")


def test_a_position_report_gets_roger(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 3000 climbing 5000")
    s.say(HAMBURG_APPROACH, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    assert s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, maintaining flight level 350") == [f"{CS}, roger"]
    assert s.say(HAMBURG_APPROACH, "roger, Lufthansa 4AB") == []  # an acknowledgement needs no answer


def test_established_hands_over_to_tower_at_once(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 3000 climbing 5000")
    s.say(HAMBURG_APPROACH, "climb flight level 350, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, with you")
    heading = s.atc.pending[-1].value
    s.say(MUNICH_APPROACH, f"descend 4500 feet, QNH 1019, speed 220 knots, heading {heading}, Lufthansa 4AB")
    # Flown the heading to 2 nm north of the point 14 nm out on the centreline: ATC turns us onto the localizer
    end = eddm.runway_end(s.atc.arrival_runway)
    lat, lon = destination_point(end.lat, end.lon, (end.heading_true + 180) % 360, 14)
    lat, lon = destination_point(lat, lon, 0, 2)
    s.sim.update(lat=lat, lon=lon, heading_mag=190)
    [clearance] = s.tick()
    turn = s.atc.pending[0]
    assert turn.phrase.startswith("turn left heading") and 100 <= turn.value <= 120  # course 08x + 30, from the left
    assert clearance == (f"{CS}, {turn.phrase}, maintain four thousand fife hundred feet until established, "
                         f"cleared ILS approach runway {spoken_runway(end.name)}, speed one eight zero knots")
    assert confirmed(s.say(MUNICH_APPROACH, f"turn left heading {turn.value}, cleared ILS runway {end.name}, "
                                            "speed 180 knots, Lufthansa 4AB"))
    assert s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, established") == [
        f"{CS}, contact Munich Tower one one eight decimal seven zero fife"]
    assert s.atc.phase == "final"


class Recorded(QueuedSpeech):
    def _start(self):
        self.spoken = []
        return "test voice"

    def _speak(self, text, station):
        self.spoken.append((time.monotonic(), text))


def test_atc_waits_while_the_pilot_holds_push_to_talk():
    out = Recorded(show=lambda text: None)
    pressed = threading.Event()
    pressed.set()
    out.hold = pressed.is_set
    out.say("Lufthansa four Alfa Bravo, contact Bremen Radar", "Hamburg Approach")
    time.sleep(0.2)
    assert out.spoken == []  # still waiting
    released = time.monotonic()
    pressed.clear()
    out.wait()
    assert out.spoken[0][0] >= released
    out.close()


def test_every_transmission_reaches_the_voice_with_its_station():
    from atc.app.server import AppSink, EventLog
    from atc.events import KINDS, Event

    said = []

    class Voice:
        def say(self, text, station=None, kind="atc"):
            said.append((text, station))

    sink = AppSink(EventLog(), Voice())
    for kind in KINDS:
        sink.emit(Event(kind, f"a {kind} line", "Hamburg Tower"))
    assert said == [("a atc line", "Hamburg Tower"), ("a atis line", "Hamburg Tower"), ("a chatter line", "Hamburg Tower"),
                    ("a cabin line", "Hamburg Tower"), ("a copilot line", "Hamburg Tower")]

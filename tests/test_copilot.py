"""C2: the co-pilot on the radio: reads back, tunes COM1 after a handoff and checks in; makes the requests by himself."""
from atc import copilot
from atc.events import Collector
from atc.runtime import handle_command, run
from tests.test_ground_flow import GROUND, Session


class Lines:
    """Typed input for text mode."""

    def __init__(self, *lines):
        self.lines = list(lines)

    def listen(self):
        return self.lines.pop(0) if self.lines else None


def flight(eddh, eddm, *lines):
    s = Session(eddh, destination=eddm)
    sink = Collector()
    run(s.sim, Lines(*lines), sink, s.atc)
    return s, [(e.kind, e.text) for e in sink.events if e.kind in ("atc", "copilot", "pilot", "notice")]


def test_what_the_pilot_says_to_the_copilot():
    assert copilot.command("Copilot, you have the radio") == "on"
    assert copilot.command("you have the radios") == "on"
    assert copilot.command("I have the radio") == "off"
    assert copilot.command("copilot, next call") == "next"
    assert copilot.command("Hamburg Ground, Lufthansa 4AB, request taxi") is None


def test_the_copilot_reads_back_and_the_pilot_still_requests(eddh, eddm):
    s, log = flight(eddh, eddm, "/com 121.705", "copilot, you have the radio",
                    "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha")
    kinds = [k for k, _ in log]
    assert kinds[-3:] == ["atc", "copilot", "atc"]  # clearance, his readback, "readback correct"
    assert log[-2][1].startswith("cleared to Munich via AMLUH 2G departure, runway 23, climb 5000 feet, squawk ") and log[-2][1].endswith("Lufthansa 4AB")
    assert not s.atc.pending


def test_next_call_makes_the_request(eddh, eddm):
    s, log = flight(eddh, eddm, "/com 121.705", "/copilot on", "/copilot next")
    request = ("copilot", "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alfa")
    i = log.index(request)
    assert "cleared to Munich" in log[i + 1][1] and log[i + 2][0] == "copilot"  # and he reads it back


def test_after_a_handoff_he_tunes_and_checks_in(eddh, eddm):
    from tests.test_air_flow import cleared_for_takeoff

    s = cleared_for_takeoff(eddh, eddm)
    s.atc.copilot_on = True
    s.sim.fly(eddh, eddm, 2, 35000)
    sink = Collector()
    run(s.sim, Lines("/copilot on"), sink, s.atc)  # one tick: Tower hands over to Departure
    texts = [(e.kind, e.text) for e in sink.events if e.kind in ("atc", "copilot")]
    assert texts[0][1].endswith("contact Hamburg Approach one one eight decimal two zero fife")
    assert texts[1] == ("copilot", "contact Hamburg Approach 118.205, Lufthansa 4AB")
    run(s.sim, Lines("/copilot on"), sink, s.atc)  # the next steps: tune, then check in
    run(s.sim, Lines("/copilot on"), sink, s.atc)
    assert s.sim.read().com1_khz == 118205
    assert any(e.kind == "copilot" and e.text.startswith("Hamburg Approach, Lufthansa 4AB, passing")
               for e in sink.events)


def test_he_gives_the_radio_back_when_a_readback_keeps_failing(eddh, eddm):
    from atc.runtime import COPILOT_TRIES, copilot_turn

    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha")
    s.atc.copilot_on = True
    s.atc.copilot_tries = (copilot.due(s.atc)["text"], COPILOT_TRIES)  # said it twice already
    sink = Collector()
    copilot_turn(s.sim, s.atc, sink)
    assert not s.atc.copilot_on and "you have the radio" in sink.events[-1].text


def test_copilot_command_usage(eddh):
    s = Session(eddh)
    sink = Collector()
    assert handle_command("/copilot maybe", s.sim, s.atc, sink)
    assert sink.events[-1].text == "usage: /copilot [on|off|next]"
    handle_command("/copilot", s.sim, s.atc, sink)
    assert s.atc.copilot_on and s.atc.status()["copilot"] is True


# --- 2026-11-16: he makes the phase's requests by himself -------------------------------------------------------


class Live:
    """The live loop step by step with a clock the test moves, the co-pilot on the radio."""

    def __init__(self, eddh, eddm):
        from atc.runtime import LiveSession

        self.s = Session(eddh, destination=eddm)
        self.sink, self.t = Collector(), [0.0]
        self.live = LiveSession(self.s.sim, self.sink, self.s.atc, clock=lambda: self.t[0])
        self.live.step("/copilot on")

    def run(self, seconds, **sim):
        """Move the sim (e.g. ground_speed_kt=3) and let `seconds` pass, a step a second."""
        if sim:
            self.s.sim.update(**sim)
        for _ in range(seconds):
            self.t[0] += 1
            self.live.step()

    def said(self):
        return [e.text for e in self.sink.events if e.kind == "copilot"]


def test_he_tunes_and_asks_for_the_clearance_at_once(eddh, eddm):
    f = Live(eddh, eddm)
    f.run(10)
    assert f.s.sim.read().com1_khz == GROUND  # tuned Ground (Hamburg has no Delivery) by himself
    said = f.said()
    assert said[0] == "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alfa"
    assert said[1].startswith("cleared to Munich via AMLUH 2G departure, runway 23, climb 5000 feet, squawk ")  # and read it back
    assert f.s.atc.phase == "cleared" and len(said) == 2  # the pushback waits for the beacon


def test_the_beacon_means_ready_for_pushback_then_taxi_after_the_push(eddh, eddm):
    f = Live(eddh, eddm)
    f.run(10)
    f.run(10, beacon=True)
    assert f.said()[2] == "Hamburg Ground, Lufthansa 4AB, request push and start"
    assert f.s.atc.phase == "pushback"
    f.run(20)
    assert len(f.said()) == 3  # not pushed yet: no taxi request
    f.run(30, ground_speed_kt=3)  # pushing
    f.run(3, ground_speed_kt=0)
    assert len(f.said()) == 3  # stopped, but not long enough
    f.run(5)
    assert f.said()[3] == "Hamburg Ground, Lufthansa 4AB, request taxi"
    f.run(10)
    assert f.said()[4].startswith("taxi to holding point A3, runway 23")  # read back
    assert f.s.atc.phase == "taxi"


def test_not_straight_after_readback_correct(eddh, eddm):
    from atc.copilot import QUIET_S

    f = Live(eddh, eddm)
    f.s.sim.update(beacon=True)  # ready at once: still he waits for a quiet radio after "readback correct"
    while len(f.said()) < 2:
        f.run(1)
    readback_at = f.t[0]
    assert f.live.radio.last == readback_at  # "readback correct" came in the same step
    f.run(QUIET_S - 1)
    assert len(f.said()) == 2
    f.run(1)
    assert f.said()[2].endswith("request push and start")


def test_ready_for_departure_once_standing_at_the_holding_point(eddh, eddm):
    from atc.runtime import LiveSession
    from tests.test_runway_traffic import at_holding_point

    s = at_holding_point(eddh, eddm)  # on Tower's frequency, standing at the holding point
    sink, t = Collector(), [0.0]
    live = LiveSession(s.sim, sink, s.atc, clock=lambda: t[0])
    live.step("/copilot on")
    calls = []
    for _ in range(15):
        t[0] += 1
        live.step()
        calls = [e.text for e in sink.events if e.kind == "copilot"]
        if calls:
            break
    assert calls[0] == "Hamburg Tower, Lufthansa 4AB, holding point runway 23, ready for departure"
    assert t[0] >= copilot.STILL_S

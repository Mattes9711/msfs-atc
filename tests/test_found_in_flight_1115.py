"""Bugs from the user's flight EDDH → EDDM on 2026-11-15 (flight log 1232Z_DLH241_2), each as a test."""
from atc.airspace.centers import CenterSectors
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff
from tests.test_centers import box, contact, fly, next_call
from tests.test_ground_flow import TOWER, Session

CS = "Lufthansa four Alfa Bravo"
NORTH, MIDDLE = 123450, 127300  # two sectors close together, like Bremen 125.100 and 119.825


def handed_to_north(eddh, eddm, strict=True):
    sectors = CenterSectors([box("North Radar", "TST1", NORTH, 52.5, 55.0),
                             box("Middle Radar", "TST2", MIDDLE, 51.0, 52.5)])
    s = cleared_for_takeoff(eddh, eddm, centers=sectors)
    s.atc.strict_readback = strict
    fly(s, 2)
    s.say(TOWER, "contact Approach 118.205, Lufthansa 4AB")
    s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    s.say(HAMBURG_APPROACH, "climb flight level 240, direct Amluh, Lufthansa 4AB")
    assert next_call(s, 3, 60)[1] == [contact("North Radar", NORTH)]
    return s


def test_no_second_center_handoff_before_the_pilot_checked_in(eddh, eddm):
    s = handed_to_north(eddh, eddm)
    assert next_call(s, 19, 150) == (None, [])  # in Middle's sector, but the pilot never reached North: no chain
    s.sim.update(com1_khz=HAMBURG_APPROACH)
    assert confirmed(s.say(HAMBURG_APPROACH, "contact North Radar 123.450, Lufthansa 4AB"))
    s.say(NORTH, "North Radar, Lufthansa 4AB, flight level 240")
    s.atc.pending = ()  # North's climb clearance is tested elsewhere
    assert s.tick() == [contact("Middle Radar", MIDDLE)]  # now North hands over


def test_a_missed_handoff_never_locks_strict_readbacks(eddh, eddm):
    # The flight's dead end: a handoff only heard as "is calling you", then every call got "read back first …"
    s = handed_to_north(eddh, eddm)
    s.say(HAMBURG_APPROACH, "contact North Radar 123.450, Lufthansa 4AB")
    s.say(NORTH, "North Radar, Lufthansa 4AB, flight level 240")
    s.atc.pending = ()  # North's climb clearance is tested elsewhere
    s.sim.update(com1_khz=HAMBURG_APPROACH)  # back on the old frequency by mistake: North's handoff is missed
    [missed] = next_call(s, 19, 150)[1]
    assert missed.startswith("(North Radar is calling you on 123.450")
    s.sim.update(com1_khz=MIDDLE)
    [answer] = s.say(MIDDLE, "Middle Radar, Lufthansa 4AB, flight level 240")
    assert "read back first" not in answer


def test_a_late_readback_on_the_new_frequency_counts(eddh, eddm):
    s = handed_to_north(eddh, eddm)
    s.sim.update(com1_khz=NORTH)
    assert s.say(NORTH, "North Radar, Lufthansa 4AB, flight level 240") == [
        "(read back first to Hamburg Approach on 118.205: contact North Radar one two tree decimal four fife zero)"]
    out = s.say(NORTH, "contact North Radar 123.450, Lufthansa 4AB, flight level 240")
    assert "read back first" not in " ".join(out)


def test_the_atis_frequency_is_not_a_center_on_the_other_side_of_the_world(eddh):
    # 124.325 is EDDH ATIS, and in MSFS's data also a Cleveland Center sector
    from atc.airspace.centers import CenterSector
    cleveland = CenterSector("Cleveland Control", "KZOB", 124325, 0, 99999,
                             ((41.0, -82.0), (42.0, -82.0), (42.0, -81.0), (41.0, -81.0)))
    s = Session(eddh, centers=CenterSectors([cleveland]))
    s.tick()
    assert s.atc.station_at(124325) is None


def test_the_read_back_reminder_waits_after_each_try(eddh):
    from tests.test_strict_readback import strict
    from tests.test_ground_flow import GROUND
    s = strict(eddh)
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    s.tick(now=100)
    s.tick(now=115)
    s.say(GROUND, "Lufthansa 4AB")  # a try that isn't the readback
    assert s.tick(now=121) == []  # not 21 s after the instruction: 20 s after the last try
    assert s.tick(now=140) == []
    assert s.tick(now=141) == [f"{CS}, read back"]


def test_being_sent_back_to_read_back_is_not_a_check_in(eddh, eddm):
    # Found while fixing the flight: after "read back first" the check-in was counted, so no Center ever came
    s = cleared_for_takeoff(eddh, eddm)
    s.atc.strict_readback = True
    fly(s, 2)  # Tower: "contact Hamburg Approach"
    s.sim.update(com1_khz=HAMBURG_APPROACH)
    assert s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000")[0].startswith("(read back first")
    assert s.atc.call_next is not None
    s.sim.update(com1_khz=TOWER)
    s.say(TOWER, "contact Approach 118.205, Lufthansa 4AB")
    s.sim.update(com1_khz=HAMBURG_APPROACH)
    assert "radar contact" in s.say(HAMBURG_APPROACH, "Hamburg Approach, Lufthansa 4AB, passing 2000")[0]


# --- speech recognition: what whisper wrote in that flight ------------------------------------------------------------

import pytest  # noqa: E402

from atc.controller.readback import same  # noqa: E402
from atc.intent.parser import parse  # noqa: E402


@pytest.mark.parametrize("heard, kind, items", [
    ("Hammer ground, it turns out, two for one, request, IFR, clearance to Munich, information, IFR.",
     "request_clearance", {}),  # the airline misheard, the flight number there
    ("Humber, ground, love turns out, two for one, request, push and start.", "request_pushback", {}),
    ("Potion start approved, facing north, Lufthansa 2 for 1.", "readback", {"pushback": True}),
    ("Contact Bremen radar, 1199, decimal, 825, Lufthansa, 241.", "readback", {"frequency_khz": 119825}),
    ("Contact Bremen Rada, 1190, decimal, 825, Lufthansa, 241.", "readback", {"frequency_khz": 119825}),
])
def test_misheard_calls_from_the_flight_are_understood(heard, kind, items):
    intent = parse(heard, "DLH241")
    assert intent.addressed_to_us and intent.kind == kind
    assert all(intent.items.get(k) == v for k, v in items.items())


@pytest.mark.parametrize("heard", ["Hamburg Ground, Lufthansa 4AB, Bravo, request taxi.", "DLH4AB bravo request taxi"])
def test_a_letter_repeated_after_our_callsign_is_not_part_of_it(heard):
    # whisper, primed with "Lufthansa 4AB", sometimes writes the last letter again
    assert parse(heard, "DLH4AB").callsign == "DLH4AB"


def test_a_close_spelling_of_the_direct_to_fix_counts():
    assert same("direct", "AMLOU", "AMLUH") and same("direct", "AMLU", "AMLUH")
    assert not same("direct", "AND", "AMLUH") and not same("direct", "DENIX", "AMLUH")


def test_whisper_gets_the_flights_words(eddh, eddm):
    from tests.test_enroute import SIMBRIEF
    from tests.test_ground_flow import GROUND
    s = Session(eddh, plan=SIMBRIEF, destination=eddm)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    context = s.atc.speech_context()
    assert context.startswith("Lufthansa 4AB. Hamburg Ground. ") and "Amluh" not in context  # SID points left out
    assert "Denix" in context and context.endswith("request IFR clearance to Munich, information alfa.")


def test_the_context_reaches_whisper():
    import numpy as np
    from atc.audio.voice import SAMPLE_RATE, WhisperInput

    class Transcriber:
        def transcribe(self, audio, context=""):
            self.context = context
            return "Hamburg Ground, Lufthansa 241, radio check"

    class OneClip:
        clips = [np.full(SAMPLE_RATE, 0.3, dtype=np.float32), None]

        def record(self):
            return self.clips.pop(0)

    transcriber = Transcriber()
    listener = WhisperInput(OneClip(), transcriber)
    listener.context = lambda: "Lufthansa 241. Hamburg Ground."
    assert listener.listen() == "Hamburg Ground, Lufthansa 241, radio check"
    assert transcriber.context == "Lufthansa 241. Hamburg Ground."

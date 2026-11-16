"""C1: the purser's announcements, in the airline's home language first, then English."""
from atc.cabin import Cabin
from tests.test_air_flow import cleared_for_takeoff


def said(events):
    return [(e.station, e.text.split(",")[0]) for e in events]


def test_a_german_airline_speaks_german_then_english():
    cabin = Cabin.for_flight("DLH241", "Munich")
    events = cabin.check("clearance", True, 50, False)
    assert said(events) == [("Kabine", "Meine Damen und Herren"), ("Cabin", "Ladies and gentlemen")]
    assert "Lufthansa Fluges nach München" in events[0].text and "Lufthansa flight to Munich" in events[1].text
    assert cabin.check("clearance", True, 50, False) == []  # once


def test_other_airlines_english_only_and_cargo_silent():
    assert said(Cabin.for_flight("BAW12", "London").announce("boarding")) == [("Cabin", "Ladies and gentlemen")]
    assert "this British Airways flight to London" in Cabin.for_flight("BAW12", "London").announce("boarding")[0].text
    assert Cabin.for_flight("BOX512", "Leipzig").announce("boarding") == []
    private = Cabin.for_flight("DEABC", None).announce("arrival")[0].text
    assert "welcome to your destination" in private and "Thank you for flying with us" in private


def test_crew_calls_stay_english():
    assert said(Cabin.for_flight("DLH241", "Munich").announce("takeoff")) == [("Cabin", "Cabin crew")]


def test_the_moments_of_a_flight_in_order():
    cabin = Cabin.for_flight("DLH241", "Munich")
    moments = []
    for phase, ground, alt, descent in [("clearance", True, 50, False), ("pushback", True, 50, False),
                                        ("takeoff", True, 50, False), ("climb", False, 12000, False),
                                        ("enroute", False, 35000, True), ("final", False, 2000, True),
                                        ("taxi_in", True, 1500, True)]:
        before = set(cabin.said)
        cabin.check(phase, ground, alt, descent)
        moments += sorted(cabin.said - before)
    assert moments == ["boarding", "doors", "takeoff", "climb", "descent", "landing", "arrival"]


def test_a_late_start_never_welcomes_after_the_descent():
    cabin = Cabin.for_flight("DLH241", "Munich")
    cabin.said |= {"boarding", "doors", "takeoff", "climb"}
    assert said(cabin.check("arrival", False, 9000, True))[0] == ("Kabine", "Meine Damen und Herren")
    assert cabin.said >= {"descent"}


def test_with_gsx_the_doors_wait_for_boarding():
    cabin = Cabin.for_flight("DLH241", "Munich")
    cabin.said.add("boarding")
    assert cabin.check("pushback", True, 50, False, boarding_done=False) == []
    assert cabin.check("clearance", True, 50, False, boarding_done=True)  # GSX: boarding completed


def test_announcements_in_the_live_loop(eddh, eddm):
    from atc.events import Collector
    from atc.runtime import LiveSession

    s = cleared_for_takeoff(eddh, eddm)
    sink = Collector()
    LiveSession(s.sim, sink, s.atc, cabin=Cabin.for_flight("DLH4AB", "Munich")).step()
    assert [e.text for e in sink.events if e.kind == "cabin"] == ["Cabin crew, seats for take-off."]  # cleared


def test_the_cabin_voice_chimes_once_and_has_no_radio_effect():
    import numpy as np

    from atc.audio.piper_tts import PiperOutput

    class Voice:
        class config:
            num_speakers, sample_rate = 10, 1000

        def synthesize(self, text, cfg):
            class Chunk:
                audio_float_array = np.ones(100, np.float32)
            return [Chunk()]

    played = []
    out = PiperOutput.__new__(PiperOutput)
    out.voice, out.effect, out.length_scale = Voice(), lambda *a: (_ for _ in ()).throw(AssertionError()), None
    out.cabin_voices, out.cabin_loading, out.last_cabin = {"Kabine": Voice()}, set(), 0.0
    out.play = lambda samples, rate: played.append(len(samples))
    out._speak("Meine Damen und Herren", "Kabine")
    out._speak("Ladies and gentlemen", "Cabin")
    from atc.audio.piper_tts import chime

    assert played[0] - played[1] == len(chime(1000))  # chime first, not again right after
    assert played[1] > 100  # the cabin's echo makes it a little longer


def test_the_cabin_sound():
    import numpy as np

    from atc.audio.cabin_sound import cabin_effect

    rate = 16000
    t = np.arange(rate) / rate
    voice = (0.5 * np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    out = cabin_effect(voice, rate, seed=3)
    assert out.dtype == np.float32 and len(out) > len(voice) and np.max(np.abs(out)) <= 1
    assert np.array_equal(out, cabin_effect(voice, rate, seed=3))  # the same text sounds the same
    spectrum = np.abs(np.fft.rfft(out[: len(voice)]))
    freqs = np.fft.rfftfreq(len(voice), 1 / rate)
    hum, tone = (spectrum[np.argmin(np.abs(freqs - f))] for f in (50, 1000))
    assert hum < tone / 20  # the ceiling loudspeakers have no deep bass
    assert np.max(np.abs(out)) <= 0.41  # through the door: quieter than the radio


def test_through_the_cockpit_door_the_highs_are_gone():
    import numpy as np

    from atc.audio.cabin_sound import wall

    rate = 16000
    t = np.arange(rate) / rate
    low, high = np.sin(2 * np.pi * 400 * t), np.sin(2 * np.pi * 4000 * t)
    assert np.max(np.abs(wall(low, rate))) > 0.95 and np.max(np.abs(wall(high, rate))) < 0.1


def test_with_gsx_even_the_welcome_waits_for_its_boarding():
    cabin = Cabin.for_flight("DLH241", "Munich")
    assert cabin.check("clearance", True, 50, False, boarding_done=False) == []
    assert cabin.check("cleared", True, 50, False, boarding_done=True)[0].text.startswith("Meine Damen und Herren, "
                                                                                        "herzlich willkommen")
    assert "Türen sind geschlossen" in cabin.check("cleared", True, 50, False, boarding_done=True)[0].text


def test_never_right_on_top_of_the_radio():
    from atc.cabin import DELAY_S, QUIET_S

    cabin = Cabin.for_flight("DLH241", "Munich")
    assert cabin.check("clearance", True, 50, False, now=100, last_radio=None) == []  # just due
    assert cabin.check("clearance", True, 50, False, now=100 + DELAY_S - 1, last_radio=None) == []
    late = 100 + DELAY_S
    assert cabin.check("clearance", True, 50, False, now=late, last_radio=late - 2) == []  # ATC just spoke
    assert cabin.check("clearance", True, 50, False, now=late + QUIET_S - 2, last_radio=late - 2)


def test_the_crew_call_for_takeoff_does_not_wait_long():
    cabin = Cabin.for_flight("DLH241", "Munich")
    cabin.said |= {"boarding", "doors"}
    assert said(cabin.check("takeoff", True, 50, False, now=10, last_radio=6)) == [("Cabin", "Cabin crew")]


def test_the_live_loop_waits_for_a_quiet_radio(eddh, eddm):
    from atc.events import Collector
    from atc.runtime import LiveSession
    from tests.test_ground_flow import GROUND, Session

    s = Session(eddh, destination=eddm)
    sink, clock = Collector(), [0.0]
    live = LiveSession(s.sim, sink, s.atc, clock=lambda: clock[0], cabin=Cabin.for_flight("DLH4AB", "Munich"))
    s.sim.update(com1_khz=GROUND)
    live.step("Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich")  # ATC answers: the radio is busy
    for t in range(1, 10):
        clock[0] = t
        live.step()
        assert not [e for e in sink.events if e.kind == "cabin"], t  # waits for 10 s of quiet radio
    clock[0] = 10
    live.step()
    assert [e for e in sink.events if e.kind == "cabin"]

"""Push-to-talk, whisper and text-to-speech without microphone, model or speakers."""
import io
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from atc.airport.json_data import JsonAirportData
from atc.audio.tts import SapiOutput, TtsError, Voice, choose_voice, sapi_rate
from atc.audio.voice import (AVIATION_PROMPT, SAMPLE_RATE, MicRecorder, WhisperInput, WhisperTranscriber, load_wav,
                             save_wav)
from atc.config import ROOT
from atc.events import ConsoleSink
from atc.main import main
from atc.runtime import run_live
from atc.weather.source import StaticWeather
from tests.test_ground_flow import TOWER, Session

SPEECH = np.full(SAMPLE_RATE, 0.3, dtype=np.float32)  # 1 s, loud enough


class Recordings:
    def __init__(self, *clips):
        self.clips = list(clips)

    def record(self):
        return self.clips.pop(0)


class Heard:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0

    def transcribe(self, audio):
        self.calls += 1
        return self.texts.pop(0)


def whisper_input(clips, texts, **kw):
    shown = []
    heard = Heard(*texts)
    w = WhisperInput(Recordings(*clips), heard, clock=iter([0, 2.1] * 10).__next__, **kw)
    w.attach(ConsoleSink(None, shown.append))
    return w, shown, heard


# --- push-to-talk + whisper -----------------------------------------------------------------------------------

def test_a_transmission_is_shown_and_returned():
    w, shown, _ = whisper_input([SPEECH], ["Hamburg Ground, Lufthansa 4AB, request taxi."])
    assert w.listen() == "Hamburg Ground, Lufthansa 4AB, request taxi."
    assert shown == ["       (heard in 2.1 s: Hamburg Ground, Lufthansa 4AB, request taxi.)"]


def test_a_tap_on_the_key_is_not_transcribed():
    w, shown, heard = whisper_input([SPEECH[:1000], SPEECH], ["Lufthansa 4AB, radio check"])
    assert w.listen() == "Lufthansa 4AB, radio check"
    assert heard.calls == 1 and len(shown) == 1


def test_nothing_heard_waits_for_the_next_transmission():
    w, shown, _ = whisper_input([SPEECH, SPEECH], ["", "Lufthansa 4AB, radio check"])
    assert w.listen() == "Lufthansa 4AB, radio check"
    assert shown[0] == "       (heard nothing in 1.0 s of audio: say again)"


def test_words_only_from_the_prompt_are_dropped():
    # Milestone 0: two seconds of room noise came back as "Clearance, ground," without the VAD
    w, shown, _ = whisper_input([SPEECH, SPEECH], ["Clearance, ground,", "Lufthansa 4AB, radio check"])
    assert w.listen() == "Lufthansa 4AB, radio check"
    assert shown[1].startswith("       (ignored: only words from the whisper prompt")



def test_a_broken_whisper_prompt_still_hears_the_transmission():
    """2026-11-18: building the prompt raised (a KeyError in the suggestion), which ended push-to-talk."""
    w, shown, heard = whisper_input([SPEECH], ["Lufthansa 4AB, radio check"])
    w.context = lambda: {}["boom"]
    assert w.listen() == "Lufthansa 4AB, radio check" and heard.calls == 1


class FailsOnce(Heard):
    def transcribe(self, audio):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("out of memory")
        return self.texts.pop(0)


def test_a_failed_transcription_says_say_again_and_listens_on():
    w = WhisperInput(Recordings(SPEECH, SPEECH), FailsOnce("Lufthansa 4AB, radio check"),
                     clock=iter([0, 2.1] * 10).__next__)
    shown = []
    w.attach(ConsoleSink(None, shown.append))
    assert w.listen() == "Lufthansa 4AB, radio check"
    assert "could not transcribe that transmission (out of memory): say again" in shown[0]

def test_a_nearly_silent_recording_hints_at_the_microphone():
    w, shown, _ = whisper_input([SPEECH * 0.01], ["Lufthansa 4AB, radio check"])
    w.listen()
    assert "wrong microphone?" in shown[0]


def test_recordings_can_be_kept(tmp_path):
    w, _, _ = whisper_input([SPEECH], ["Lufthansa 4AB, radio check"], save_dir=tmp_path)
    w.listen()
    [path] = tmp_path.glob("*.wav")
    assert path.name == "001.wav"
    assert load_wav(path) == pytest.approx(SPEECH, abs=1e-4)


def test_the_prompt_has_no_expected_names():
    # With names in the prompt, whisper returned the prompt instead of what the pilot said (Milestone 0)
    for name in ("Lufthansa", "Hamburg", "Munich", "DLH", "4AB"):
        assert name not in AVIATION_PROMPT
    assert "Juliett" in AVIATION_PROMPT and "niner" in AVIATION_PROMPT


class FakeModel:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs, self.calls = args, kwargs, []

    def transcribe(self, audio, **options):
        self.calls.append(options)
        return iter([SimpleNamespace(text=" Lufthansa 4AB, "), SimpleNamespace(text="radio check. ")]), None


def test_whisper_settings_from_the_spikes():
    t = WhisperTranscriber("small.en", "cpu", 5, load=FakeModel)
    assert t.model.args == ("small.en",) and t.model.kwargs == {"device": "cpu", "compute_type": "int8"}
    assert len(t.model.calls) == 1  # warm-up, so a broken setup fails at startup
    assert t.transcribe(SPEECH) == "Lufthansa 4AB, radio check."
    assert t.model.calls[1] == {"language": "en", "beam_size": 5, "vad_filter": True,
                                "initial_prompt": AVIATION_PROMPT}


def test_cuda_failure_says_what_to_do():
    class Broken(FakeModel):
        def transcribe(self, audio, **options):
            raise RuntimeError("Library cublas64_12.dll is not found")

    with pytest.raises(RuntimeError, match='cuBLAS 12 .* device = "cpu"'):
        WhisperTranscriber("small.en", "cuda", 5, load=Broken)


def test_unknown_push_to_talk_key():
    with pytest.raises(ValueError, match="unknown push-to-talk binding 'space'"):
        MicRecorder("space")


# --- text-to-speech ---------------------------------------------------------------------------------------------

VOICES = [Voice("Microsoft Hedda Desktop - German", "hedda"),
          Voice("Microsoft Zira Desktop - English (United States)", "zira")]


class FakeEngine:
    """Like SAPI: speak() blocks until the sentence is spoken."""

    def __init__(self, fail_on: str | None = None):
        self.voice, self.rate, self.spoken, self.fail_on = None, None, [], fail_on

    def voices(self):
        return VOICES

    def use(self, voice, rate):
        self.voice, self.rate = voice.token, rate

    def speak(self, text, volume=1.0):
        if text == self.fail_on:
            raise OSError("audio device lost")
        self.spoken.append(text)


def test_an_english_voice_is_chosen_not_the_german_default():
    assert choose_voice(VOICES, "zira").token == "zira"
    with pytest.raises(TtsError, match="English voices: Microsoft Zira"):
        choose_voice(VOICES, "Hedda")  # installed, but not English


def test_every_transmission_is_spoken_in_order_in_the_background():
    # pyttsx3 spoke only the first one: ATC was silent in the app from the second transmission on (F1)
    engine, shown = FakeEngine(), []
    out = SapiOutput("Zira", rate=180, show=shown.append, make_engine=lambda: engine)
    assert out.voice_name.startswith("Microsoft Zira")
    texts = ["Lufthansa four Alfa Bravo, radio check, read you fife",
             "Lufthansa four Alfa Bravo, contact Hamburg Tower", "Lufthansa four Alfa Bravo, readback correct"]
    for text in texts:
        out.say(text)
    out.wait()
    assert engine.spoken == texts
    assert shown[0] == "ATC:   Lufthansa four Alfa Bravo, radio check, read you fife"
    assert engine.voice == "zira" and engine.rate == 180
    out.close()


def test_a_failed_transmission_is_reported_and_the_next_one_still_spoken():
    engine, reports = FakeEngine(fail_on="first"), []
    out = SapiOutput("Zira", show=lambda text: None, make_engine=lambda: engine, report=reports.append)
    out.say("first")
    out.say("second")
    out.wait()
    assert reports == ["ATC voice failed: audio device lost"] and engine.spoken == ["second"]
    out.close()


def test_words_per_minute_become_sapi_rates():
    assert [sapi_rate(wpm) for wpm in (200, 180, 260, 600, 40)] == [0, -1, 2, 10, -10]


def test_engine_failure_is_reported_at_startup():
    def broken():
        raise OSError("SAPI not available")

    with pytest.raises(TtsError, match="text-to-speech failed: SAPI not available"):
        SapiOutput(make_engine=broken)


# --- wiring -----------------------------------------------------------------------------------------------------

class Lines:
    def __init__(self, *lines):
        self.lines = list(lines)

    def listen(self):
        return self.lines.pop(0) if self.lines else None


class NeverSpeaks:
    def listen(self):
        threading.Event().wait()



class RaisesOnce:
    """An input whose first listen fails (a bug behind the transmission), then hears the next one."""
    def __init__(self, text):
        self.calls, self.text = 0, text

    def listen(self):
        self.calls += 1
        if self.calls == 1:
            raise KeyError("hold_position")
        if self.calls == 2:
            return self.text
        threading.Event().wait()

class Spoken:
    def __init__(self):
        self.lines = []

    def say(self, text, station=None, kind="atc"):
        self.lines.append(text)


def test_the_session_ends_with_the_keyboard_even_while_push_to_talk_waits(eddh):
    s, out = Session(eddh), Spoken()
    s.sim.update(com1_khz=TOWER)
    run_live(s.sim, [NeverSpeaks(), Lines("Hamburg Tower, Lufthansa 4AB, radio check")],
             ConsoleSink(out, lambda text: None), s.atc, tick_s=0.01)
    assert out.lines == ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]


def test_main_without_text_uses_the_voice(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    out = Spoken()
    main(["--nosim", "--from", "EDDH", "--callsign", "DLH4AB"],
         weather=StaticWeather({}), airports=[JsonAirportData(ROOT / "data" / "airports")],
         voice=lambda config: ([Lines("/com 121.280", "Hamburg Tower, Lufthansa 4AB, radio check")], out))
    assert "Push-to-talk: hold [Right Ctrl] while you speak." in capsys.readouterr().out
    assert out.lines == ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]


class ThreadBoundEngine(FakeEngine):
    """Records the thread it is released in: SAPI's COM object crashes the process if another thread frees it."""
    released_in: list = []

    def __init__(self):
        super().__init__()
        self.made_in = threading.get_ident()

    def __del__(self):
        ThreadBoundEngine.released_in.append(threading.get_ident() == self.made_in)


@pytest.mark.parametrize("voice", ["Zira", "silent-test-voice"])  # a normal end, and a voice that doesn't exist
def test_the_engine_is_released_in_the_speech_thread(voice):
    import gc

    ThreadBoundEngine.released_in = []
    try:
        out = SapiOutput(voice, show=lambda text: None, make_engine=ThreadBoundEngine)
        out.close()
        out.thread.join(5)
    except TtsError:
        pass
    gc.collect()
    assert ThreadBoundEngine.released_in == [True]



def test_push_to_talk_survives_a_failed_transmission(eddh, monkeypatch, capsys):
    """2026-11-18: one exception in the push-to-talk thread ended it, and the pilot could no longer transmit."""
    import atc.runtime
    monkeypatch.setattr(atc.runtime, "INPUT_RETRY_S", 0)
    s, out = Session(eddh), Spoken()
    s.sim.update(com1_khz=TOWER)
    stop = threading.Event()
    sink = ConsoleSink(out, lambda text: None)
    original = sink.emit
    sink.emit = lambda event: (original(event), out.lines and stop.set())
    threading.Timer(5, stop.set).start()  # without the fix: fail, don't hang
    run_live(s.sim, [RaisesOnce("Hamburg Tower, Lufthansa 4AB, radio check")], sink, s.atc, tick_s=0.01, stop=stop)
    assert out.lines == ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]
    assert "KeyError" in capsys.readouterr().err  # in app.log

"""The words while push-to-talk is held (2026-11-18): a live pass every so often, the full pass after release."""
import threading
import time

import numpy as np

from atc.audio.voice import IDLE, SAMPLE_RATE, SPEAKING, TRANSCRIBING, WhisperInput, WhisperTranscriber
from tests.test_voice import SPEECH


class HeldRecorder:
    """Records while `held` is set; so_far() gives the audio so far, as MicRecorder does."""

    def __init__(self):
        self.audio = None
        self.release = threading.Event()

    def so_far(self):
        return self.audio

    def record(self):
        self.audio = SPEECH.copy()  # 1 s: above the minimum even when released at once
        for _ in range(40):  # up to 2 s of "speaking"
            self.audio = np.concatenate([self.audio, SPEECH[:SAMPLE_RATE // 20]])
            if self.release.wait(0.05):
                break
        audio, self.audio = self.audio, None
        return audio


class Words:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, context="", fast=False):
        self.calls.append((audio.size, fast))
        return "Hamburg Ground" if fast else "Hamburg Ground, DEABC, request taxi"


def wait_for(check, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_words_while_speaking_then_the_full_pass():
    recorder, words, shown = HeldRecorder(), Words(), []
    listener = WhisperInput(recorder, words)
    listener.live = lambda text, state: shown.append((text, state))
    listener.live_every = 0.1
    result = []
    t = threading.Thread(target=lambda: result.append(listener.listen()))
    t.start()
    assert wait_for(lambda: ("Hamburg Ground", SPEAKING) in shown)
    recorder.release.set()
    t.join(5)
    listener.close()
    assert result == ["Hamburg Ground, DEABC, request taxi"]
    assert shown[-2:] == [("Hamburg Ground", TRANSCRIBING), ("", IDLE)]  # the live words stay until the full text
    assert words.calls[-1][1] is False  # the last one the full pass (beam as set)
    assert any(fast for _, fast in words.calls)


def test_without_live_no_worker_and_no_fast_pass():
    recorder, words = HeldRecorder(), Words()
    recorder.release.set()
    listener = WhisperInput(recorder, words)
    assert listener.listen() == "Hamburg Ground, DEABC, request taxi"
    assert listener.worker is None and [fast for _, fast in words.calls] == [False]


def test_a_failing_window_never_stops_push_to_talk():
    recorder, words = HeldRecorder(), Words()
    recorder.release.set()
    listener = WhisperInput(recorder, words)
    listener.live = lambda text, state: 1 / 0
    assert listener.listen() == "Hamburg Ground, DEABC, request taxi"
    listener.close()


def test_the_fast_pass_beam_one():
    seen = {}

    class Model:
        def transcribe(self, audio, **options):
            seen.update(options)
            return [], None

    t = WhisperTranscriber("tiny.en", "cpu", 5, load=lambda *a, **k: Model())
    t.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), fast=True)
    assert seen["beam_size"] == 1
    t.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
    assert seen["beam_size"] == 5


def test_the_setting():
    from atc.config import WhisperConfig
    from atc.settings_file import EDITABLE

    assert WhisperConfig().live_text is True and EDITABLE["whisper.live_text"] == ("bool", None)


def test_listening_shows_as_soon_as_the_key_is_down():
    """The user (2026-11-19): nothing showed while speaking, only "recognising" after release. A live pass takes
    1.5-2 s on the user's PC, so the window now says "speaking" (Listening …) the moment push-to-talk is held."""

    class Slow(Words):
        def transcribe(self, audio, context="", fast=False):
            if fast:
                time.sleep(5)  # the first words come long after the key is released
            return super().transcribe(audio, context, fast)

    recorder, shown = HeldRecorder(), []
    listener = WhisperInput(recorder, Slow())
    listener.live = lambda text, state: shown.append((text, state))
    threading.Thread(target=listener.listen, daemon=True).start()
    assert wait_for(lambda: ("", SPEAKING) in shown, seconds=0.5)
    assert recorder.so_far() is not None  # still held
    recorder.release.set()
    listener.close()


def test_the_live_model_setting():
    """The live words come from base.en by default (2026-11-19): three times faster than small.en."""
    from atc.config import WhisperConfig

    assert (WhisperConfig().model, WhisperConfig().live_model) == ("small.en", "base.en")


def test_live_passes_to_the_live_model_the_full_pass_to_the_main_one():
    recorder, main, fast = HeldRecorder(), Words(), Words()
    listener = WhisperInput(recorder, main)
    listener.live_transcriber = fast
    listener.live = lambda text, state: None
    listener.live_every = 0.1
    t = threading.Thread(target=listener.listen)
    t.start()
    assert wait_for(lambda: fast.calls)
    recorder.release.set()
    t.join(5)
    listener.close()
    assert all(f for _, f in fast.calls) and [f for _, f in main.calls] == [False]


def test_the_full_pass_never_waits_for_a_live_pass_of_the_other_model():
    started = threading.Event()

    class Stuck(Words):
        def transcribe(self, audio, context="", fast=False):
            started.set()
            time.sleep(3)
            return "Hamburg"

    listener = WhisperInput(HeldRecorder(), Words())
    listener.live_transcriber = Stuck()
    threading.Thread(target=listener._transcribe, args=(SPEECH, True), daemon=True).start()
    assert started.wait(1)
    begin = time.monotonic()
    assert listener._transcribe(SPEECH) == "Hamburg Ground, DEABC, request taxi"
    assert time.monotonic() - begin < 1


def test_loading_the_live_model(monkeypatch):
    from dataclasses import replace

    from atc.audio import setup
    from atc.audio.setup import VoiceUnavailable
    from atc.config import Config

    main, messages, loaded = object(), [], []
    monkeypatch.setattr(setup, "ensure_model", lambda name, progress: f"models/{name}")
    monkeypatch.setattr(setup, "WhisperTranscriber", lambda path, device, beam: loaded.append(path) or "live")
    config = Config()
    assert setup.load_live_transcriber(config, messages.append, main) == "live" and loaded == ["models/base.en"]
    # The same model, or live text off: no second model
    same = replace(config, whisper=replace(config.whisper, live_model="small.en"))
    off = replace(config, whisper=replace(config.whisper, live_text=False))
    none = replace(config, whisper=replace(config.whisper, live_model=""))
    assert all(setup.load_live_transcriber(c, messages.append, main) is main for c in (same, off, none))
    assert loaded == ["models/base.en"]

    def offline(name, progress):
        raise VoiceUnavailable("could not download the speech model base.en (no internet)")

    monkeypatch.setattr(setup, "ensure_model", offline)
    assert setup.load_live_transcriber(config, messages.append, main) is main  # slower live words, but some
    assert messages[-1].startswith("Live text uses small.en (base.en could not be loaded")

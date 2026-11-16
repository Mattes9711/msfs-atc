"""Getting speech ready (D3): the model download with progress, push-to-talk that arrives late, and voice in the app."""
import json
import threading
import time

import numpy as np
import pytest

from atc.app.server import App, DeferredInput
from atc.audio import setup
from atc.audio.voice import MicRecorder, WhisperInput
from atc.config import CabinConfig, Config
from atc.events import Collector
from tests.test_app import INJECT, PLAN


class Response:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, n=-1):
        data, self.body = (self.body, b"") if n < 0 else (self.body[:n], self.body[n:])
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHub:
    """Stands in for huggingface.co: the file list, then each file."""

    FILES = {"config.json": b"{}", "model.bin": b"x" * 3_000_000, "tokenizer.json": b"{}", "vocabulary.txt": b"a",
             "README.md": b"not needed"}

    def __init__(self, fail=False):
        self.fail, self.urls = fail, []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("no internet")
        if "/api/models/" in url:
            return Response(json.dumps({"siblings": [{"rfilename": n} for n in self.FILES]}).encode())
        return Response(self.FILES[url.rsplit("/", 1)[1]])


NO_CABIN = Config(cabin=CabinConfig(announcements=False))  # only ATC's voice is checked here

def no_cache(model):
    return None


def test_first_start_downloads_with_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PROGRESS_EVERY_S", 0)
    monkeypatch.setattr(setup, "CHUNK", 1_000_000)
    hub, messages = FakeHub(), []
    path = setup.ensure_model("small.en", messages.append, tmp_path, hub, no_cache)
    assert path == str(tmp_path / "small.en")
    assert sorted(p.name for p in (tmp_path / "small.en").iterdir()) == [
        ".complete", "config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]  # no README, no .part
    assert hub.urls[0] == "https://huggingface.co/api/models/Systran/faster-whisper-small.en"
    assert messages[0] == "Downloading the speech recognition model small.en (about 464 MB) - only on the first start"
    assert "Speech model: 3 of 464 MB" in messages
    assert messages[-1] == "Speech model downloaded"


def test_downloaded_model_is_used_without_network(tmp_path):
    setup.ensure_model("small.en", lambda m: None, tmp_path, FakeHub(), no_cache)
    offline = FakeHub(fail=True)
    assert setup.ensure_model("small.en", lambda m: None, tmp_path, offline, no_cache) == str(tmp_path / "small.en")
    assert offline.urls == []


def test_interrupted_download_starts_again(tmp_path):
    (tmp_path / "small.en").mkdir()
    (tmp_path / "small.en" / "model.bin.part").write_bytes(b"half")  # no .complete marker
    hub = FakeHub()
    setup.ensure_model("small.en", lambda m: None, tmp_path, hub, no_cache)
    assert (tmp_path / "small.en" / ".complete").exists() and len(hub.urls) == 5


def test_model_from_the_default_hugging_face_cache_is_reused(tmp_path):
    # The developer's model from the spikes lives there: no second 464 MB download
    hub = FakeHub()
    assert setup.ensure_model("small.en", print, tmp_path, hub, lambda m: "hf-cache/small.en") == "hf-cache/small.en"
    assert hub.urls == []


def test_cache_lookup_asks_only_for_the_model_files(monkeypatch):
    # Found live: without the file list, huggingface_hub called the cached model incomplete (no README.md)
    calls = []
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda repo, **kw: calls.append((repo, kw)) or "cached")
    assert setup.in_huggingface_cache("small.en") == "cached"
    assert calls == [("Systran/faster-whisper-small.en",
                      {"local_files_only": True, "allow_patterns": setup.CACHE_PATTERNS})]


def test_failed_download_says_typing_still_works(tmp_path):
    with pytest.raises(setup.VoiceUnavailable, match="no internet.*typing still works"):
        setup.ensure_model("small.en", lambda m: None, tmp_path, FakeHub(fail=True), no_cache)


def test_a_model_folder_from_the_settings_is_used_as_is(tmp_path):
    assert setup.ensure_model(str(tmp_path), print, tmp_path, FakeHub(fail=True), no_cache) == str(tmp_path)


# --- push-to-talk that arrives late, and stops ------------------------------------------------------------

class OneLine:
    def __init__(self, text):
        self.text, self.closed, self.sink = text, False, None

    def attach(self, sink):
        self.sink = sink

    def close(self):
        self.closed = True

    def listen(self):
        text, self.text = self.text, None
        if text is None:
            threading.Event().wait()
        return text


def test_deferred_input_waits_until_speech_is_ready():
    deferred, got = DeferredInput(), []
    thread = threading.Thread(target=lambda: got.append(deferred.listen()), daemon=True)
    thread.start()
    thread.join(0.1)
    assert thread.is_alive()  # nothing yet: still loading
    sink = Collector()
    deferred.attach(sink)
    source = OneLine("Lufthansa 4AB, radio check")
    deferred.ready(source)
    thread.join(1)
    assert got == ["Lufthansa 4AB, radio check"] and source.sink is sink


def test_closing_before_speech_is_ready_ends_listening_and_closes_the_late_source():
    deferred = DeferredInput()
    deferred.close()
    assert deferred.listen() is None
    source = OneLine("too late")
    deferred.ready(source)
    assert source.closed


def test_closed_recorder_stops_waiting_for_the_key():
    recorder = MicRecorder("right ctrl", is_down=lambda vk: False)
    threading.Timer(0.05, recorder.close).start()
    assert recorder.record() is None
    assert WhisperInput(recorder, transcriber=None).listen() is None


def test_microphone_error_is_shown_and_listening_goes_on(monkeypatch):
    monkeypatch.setattr("atc.audio.voice.time.sleep", lambda s: None)

    class Flaky:
        def __init__(self):
            self.calls = 0

        def record(self):
            self.calls += 1
            if self.calls == 1:
                raise OSError("Error opening InputStream: device unavailable")
            return np.full(16000, 0.3, dtype=np.float32)

    class Heard:
        def transcribe(self, audio):
            return "Lufthansa 4AB, radio check"

    w, log = WhisperInput(Flaky(), Heard(), clock=lambda: 0), Collector()
    w.attach(log)
    assert w.listen() == "Lufthansa 4AB, radio check"
    assert log.events[0].text.startswith("microphone error: Error opening InputStream")


# --- voice in the app window ------------------------------------------------------------------------------

def wait_for(app, text, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(text in e.text for e in app.log.events):
            return
        time.sleep(0.02)
    raise AssertionError(f"no event with {text!r}: {[e.text for e in app.log.events]}")


def test_without_voice_the_flight_goes_on_with_typing():
    app = App(Config(), INJECT)  # load_voice is blocked in tests: like a PC without microphone
    app.start(PLAN)
    wait_for(app, "Voice is off: no microphone or speakers in tests. Typing still works.")
    assert app.running
    app.stop()


def test_push_to_talk_and_atc_voice_in_the_app(monkeypatch):
    spoken = []

    class Tts:
        voice_name = "Fake Zira"

        def say(self, text, station=None, kind="atc"):
            spoken.append(text)

    class TunedFirst(OneLine):
        def listen(self):  # a pilot tunes Tower before speaking
            if self.text:
                wait_for(app, "COM1 121.280: Hamburg Tower")
            return super().listen()

    loads = []
    monkeypatch.setattr("atc.app.server.load_voice", lambda config, progress: loads.append(1) or "model")
    monkeypatch.setattr("atc.app.server.load_tts", lambda config, report, progress: loads.append(2) or Tts())
    monkeypatch.setattr(setup, "make_whisper_input", lambda config, transcriber: TunedFirst(
        "Hamburg Tower, Lufthansa 4AB, radio check"))
    app = App(NO_CABIN, INJECT)
    app.start({**PLAN, "nosim": True})
    app.say("/com 121.280")
    wait_for(app, "Push-to-talk ready: hold [Right Ctrl] while you speak")
    wait_for(app, "Hamburg Tower, read you fife")
    assert spoken == ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]
    app.stop()
    app.start(PLAN)  # second flight: the model is not loaded again
    wait_for(app, "Push-to-talk ready")
    assert loads == [2, 1]
    app.stop()


def test_atc_speaks_even_when_speech_recognition_is_off(monkeypatch):
    # The voice used to be made only after the whisper model had loaded: no model, no ATC voice
    spoken = []

    class Tts:
        voice_name = "Fake Zira"

        def say(self, text, station=None, kind="atc"):
            spoken.append(text)

    monkeypatch.setattr("atc.app.server.load_tts", lambda config, report, progress: Tts())
    app = App(NO_CABIN, INJECT)  # load_voice is still blocked: no speech recognition
    app.start(PLAN)
    wait_for(app, "Voice is off")
    app.say("/com 121.280")
    app.say("Hamburg Tower, Lufthansa 4AB, radio check")
    wait_for(app, "Hamburg Tower, read you fife")
    assert spoken == ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]
    assert any(e.text == "ATC voice: Fake Zira" for e in app.log.events)
    app.stop()

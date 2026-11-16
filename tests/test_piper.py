"""Piper as the ATC voice (V1): a speaker per controller, the first-start download and the fallback to Windows.
No model, no sound card: the voice, the download and the playback are fakes."""
import io
from types import SimpleNamespace

import numpy as np
import pytest

from atc.audio import setup
from atc.audio.piper_tts import VOICE, PiperOutput, ensure_voice, speaker_for
from atc.config import Config, TtsConfig


class FakeVoice:
    config = SimpleNamespace(num_speakers=904, sample_rate=22050)

    def __init__(self):
        self.calls = []

    def synthesize(self, text, syn_config):
        self.calls.append((text, syn_config.speaker_id, syn_config.length_scale))
        yield SimpleNamespace(audio_float_array=np.zeros(100, dtype=np.float32))
        yield SimpleNamespace(audio_float_array=np.ones(50, dtype=np.float32))


def piper(rate=None):
    voice, played = FakeVoice(), []
    out = PiperOutput("voice.onnx", rate, show=lambda text: None, load=lambda model: voice,
                      play=lambda samples, sr: played.append((len(samples), sr)))
    return out, voice, played


def test_each_controller_has_its_own_speaker_and_keeps_it():
    out, voice, played = piper()
    out.say("Lufthansa four Alfa Bravo, cleared to Munich", "Hamburg Ground")
    out.say("Lufthansa four Alfa Bravo, cleared for takeoff", "Hamburg Tower")
    out.say("Lufthansa four Alfa Bravo, readback correct", "Hamburg Ground")
    out.wait()
    ground, tower, ground_again = (speaker for _, speaker, _ in voice.calls)
    assert ground != tower and ground == ground_again
    assert played == [(150, 22050)] * 3  # the chunks of one transmission are played as one
    assert out.voice_name == f"Piper {VOICE} (904 speakers)"
    out.close()


def test_speakers_are_the_same_on_every_start():
    # Python's hash() of a string changes per process; the speaker must not
    assert speaker_for("Hamburg Ground", 904) == speaker_for("hamburg ground", 904) == 894
    assert speaker_for(None, 904) == speaker_for("ATC", 904)


def test_the_rate_setting_changes_the_speed():
    out, voice, _ = piper(rate=200)
    out.say("roger", "Hamburg Ground")
    out.wait()
    assert voice.calls[0][2] == pytest.approx(0.85)  # faster than Piper's ~170 words per minute
    out.close()


class FakeHub:
    def __init__(self):
        self.urls = []

    def __call__(self, url, timeout=30):
        self.urls.append(url)
        return io.BytesIO(b"{}" if url.endswith(".json") else b"\0" * 3_000_000)


def test_the_voice_is_downloaded_once(tmp_path):
    hub, messages = FakeHub(), []
    model = ensure_voice(messages.append, tmp_path, hub)
    assert model == tmp_path / "piper" / VOICE / f"{VOICE}.onnx" and model.stat().st_size == 3_000_000
    assert messages[0] == f"Downloading the ATC voice {VOICE} (about 79 MB) - only on the first start"
    assert messages[-1] == "ATC voice downloaded"
    assert [u.rsplit("/", 1)[1] for u in hub.urls] == [f"{VOICE}.onnx.json", f"{VOICE}.onnx"]
    assert hub.urls[0].startswith("https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/")
    ensure_voice(messages.append, tmp_path, hub)
    assert len(hub.urls) == 2  # not again


def test_no_internet_on_the_first_start_falls_back_to_the_windows_voice(monkeypatch):
    def offline(url, timeout=30):
        raise OSError("no connection")

    monkeypatch.setattr(setup, "_http", offline)
    made, messages = [], []
    monkeypatch.setattr(setup, "SapiOutput", lambda *args, **kwargs: made.append(args) or "windows voice")
    assert setup.make_tts(Config(), progress=messages.append) == "windows voice"
    assert messages[-1] == "Piper voice is off (could not download the ATC voice (no connection)); using the Windows voice"
    assert made == [("Zira", None)]


def test_sapi_can_be_chosen_and_typos_are_caught(monkeypatch):
    monkeypatch.setattr(setup, "SapiOutput", lambda *args, **kwargs: "windows voice")
    assert setup.make_tts(Config(tts=TtsConfig(engine="sapi"))) == "windows voice"
    with pytest.raises(setup.TtsError, match='engine = "pipper": use one of piper, sapi'):
        setup.make_tts(Config(tts=TtsConfig(engine="pipper")))


def test_the_radio_effect_is_applied_before_playing():
    voice, played, effects = FakeVoice(), [], []

    def effect(samples, rate, seed):
        effects.append((len(samples), rate, seed))
        return samples[:10]

    out = PiperOutput("voice.onnx", show=lambda text: None, load=lambda model: voice,
                      play=lambda samples, sr: played.append(len(samples)), effect=effect)
    out.say("roger", "Hamburg Ground")
    out.say("roger", "Hamburg Tower")
    out.wait()
    assert played == [10, 10]
    assert effects[0] == effects[1] == (150, 22050, effects[0][2])  # same text, same seed, same sound
    out.close()

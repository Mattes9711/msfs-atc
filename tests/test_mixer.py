"""The sound mixer (2026-11-16): how loud ATC, the other aircraft, the co-pilot and the cabin are."""
from dataclasses import replace

import numpy as np

from atc import settings_file
from atc.audio.tts import QueuedSpeech, mixer_gain
from atc.config import Config, MixerConfig
from atc.events import ConsoleSink, Event


def test_each_kind_has_its_slider_times_the_master():
    mixer = MixerConfig(master=50, atc=100, traffic=40, copilot=80, cabin=20)
    assert mixer_gain(mixer, "atc") == 0.5 and mixer_gain(mixer, "atis") == 0.5
    assert mixer_gain(mixer, "chatter") == 0.2 and mixer_gain(mixer, "copilot") == 0.4
    assert mixer_gain(mixer, "cabin") == 0.1
    assert mixer_gain(None, "cabin") == 1.0


def test_the_settings_page_sets_it():
    new = settings_file.apply(Config(), {"mixer.cabin": "35", "mixer.master": "0"})
    assert new.mixer == replace(MixerConfig(), cabin=35, master=0)
    assert settings_file.view(new)["mixer.cabin"] == 35


class Loud(QueuedSpeech):
    """Records how loud each transmission played."""

    def __init__(self):
        self.played = []
        super().__init__(show=lambda text: None)

    def _start(self):
        return "test"

    def _speak(self, text, station):
        self.played.append((text, self.gain()))


def test_the_voice_plays_each_kind_at_its_loudness():
    out = Loud()
    out.mixer = MixerConfig(cabin=50, traffic=0)
    sink = ConsoleSink(out, write=lambda line: None)
    for kind in ("atc", "cabin", "chatter"):
        sink.emit(Event(kind, kind, "Cabin" if kind == "cabin" else "Hamburg Tower"))
    out.wait()
    assert out.played == [("atc", 1.0), ("cabin", 0.5), ("chatter", 0.0)]
    out.close()


def test_piper_scales_its_samples():
    from atc.audio.piper_tts import PiperOutput

    played = []
    out = PiperOutput.__new__(PiperOutput)
    out.effect, out.play, out.mixer, out.kind = None, lambda s, r: played.append(s), MixerConfig(atc=25), "atc"
    out.samples = lambda text, station: (np.ones(4, np.float32), 1000)
    out._speak("hello", "Hamburg Tower")
    assert np.allclose(played[0], 0.25)

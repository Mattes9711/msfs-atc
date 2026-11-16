"""Tuning away (2026-11-16, the user's wish): what was heard on the old frequency stops the moment COM1 changes."""
import threading

import numpy as np

from atc.audio.tts import QueuedSpeech
from atc.events import ConsoleSink, Event


class Radio(QueuedSpeech):
    """Each transmission "plays" until released or halted, like sounddevice.wait()."""

    def __init__(self):
        self.started, self.done, self.halted = [], [], []
        self.release = threading.Event()
        self.playing = threading.Event()
        super().__init__(show=lambda text: None)

    def _start(self):
        return "test"

    def _speak(self, text, station):
        self.started.append(text)
        self.playing.set()
        self.release.wait(timeout=5)
        self.release.clear()
        self.done.append((text, self.cut_current))

    def _halt(self):
        self.halted.append(self.kind)
        self.release.set()


def wait_until(condition, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_tuning_away_cuts_the_old_frequency_but_not_the_cabin():
    radio = Radio()
    sink = ConsoleSink(radio, write=lambda line: None)
    sink.emit(Event("atc", "Lufthansa 4AB, contact Tower", "Hamburg Ground"))
    assert radio.playing.wait(timeout=5)
    sink.emit(Event("atc", "tschüss", "Hamburg Ground"))  # still waiting to be said
    sink.emit(Event("cabin", "Ladies and gentlemen", "Cabin"))
    sink.emit(Event("chatter", "Speedbird 12, taxi via A", "Hamburg Ground"))
    sink.emit(Event("tuning", "COM1 121.280: Hamburg Tower", "Hamburg Tower"))
    wait_until(lambda: len(radio.started) == 2)  # the cabin announcement has begun
    radio.release.set()  # and plays to its end
    radio.wait()
    assert radio.halted == ["atc"]
    assert radio.done == [("Lufthansa 4AB, contact Tower", True), ("Ladies and gentlemen", False)]
    radio.close()


def test_the_cabin_playing_is_not_cut():
    radio = Radio()
    sink = ConsoleSink(radio, write=lambda line: None)
    sink.emit(Event("cabin", "Ladies and gentlemen", "Cabin"))
    assert radio.playing.wait(timeout=5)
    sink.emit(Event("tuning", "COM1 121.280: Hamburg Tower", "Hamburg Tower"))
    radio.release.set()
    radio.wait()
    assert radio.halted == [] and radio.done == [("Ladies and gentlemen", False)]
    radio.close()


def test_piper_stops_the_sound_and_skips_one_cut_while_being_made():
    from atc.audio.piper_tts import PiperOutput

    played, stopped = [], []
    out = PiperOutput.__new__(PiperOutput)
    out.effect, out.play, out.mixer, out.kind = None, lambda s, r: played.append(len(s)), None, "atc"
    out.stop_audio = lambda: stopped.append(True)
    out.samples = lambda text, station: (np.ones(4, np.float32), 1000)
    out.cut_current = True  # COM1 changed while the voice was being made
    out._speak("contact Tower", "Hamburg Ground")
    assert played == []
    out._halt()
    assert stopped == [True]

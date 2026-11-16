"""The radio effect (V2): narrow band, loud but not clipping, squelch at the end, the same every time."""
import numpy as np
import pytest

from atc.audio.radio import HIGH_HZ, KEY_S, LOW_HZ, TAIL_S, radio_effect

RATE = 22050


def tone(hz, seconds=1.0, level=0.5):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def level_at(signal, hz):
    """Amplitude of one frequency in the signal."""
    spectrum = np.abs(np.fft.rfft(signal)) / len(signal)
    freqs = np.fft.rfftfreq(len(signal), 1 / RATE)
    return spectrum[np.argmin(np.abs(freqs - hz))]


def test_only_the_airband_audio_range_gets_through():
    voice = tone(100) + tone(1000) + tone(6000)
    out = radio_effect(voice, RATE)
    assert level_at(out, 1000) > 20 * level_at(out, 100)
    assert level_at(out, 1000) > 20 * level_at(out, 6000)
    assert LOW_HZ < 1000 < HIGH_HZ


def test_loud_but_never_clipping_and_float32():
    out = radio_effect(tone(1000, level=0.05), RATE)  # a quiet voice comes out loud
    assert out.dtype == np.float32
    assert np.max(np.abs(out)) == pytest.approx(0.8, abs=1e-3)


def test_key_click_and_squelch_tail_make_it_a_little_longer():
    voice = tone(1000)
    out = radio_effect(voice, RATE)
    assert len(out) == len(voice) + int(KEY_S * RATE) + int(TAIL_S * RATE)
    tail = out[-int(TAIL_S * RATE):]
    assert np.max(np.abs(tail[:200])) > 0.05  # the squelch is heard after the voice


def test_the_same_seed_sounds_the_same():
    voice = tone(800)
    assert np.array_equal(radio_effect(voice, RATE, seed=3), radio_effect(voice, RATE, seed=3))
    assert not np.array_equal(radio_effect(voice, RATE, seed=3), radio_effect(voice, RATE, seed=4))


def test_silence_does_not_break_it():
    assert len(radio_effect(np.zeros(1000, dtype=np.float32), RATE)) > 1000

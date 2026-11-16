"""Make a clean voice sound like the cabin's PA system, heard from the cockpit (2026-11-16, user wish). numpy only.

What an announcement in an airliner's cabin sounds like, and how each part is made:
1. Small ceiling loudspeakers: no deep bass and no crisp highs, about 250-5500 Hz (cut in the frequency domain with
   soft edges, like atc/audio/radio.py), and a little compression from the PA amplifier (tanh).
2. Many loudspeakers along the aisle: the nearest one first, the farther ones a few milliseconds later and quieter.
3. A small, soft room: seats and passengers swallow most of the echo, so a short reverb tail (~0.3 s).
4. The cabin's own sound under it all: the air conditioning's low rumble and hiss, fading in and out.
5. The cockpit door between it and us: quiet and muffled. A wall lets the low sounds through and swallows the high
   ones, so above WALL_PASS_HZ the sound fades down to WALL_FLOOR at WALL_STOP_HZ.

Seeded, so the same announcement always sounds the same.
"""
import numpy as np

LOW_HZ, HIGH_HZ, EDGE_HZ = 250, 5500, 200
DRIVE = 1.8  # the PA amplifier's compression
SPEAKERS = ((0.0, 1.0), (0.011, 0.55), (0.024, 0.35), (0.039, 0.22))  # (delay s, loudness) along the aisle
REVERB_S, REVERB_MIX = 0.3, 0.18
AMBIENCE = 0.035  # the air conditioning, of full scale
FADE_S = 0.25
WALL_PASS_HZ, WALL_STOP_HZ, WALL_FLOOR = 600, 2500, 0.06
PEAK = 0.4  # through the door: well below the radio (0.8)


def _band(samples: np.ndarray, rate: int, low: float, high: float, edge: float) -> np.ndarray:
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    rise = np.clip((freqs - (low - edge)) / edge, 0, 1)
    fall = np.clip(((high + edge) - freqs) / edge, 0, 1)
    mask = (0.5 - 0.5 * np.cos(np.pi * rise)) * (0.5 - 0.5 * np.cos(np.pi * fall))
    return np.fft.irfft(spectrum * mask, len(samples))


def wall(samples: np.ndarray, rate: int) -> np.ndarray:
    """The cockpit door: lows pass, highs fade down to WALL_FLOOR."""
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    ramp = np.clip((freqs - WALL_PASS_HZ) / (WALL_STOP_HZ - WALL_PASS_HZ), 0, 1)
    mask = WALL_FLOOR + (1 - WALL_FLOOR) * (0.5 + 0.5 * np.cos(np.pi * ramp))
    return np.fft.irfft(spectrum * mask, len(samples))


def _convolve(signal: np.ndarray, response: np.ndarray) -> np.ndarray:
    n = len(signal) + len(response) - 1
    size = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(response, size), size)[:n]


def room_response(rate: int, rng: np.random.Generator) -> np.ndarray:
    """The loudspeakers along the aisle, then a short soft reverb tail."""
    length = int(rate * (SPEAKERS[-1][0] + REVERB_S)) + 1
    response = np.zeros(length)
    for delay, loudness in SPEAKERS:
        response[int(delay * rate)] += loudness
    t = np.arange(length) / rate
    tail = rng.standard_normal(length) * np.exp(-6.9 * t / REVERB_S)  # -60 dB after REVERB_S
    tail[: int(0.005 * rate)] = 0  # the first reflections come a little after the direct sound
    return response + REVERB_MIX * tail / np.sqrt(np.sum(tail ** 2) / rate * 50)


def ambience(length: int, rate: int, rng: np.random.Generator) -> np.ndarray:
    """Air conditioning: mostly a low rumble with a little hiss on top."""
    noise = rng.standard_normal(length)
    rumble = _band(noise, rate, 40, 400, 60)
    hiss = _band(noise, rate, 2000, 8000, 500)
    sound = rumble / (np.max(np.abs(rumble), initial=0) or 1) + 0.3 * hiss / (np.max(np.abs(hiss), initial=0) or 1)
    return AMBIENCE * sound / 1.3


def cabin_effect(samples: np.ndarray, rate: int, seed: int = 0) -> np.ndarray:
    """float32 samples of a clean voice (with its chime) → the announcement as heard through the cockpit door (a
    little longer for the echo)."""
    rng = np.random.default_rng(seed)
    voice = np.asarray(samples, dtype=np.float64)
    if peak := np.max(np.abs(voice), initial=0):
        voice = voice / peak
    voice = np.tanh(DRIVE * _band(voice, rate, LOW_HZ, HIGH_HZ, EDGE_HZ)) / np.tanh(DRIVE)
    signal = _convolve(voice, room_response(rate, rng))
    if peak := np.max(np.abs(signal), initial=0):
        signal = signal / peak
    signal = wall(signal + ambience(len(signal), rate, rng), rate)  # the cabin's air through the door too
    if peak := np.max(np.abs(signal), initial=0):
        signal = signal * (PEAK / peak)
    fade = min(int(FADE_S * rate), len(signal) // 2)
    if fade:
        ramp = np.linspace(0, 1, fade)
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]
    return np.clip(signal, -1, 1).astype(np.float32)

"""Make a clean voice sound like VHF airband radio (step V2). numpy only, no new dependency.

What a real transmission sounds like, and how each part is made:
1. A short click and burst of noise when the transmitter keys (the carrier comes up): `KEY_S` of noise.
2. Narrow audio, about 300-3400 Hz: everything outside is removed in the frequency domain (FFT), with soft
   edges so the cut doesn't ring.
3. Loud and a little distorted: the radio's automatic gain and clipping, here a gain into tanh (soft clipping).
4. A little hiss under the voice.
5. The "squelch tail" when the pilot or controller lets go of the button: a louder burst of noise, `TAIL_S`.

The noise comes from a seeded random generator, so the same text always sounds the same (tests can compare).
"""
import numpy as np

LOW_HZ, HIGH_HZ = 300, 3400
EDGE_HZ = 150  # width of the soft edge of the band
DRIVE = 4.0  # gain into the soft clipping: higher = more compressed and distorted
HISS = 0.015  # noise under the voice, of full scale
KEY_S, TAIL_S = 0.06, 0.12
BURST = 0.25  # loudness of the key click and the squelch tail
PEAK = 0.8  # final loudness, leaves some headroom


def band_pass(samples: np.ndarray, rate: int) -> np.ndarray:
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    # 1 inside the band, 0 outside, a cosine ramp of EDGE_HZ at both ends
    rise = np.clip((freqs - (LOW_HZ - EDGE_HZ)) / EDGE_HZ, 0, 1)
    fall = np.clip(((HIGH_HZ + EDGE_HZ) - freqs) / EDGE_HZ, 0, 1)
    mask = (0.5 - 0.5 * np.cos(np.pi * rise)) * (0.5 - 0.5 * np.cos(np.pi * fall))
    return np.fft.irfft(spectrum * mask, len(samples))


def burst(length: int, rng: np.random.Generator) -> np.ndarray:
    """Noise that dies away quickly, like a squelch opening or closing."""
    decay = np.exp(-np.linspace(0, 5, length))
    return BURST * rng.standard_normal(length) * decay


def radio_effect(samples: np.ndarray, rate: int, seed: int = 0) -> np.ndarray:
    """float32 samples of a clean voice → the same transmission as heard over the radio (slightly longer)."""
    rng = np.random.default_rng(seed)
    voice = np.asarray(samples, dtype=np.float64)
    if peak := np.max(np.abs(voice), initial=0):
        voice = voice / peak
    voice = np.tanh(DRIVE * voice) / np.tanh(DRIVE)
    key, tail = burst(int(KEY_S * rate), rng), burst(int(TAIL_S * rate), rng)
    signal = np.concatenate([key, voice, tail])
    signal = signal + HISS * rng.standard_normal(len(signal))
    signal = band_pass(signal, rate)  # after the noise, so the hiss is narrow-band too, like on a real radio
    if peak := np.max(np.abs(signal), initial=0):
        signal = signal * (PEAK / peak)
    return signal.astype(np.float32)

"""Piper (local neural text-to-speech) as the controller's voice, one speaker per controller (step V1).

LICENCE: piper-tts is GPL-3.0-or-later and contains espeak-ng (GPL-3.0). The user decided to use it directly
(2026-11-14): a public build must then be released as open source under the GPL-3.0. See BUILD.md.

DATA SOURCE: the voice is not bundled. On the first start it is downloaded from huggingface.co/rhasspy/piper-voices
into models/piper/. It is "en_US-libritts_r-medium", trained on LibriTTS-R (CC BY 4.0, credit required): one
model with 904 speakers, so every controller gets a voice of its own from a single 79 MB download. Voices whose
data is non-commercial (ryan, hfc_male) or restricted (lessac) are avoided on purpose.

The cabin (C1) speaks German announcements with "de_DE-thorsten-medium" (Thorsten Mueller, CC0), downloaded in the
background the first time it is needed; until then the English voice reads them with German sounds (espeak).
"""
import threading
import time
import zlib
from pathlib import Path
from typing import Callable

from atc import paths
from atc.audio import setup
from atc.audio.tts import QueuedSpeech, _print_error
from atc.phraseology.farewell import spoken_in_own_language

VOICE = "en_US-libritts_r-medium"
VOICE_URL = f"{setup.HUB}/rhasspy/piper-voices/resolve/main/en/en_US/libritts_r/medium"
VOICE_MB = 79
PIPER_DEFAULT_WPM = 170  # roughly what length_scale 1.0 speaks
THORSTEN_URL = f"{setup.HUB}/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium"
# station -> (voice, folder URL, MB, espeak language for the fallback)
CABIN_VOICES = {"Kabine": ("de_DE-thorsten-medium", THORSTEN_URL, 63, "de")}
CABIN = ("Cabin", "Kabine")  # announcements in the cabin: a chime, the PA sound (cabin_sound.py), no radio
CHIME_GAP_S = 3  # the second language right after the first gets no second chime


def ensure_voice(progress: setup.Progress, models_dir: Path | None = None, http=None, voice: str = VOICE,
                 url: str = VOICE_URL, mb: int = VOICE_MB, what: str = "ATC voice") -> Path:
    """The voice's .onnx file, downloaded first if needed (with progress messages, like the whisper model).
    `http` is looked up when called, not when defined, so a test can replace setup._http."""
    folder = (models_dir or paths.models_dir()) / "piper" / voice
    model = folder / f"{voice}.onnx"
    if (folder / setup.DONE_MARKER).exists():
        return model
    progress(f"Downloading the {what} {voice} (about {mb} MB) - only on the first start")
    try:
        setup.fetch([(f"{url}/{name}", name) for name in (f"{voice}.onnx.json", f"{voice}.onnx")],
                    folder, progress, what, mb, http or setup._http)
    except OSError as e:
        raise setup.VoiceUnavailable(f"could not download the {what} ({e})") from None
    return model


def chime(rate: int):
    """The cabin's ding-dong: two soft tones, high then low."""
    import numpy as np

    def tone(freq: float, seconds: float):
        t = np.arange(int(rate * seconds)) / rate
        return (0.25 * np.sin(2 * np.pi * freq * t) * np.exp(-3 * t)).astype(np.float32)

    return np.concatenate([tone(880, 0.6), tone(698.5, 0.9), np.zeros(int(rate * 0.3), np.float32)])


def speaker_for(station: str | None, speakers: int) -> int:
    """The same controller always gets the same speaker. crc32, not hash(): Python's hash of a string changes
    with every start."""
    return zlib.crc32((station or "ATC").lower().encode()) % speakers


def _phonemize(language: str, text: str) -> str:
    from piper.phonemize_espeak import EspeakPhonemizer

    global _espeak
    _espeak = _espeak or EspeakPhonemizer()
    return "".join(p for sentence in _espeak.phonemize(language, text) for p in sentence)


_espeak = None


def _load_voice(model: Path):
    from piper import PiperVoice

    return PiperVoice.load(model)


def _play(samples, rate: int) -> None:
    import sounddevice

    sounddevice.play(samples, rate)
    sounddevice.wait()  # blocks until played (or stopped): the next transmission waits its turn


def _stop_audio() -> None:
    import sounddevice

    sounddevice.stop()  # the waiting sounddevice.wait() in the speech thread returns


class PiperOutput(QueuedSpeech):
    def __init__(self, model: Path, rate: int | None = None, show: Callable[[str], None] = print,
                 report: Callable[[str], None] = _print_error, load: Callable = _load_voice,
                 play: Callable = _play, timeout: float = 30, effect: Callable | None = None, mixer=None,
                 stop_audio: Callable = _stop_audio):
        """`effect(samples, rate, seed)` changes the sound before it is played, e.g. radio.radio_effect."""
        self.model, self.load, self.play, self.effect, self.stop_audio = model, load, play, effect, stop_audio
        self.length_scale = PIPER_DEFAULT_WPM / rate if rate else None  # > 1 is slower
        self.cabin_voices: dict[str, object] = {}  # station -> loaded voice, once its download has finished
        self.cabin_loading: set[str] = set()
        self.last_cabin = 0.0
        super().__init__(show, report, timeout, mixer)

    def _cabin_voice(self, station: str | None):
        """The cabin's own voice for that station, or None while it is still downloading (in the background)."""
        if station not in CABIN_VOICES or station in self.cabin_voices:
            return self.cabin_voices.get(station)
        if station not in self.cabin_loading:
            self.cabin_loading.add(station)
            voice, url, mb, _ = CABIN_VOICES[station]

            def load():
                try:
                    model = ensure_voice(lambda text: None, voice=voice, url=url, mb=mb, what="cabin voice")
                    self.cabin_voices[station] = self.load(model)
                except Exception as e:  # no internet: the English voice keeps reading it with German sounds
                    self.report(f"cabin voice {voice} is not available ({e})")

            threading.Thread(target=load, daemon=True).start()
        return None

    def _start(self) -> str:
        self.voice = self.load(self.model)
        return f"Piper {VOICE} ({self.voice.config.num_speakers} speakers)"

    def samples(self, text: str, station: str | None):
        """The transmission as float32 samples, and the sample rate."""
        import numpy as np
        from piper import SynthesisConfig

        if (own := self._cabin_voice(station)) is not None:  # the German cabin voice: one speaker
            chunks = list(own.synthesize(text, SynthesisConfig(length_scale=self.length_scale)))
            return np.concatenate([c.audio_float_array for c in chunks]), own.config.sample_rate
        speaker = speaker_for(station, self.voice.config.num_speakers)
        if station in CABIN_VOICES:  # its voice isn't there yet: German sounds from the English voice
            text = f"[[ {_phonemize(CABIN_VOICES[station][3], text)} ]]"
        else:
            text = spoken_in_own_language(text, _phonemize)  # "tschüss" in German sounds, not "tee-shoos"
        chunks = list(self.voice.synthesize(text, SynthesisConfig(speaker_id=speaker,
                                                                  length_scale=self.length_scale)))
        return np.concatenate([c.audio_float_array for c in chunks]), self.voice.config.sample_rate

    def _halt(self) -> None:
        self.stop_audio()

    def _speak(self, text: str, station: str | None) -> None:
        samples, rate = self.samples(text, station)
        if getattr(self, "cut_current", False):  # tuned away while it was being made
            return
        if station in CABIN:  # the cabin PA: a chime first (not again for the second language), cabin sound
            import numpy as np

            from atc.audio.cabin_sound import cabin_effect

            if time.monotonic() - self.last_cabin > CHIME_GAP_S:
                samples = np.concatenate([chime(rate), samples])
            samples = cabin_effect(samples, rate, zlib.crc32(text.encode()))
            self.play(samples * self.gain(), rate)
            self.last_cabin = time.monotonic()
            return
        if self.effect is not None and station != "Copilot":  # we hear our own side without the radio's sound
            samples = self.effect(samples, rate, zlib.crc32(text.encode()))  # seeded: same text, same sound
        self.play(samples * self.gain(), rate)

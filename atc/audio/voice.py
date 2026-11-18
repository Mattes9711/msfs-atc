"""Push-to-talk + faster-whisper: the pilot's voice as text (step 23).

Rules from the Milestone 0 spikes:
- push-to-talk polls GetAsyncKeyState (the `keyboard` package is dead on Python 3.14) and works while MSFS
  has the focus
- whisper always gets a 16 kHz float32 array (PyAV 19 breaks its own file decoding) and vad_filter=True
  (without it, silence turned into "Clearance, ground,")
- the prompt is generic aviation vocabulary plus the ICAO alphabet, never expected names: with names in it,
  whisper returned the prompt instead of what was said. The parser corrects names afterwards.

Live text (2026-11-18, the user's wish): while push-to-talk is held, a worker thread transcribes the audio so far
every LIVE_EVERY_S, fast (beam 1), and shows it. Only the full pass after the key is released goes to ATC, so the
live text never makes recognition worse; on a slow PC the final text can come a little later (one live pass may
still be running when the key is released).
"""
import ctypes
import re
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from atc.audio.ptt import PTT_KEYS, is_held, joystick_buttons, key_down  # noqa: F401 (PTT_KEYS: older imports)
from atc.audio.ptt import parse as parse_binding

from atc.events import Event

SAMPLE_RATE = 16000
MIN_SECONDS = 0.3  # shorter = the key was only tapped
QUIET_PEAK = 0.02  # below this the wrong microphone is probably selected
LIVE_EVERY_S = 0.7  # how often the live text is updated while speaking
LIVE_MIN_S = 0.5  # less audio than this: nothing to show yet
AVIATION_PROMPT = (
    "Clearance, ground, tower, departure, approach, runway, taxi, holding point, hold short, "
    "line up and wait, cleared for takeoff, cleared to land, flight level, squawk, QNH, "
    "information, niner, decimal, wilco, roger, going around. "
    "Alpha, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliett, Kilo, Lima, Mike, "
    "November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, Uniform, Victor, Whiskey, X-ray, Yankee, Zulu."
)


class Recorder(Protocol):
    def record(self) -> np.ndarray:
        """Block until the pilot has pressed and released push-to-talk; return the audio (16 kHz mono float32)."""

    # optional: so_far() -> np.ndarray | None, the audio while recording (None when not), for the live text


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


# The live text's states, for the window: the words while speaking, then while the full pass runs, then nothing
SPEAKING, TRANSCRIBING, IDLE = "speaking", "transcribing", "idle"


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


PROMPT_WORDS = words(AVIATION_PROMPT)


class WhisperInput:
    """SpeechInput for push-to-talk. Shows what was heard, and drops what can't be a real transmission."""

    def __init__(self, recorder: Recorder, transcriber: Transcriber, save_dir: Path | None = None,
                 clock: Callable[[], float] = time.perf_counter):
        self.recorder, self.transcriber = recorder, transcriber
        self.save_dir, self.clock = save_dir, clock
        self.sink = None
        self.context: Callable[[], str] | None = None  # the flight's words for the whisper prompt, if set
        self.live: Callable[[str, str], None] | None = None  # live text (text, state), if set and the recorder can
        self.live_every = LIVE_EVERY_S
        self.live_wanted = True  # the setting whisper.live_text
        self.lock = threading.Lock()  # one transcription at a time: a live pass and the full pass share the model
        self.closed = threading.Event()
        self.worker: threading.Thread | None = None
        self.so_far = ""  # the last live words of this transmission, shown on while the full pass runs

    def attach(self, sink) -> None:
        """Where to show what was heard (the live loop attaches its sink before listening starts)."""
        self.sink = sink

    def _show(self, kind: str, text: str) -> None:
        if self.sink is not None:
            self.sink.emit(Event(kind, text))

    def close(self) -> None:
        self.closed.set()
        getattr(self.recorder, "close", lambda: None)()

    def _transcribe(self, audio: np.ndarray, fast: bool = False) -> str:
        context = self.context() if self.context else ""
        with self.lock:
            if fast:
                return self.transcriber.transcribe(audio, context, fast=True).strip()
            return (self.transcriber.transcribe(audio, context) if context
                    else self.transcriber.transcribe(audio)).strip()

    def _show_live(self, text: str, state: str) -> None:
        if self.live is not None:
            try:
                self.live(text, state)
            except Exception:  # the window's live text must never stop push-to-talk
                pass

    def _start_live(self) -> None:
        if self.live is None or self.worker is not None or not hasattr(self.recorder, "so_far"):
            return
        self.worker = threading.Thread(target=self._live_loop, daemon=True, name="live text")
        self.worker.start()

    def _live_loop(self) -> None:
        """While push-to-talk is held: every live_every seconds the words so far."""
        last, done = None, 0
        while not self.closed.is_set():
            audio = self.recorder.so_far()
            now = time.monotonic()  # not self.clock: that one times the full pass
            if audio is None:
                last, done = None, 0
                time.sleep(0.05)
                continue
            if audio.size < LIVE_MIN_S * SAMPLE_RATE or audio.size == done or (last and now - last < self.live_every):
                time.sleep(0.05)
                continue
            last, done = now, audio.size
            try:
                text = self._transcribe(audio, fast=True)
            except Exception:
                continue
            if self.recorder.so_far() is not None and text:  # not released meanwhile: still speaking
                self.so_far = text
                self._show_live(text, SPEAKING)

    def listen(self) -> str | None:
        self._start_live()
        while True:
            try:
                audio = self.recorder.record()
            except Exception as e:  # e.g. the microphone was unplugged
                self._show("notice", f"microphone error: {e}; check Settings → Audio → Microphone")
                time.sleep(2)
                continue
            if audio is None:
                return None  # closed
            seconds = audio.size / SAMPLE_RATE
            if seconds < MIN_SECONDS:
                self.so_far = ""
                self._show_live("", IDLE)
                continue  # tapped by accident
            peak = float(np.abs(audio).max())
            if peak < QUIET_PEAK:
                self._show("notice", f"nearly silent recording, peak {peak:.3f}: wrong microphone? "
                                     "check Settings → Audio → Microphone")
            if self.save_dir:
                save_wav(audio, self.save_dir)
            start = self.clock()
            self._show_live(self.so_far, TRANSCRIBING)
            try:
                text = self._transcribe(audio)
            finally:
                self.so_far = ""
                self._show_live("", IDLE)
            took = self.clock() - start
            if not text:
                self._show("notice", f"heard nothing in {seconds:.1f} s of audio: say again")
                continue
            self._show("heard", f"heard in {took:.1f} s: {text}")
            if words(text) <= PROMPT_WORDS:
                self._show("notice", "ignored: only words from the whisper prompt, which whisper invents from "
                                     "noise. Say it again with your callsign.")
                continue
            return text


class WhisperTranscriber:
    def __init__(self, model: str = "small.en", device: str = "cpu", beam_size: int = 5, load=None):
        if load is None:
            from faster_whisper import WhisperModel
            load = WhisperModel
        compute_type = "float16" if device == "cuda" else "int8"
        self.beam_size = beam_size
        try:
            self.model = load(model, device=device, compute_type=compute_type)
            # CUDA libraries load on the first transcription: fail now, not on the first radio call
            self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
        except RuntimeError as e:
            if device == "cuda":
                raise RuntimeError(f"whisper on CUDA failed ({e}); it needs cuBLAS 12 + cuDNN 9, "
                                   f'or set device = "cpu" in settings.toml') from None
            raise

    def transcribe(self, audio: np.ndarray, context: str = "", fast: bool = False) -> str:
        """`context`: this flight's words (callsign, stations, waypoints, the call ATC expects next), added to the
        prompt. Whisper takes the prompt as the text said just before, so it spells these words as given instead of
        "Humber Ground" or "two for one" (the user's flight, 2026-11-15)."""
        prompt = f"{AVIATION_PROMPT} {context}".strip()
        beam = 1 if fast else self.beam_size  # fast: the live text while speaking
        segments, _ = self.model.transcribe(audio, language="en", beam_size=beam,
                                            vad_filter=True, initial_prompt=prompt)
        return " ".join(s.text.strip() for s in segments)


class MicRecorder:
    """Records while a push-to-talk binding (a key, or a joystick button; atc/audio/ptt.py) is held, the main one
    or the spare. Polls every 10 ms, works whichever window has the focus."""

    def __init__(self, key: str = "right ctrl", mic: int | None = None, is_down: Callable[[int], bool] = key_down,
                 spare: str | None = None, joysticks: Callable[[int], int] = joystick_buttons):
        self.bindings = [parse_binding(key)] + ([parse_binding(spare)] if spare else [])  # ValueError if unknown
        self.mic, self.is_down, self.joysticks = mic, is_down, joysticks
        self.stopped = threading.Event()
        self.chunks: list[np.ndarray] | None = None  # while recording

    def held(self) -> bool:
        return any(is_held(b, self.is_down, self.joysticks) for b in self.bindings)

    def close(self) -> None:
        """Stop waiting for the key (end of a session), so no old recorder listens alongside a new one."""
        self.stopped.set()

    def so_far(self) -> np.ndarray | None:
        """The audio while push-to-talk is held (for the live text), None when not recording."""
        chunks = self.chunks
        if chunks is None:
            return None
        parts = list(chunks)  # the audio callback appends meanwhile
        return np.concatenate(parts).flatten() if parts else np.zeros(0, dtype=np.float32)

    def record(self) -> np.ndarray | None:
        """None once closed. Raises sounddevice's PortAudioError if the microphone can't be opened."""
        import sounddevice as sd

        while not self.held():
            if self.stopped.is_set():
                return None
            time.sleep(0.01)
        chunks = []
        self.chunks = chunks
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=self.mic,
                                callback=lambda data, frames, t, status: chunks.append(data.copy())):
                while self.held():
                    time.sleep(0.01)
        finally:
            self.chunks = None
        return np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype=np.float32)


def list_mics() -> list[str]:
    import sounddevice as sd

    default_in = sd.default.device[0]
    return [("* " if i == default_in else "  ") + f"{i:3} {d['name']}"
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0 and d["hostapi"] == 0]


def save_wav(audio: np.ndarray, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{len(list(directory.glob('*.wav'))) + 1:03}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def load_wav(path: Path) -> np.ndarray:
    """16-bit PCM wav -> 16 kHz mono float32, resampled if needed."""
    with wave.open(str(path), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768
    target_len = int(len(audio) * SAMPLE_RATE / rate)
    return np.interp(np.linspace(0, len(audio) - 1, target_len), np.arange(len(audio)), audio).astype(np.float32)

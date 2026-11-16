"""The controller's voice: the thread both voices share, and Windows SAPI (the fallback; Piper is in piper_tts.py).

Speaking blocks for seconds, so it runs in its own thread with a queue: the 1-second tick keeps running while ATC
talks. The engine is made inside that thread, because COM objects (SAPI) belong to the thread that made them.

SAPI is used directly through comtypes. pyttsx3 (used before) spoke only the first transmission: from the second
one on, its runAndWait() returned after 0.1 s without a sound, which is why ATC was silent in the app (step F1).
`dynamic=True` talks to SAPI through IDispatch, so comtypes doesn't generate wrapper code (that would need a writable
folder inside a PyInstaller build). The Windows default voice here is German, so the voice is chosen by name and
must be English."""
import math
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

SAPI_DEFAULT_WPM = 200  # roughly what SAPI's rate 0 speaks
CHANNEL = {"atc": "atc", "atis": "atc", "chatter": "traffic", "copilot": "copilot", "cabin": "cabin"}
ON_FREQUENCY = ("atc", "atis", "chatter")  # heard on COM1: gone the moment it is tuned away (2026-11-16)


def mixer_gain(mixer, kind: str) -> float:
    """0..1 for a kind of transmission: its own slider times the master, both in percent."""
    if mixer is None:
        return 1.0
    channel = getattr(mixer, CHANNEL.get(kind, "atc"))
    return max(0, min(100, mixer.master)) / 100 * max(0, min(100, channel)) / 100


class TtsError(Exception):
    pass


def _print_error(text: str) -> None:
    print(f"       ({text})")


class QueuedSpeech:
    """A SpeechOutput that shows each transmission and speaks it in its own thread, one after the other.
    Subclasses say how to start the engine (`_start`, in the thread) and how to speak one text (`_speak`).
    `report` gets a message when speaking fails, so a broken voice is visible instead of silent; the next
    transmission tries again."""

    def __init__(self, show: Callable[[str], None] = print, report: Callable[[str], None] = _print_error,
                 timeout: float = 15, mixer=None):
        self.show, self.report = show, report
        # While this returns True (the pilot is holding push-to-talk), ATC waits: no talking over the pilot
        self.hold: Callable[[], bool] | None = None
        self.queue: queue.Queue[tuple[str, str | None, str] | None] = queue.Queue()
        self.mixer = mixer  # a MixerConfig (atc/config.py): how loud each kind of voice is; None = all full
        self.kind = "atc"  # the kind of the transmission being spoken (atc.events kinds), for the mixer
        self.speaking = False
        self.cut_current = False  # the transmission being spoken was cut off: COM1 was tuned away
        ready: queue.Queue[Exception | str] = queue.Queue()
        self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self.thread.start()
        try:
            result = ready.get(timeout=timeout)
        except queue.Empty:
            raise TtsError("the text-to-speech engine did not start") from None
        if isinstance(result, Exception):
            raise result
        self.voice_name = result

    def _start(self) -> str:
        """Make the engine; returns the voice's name for the screen."""
        raise NotImplementedError

    def _speak(self, text: str, station: str | None) -> None:
        raise NotImplementedError

    def _stop(self) -> None:
        """Let go of the engine. Runs in the speech thread: a COM object (SAPI) released from another thread,
        e.g. by the garbage collector, crashes the whole process (found with a voice name that doesn't exist)."""

    def _run(self, ready: queue.Queue) -> None:
        try:
            name = self._start()
        except Exception as e:  # reported to the constructor, which raises it in the main thread
            self._stop()
            error = e if isinstance(e, TtsError) else TtsError(f"text-to-speech failed: {e}")
            ready.put(error.with_traceback(None))  # the traceback would keep the engine alive
            return
        ready.put(name)
        while (job := self.queue.get()) is not None:
            try:
                while self.hold is not None and self.hold():
                    time.sleep(0.05)
                text, station, self.kind = job
                self.cut_current, self.speaking = False, True
                self._speak(text, station)
            except Exception as e:
                self.report(f"ATC voice failed: {e}")
            finally:
                self.speaking = False
                self.queue.task_done()
        self._stop()

    def say(self, text: str, station: str | None = None, kind: str = "atc") -> None:
        """`station` (e.g. "Hamburg Tower") lets a voice sound different per controller; `kind` (an event kind:
        atc, atis, chatter, cabin, copilot) picks its slider in the mixer."""
        self.show(f"ATC:   {text}")
        self.queue.put((text, station, kind))

    def speak(self, text: str, station: str | None = None, kind: str = "atc") -> None:
        """Speak without showing it (the caller shows it differently, e.g. other aircraft's calls)."""
        self.queue.put((text, station, kind))

    def cut_radio(self) -> None:
        """COM1 was tuned to another frequency: what was heard on the old one stops at once, and what was still
        waiting on it is dropped. Cabin and co-pilot go on: they are not on the radio."""
        kept = []
        while True:
            try:
                job = self.queue.get_nowait()
            except queue.Empty:
                break
            self.queue.task_done()
            if job is None or job[2] not in ON_FREQUENCY:
                kept.append(job)
        for job in kept:
            self.queue.put(job)
        if self.speaking and self.kind in ON_FREQUENCY:
            self.cut_current = True
            self._halt()

    def _halt(self) -> None:
        """Stop the sound now playing. Called from another thread; the Windows voice can't be (its COM object
        belongs to the speech thread), so with it only the waiting transmissions are dropped."""

    def gain(self) -> float:
        """How loud the transmission being spoken plays, 0..1, from the mixer."""
        return mixer_gain(getattr(self, "mixer", None), getattr(self, "kind", "atc"))  # tests skip __init__

    def wait(self) -> None:
        """Until everything queued has been spoken (tests, and before quitting)."""
        self.queue.join()

    def close(self) -> None:
        self.queue.put(None)


# --- Windows SAPI ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Voice:
    name: str
    token: Any = None  # SAPI's voice token


def sapi_rate(wpm: int) -> int:
    """Words per minute → SAPI's rate, -10..10, where +10 is 3x as fast and -10 a third as fast."""
    return max(-10, min(10, round(10 * math.log(wpm / SAPI_DEFAULT_WPM, 3))))


class SapiEngine:
    """The real engine, made inside the speech thread."""

    def __init__(self):
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        self.voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)

    def voices(self) -> list[Voice]:
        tokens = self.voice.GetVoices()
        return [Voice(tokens.Item(i).GetDescription(), tokens.Item(i)) for i in range(tokens.Count)]

    def use(self, voice: Voice, rate: int | None) -> None:
        self.voice.Voice = voice.token
        if rate is not None:
            self.voice.Rate = sapi_rate(rate)

    def speak(self, text: str, volume: float = 1.0) -> None:
        self.voice.Volume = round(100 * volume)  # SAPI: 0..100
        self.voice.Speak(text, 0)  # 0 = synchronous: returns when the sentence has been spoken


def choose_voice(voices: list[Voice], wanted: str) -> Voice:
    english = [v for v in voices if "english" in v.name.lower()]
    for v in english:
        if wanted.lower() in v.name.lower():
            return v
    names = ", ".join(v.name for v in english) or "none installed"
    raise TtsError(f'no English voice matching "{wanted}" (English voices: {names}); set [tts] voice in settings.toml')


class SapiOutput(QueuedSpeech):
    """One Windows voice for every controller."""

    def __init__(self, voice: str = "Zira", rate: int | None = None, show: Callable[[str], None] = print,
                 make_engine: Callable = SapiEngine, timeout: float = 15,
                 report: Callable[[str], None] = _print_error, mixer=None):
        self.wanted, self.rate, self.make_engine = voice, rate, make_engine
        super().__init__(show, report, timeout, mixer)

    def _start(self) -> str:
        self.engine = None
        self.engine = self.make_engine()
        chosen = choose_voice(self.engine.voices(), self.wanted)
        self.engine.use(chosen, self.rate)
        return chosen.name

    def _speak(self, text: str, station: str | None) -> None:
        self.engine.speak(text, self.gain())

    def _stop(self) -> None:
        self.engine = None  # the last reference: SAPI is released here, in the speech thread

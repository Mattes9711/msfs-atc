"""Everything the user sees, as data (Milestone 3b, A1).

The controller, the live loop, the /commands and push-to-talk emit Events into a Sink. The console prints them
exactly as it always did; the app window shows them as a radio log with colours and status.
"""
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from atc.audio.base import SpeechOutput

KINDS = {
    "atc": "a controller transmission (spoken); station = who",
    "atis": "the ATIS broadcast after tuning its frequency (spoken)",
    "chatter": "another aircraft or its controller on your frequency (spoken); station = who is talking",
    "cabin": "a cabin announcement (spoken); station = Cabin (English) or Kabine (German)",
    "copilot": "the co-pilot's transmission while he has the radio (spoken); station = Copilot",
    "pilot": "a transmission by the pilot, typed or heard",
    "heard": "what speech recognition heard",
    "understood": "how the parser read the transmission",
    "readback": "the readback was correct",
    "missed_call": "ATC called on a frequency the pilot isn't tuned to; station = who",
    "notice": "anything else the controller or the live loop points out",
    "tuning": "COM1 changed; station = what is on that frequency",
    "position": "the fake sim moved",
    "track": "where the aircraft is, for the flight log only (not shown): every minute and after each call",
    "info": "output of a /command (taxi preview, usage, help)",
    "system": "the app itself: session started or ended, errors",
}
SPOKEN = ("atc", "atis", "chatter", "cabin", "copilot")


@dataclass(frozen=True)
class Event:
    kind: str
    text: str
    station: str | None = None
    time: float = field(default_factory=time.time, compare=False)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}")


class Sink(Protocol):
    def emit(self, event: Event) -> None: ...


class ConsoleSink:
    """The console as it always looked: transmissions through the speech output (printed "ATC:   …" and/or
    spoken), everything else as an indented hint in brackets. The pilot's own lines are already on screen."""

    def __init__(self, speech: SpeechOutput, write: Callable[[str], None] = print):
        self.speech, self.write = speech, write

    def emit(self, event: Event) -> None:
        if event.kind == "tuning" and (cut := getattr(self.speech, "cut_radio", None)):
            cut()  # the old frequency goes quiet at once
        if event.kind in ("chatter", "cabin", "copilot"):  # not ATC talking to us: shown with who, spoken if it can
            self.write(f"       [{event.station}] {event.text}")
            if speak := getattr(self.speech, "speak", None):
                speak(event.text, event.station, kind=event.kind)
        elif event.kind in SPOKEN:
            self.speech.say(event.text, event.station, kind=event.kind)
        elif event.kind not in ("pilot", "track"):
            self.write(f"       ({event.text})")


class Tee:
    """Sends every event to several sinks, e.g. the console and the flight log."""

    def __init__(self, *sinks: Sink):
        self.sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self.sinks:
            sink.emit(event)


class Collector:
    """Keeps every event (tests, and the app's history for a window that connects late)."""

    def __init__(self):
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

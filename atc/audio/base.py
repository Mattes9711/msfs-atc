from typing import Protocol


class SpeechInput(Protocol):
    def listen(self) -> str | None:
        """Block until the pilot transmits; return the text, or None when input has ended."""


class SpeechOutput(Protocol):
    def say(self, text: str, station: str | None = None, kind: str = "atc") -> None:
        """`station` (who is talking, e.g. "Hamburg Tower") lets a voice sound different per controller; `kind`
        (atc, atis, chatter, cabin, copilot) picks its slider in the sound mixer."""

import sys
from typing import TextIO


class TextInput:
    """Pilot transmissions typed on the keyboard (--text)."""

    def __init__(self, stream: TextIO | None = None, prompt: str = "PILOT> "):
        self.stream, self.prompt = stream, prompt

    def listen(self) -> str | None:
        if self.prompt:
            print(self.prompt, end="", flush=True)
        line = (self.stream or sys.stdin).readline()
        if not line:
            return None
        # PowerShell pipes start with a UTF-8 BOM, which would hide a leading "/" of a command
        return line.lstrip("﻿").strip()


class PrintOutput:
    """ATC transmissions printed instead of spoken."""

    def say(self, text: str, station: str | None = None, kind: str = "atc") -> None:
        print(f"ATC:   {text}")

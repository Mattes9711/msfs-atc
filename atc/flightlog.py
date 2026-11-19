"""The flight log (step F4, was A7): every event of a flight, written line by line to
logs/<date>_<time>Z_<callsign>.txt in the data folder (%LOCALAPPDATA%\\MSFS ATC\\logs).

Written as the flight goes, so a flight's radio log survives a restart or a crash and can be attached to a bug
report. One line per event, with the UTC time:
    14:52:07Z  PILOT  Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha
    14:52:09Z  ATC    Hamburg Ground: Lufthansa four Alfa Bravo, cleared to Munich via ...
    14:52:09Z         (readback correct)
    14:53:10Z  POS    53.6301N 009.9882E, 24512 ft, GS 420 kt, HDG 330, enroute, cleared FL100, ...
"""
import re
import time
from pathlib import Path
from typing import TextIO

from atc.events import Event

WHO = {"atc": "ATC", "atis": "ATIS", "pilot": "PILOT", "chatter": "RADIO", "cabin": "CABIN", "copilot": "F/O",
       "track": "POS"}


def log_path(folder: Path, callsign: str, started: float) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%MZ", time.gmtime(started))
    safe = re.sub(r"[^A-Za-z0-9]", "", callsign) or "flight"
    path = folder / f"{stamp}_{safe}.txt"
    n = 2
    while path.exists():  # two flights in the same minute
        path = folder / f"{stamp}_{safe}_{n}.txt"
        n += 1
    return path


def format_line(event: Event) -> str:
    stamp = time.strftime("%H:%M:%SZ", time.gmtime(event.time))
    if event.kind in WHO:
        station = f"{event.station}: " if event.station and event.kind in ("atc", "chatter") else ""
        return f"{stamp}  {WHO[event.kind]:<5}  {station}{event.text}"
    return f"{stamp}         ({event.text})"


class FlightLog:
    """A Sink that appends each event to the log file and flushes it at once."""

    def __init__(self, path: Path, header: list[str] = ()):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.file: TextIO | None = path.open("w", encoding="utf-8")
        for line in header:
            self.file.write(f"# {line}\n")
        self.file.flush()

    def emit(self, event: Event) -> None:
        if self.file is None:
            return
        self.file.write(format_line(event) + "\n")
        self.file.flush()

    def close(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None

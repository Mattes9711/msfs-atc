"""GSX Pro (FSDreamTeam ground services) read and controlled through its L-vars (Milestone 7, C3 and C4).

GSX tells its state in L-vars: FSDT_GSX_COUATL_STARTED (1 while GSX runs) and one per service,
FSDT_GSX_BOARDING_STATE, FSDT_GSX_DEBOARDING_STATE and FSDT_GSX_DEPARTURE_STATE (the pushback), with
1 available, 2 not available, 3 bypassed, 4 requested, 5 performing, 6 completed.

It is controlled through its menu, as other tools do (e.g. Fenix2GSX): FSDT_GSX_MENU_OPEN = 1 opens the menu and GSX
writes its text to %APPDATA%\\Virtuali\\GSX\\menu (the title, then one option per line); FSDT_GSX_MENU_CHOICE = n
picks option n (0 = the first option line). A choice can lead to another menu (the handling operator, the push
direction): that one is left to the pilot in GSX's own window and shown in the log, since picking blindly could order
the wrong service.

MSFS 2020 reads and writes L-vars through SimConnect data definitions since Sim Update 12 (2023). **All of this is
still to be checked in MSFS with GSX running**: the values, the menu file, the option texts.
"""
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

AVAILABLE, NOT_AVAILABLE, BYPASSED, REQUESTED, PERFORMING, COMPLETED = 1, 2, 3, 4, 5, 6
STATE_LVARS = {"running": "L:FSDT_GSX_COUATL_STARTED", "boarding": "L:FSDT_GSX_BOARDING_STATE",
               "deboarding": "L:FSDT_GSX_DEBOARDING_STATE", "departure": "L:FSDT_GSX_DEPARTURE_STATE"}
MENU_OPEN, MENU_CHOICE = "L:FSDT_GSX_MENU_OPEN", "L:FSDT_GSX_MENU_CHOICE"
SERVICE_WORDS = {"pushback": ("pushback", "push-back", "push back"), "deboarding": ("deboarding",)}
MENU_WAIT_S = 3  # GSX rewrites the menu file within about a second


def menu_file() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Virtuali" / "GSX" / "menu"


@dataclass(frozen=True)
class GsxState:
    boarding: int
    deboarding: int
    departure: int  # the pushback service

    @property
    def boarding_done(self) -> bool:
        return self.boarding == COMPLETED

    @property
    def pushing(self) -> bool:
        return self.departure == PERFORMING


def state_from_lvars(values: dict[str, float] | None) -> GsxState | None:
    """None while GSX isn't running (or the sim gave no answer)."""
    if not values or not values.get(STATE_LVARS["running"]):
        return None
    return GsxState(*(int(values.get(STATE_LVARS[k]) or 0) for k in ("boarding", "deboarding", "departure")))


class GsxMenu:
    """Picks a service in the GSX menu. `set_lvar(name, value)` writes an L-var through SimConnect."""

    def __init__(self, set_lvar: Callable[[str, float], None], path: Path | None = None,
                 clock=time.monotonic, sleep=time.sleep):
        self.set_lvar, self.path, self.clock, self.sleep = set_lvar, path or menu_file(), clock, sleep

    def _open(self, previous: float | None) -> list[str] | None:
        """The menu's lines after GSX has written them anew, or None when it didn't."""
        deadline = self.clock() + MENU_WAIT_S
        while self.clock() < deadline:
            try:
                if self.path.stat().st_mtime != previous:
                    lines = [line.strip() for line in self.path.read_text(encoding="utf-8").splitlines()]
                    if len(lines) > 1:
                        return lines
            except OSError:
                pass
            self.sleep(0.1)
        return None

    def _mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def request(self, service: str) -> str:
        """"pushback" or "deboarding". Returns what happened, for the log."""
        before = self._mtime()  # an old menu file from earlier: wait until GSX has written it anew
        self.set_lvar(MENU_OPEN, 1)
        lines = self._open(before)
        if lines is None:
            return f"GSX: its menu did not open ({self.path} not written)"
        options = lines[1:]
        choice = next((i for i, o in enumerate(options) if any(w in o.lower() for w in SERVICE_WORDS[service])),
                      None)
        if choice is None:
            self.set_lvar(MENU_CHOICE, -2)  # close the menu again
            return f"GSX: no {service} in its menu ({' | '.join(options)})"
        before = self._mtime()
        self.set_lvar(MENU_CHOICE, choice)
        follow = self._open(before)
        if follow is not None and follow[1:] != options:  # GSX asks something: the pilot answers it in GSX
            return f"GSX: {service} requested; GSX asks \"{follow[0]}\": answer it in the GSX menu"
        return f"GSX: {service} requested ({options[choice]})"

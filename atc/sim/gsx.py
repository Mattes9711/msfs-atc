"""GSX Pro (FSDreamTeam ground services) read and controlled through its L-vars (Milestone 7, C3 and C4).

GSX tells its state in L-vars: FSDT_GSX_COUATL_STARTED (1 while GSX runs) and one per service,
FSDT_GSX_BOARDING_STATE, FSDT_GSX_DEBOARDING_STATE and FSDT_GSX_DEPARTURE_STATE (the pushback), with
1 available, 2 not available, 3 bypassed, 4 requested, 5 performing, 6 completed.

It is controlled through its menu, as other tools do (e.g. Fenix2GSX): FSDT_GSX_MENU_OPEN = 1 opens the menu and GSX
writes its text to the file "menu" of its in-game panel (the title, then one option per line; see menu_file);
FSDT_GSX_MENU_CHOICE = n picks option n (0 = the first option line). A choice can lead to another menu (the handling operator, the push
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
STATE_NAMES = {AVAILABLE: "available", NOT_AVAILABLE: "not available", BYPASSED: "bypassed", REQUESTED: "requested",
               PERFORMING: "in progress", COMPLETED: "completed"}
STATE_LVARS = {"running": "L:FSDT_GSX_COUATL_STARTED", "boarding": "L:FSDT_GSX_BOARDING_STATE",
               "deboarding": "L:FSDT_GSX_DEBOARDING_STATE", "departure": "L:FSDT_GSX_DEPARTURE_STATE"}
MENU_OPEN, MENU_CHOICE = "L:FSDT_GSX_MENU_OPEN", "L:FSDT_GSX_MENU_CHOICE"
SERVICE_WORDS = {"pushback": ("pushback", "push-back", "push back"), "deboarding": ("deboarding",)}
MENU_WAIT_S = 10  # GSX rewrites the menu file within about a second, but not always (E1: 3 s were too short)
FOLLOW_WAIT_S = 3  # after a choice: a follow-up question, if any, comes as fast as the menu
MENU_TRIES = 2  # opening the menu once more before giving up
CLOSE = -2  # MENU_CHOICE value that closes the menu


PANEL = Path("html_ui") / "InGamePanels" / "FSDT_GSX_Panel" / "menu"
PACKAGE = "fsdreamteam-gsx-pro"
BOOT = "#BOOT#"  # GSX's auto-restarter writes its messages into the menu file: never a menu


def _fsdt_root() -> str | None:
    """Where the FSDreamTeam Addon Manager installed GSX (its own registry value)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Fsdreamteam") as key:
            return str(winreg.QueryValueEx(key, "root")[0])
    except (ImportError, OSError):
        return None


def _packages_path(env=os.environ) -> Path | None:
    """MSFS's InstalledPackagesPath from UserCfg.opt (MS Store or Steam), for the Community folder."""
    for cfg in (Path(env.get("LOCALAPPDATA", "")) / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe"
                / "LocalCache" / "UserCfg.opt", Path(env.get("APPDATA", "")) / "Microsoft Flight Simulator" / "UserCfg.opt"):
        try:
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("InstalledPackagesPath"):
                    return Path(line.split(None, 1)[1].strip().strip('"'))
        except (OSError, IndexError):
            continue
    return None


def menu_candidates(root: str | None = None, packages: Path | None = None, env=os.environ) -> list[Path]:
    """Where GSX may write its menu, the likeliest first: GSX Pro on MSFS writes it into its own panel's folder
    (found 2026-11-25; until then the app waited for the old FSX/P3D place, %APPDATA%\\Virtuali\\GSX\\menu)."""
    found = []
    if root:
        found.append(Path(root) / "MSFS" / PACKAGE / PANEL)
    if packages:
        found.append(packages / "Community" / PACKAGE / PANEL)
    found.append(Path(env.get("APPDATA", "")) / "Virtuali" / "GSX" / "menu")
    return found


def menu_file(candidates: list[Path] | None = None) -> Path:
    """The first place that exists (the last one if none does, so the log names a place)."""
    if candidates is None:
        candidates = menu_candidates(_fsdt_root(), _packages_path())
    return next((p for p in candidates if p.exists()), candidates[-1])


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
    """Picks a service in the GSX menu. `set_lvar(name, value)` writes an L-var through SimConnect.

    Stepped (E1): start() opens the menu, then poll() once per live-loop step until it returns what happened. So
    the clicks go through the live loop's own SimConnect connection, one user at a time (before 2026-11-16 a thread
    wrote them while the loop read: "its menu did not open" twice in the test flight), and the loop never waits."""

    def __init__(self, set_lvar: Callable[[str, float], None], path: Path | None = None,
                 clock=time.monotonic, sleep=time.sleep):
        self.set_lvar, self.path, self.clock, self.sleep = set_lvar, path or menu_file(), clock, sleep
        self.service: str | None = None  # being requested
        self.stage = ""  # "open" (waiting for the menu), "chosen" (waiting for a follow-up question)
        self.since: float | None = None  # mtime of the menu file before the last click
        self.deadline = 0.0
        self.tries = 0
        self.options: list[str] = []
        self.choice = 0

    @property
    def busy(self) -> bool:
        return self.service is not None

    def _mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def _lines(self) -> list[str] | None:
        try:
            return [line.strip() for line in self.path.read_text(encoding="utf-8").splitlines()]
        except OSError:
            return None

    def _new_menu(self) -> list[str] | None:
        """The menu's lines once GSX has written them anew (an old file from earlier doesn't count)."""
        if self._mtime() == self.since:
            return None
        lines = self._lines()
        return lines if lines and len(lines) > 1 and not lines[0].startswith(BOOT) else None

    def _click(self, name: str, value: float, stage: str, wait_s: float) -> None:
        self.since = self._mtime()
        self.set_lvar(name, value)
        self.stage, self.deadline = stage, self.clock() + wait_s

    def start(self, service: str) -> None:
        """"pushback" or "deboarding"."""
        self.service, self.tries = service, 1
        self._click(MENU_OPEN, 1, "open", MENU_WAIT_S)

    def poll(self) -> str | None:
        """What happened, for the log, once it is over; None while still waiting."""
        if self.service is None:
            return None
        service = self.service
        lines = self._new_menu()
        if self.stage == "open":
            if lines is None:
                if self.clock() < self.deadline:
                    return None
                if self.tries < MENU_TRIES:
                    self.tries += 1
                    self._click(MENU_OPEN, 1, "open", MENU_WAIT_S)
                    return None
                self.set_lvar(MENU_CHOICE, CLOSE)  # in case it opened after all
                found = self._lines()
                said = " | ".join(found) if found else "nothing"
                return self._done(f"GSX: its menu did not open (tried {MENU_TRIES} times, {MENU_WAIT_S} s each; "
                                  f"{self.path} said: {said})")
            self.options = lines[1:]
            choice = next((i for i, o in enumerate(self.options)
                           if any(w in o.lower() for w in SERVICE_WORDS[service])), None)
            if choice is None:
                self.set_lvar(MENU_CHOICE, CLOSE)
                return self._done(f"GSX: no {service} in its menu ({' | '.join(self.options)})")
            self.choice = choice
            self._click(MENU_CHOICE, choice, "chosen", FOLLOW_WAIT_S)
            return None
        if lines is not None and lines[1:] != self.options:  # GSX asks something: the pilot answers it in GSX
            return self._done(f"GSX: {service} requested; GSX asks \"{lines[0]}\": answer it in the GSX menu")
        if lines is None and self.clock() < self.deadline:
            return None
        return self._done(f"GSX: {service} requested ({self.options[self.choice]})")

    def _done(self, result: str) -> str:
        self.service, self.stage = None, ""
        return result

    def request(self, service: str) -> str:
        """The whole request at once, waiting (the tests, a one-off check)."""
        self.start(service)
        while (result := self.poll()) is None:
            self.sleep(0.1)
        return result

"""Which Little Navmap database to read: the user's setting, else the one of the simulator that runs.

Little Navmap keeps one scenery database per simulator in %APPDATA%\\ABarthel\\little_navmap_db: for MSFS 2020
"little_navmap_msfs.sqlite", for MSFS 2024 one with "msfs" and "24" in its name (since Little Navmap 3.0.14, loaded
through SimConnect while MSFS 2024 runs). Found 2026-11-16 with a friend on MSFS 2024: the app read only the 2020
file, so he got "unknown airport". Now the running sim decides (FlightSimulator.exe or FlightSimulator2024.exe);
with neither running, the database loaded last.

LICENCE: the user's own database, read in place on their machine only; never shipped.
"""
import os
import subprocess
from pathlib import Path
from typing import Callable

NOT_SCENERY = {"", "navigraph", "userdata", "logbook", "track", "onlinedata", "userairspace"}
SIM_PROCESSES = {"flightsimulator.exe": "2020", "flightsimulator2024.exe": "2024"}
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flashing up from the windowed app


def folder() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "ABarthel" / "little_navmap_db"


def scenery_databases(where: Path) -> dict[str, Path]:
    """{"2020": file, "2024": file}, for the MSFS databases found there."""
    found = {}
    for file in sorted(where.glob("little_navmap_*.sqlite")):
        key = file.stem.lower().removeprefix("little_navmap_")
        if key in NOT_SCENERY or "msfs" not in key:
            continue  # Navigraph, logbook, …, or another simulator's (X-Plane, P3D)
        found["2024" if "24" in key else "2020"] = file
    return found


def _process_names() -> set[str]:
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}


def running_sim(processes: Callable[[], set[str]] = _process_names) -> str | None:
    """"2020", "2024", or None when no MSFS runs."""
    names = processes()
    return next((sim for process, sim in SIM_PROCESSES.items() if process in names), None)


def find(setting: Path, where: Path | None = None, sim: Callable[[], str | None] = running_sim) -> Path | None:
    """The database to read, or None without one. A path set in Settings wins (if it is there)."""
    if setting != Path():
        return setting if setting.is_file() else None
    found = scenery_databases(where or folder())
    if len(found) <= 1:
        return next(iter(found.values()), None)  # nothing to choose: no need to look at the processes
    if (running := sim()) in found:
        return found[running]
    return max(found.values(), key=lambda f: f.stat().st_mtime)  # the scenery loaded last


def describe(path: Path) -> str:
    """"Little Navmap (MSFS 2024)" for the banner, so it shows which scenery the airports come from."""
    key = path.stem.lower().removeprefix("little_navmap_")
    return f"Little Navmap (MSFS {'2024' if '24' in key else '2020'})" if "msfs" in key else f"Little Navmap ({path.name})"

"""LiveTraffic (real ADS-B traffic in MSFS) starts together with the app (Milestone 7).

LiveTraffic is a program of its own: "LiveTraffic MSFS.exe app" opens it with its app window, and it waits for the
sim. A second copy exits by itself when one already runs (its README), so the app can always start it. Where it
is: the path in Settings, else the entry LiveTraffic writes into MSFS's EXE.xml ("Start with the simulator"). The
app never ships or downloads LiveTraffic.
"""
import subprocess
from pathlib import Path
from typing import Callable

from atc.config import Config
from atc.sim.msfs_addons import addons, exe_xml_files

EXE_NAME = "LiveTraffic MSFS.exe"


def from_exe_xml(path: Path) -> Path | None:
    """LiveTraffic's program path from one EXE.xml, or None."""
    for name, program in addons(path):
        if program.name.lower() == EXE_NAME.lower() or "livetraffic" in name.lower():
            return program
    return None


def find_exe(config: Config, exe_xmls: list[Path] | None = None) -> Path | None:
    if config.traffic.livetraffic_exe != Path():
        return config.traffic.livetraffic_exe if config.traffic.livetraffic_exe.is_file() else None
    for xml in exe_xmls if exe_xmls is not None else exe_xml_files():
        if (exe := from_exe_xml(xml)) is not None and exe.is_file():
            return exe
    return None


def start(config: Config, popen: Callable = subprocess.Popen, exe_xmls: list[Path] | None = None) -> str:
    """Start LiveTraffic if the settings say so. Returns a line for the log."""
    if not config.traffic.start_livetraffic:
        return "LiveTraffic: not started (off in Settings, Traffic)"
    exe = find_exe(config, exe_xmls)
    if exe is None:
        where = config.traffic.livetraffic_exe if config.traffic.livetraffic_exe != Path() else None
        return (f"LiveTraffic: {where} not found" if where else
                "LiveTraffic: not found (set its program in Settings, Traffic)")
    try:
        popen([str(exe), "app"], cwd=str(exe.parent),
              creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))  # its own console, as MSFS starts it
    except OSError as e:
        return f"LiveTraffic: could not start {exe} ({e})"
    return f"LiveTraffic: started ({exe}); it closes by itself if it was already running"

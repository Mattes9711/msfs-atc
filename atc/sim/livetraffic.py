"""LiveTraffic (real ADS-B traffic in MSFS) starts together with the app (Milestone 7).

LiveTraffic is a program of its own: "LiveTraffic MSFS.exe app" opens it with its app window, and it waits for the
sim. A second copy exits by itself when one already runs (its README), so the app can always start it. Where it
is: the path in Settings, else the entry LiveTraffic writes into MSFS's EXE.xml ("Start with the simulator"). The
app never ships or downloads LiveTraffic.
"""
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from atc.config import Config

EXE_NAME = "LiveTraffic MSFS.exe"


def exe_xml_files() -> list[Path]:
    """Where MSFS keeps EXE.xml: Microsoft Store and Steam, 2020 and 2024."""
    local, roaming = Path(os.environ.get("LOCALAPPDATA", "")), Path(os.environ.get("APPDATA", ""))
    return [local / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "EXE.xml",
            local / "Packages" / "Microsoft.Limitless_8wekyb3d8bbwe" / "LocalCache" / "EXE.xml",
            roaming / "Microsoft Flight Simulator" / "EXE.xml",
            roaming / "Microsoft Flight Simulator 2024" / "EXE.xml"]


def from_exe_xml(path: Path) -> Path | None:
    """LiveTraffic's program path from one EXE.xml, or None."""
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError):
        return None
    for addon in root.iter("Launch.Addon"):
        exe = (addon.findtext("Path") or "").strip()
        if exe.lower().endswith(EXE_NAME.lower()) or "livetraffic" in (addon.findtext("Name") or "").lower():
            return Path(exe)
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

"""The programs MSFS starts with itself, from its EXE.xml (LiveTraffic, GSX's Couatl, FSUIPC, aircraft helpers).

Used to find LiveTraffic (atc/sim/livetraffic.py) and a SimConnect.dll another add-on brought along
(atc/sim/native.py find_dll).
"""
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def exe_xml_files() -> list[Path]:
    """Where MSFS keeps EXE.xml: Microsoft Store and Steam, 2020 and 2024."""
    local, roaming = Path(os.environ.get("LOCALAPPDATA", "")), Path(os.environ.get("APPDATA", ""))
    return [local / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "EXE.xml",
            local / "Packages" / "Microsoft.Limitless_8wekyb3d8bbwe" / "LocalCache" / "EXE.xml",
            roaming / "Microsoft Flight Simulator" / "EXE.xml",
            roaming / "Microsoft Flight Simulator 2024" / "EXE.xml"]


def addons(path: Path) -> list[tuple[str, Path]]:
    """(name, program) of every add-on in one EXE.xml; empty when it is missing or broken."""
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError):
        return []
    found = []
    for addon in root.iter("Launch.Addon"):
        program = (addon.findtext("Path") or "").strip()
        if program:
            found.append(((addon.findtext("Name") or "").strip(), Path(program)))
    return found

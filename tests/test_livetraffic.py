"""LiveTraffic starts with the app: found through MSFS's EXE.xml or the path in Settings."""
from dataclasses import replace
from pathlib import Path

from atc.config import Config
from atc.sim.livetraffic import find_exe, from_exe_xml, start

EXE_XML = """<?xml version="1.0" encoding="Windows-1252"?>
<SimBase.Document Type="Launch" version="1,0">
    <Launch.Addon><Name>Couatl</Name><Path>C:\\Addon Manager\\couatl64_boot.exe</Path></Launch.Addon>
    <Launch.Addon>
        <Name>LiveTraffic MSFS</Name>
        <Path>{exe}</Path>
        <CommandLine>app</CommandLine>
    </Launch.Addon>
</SimBase.Document>"""


def installed(tmp_path) -> tuple[Path, Path]:
    exe = tmp_path / "LiveTraffic-MSFS" / "LiveTraffic MSFS.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    xml = tmp_path / "EXE.xml"
    xml.write_text(EXE_XML.format(exe=exe), encoding="cp1252")
    return exe, xml


def test_found_through_msfs_exe_xml(tmp_path):
    exe, xml = installed(tmp_path)
    assert from_exe_xml(xml) == exe
    assert find_exe(Config(), [tmp_path / "missing.xml", xml]) == exe
    assert from_exe_xml(tmp_path / "missing.xml") is None


def test_the_path_in_settings_wins(tmp_path):
    exe, xml = installed(tmp_path)
    own = tmp_path / "elsewhere.exe"
    own.write_bytes(b"")
    config = Config()
    assert find_exe(replace(config, traffic=replace(config.traffic, livetraffic_exe=own)), [xml]) == own


ON = replace(Config(), traffic=replace(Config().traffic, start_livetraffic=True))


def test_off_unless_switched_on():
    assert Config().traffic.start_livetraffic is False  # the user's wish (2026-11-16): not with the launcher


def test_started_with_its_app_window(tmp_path):
    exe, xml = installed(tmp_path)
    calls = []
    line = start(ON, lambda args, **kw: calls.append((args, kw["cwd"])), [xml])
    assert calls == [([str(exe), "app"], str(exe.parent))]
    assert line.startswith("LiveTraffic: started")


def test_not_started_when_off_or_not_found(tmp_path):
    config = ON
    off = replace(config, traffic=replace(config.traffic, start_livetraffic=False))
    never = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not start"))  # noqa: E731
    assert "off in Settings" in start(off, never, [])
    assert "not found" in start(config, never, [tmp_path / "missing.xml"])

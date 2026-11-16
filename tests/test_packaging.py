"""Setup files stay consistent: requirements.txt (pinned, what start.bat installs) vs pyproject.toml (minimums)."""
import re
import tomllib

from atc.config import ROOT


def requirements(path):
    pins = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-r"):
            name, version = line.split("==")
            pins[name.strip().lower().replace("_", "-")] = tuple(int(x) for x in version.strip().split("."))
    return pins


def test_every_dependency_is_pinned_at_or_above_its_minimum():
    pins = requirements("requirements.txt")
    for dep in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]:
        name, minimum = re.fullmatch(r"([A-Za-z0-9_.-]+)>=([\d.]+)", dep).groups()
        pinned = pins[name.lower().replace("_", "-")]
        assert pinned >= tuple(int(x) for x in minimum.split(".")), dep


def test_start_bat_keeps_windows_line_endings():
    data = (ROOT / "start.bat").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b"requirements.txt" in data


def test_the_build_ships_the_page_but_never_the_airport_data():
    spec = (ROOT / "packaging" / "msfs_atc.spec").read_text(encoding="utf-8")
    assert '"atc" / "app" / "static"' in spec and '"centers.json"' in spec
    assert '"airports"' not in spec.replace("NOT data/airports", "")  # exported from the developer's scenery


def test_the_icon_is_a_windows_icon_with_all_sizes():
    import struct

    data = (ROOT / "packaging" / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 4
    assert data[6] == 16  # the first entry is the 16 px one


def test_the_licence_list_covers_the_gpl_voice():
    import sys

    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import build
    finally:
        sys.path.pop(0)
    packages = build.runtime_packages()
    assert "piper-tts" in packages and "faster-whisper" in packages and "pytest" not in packages
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("GNU GENERAL PUBLIC LICENSE")

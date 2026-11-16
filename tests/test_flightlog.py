"""The flight log (F4): every event of a flight in logs/, written as the flight goes."""

from atc import paths
from atc.app.server import App
from atc.config import Config
from atc.events import Event
from atc.flightlog import FlightLog, format_line, log_path
from tests.test_app import INJECT, PLAN, wait_for
from tests.test_main import run_session

T = 1763131927.0  # 2025-11-14 14:52:07 UTC


def test_lines_have_the_utc_time_and_who_spoke():
    assert format_line(Event("pilot", "Lufthansa 4AB, radio check", time=T)) == \
        "14:52:07Z  PILOT  Lufthansa 4AB, radio check"
    assert format_line(Event("atc", "Lufthansa four Alfa Bravo, read you fife", "Hamburg Tower", time=T)) == \
        "14:52:07Z  ATC    Hamburg Tower: Lufthansa four Alfa Bravo, read you fife"
    assert format_line(Event("readback", "readback correct", time=T)) == "14:52:07Z         (readback correct)"


def test_file_name_from_date_time_and_callsign_never_overwrites(tmp_path):
    first = log_path(tmp_path, "DLH4AB", T)
    assert first.name == "2025-11-14_1452Z_DLH4AB.txt"
    first.write_text("earlier flight")
    assert log_path(tmp_path, "DLH4AB", T).name == "2025-11-14_1452Z_DLH4AB_2.txt"
    assert log_path(tmp_path, "../x", T).name == "2025-11-14_1452Z_x.txt"  # no path tricks from a callsign


def test_each_line_is_on_disk_at_once(tmp_path):
    log = FlightLog(tmp_path / "logs" / "f.txt", ["DLH4AB EDDH -> EDDM"])
    log.emit(Event("pilot", "radio check", time=T))
    # Not closed yet: a crash now must not lose the line
    assert (tmp_path / "logs" / "f.txt").read_text(encoding="utf-8") == \
        "# DLH4AB EDDH -> EDDM\n14:52:07Z  PILOT  radio check\n"
    log.close()
    log.emit(Event("pilot", "after the end"))  # ignored, no error
    log.close()


def test_the_console_writes_a_flight_log(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/com 121.280", "Hamburg Tower, Lufthansa 4AB, radio check"])
    [log] = paths.logs_dir().glob("*_DLH4AB.txt")
    assert f"Flight log: {log}" in out
    text = log.read_text(encoding="utf-8")
    assert "# Flight plan (manual): DLH4AB IFR EDDH -> ?" in text
    assert "PILOT  Hamburg Tower, Lufthansa 4AB, radio check" in text
    assert "ATC    Hamburg Tower: Lufthansa four Alfa Bravo, Hamburg Tower, read you fife" in text


def test_the_app_writes_a_flight_log_per_flight():
    app = App(Config(), INJECT)
    app.start(PLAN)
    app.say("/com 121.280")
    app.say("Hamburg Tower, Lufthansa 4AB, radio check")
    wait_for(app, lambda e: e.kind == "atc")
    app.stop()
    wait_for(app, lambda e: e.text == "session ended")
    [log] = paths.logs_dir().glob("*_DLH4AB.txt")
    assert any(e.text == f"Flight log: {log}" for e in app.log.events)
    text = log.read_text(encoding="utf-8")
    assert "ATC    Hamburg Tower: Lufthansa four Alfa Bravo, Hamburg Tower, read you fife" in text
    assert text.rstrip().endswith("(session ended)")

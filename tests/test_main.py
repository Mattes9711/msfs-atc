import io

import pytest

from atc.airport.json_data import JsonAirportData
from atc.config import ROOT
from atc.flightplan.simbrief import SimbriefError, parse_simbrief
from atc.main import main
from atc.weather.source import StaticWeather

MODES = ["--text", "--nosim"]
ARGS = [*MODES, "--from", "EDDH", "--callsign", "dlh4ab"]
WEATHER = StaticWeather({"EDDH": "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"})
AIRPORTS = [JsonAirportData(ROOT / "data" / "airports")]
SIMBRIEF_PLAN = parse_simbrief((ROOT / "tests" / "fixtures" / "simbrief_sample.xml").read_bytes())


def run_session(monkeypatch, capsys, lines, extra_args=(), weather=WEATHER, args=ARGS, simbrief=None):
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(line + "\n" for line in lines)))
    main([*args, *extra_args], weather=weather, airports=AIRPORTS, simbrief=simbrief)
    return capsys.readouterr().out


class FakeSimbrief:
    def __init__(self, cached=False):
        self.cached, self.users = cached, []

    def __call__(self, user):
        self.users.append(user)
        return SIMBRIEF_PLAN, self.cached


def test_manual_plan_is_shown(monkeypatch, capsys):
    assert "Flight plan (manual): DLH4AB IFR EDDH -> ?" in run_session(monkeypatch, capsys, [])


def test_simbrief_plan_is_used(monkeypatch, capsys):
    simbrief = FakeSimbrief()
    out = run_session(monkeypatch, capsys, ["/com 121.280", "Hamburg Tower, Lufthansa 759, radio check"],
                      args=[*MODES, "--simbrief", "pilot"], simbrief=simbrief)
    assert simbrief.users == ["pilot"]
    assert "Flight plan (SimBrief): DLH759 A20N IFR EDDH -> EDDM FL350, route AMLU2G AMLUH M852" in out
    assert "ATC:   Lufthansa seven fife niner, Hamburg Tower, read you fife" in out


def test_command_line_values_override_simbrief(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, [], args=[*MODES, "--simbrief", "pilot", "--callsign", "dlh4ab",
                                                     "--cruise", "FL240"], simbrief=FakeSimbrief())
    assert "Flight plan (SimBrief): DLH4AB A20N IFR EDDH -> EDDM FL240" in out


def test_simbrief_username_comes_from_config(monkeypatch, capsys, tmp_path):
    config = tmp_path / "mine.toml"
    config.write_text('simbrief_username = "Mattes9711"\n', encoding="utf-8")
    simbrief = FakeSimbrief(cached=True)
    out = run_session(monkeypatch, capsys, [], args=[*MODES, "--simbrief", "--config", str(config)],
                      simbrief=simbrief)
    assert simbrief.users == ["Mattes9711"]
    assert "Flight plan (SimBrief, cached copy (offline))" in out


def test_banner_shows_weather_and_runway_in_use(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/quit"])
    assert "Weather: METAR EDDH 141450Z" in out
    assert "Runway in use: 23 (headwind 7 kt, crosswind 1 kt from the left), ATIS information A" in out


def test_no_weather_assumes_calm(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/quit"], weather=StaticWeather({}))
    assert "no METAR available, assuming calm wind" in out
    assert "(calm or variable wind)" in out


def test_text_nosim_session_end_to_end(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, [
        "Hamburg Tower, DLH4AB, radio check",  # COM1 not tuned yet
        "/com 121.280",
        "Hamburg Tower, DLH4AB, radio check",
        "/quit",
    ])
    assert "DLH4AB parked at EDDH Hamburg, G 1 (fake sim, airport data: JSON)" in out
    assert "COM1 is not tuned" in out
    assert "(COM1 121.280: Hamburg Tower)" in out
    assert "ATC:   Lufthansa four Alfa Bravo, Hamburg Tower, read you fife" in out


def test_tuning_the_atis_frequency_plays_the_atis(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/com 124.325"])
    assert "(COM1 124.325: ATIS)" in out
    assert "ATC:   Hamburg information Alfa, time one four fife zero. Runway in use two tree." in out


def test_taxi_command_shows_the_ground_clearance(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/taxi"])
    assert "Ground would say: Lufthansa four Alfa Bravo, taxi to holding point runway two tree" in out
    assert "unnamed, crossings" in out


def test_piped_input_with_bom_still_runs_commands(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["﻿/com 121.280"])
    assert "(COM1 121.280: Hamburg Tower)" in out


def test_input_ending_without_quit_exits_cleanly(monkeypatch, capsys):
    assert "PILOT>" in run_session(monkeypatch, capsys, ["/help"])


def test_bad_frequency_is_reported_not_crashing(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["/com 140.000", "/com abc"])
    assert "outside the VHF COM band" in out
    assert "not a frequency" in out


def test_strict_freq_prints_no_hint(monkeypatch, capsys):
    out = run_session(monkeypatch, capsys, ["hello"], extra_args=["--strict-freq"])
    assert "COM1 is not tuned. EDDH" not in out.split("PILOT>", 1)[1]


def failing_simbrief(user):
    raise SimbriefError("Error: No flight plan on file for the specified user")


@pytest.mark.parametrize("args, message", [
    (["--nosim", "--from", "EDDH", "--callsign", "X"], "no microphone or speakers in tests"),
    (["--text", "--from", "EDDH", "--callsign", "X"], "MSFS is not running"),
    ([*MODES, "--weather", "sim", "--from", "EDDH", "--callsign", "X"], "--weather sim reads the weather from MSFS"),
    ([*MODES, "--callsign", "X"], "--from is required with --nosim"),
    ([*MODES, "--from", "ZZZZ", "--callsign", "X"], "no airport data for ZZZZ (searched: JSON)"),
    ([*MODES, "--from", "EDDH"], "--callsign is required (or use --simbrief)"),
    ([*MODES, "--simbrief"], "--simbrief needs a username"),
    ([*MODES, "--simbrief", "pilot"], "No flight plan on file"),
])
def test_unusable_setups_explain_themselves(capsys, args, message):
    with pytest.raises(SystemExit):
        main(args, weather=WEATHER, airports=AIRPORTS, simbrief=failing_simbrief)
    assert message in capsys.readouterr().err

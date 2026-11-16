"""The MSFS side without MSFS: simvar conversion, the SimConnectSource with a fake request object,
weather from the sim, airport detection and the live loop."""
import io
from datetime import datetime, timezone

import pytest

from atc.airport.json_data import JsonAirportData
from atc.config import ROOT
from atc.flightplan.model import FlightPlan
from atc.events import ConsoleSink
from atc.main import main
from atc.runtime import LiveSession, run_live
from atc.session import departure_from_position, sample_wind
from atc.sim.fake import FakeSim
from atc.sim.simconnect import STATE_VARS, SimConnectSource, SimUnavailable, SimWeather, state_from_simvars
from atc.weather.metar import parse_metar
from atc.weather.sim_weather import average_wind, metar_from_sim
from atc.weather.source import StaticWeather
from tests.test_ground_flow import GROUND, TOWER, Session

# Values as MSFS returned them on 2026-11-14, parked at EDDH
PARKED_EDDH = {
    "PLANE_LATITUDE": 53.63536398850884, "PLANE_LONGITUDE": 9.998328755680662, "PLANE_ALTITUDE": 49.95,
    "PLANE_ALT_ABOVE_GROUND": 8.763, "SIM_ON_GROUND": 1.0, "PLANE_HEADING_DEGREES_MAGNETIC": 3.9464559676033626,
    "GROUND_VELOCITY": 0.0012, "COM_ACTIVE_FREQUENCY:1": 126.85499999999999,
    "AMBIENT_WIND_DIRECTION": 199.99, "AMBIENT_WIND_VELOCITY": 9.02, "LIGHT_BEACON": 0.0,  # beacon: added later
    "AMBIENT_TEMPERATURE": 5.98, "SEA_LEVEL_PRESSURE": 1018.0, "AMBIENT_VISIBILITY": 6500.0,
}
AIRPORTS = [JsonAirportData(ROOT / "data" / "airports")]
WEATHER = StaticWeather({"EDDH": "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"})


class FakeRequests:
    """Stands in for Python-SimConnect's AircraftRequests."""

    def __init__(self, values):
        self.values = values

    def get(self, name):
        if isinstance(self.values, Exception):
            raise self.values
        return self.values.get(name)


# --- simvars ----------------------------------------------------------------------------------------------------

def test_simvars_are_converted():
    s = state_from_simvars(PARKED_EDDH)
    assert s.com1_khz == 126855  # not 126854: the MHz float is rounded
    assert s.heading_mag == pytest.approx(226.1, abs=0.1)  # radians -> degrees
    assert s.on_ground and s.alt_agl_ft < 10 and s.alt_msl_ft == pytest.approx(50, abs=1)
    assert (round(s.wind_dir_true), round(s.wind_speed_kt)) == (200, 9)


def test_com1_outside_the_band_counts_as_not_tuned():
    assert state_from_simvars(PARKED_EDDH | {"COM_ACTIVE_FREQUENCY:1": 0.0}).com1_khz == 0


def test_no_data_before_the_flight_has_loaded():
    with pytest.raises(SimUnavailable, match="no data from MSFS yet"):
        SimConnectSource(FakeRequests({})).read()


def test_missing_data_later_keeps_the_last_state():
    requests = FakeRequests(dict(PARKED_EDDH))
    sim = SimConnectSource(requests)
    first = sim.read()
    assert not sim.stale
    requests.values["PLANE_LATITUDE"] = None  # e.g. the pause menu
    assert sim.read() == first and sim.stale
    requests.values = OSError("pipe closed")
    assert sim.read() == first and sim.stale
    requests.values = dict(PARKED_EDDH)
    sim.read()
    assert not sim.stale


def test_sim_weather():
    assert SimConnectSource(FakeRequests(PARKED_EDDH)).weather() == SimWeather(5.98, 1018.0, 6500.0)
    assert SimConnectSource(FakeRequests({})).weather() is None


def test_every_state_var_is_known_to_python_simconnect():
    source = (ROOT / ".venv" / "Lib" / "site-packages" / "SimConnect" / "RequestList.py")
    if not source.exists():
        pytest.skip("Python-SimConnect not installed in .venv")
    text = source.read_text(encoding="utf-8")
    assert all(f'"{name.replace(":1", ":index")}"' in text for name in STATE_VARS)


# --- --weather sim ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("samples, expected", [
    ([(200, 9), (195, 11)], (200, 10)),
    ([(350, 10), (10, 10)], (360, 10)),  # vector average across north, not 180
    ([(90, 10), (270, 10)], (None, 0)),  # cancels out: calm
    ([], (None, 0)),
])
def test_average_wind(samples, expected):
    direction, speed = average_wind(samples)
    assert (direction if speed else None, speed) == expected


def test_metar_from_sim_goes_through_the_normal_parser():
    raw = metar_from_sim("eddh", datetime(2026, 11, 14, 14, 50, tzinfo=timezone.utc), [(200, 9), (195, 11)],
                         SimWeather(6.0, 1018.4, 12000))
    assert raw == "EDDH 141450Z 20010KT 9999 Q1018 RMK MSFS"
    m = parse_metar(raw)
    assert (m.wind_dir, m.wind_kt, m.visibility_m, m.qnh_hpa, m.clouds) == (200, 10, 9999, 1018, ())


def test_calm_sim_wind_and_no_weather_vars():
    raw = metar_from_sim("EDDH", datetime(2026, 11, 14, 14, 50, tzinfo=timezone.utc), [(90, 0.4)], None)
    assert raw == "EDDH 141450Z 00000KT RMK MSFS"


def test_wind_samples_are_taken_with_pauses(eddh):
    sim, pauses = FakeSim.parked_at(eddh), []
    sim.update(wind_dir_true=200.0, wind_speed_kt=9.0)
    assert sample_wind(sim, 3, 0.5, pauses.append) == [(200.0, 9.0)] * 3
    assert pauses == [0.5, 0.5]


# --- airport detection --------------------------------------------------------------------------------------------

def at(lat, lon, on_ground=True):
    return state_from_simvars(PARKED_EDDH | {"PLANE_LATITUDE": lat, "PLANE_LONGITUDE": lon,
                                             "SIM_ON_GROUND": float(on_ground)})


def test_departure_is_detected_from_the_position():
    plan, notice = departure_from_position(AIRPORTS, FlightPlan("DLH4AB", ""), at(53.6354, 9.9983))
    assert plan.departure == "EDDH" and "detected" in notice


def test_the_aircraft_position_beats_the_flight_plan():
    plan, notice = departure_from_position(AIRPORTS, FlightPlan("DLH4AB", "EDDH", "EDDM"), at(48.35, 11.78))
    assert plan.departure == "EDDM"
    assert notice == "The aircraft is at EDDM, not at the flight plan's departure EDDH: using EDDM."


def test_no_detection_in_the_air_or_far_from_airports():
    plan = FlightPlan("DLH4AB", "EDDH")
    assert departure_from_position(AIRPORTS, plan, at(48.35, 11.78, on_ground=False)) == (plan, None)
    assert departure_from_position(AIRPORTS, plan, at(50.0, 10.0)) == (plan, None)


# --- live loop ----------------------------------------------------------------------------------------------------

class Collect:
    def __init__(self):
        self.lines = []

    def say(self, text, station=None, kind="atc"):
        self.lines.append(f"ATC:   {text}")

    def show(self, text):
        self.lines.append(text)


class StaleFakeSim(FakeSim):
    stale = False


def live(eddh, eddm=None):
    s = Session(eddh, destination=eddm)
    out = Collect()
    return s, out, LiveSession(s.sim, ConsoleSink(out, out.show), s.atc)


def test_tuning_in_the_cockpit_is_noticed(eddh):
    s, out, session = live(eddh)
    session.step()
    assert out.lines == ["       (COM1 not tuned)"]
    s.sim.update(com1_khz=124325)
    session.step()
    assert out.lines[1] == "       (COM1 124.325: ATIS)" and out.lines[2].startswith("ATC:   Hamburg information Alfa")
    session.step()
    assert len(out.lines) == 3  # no change, nothing new


def test_tuning_with_the_com_command_is_shown_once(eddh):
    # Found in the app window: /com announced the station, then the next tick noticed the change again
    s, out, session = live(eddh)
    session.step()
    session.step("/com 121.280")
    session.step()
    assert out.lines.count("       (COM1 121.280: Hamburg Tower)") == 1


def test_atc_calls_without_a_transmission(eddh, eddm):
    s, out, session = live(eddh, eddm)
    s.sim.update(com1_khz=GROUND)
    session.step("Lufthansa 4AB, request clearance information alpha")
    session.step(f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    session.step("Lufthansa 4AB, request taxi")
    session.step("holding point runway 23, Lufthansa 4AB")
    out.lines.clear()
    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])  # the pilot taxied there in the sim
    session.step()  # just a tick, as every second
    assert out.lines == ["ATC:   Lufthansa four Alfa Bravo, contact Hamburg Tower one two one decimal two eight zero"]


def test_lost_sim_data_is_shown_once(eddh):
    sim, out = StaleFakeSim.parked_at(eddh), Collect()
    session = LiveSession(sim, ConsoleSink(out, out.show), Session(eddh).atc)
    session.step()
    sim.stale = True
    session.step()
    session.step()
    sim.stale = False
    session.step()
    assert [line for line in out.lines if "MSFS" in line] == [
        "       (no data from MSFS, using the last known position)", "       (MSFS data is back)"]


class Lines:
    def __init__(self, *lines):
        self.lines = list(lines)

    def listen(self):
        return self.lines.pop(0) if self.lines else None


def test_run_live_until_input_ends_with_a_weather_refresh(eddh):
    s, out, _ = live(eddh)
    s.sim.update(com1_khz=TOWER)
    later = parse_metar("METAR EDDH 141520Z AUTO 22012KT 9999 SCT035 07/04 Q1017 NOSIG")
    times = iter(range(0, 1_000_000, 1000))
    run_live(s.sim, Lines("Hamburg Tower, Lufthansa 4AB, radio check"), ConsoleSink(out, out.show), s.atc,
             refresh=lambda: (later, None), tick_s=0.01, refresh_s=1500, clock=lambda: next(times))
    assert "ATC:   Lufthansa four Alfa Bravo, Hamburg Tower, read you fife" in out.lines
    assert ("       (EDDH weather: METAR EDDH 141520Z AUTO 22012KT 9999 SCT035 07/04 Q1017 NOSIG, "
            "ATIS information B)") in out.lines


def test_quit_ends_the_live_loop(eddh):
    s, out = Session(eddh), Collect()
    run_live(s.sim, Lines("/quit", "Hamburg Tower, Lufthansa 4AB, radio check"), ConsoleSink(out, out.show), s.atc,
             tick_s=0.01)
    assert not any(line.startswith("ATC:") for line in out.lines)


# --- main with a (fake) MSFS ------------------------------------------------------------------------------------

def test_main_with_msfs_detects_the_airport_and_uses_sim_weather(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("atc.session.SIM_WIND_INTERVAL_S", 0)
    monkeypatch.setattr("sys.stdin", io.StringIO("Hamburg Tower, Lufthansa 4AB, radio check\n"))
    closed = []
    sim = SimConnectSource(FakeRequests(PARKED_EDDH), close=lambda: closed.append(True))
    main(["--text", "--callsign", "DLH4AB", "--weather", "sim"], weather=WEATHER, airports=AIRPORTS,
         connect_sim=lambda: sim)
    out = capsys.readouterr().out
    assert "Departure airport detected from the aircraft position: EDDH." in out
    assert "DLH4AB at EDDH Hamburg (MSFS, airport data: JSON), on the ground." in out
    assert "Weather: EDDH " in out and "20009KT 6500 Q1018 RMK MSFS (built from MSFS at the aircraft)" in out
    assert "(COM1 126.855: Hamburg Tower)" in out  # COM1 as tuned in the cockpit
    assert "ATC:   Lufthansa four Alfa Bravo, Hamburg Tower, read you fife" in out
    assert closed == [True]


def test_sim_commands_are_refused_with_msfs(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.stdin", io.StringIO("/fly 10\n"))
    main(["--text", "--callsign", "DLH4AB"], weather=WEATHER, airports=AIRPORTS,
         connect_sim=lambda: SimConnectSource(FakeRequests(PARKED_EDDH)))
    assert "(With MSFS, tune and fly in the cockpit.)" in capsys.readouterr().out


def test_the_live_loop_gives_the_controller_the_time_for_the_hold_short_hint(eddh):
    # EDDH runway 15: the route crosses runway 05/23. The live loop's clock lets ATC notice a silent pilot there.
    s = Session(eddh, metar=parse_metar("METAR EDDH 141450Z AUTO 15010KT 9999 Q1018"))
    out, now = Collect(), [0.0]
    session = LiveSession(s.sim, ConsoleSink(out, out.show), s.atc, clock=lambda: now[0])
    s.sim.update(com1_khz=GROUND)
    session.step("Lufthansa 4AB, request clearance information alpha")
    session.step(f"runway 15, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    session.step("Lufthansa 4AB, request taxi")
    session.step("holding point runway 15 via A5, E1, hold short runway 05, Lufthansa 4AB")
    [(_, hold)] = s.atc.crossing_points(s.atc.route_out)
    s.sim.update(lat=s.atc.taxi.latlon[hold][0], lon=s.atc.taxi.latlon[hold][1])
    out.lines.clear()
    for now[0] in (100.0, 110.0, 116.0):
        session.step()
    assert out.lines == ['       (you are holding short of runway 05: report it, e.g. "Hamburg Ground, Lufthansa '
                         'four Alfa Bravo, holding short runway zero fife")']
